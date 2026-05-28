# -*- coding: utf-8 -*-
"""
Telegram listener — event loop orchestration.
Handles NewMessage + Album events, download, upload queue.
"""
from __future__ import annotations

import asyncio
import atexit
import logging
import os
import signal as _signal
import sys
import time
from collections import OrderedDict
from pathlib import Path

from telethon import TelegramClient, events
from telethon.errors import AuthKeyDuplicatedError, FloodWaitError, TimedOutError
from telethon.sessions import StringSession

from config import AppConfig
from core.cleanup import _cleanup_task
from core.download_handler import (
    DL_SEM, _cfg, _extract_peer_id, _file_hash,
    _fmt_speed, _hashes, _media_name,
    _resolve_download_path, _resolve_group_name, _resolve_peer_ids,
    _resolve_sender_info, _mtype, _ensure_dir,
)
from core.state import load_state
from rules import load_rules, compile_rules, evaluate_rules

log = logging.getLogger("guard.listener")
_MAX_PROCESSED = 50000


# ── Dedup cache ─────────────────────────────────────────────────


class _DedupCache(OrderedDict):
    def __init__(self, maxsize: int = _MAX_PROCESSED):
        super().__init__()
        self._maxsize = maxsize

    def add(self, key: int) -> None:
        self[key] = True
        if len(self) > self._maxsize:
            self.popitem(last=False)


# ── Connection ──────────────────────────────────────────────────


async def connect_retry(client: TelegramClient, retries: int = 10, base: float = 5.0) -> bool:
    for i in range(1, retries + 1):
        try:
            await client.connect()
            if await client.is_user_authorized():
                return True
            return False
        except AuthKeyDuplicatedError:
            return False
        except FloodWaitError as e:
            await asyncio.sleep(e.seconds)
        except (OSError, TimedOutError) as e:
            delay = min(base * (2 ** (i - 1)), 300)
            log.warning("Connect %d/%d: %s (retry %.0fs)", i, retries, e, delay)
            await asyncio.sleep(delay)
        except Exception as e:
            log.error("Connect error: %s", e)
            await asyncio.sleep(base)
    return False


# ── Pre-check (shared) ──────────────────────────────────────────


async def _pre_check(
    event, msg, peer_ids: set[int], media_set: set[str],
    blocked: list[str], min_file_size: int,
) -> tuple[str, str | None, str, str, int] | None:
    """Validate message. Returns (sender, username, group_name, media_type, file_size) or skip."""
    # Peer filter
    pid = _extract_peer_id(msg)
    if peer_ids and pid and pid not in peer_ids:
        return None
    if peer_ids and pid is None:
        try:
            chat = await event.get_chat()
            if getattr(chat, "id", None) not in peer_ids:
                return None
        except Exception:
            return None

    if not msg.media:
        return None

    mt = _mtype(msg.media)
    if mt not in media_set:
        return None

    sender, username = await _resolve_sender_info(event)

    if blocked and sender.lower() in blocked:
        return None

    file_size = getattr(getattr(msg.media, "document", None), "size", 0) or 0
    if min_file_size > 0 and mt != "photo" and file_size < min_file_size * 1024:
        return None

    group_name = await _resolve_group_name(event)
    return sender, username, group_name, mt, file_size


# ── Download + queue ───────────────────────────────────────────


async def _do_download(
    client, msg, fpath: Path, ddir: Path, mt: str, sender: str,
    username: str | None, group_name: str, original_caption: str,
    album_group, file_size: int, upload_queue, dedup_method: str,
    show_speed: bool, today_stats: dict | None = None,
) -> bool:
    """Download media file. Returns True on success."""
    async with DL_SEM:
        _ensure_dir(ddir)
        t0 = asyncio.get_event_loop().time()

        progress_cb = None
        if file_size > 5_242_880:
            def _progress(cur, total):
                pct = cur / total * 100 if total else 0
                print(f"\r  [{pct:.0f}% {cur/1024/1024:.1f}MB/{total/1024/1024:.1f}MB]", end="", flush=True)
            progress_cb = _progress

        for attempt in range(3):
            try:
                ok = await client.download_media(msg.media, file=str(fpath), progress_callback=progress_cb)
                if progress_cb:
                    print()
                if ok and fpath.exists():
                    sz = fpath.stat().st_size
                    elapsed = asyncio.get_event_loop().time() - t0
                    speed = sz / elapsed if elapsed > 0 else 0

                    if dedup_method == "hash":
                        fh = _file_hash(fpath)
                        if fh:
                            _hashes.put(fh, str(fpath))

                    ss = f" ({_fmt_speed(speed)})" if show_speed and speed > 0 else ""
                    print(f"  [{mt}] {sender}/{fpath.name} ({sz / 1_048_576:.1f}MB{ss})")
                    sys.stdout.flush()

                    if upload_queue is not None:
                        upload_queue.put_nowait(
                            (str(fpath), sender, username, msg.date,
                             group_name, original_caption, album_group)
                        )
                    # Track for TUI
                    if today_stats:
                        today_stats["t"]["downloaded"] += 1
                        today_stats["t"]["uploaded"] += 1
                        today_stats["t"]["bytes"] += sz
                        today_stats["recent"].append({"ok": True, "msg": f"{mt} {sender}/{fpath.name} ({sz/1_048_576:.1f}MB)"})
                        if len(today_stats["recent"]) > 50:
                            today_stats["recent"].pop(0)
                    return True
                else:
                    if fpath.exists() and fpath.stat().st_size == 0:
                        fpath.unlink()
                    # Track failure
                    if today_stats:
                        today_stats["t"]["failed"] += 1
                        today_stats["recent"].append({"ok": False, "msg": f"FAIL {sender}/{fpath.name}"})
                        if len(today_stats["recent"]) > 50:
                            today_stats["recent"].pop(0)
                    return False

            except FloodWaitError as e:
                await asyncio.sleep(e.seconds)
                if attempt == 2:
                    return False
            except (OSError, TimedOutError):
                await asyncio.sleep(2 * (attempt + 1))
            except Exception as e:
                log.error("Download error: %s", e)
                if fpath.exists() and fpath.stat().st_size == 0:
                    fpath.unlink()
                return False
        return False


# ── Main listener ──────────────────────────────────────────────


async def run() -> None:
    import core.download_handler as dh

    dh.CFG = AppConfig.load()
    dh.DL_DIR = Path(dh.CFG.download_dir)
    dh.DL_SEM = asyncio.Semaphore(max(dh.CFG.queue_size, 10))
    CFG = dh.CFG
    DL_DIR = dh.DL_DIR

    _ensure_dir(DL_DIR)
    _ensure_dir(Path("logs"))

    # State
    processed = _DedupCache()
    state_processed, _group_name_cache = load_state()
    # Fix #3: state_processed is a list of ints from load_state()
    if isinstance(state_processed, dict):
        for mid in state_processed:
            processed.add(int(mid))
    else:
        for mid in state_processed:
            processed.add(int(mid))
    dh._group_name_cache = _group_name_cache

    # Rules
    _rules = compile_rules(load_rules())
    if _rules:
        print(f"  Rules: {len(_rules)} rules loaded")

    # Filters
    media_set = {t.strip() for t in CFG.media_types.split(",") if t.strip()}
    blocked = [s.strip().lower() for s in CFG.blocked_senders.split(",") if s.strip()] if CFG.blocked_senders else []
    # Fix #4: removed unused fe = FilterEngine(...)

    # Client
    client = TelegramClient(
        StringSession(CFG.session_string) if CFG.session_string else StringSession(),
        CFG.api_id, CFG.api_hash,
        connection_retries=10, retry_delay=5, auto_reconnect=True,
    )

    peer_ids: set[int] = set()
    if CFG.target_groups:
        if not await connect_retry(client):
            return
        peer_ids = await _resolve_peer_ids(client, CFG.target_groups)

    if not peer_ids:
        print("  No valid groups.")
        return

    if CFG.history_enabled:
        log.warning("History scan enabled but history.py unavailable")

    print(f"  Peers: {len(peer_ids)} | media={','.join(sorted(media_set))} | dedup={CFG.dedup_method}")
    print(f"  Download dir: {DL_DIR}")

    # Upload worker
    upload_queue = None
    upload_task = None
    if CFG.upload_enabled and CFG.storage_group_id:
        from uploader import upload_worker
        upload_queue = asyncio.Queue()
        try:
            storage_gid = int(CFG.storage_group_id)
            upload_mode = os.getenv("UPLOAD_MODE", "realtime_keep")
            upload_task = asyncio.create_task(upload_worker(client, storage_gid, upload_queue, upload_mode))
            print(f"  Upload: {upload_mode} -> {storage_gid}")
        except ValueError:
            print(f"  Upload: invalid storage_group_id: {CFG.storage_group_id!r}")
    else:
        print("  Upload: disabled")

    asyncio.create_task(_cleanup_task(_cfg))

    # Config hot-reload
    from core.config_reloader import ConfigReloader
    _reloader = ConfigReloader()
    asyncio.create_task(_reloader.start())

    # Commands (Telegram)
    from core.commands import CommandHandler
    _cmd_handler = CommandHandler()
    asyncio.create_task(_cmd_handler.start(client))

    sys.stdout.flush()

    def _persist():
        from core.state import persist_state
        persist_state(dict(processed), _group_name_cache)

    atexit.register(_persist)

    # ── Event handlers ─────────────────────────────────────────

    # Fix #6: Album handler registered FIRST so Telethon processes album events
    # before NewMessage. Album has grouped_id which includes all items.
    # NewMessage handler skips items that have grouped_id (they belong to album).
    @client.on(events.Album)
    async def _on_album(event) -> None:
        nonlocal total
        msgs = event.messages
        if not msgs:
            return

        first_msg = msgs[0]
        first_gid = getattr(first_msg, "grouped_id", None)

        # Pre-check first message
        if _cmd_handler.is_paused():
            for m in msgs:
                processed.add(m.id)
            return

        r = await _pre_check(event, first_msg, peer_ids, media_set, blocked, CFG.min_file_size)
        if r is None:
            for m in msgs:
                processed.add(m.id)
            return
        sender, username, group_name, _, _ = r
        original_caption = (getattr(first_msg, "message", None) or "").strip()
        ddir = DL_DIR / _sanitize_group(group_name) / sender
        _ensure_dir(ddir)

        # Collect all valid download tasks
        tasks = []
        for msg in msgs:
            if msg.id in processed:
                continue
            processed.add(msg.id)

            if not msg.media:
                continue

            mt = _mtype(msg.media)
            if mt not in media_set:
                continue

            fname = _media_name(msg.media, msg.date, msg.id)
            fpath = ddir / fname
            fsize = getattr(getattr(msg.media, "document", None), "size", 0) or 0
            fpath = _resolve_download_path(fpath, fsize or None, msg.id)
            if fpath is None:
                continue

            _ts = {"t": _today, "recent": _recent_activity}
            tasks.append(
                _do_download(
                    client, msg, fpath, ddir, mt, sender, username,
                    group_name, original_caption, first_gid, fsize,
                    upload_queue, CFG.dedup_method, CFG.show_speed,
                    today_stats=_ts,
                )
            )

        # Download all in parallel
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for ok in results:
                if ok is True:
                    total += 1
                elif isinstance(ok, Exception):
                    log.error("Album error: %s", ok)

    @client.on(events.NewMessage)
    async def _on_msg(event) -> None:
        nonlocal total
        msg = event.message

        # Fix #6: Skip album items (they are handled by _on_album)
        if getattr(msg, "grouped_id", None) is not None:
            return

        if msg.id in processed:
            return
        processed.add(msg.id)

        if _cmd_handler.is_paused():
            return

        r = await _pre_check(event, msg, peer_ids, media_set, blocked, CFG.min_file_size)
        if r is None:
            return
        sender, username, group_name, mt, file_size = r

        # Rule engine
        fname = _media_name(msg.media, msg.date, msg.id)
        if _rules:
            rule_action = evaluate_rules(_rules, sender, fname, mt, file_size, group_name)
            if rule_action and rule_action.skip:
                return

        fpath = DL_DIR / _sanitize_group(group_name) / sender / fname
        fpath = _resolve_download_path(fpath, file_size or None, msg.id)
        if fpath is None:
            return

        original_caption = (getattr(msg, "message", None) or "").strip()
        album_group = None  # single messages have no album_group

        _ts = {"t": _today, "recent": _recent_activity}
        ok = await _do_download(
            client, msg, fpath, fpath.parent, mt, sender, username,
            group_name, original_caption, album_group, file_size,
            upload_queue, CFG.dedup_method, CFG.show_speed,
            today_stats=_ts,
        )
        if ok:
            total += 1

    # ── Start listening ────────────────────────────────────────

    me = await client.get_me()
    _cmd_handler.set_user(me.id)
    print(f"\n  Logged in as: {me.first_name}")

    # IPC — status writer + command reader
    from core.ipc import write_status, read_command, append_log
    _ipc_running = True
    _ipc_start = time.time()
    _ipc_me = me
    _today = {"downloaded": 0, "uploaded": 0, "failed": 0, "bytes": 0}
    _recent_activity: list[dict] = []

    async def _ipc_status_loop() -> None:
        from utils import format_bytes
        while _ipc_running:
            uptime = time.time() - _ipc_start
            s = {
                "running": True, "paused": _cmd_handler.is_paused(),
                "uptime": int(uptime), "processed": total,
                "user": _ipc_me.first_name,
                "storage_group": CFG.storage_group_id,
                "target_groups": CFG.target_groups,
                "upload_mode": os.getenv("UPLOAD_MODE", "realtime_keep"),
                "media_types": CFG.media_types, "queue_size": CFG.queue_size,
                "today_downloaded": _today["downloaded"],
                "today_uploaded": _today["uploaded"],
                "today_failed": _today["failed"],
                "today_size": format_bytes(_today["bytes"]),
                "storage_total": 0, "storage_uploaded": 0,
                "storage_pending": 0, "storage_size": "0 B",
                "recent": _recent_activity[-10:],
            }
            write_status(s)
            await asyncio.sleep(3)

    async def _ipc_command_loop() -> None:
        while _ipc_running:
            cmd = read_command()
            if cmd:
                action = cmd.get("action")
                if action == "pause":
                    _cmd_handler._paused = True
                    append_log("Paused via TUI")
                elif action == "resume":
                    _cmd_handler._paused = False
                    append_log("Resumed via TUI")
                elif action == "restart":
                    append_log("Restart requested via TUI")
            await asyncio.sleep(1)

    asyncio.create_task(_ipc_status_loop())
    asyncio.create_task(_ipc_command_loop())

    total = 0
    print(f"  Listening... (Ctrl+C to stop)\n")
    sys.stdout.flush()

    if not await client.is_user_authorized():
        log.error("Session not authorized")
        print("  Session not authorized")
        return

    shutdown = asyncio.Event()

    def _sig_handler(sig, frame):
        shutdown.set()

    try:
        _signal.signal(_signal.SIGINT, _sig_handler)
        _signal.signal(_signal.SIGTERM, _sig_handler)
    except (ValueError, OSError):
        pass

    try:
        await client.run_until_disconnected()
        await shutdown.wait()
    except (OSError, TimedOutError) as e:
        log.error("Disconnected: %s", e)
    except AuthKeyDuplicatedError:
        log.error("Session expired")
    except Exception as e:
        log.error("Listener error: %s: %s", type(e).__name__, e)
    finally:
        if upload_queue is not None:
            await upload_queue.put(None)
        if upload_task is not None:
            try:
                await asyncio.wait_for(upload_task, timeout=30)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                upload_task.cancel()
        try:
            await client.disconnect()
        except Exception:
            pass
        _persist()
        log.info("Stopped. Total: %d", total)


def _sanitize_group(name: str) -> str:
    try:
        from utils import sanitize_group
        return sanitize_group(name)
    except Exception:
        return "".join(c if c.isalnum() or c in "_- " else "_" for c in name)[:50]

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
import zipfile
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any

from telethon import TelegramClient, events
from telethon.errors import AuthKeyDuplicatedError, FloodWaitError, TimedOutError
from telethon.sessions import StringSession

from config import AppConfig
from core.cleanup import _cleanup_task, _aggressive_uploaded_cleanup_task
import core.download_handler as dh
from core.download_handler import (
    _cfg, _extract_peer_id, _file_hash, _file_hash_async, _dhash_async,
    _hashes, _media_name,
    _resolve_download_path, _resolve_group_name, _resolve_peer_ids,
    _resolve_sender_info, _mtype, _ensure_dir, compute_priority_key,
)
from core.state import (
    load_state, GLOBAL_STATUS, ACTIVE_DOWNLOADS, ACTIVE_TASKS,
    ACTIVE_UPLOADS, get_pending_details, remove_entry, persist_state,
    mark_pending, is_hash_exists, is_phash_exists, get_phash_match
)
from core.utils import sanitize_group, format_bytes
from core.commands import CommandHandler
from uploader import upload_worker

log = logging.getLogger("guard.listener")
_MAX_PROCESSED = 50000
MAX_PENDING = 50  # hard limit for fire-and-forget download tasks
_pending_tasks: set[asyncio.Task] = set()
ALBUM_BUFFER: dict[int, dict[str, Any]] = {}
FORWARD_LOCK = asyncio.Lock()
_last_forward_time = 0.0


# Dedup cache


class _DedupCache(OrderedDict):
    def __init__(self, maxsize: int = _MAX_PROCESSED):
        super().__init__()
        self._maxsize = maxsize

    def add(self, key: int) -> None:
        self[key] = True
        if len(self) > self._maxsize:
            self.popitem(last=False)


# Connection management


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


# Pre-check validation


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
    is_super = getattr(dh.CFG, "super_grabber_mode", False) if dh.CFG else False
    if not is_super and mt not in media_set:
        return None

    sender, username = await _resolve_sender_info(event)

    if not is_super and blocked and sender.lower() in blocked:
        return None

    file_size = getattr(getattr(msg.media, "document", None), "size", 0) or 0
    if not is_super and min_file_size > 0 and mt != "photo" and file_size < min_file_size * 1024:
        return None

    # Max file size guardrail (MB)
    max_file_size_mb = getattr(dh.CFG, "max_file_size", 0) if dh.CFG else 0
    if not is_super and max_file_size_mb > 0 and file_size > max_file_size_mb * 1_048_576:
        log.debug("Skip: file too large (%d bytes > %d MB limit)", file_size, max_file_size_mb)
        return None

    group_name = await _resolve_group_name(event)
    return sender, username, group_name, mt, file_size


# Download pipeline


async def _do_download(
    client, msg, fpath: Path, ddir: Path, mt: str, sender: str,
    username: str | None, group_name: str, original_caption: str,
    album_group, file_size: int, upload_queue, dedup_method: str,
    show_speed: bool,
) -> bool:
    # Throttle download if active uploads backlog is too large to prevent local disk build-up
    if upload_queue is not None:
        while len(ACTIVE_UPLOADS) >= 5:
            await asyncio.sleep(0.5)

    async with dh.DL_SEM:
        _ensure_dir(ddir)
        t0 = asyncio.get_event_loop().time()

        # Register running task reference
        ACTIVE_TASKS[msg.id] = asyncio.current_task()

        # Initialize active download entry in memory
        ACTIVE_DOWNLOADS[msg.id] = {
            "filename": fpath.name,
            "current": 0,
            "total": file_size or 1,
            "speed": "0 B/s",
            "speed_bps": 0.0,
            "eta": "ETA: ?"
        }

        # Custom progress callback to feed TUI ProgressBar real-time
        # Throttled to avoid dict churn on every 64KB chunk.
        _last_prog_update = 0.0

        def _progress(cur, total):
            nonlocal _last_prog_update
            t_now = asyncio.get_event_loop().time()
            # Throttle: update at most every 0.3 seconds
            if t_now - _last_prog_update < 0.3 and cur < (total or cur + 1):
                return
            _last_prog_update = t_now
            elapsed = t_now - t0
            speed_bps = cur / elapsed if elapsed > 0 else 0
            
            # Format download speed
            if speed_bps >= 1_048_576:
                speed_str = f"{speed_bps / 1_048_576:.1f} MB/s"
            elif speed_bps >= 1024:
                speed_str = f"{speed_bps / 1024:.1f} KB/s"
            else:
                speed_str = f"{speed_bps:.0f} B/s"
                
            # ETA calculation safely
            total_val = total if (total is not None and total > 0) else 0
            remaining = total_val - cur if total_val > 0 else 0
            if total_val > 0 and speed_bps > 0:
                eta_sec = int(remaining / speed_bps)
                eta_str = f"ETA: {eta_sec}s"
            else:
                eta_str = "ETA: ?"
                
            ACTIVE_DOWNLOADS[msg.id] = {
                "filename": fpath.name,
                "current": cur,
                "total": total_val or cur or 1,
                "speed": speed_str,
                "speed_bps": speed_bps,
                "eta": eta_str
            }

        try:
            for attempt in range(3):
                try:
                    ok = await client.download_media(msg.media, file=str(fpath), progress_callback=_progress)
                    if ok and fpath.exists():
                        sz = fpath.stat().st_size
                        elapsed = asyncio.get_event_loop().time() - t0
                        speed = sz / elapsed if elapsed > 0 else 0

                        fh = None
                        ph = None
                        if dedup_method == "hash":
                            fh = await _file_hash_async(fpath)
                            if fh:
                                if is_hash_exists(fh):
                                    log.info(f"Duplicate detected via database hash: {fpath.name}. Deleting local copy and skipping.")
                                    try:
                                        fpath.unlink()
                                    except Exception:
                                        pass
                                    return True
                                _hashes.put(fh, str(fpath))

                        if mt == "photo":
                            ph = await _dhash_async(fpath)
                            if ph:
                                match_path = get_phash_match(ph, max_distance=3)
                                if match_path or is_phash_exists(ph):
                                    log.info(f"Duplicate photo detected via perceptual hash (dHash): {fpath.name}. Match: {match_path}. Deleting local copy and skipping.")
                                    try:
                                        fpath.unlink()
                                    except Exception:
                                        pass
                                    return True

                        ss = f" ({format_bytes(int(speed))}/s)" if show_speed and speed > 0 else ""
                        log_msg = f"[{mt}] {sender}/{fpath.name} ({sz / 1_048_576:.1f}MB{ss})"
                        print(f"  {log_msg}")
                        sys.stdout.flush()
                        log.info(log_msg)

                        if upload_queue is not None:
                            mark_pending(str(fpath), source_group=group_name, sender_name=sender, caption=original_caption, file_hash=fh, p_hash=ph)
                            ACTIVE_UPLOADS.add(str(fpath))
                            pkey = compute_priority_key(sz, GLOBAL_STATUS.get("processed", 0))
                            payload = (str(fpath), sender, username, msg.date,
                                       group_name, original_caption, album_group)
                            upload_queue.put_nowait((pkey, msg.id, payload))
                        # Track for TUI
                        GLOBAL_STATUS["today_downloaded"] += 1
                        GLOBAL_STATUS["today_bytes"] += sz
                        GLOBAL_STATUS["processed"] += 1
                        GLOBAL_STATUS["recent_activity"].append({"ok": True, "msg": f"{mt} {sender}/{fpath.name} ({sz/1_048_576:.1f}MB)"})
                        if len(GLOBAL_STATUS["recent_activity"]) > 50:
                            GLOBAL_STATUS["recent_activity"].pop(0)
                        return True
                    else:
                        if fpath.exists() and fpath.stat().st_size == 0:
                            fpath.unlink()
                        log.error(f"FAIL: {sender}/{fpath.name}")
                        # Track failure
                        GLOBAL_STATUS["today_failed"] += 1
                        GLOBAL_STATUS["recent_activity"].append({"ok": False, "msg": f"FAIL {sender}/{fpath.name}"})
                        if len(GLOBAL_STATUS["recent_activity"]) > 50:
                            GLOBAL_STATUS["recent_activity"].pop(0)
                        return False

                except FloodWaitError as e:
                    await asyncio.sleep(e.seconds)
                    if attempt == 2:
                        return False
                except (OSError, TimedOutError):
                    await asyncio.sleep(2 * (attempt + 1))
                except asyncio.CancelledError:
                    log.warning("Download cancelled by user request: %s", fpath.name)
                    if fpath.exists():
                        try:
                            fpath.unlink()
                        except Exception:
                            pass
                    raise
                except Exception as e:
                    log.error("Download error: %s", e)
                    if fpath.exists() and fpath.stat().st_size == 0:
                        fpath.unlink()
                    return False
            return False
        finally:
            # Guarantee cleanup of memory dict to prevent TUI progress row freeze on cancels or failures
            ACTIVE_DOWNLOADS.pop(msg.id, None)
            ACTIVE_TASKS.pop(msg.id, None)


# Main daemon runtime

async def run(provided_client: TelegramClient | None = None) -> None:
    ACTIVE_UPLOADS.clear()
    GLOBAL_STATUS["running"] = True
    GLOBAL_STATUS["uptime_start"] = time.time()

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
    for mid in state_processed:
        processed.add(int(mid))
    dh._group_name_cache = _group_name_cache

    # Filters
    media_set = {t.strip() for t in CFG.media_types.split(",") if t.strip()}
    blocked = [s.strip().lower() for s in CFG.blocked_senders.split(",") if s.strip()] if CFG.blocked_senders else []

    # Client Setup
    if provided_client is not None:
        client = provided_client
    else:
        client = TelegramClient(
            StringSession(CFG.session_string) if CFG.session_string else StringSession(),
            CFG.api_id, CFG.api_hash,
            connection_retries=10, retry_delay=5, auto_reconnect=True,
        )

    peer_ids: set[int] = set()
    if CFG.target_groups:
        if provided_client is None:
            if not await connect_retry(client):
                GLOBAL_STATUS["running"] = False
                return
        peer_ids = await _resolve_peer_ids(client, CFG.target_groups)

    if not peer_ids:
        print("  No valid groups.")
        GLOBAL_STATUS["running"] = False
        return

    # Upload worker
    upload_queue = None
    upload_task = None
    if CFG.upload_enabled and CFG.storage_group_id:
        upload_queue = asyncio.PriorityQueue()
        import core.state as cs
        cs.UPLOAD_QUEUE = upload_queue
        try:
            storage_gid = int(CFG.storage_group_id)
            upload_mode = os.getenv("UPLOAD_MODE", "realtime_keep")
            upload_workers = max(1, min(CFG.upload_workers, 5))
            upload_task = asyncio.create_task(upload_worker(client, storage_gid, upload_queue, upload_mode, upload_workers))
            print(f"  Upload: {upload_mode} -> {storage_gid} (workers={upload_workers})")
            
            # Enqueue previous pending uploads on startup to resume uploading seamlessly
            pending_items = get_pending_details()
            enqueued_count = 0
            for item in pending_items:
                fpath = Path(item["filepath"])
                if fpath.exists():
                    sz = item["size"] or fpath.stat().st_size
                    _prio = CFG.download_priority
                    if _prio == "size_asc":
                        pkey = sz
                    elif _prio == "size_desc":
                        pkey = -sz
                    else:
                        pkey = enqueued_count
                    
                    # Construct payload
                    dt = datetime.fromtimestamp(fpath.stat().st_mtime)
                    payload = (str(fpath), item["sender_name"], None, dt,
                               item["source_group"], item["original_caption"], None)
                    
                    ACTIVE_UPLOADS.add(str(fpath))
                    # PriorityQueue format: (priority, seq, payload)
                    upload_queue.put_nowait((pkey, 999000 + enqueued_count, payload))
                    enqueued_count += 1
                else:
                    # File no longer exists, remove entry to keep DB clean
                    remove_entry(item["filepath"])
            
            if enqueued_count > 0:
                print(f"  [OK] Enqueued {enqueued_count} pending files from previous session for upload.")
        except ValueError:
            print(f"  Upload: invalid storage_group_id: {CFG.storage_group_id!r}")
    else:
        print("  Upload: disabled")

    if CFG.history_enabled:
        try:
            from core.history import run_history_scan
            asyncio.create_task(run_history_scan(
                client=client,
                peer_ids=peer_ids,
                cfg=CFG,
                upload_queue=upload_queue,
                download_sem=dh.DL_SEM,
                show_speed=CFG.show_speed
            ))
            log.info("History scan started in background")
        except Exception as e:
            log.error("Failed to initialize history scan: %s", e)

    print(f"  Peers: {len(peer_ids)} | media={','.join(sorted(media_set))} | dedup={CFG.dedup_method}")
    print(f"  Download dir: {DL_DIR}")

    asyncio.create_task(_cleanup_task(_cfg))
    asyncio.create_task(_aggressive_uploaded_cleanup_task())

    # Lightweight in-process config hot-reload
    async def _reload_config_loop():
        while True:
            await asyncio.sleep(5.0)
            dh.CFG = AppConfig.load()
    asyncio.create_task(_reload_config_loop())

    # Commands (Telegram)
    _cmd_handler = CommandHandler()
    asyncio.create_task(_cmd_handler.start(client))

    sys.stdout.flush()

    def _persist():
        persist_state(dict(processed), _group_name_cache)

    atexit.register(_persist)

    # Telegram event handlers

    async def _enqueue_album_items_individually(
        download_targets: list, group_name: str, sender: str, username: str | None,
        grouped_id: int, upload_queue
    ) -> None:
        for msg, fpath, mt, original_caption, fsize in download_targets:
            if fpath.exists() and fpath.stat().st_size > 0:
                sz = fpath.stat().st_size
                fh = await _file_hash_async(fpath)
                mark_pending(str(fpath), source_group=group_name, sender_name=sender, caption=original_caption, file_hash=fh)
                ACTIVE_UPLOADS.add(str(fpath))
                pkey = compute_priority_key(sz, GLOBAL_STATUS.get("processed", 0))
                payload = (str(fpath), sender, username, msg.date, group_name, original_caption, grouped_id)
                await upload_queue.put((pkey, msg.id, payload))

    async def _flush_album_after_delay(grouped_id: int, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        album_data = ALBUM_BUFFER.pop(grouped_id, None)
        if not album_data:
            return

        msgs = album_data["messages"]
        event = album_data["event"]
        if not msgs:
            return

        # Sort messages sequentially to preserve chronological ordering
        msgs.sort(key=lambda m: m.id)
        first_msg = msgs[0]

        if _cmd_handler.is_paused() or GLOBAL_STATUS["paused"]:
            for m in msgs:
                processed.add(m.id)
            return

        if getattr(dh.CFG, "processing_mode", "download") == "forward":
            if not getattr(dh.CFG, "storage_group_id", None):
                log.error("Forwarding failed: STORAGE_GROUP_ID is not configured.")
                for m in msgs:
                    processed.add(m.id)
                return
            try:
                storage_id = int(dh.CFG.storage_group_id)
                storage_entity = await client.get_entity(storage_id)
                source_entity = await event.get_input_chat()
                to_forward = []
                for msg in msgs:
                    if msg.id in processed:
                        continue
                    processed.add(msg.id)
                    to_forward.append(msg.id)
                if to_forward:
                    log.info(f"Instant Album Forward: Forwarding {len(to_forward)} messages to storage group {storage_id}")
                    async with FORWARD_LOCK:
                        global _last_forward_time
                        elapsed = time.time() - _last_forward_time
                        if elapsed < 1.0:
                            await asyncio.sleep(1.0 - elapsed)
                        _last_forward_time = time.time()
                        await client.forward_messages(storage_entity, to_forward, source_entity)
                return
            except Exception as fe:
                log.error(f"Instant Album Forward failed: {fe}")
                return

        media_set_dyn = {t.strip() for t in dh.CFG.media_types.split(",") if t.strip()}
        blocked_dyn = [s.strip().lower() for s in dh.CFG.blocked_senders.split(",") if s.strip()] if dh.CFG.blocked_senders else []

        r = await _pre_check(event, first_msg, peer_ids, media_set_dyn, blocked_dyn, dh.CFG.min_file_size)
        if r is None:
            for m in msgs:
                processed.add(m.id)
            return

        sender, username, group_name, _, _ = r
        original_caption = (getattr(first_msg, "message", None) or "").strip()
        ddir = Path(dh.CFG.download_dir) / sanitize_group(group_name) / sender
        _ensure_dir(ddir)

        # Collect download tasks for all messages in the album
        tasks = []
        download_targets = []  # List of tuples: (msg, fpath, mt, original_caption, rule_priority, fsize)
        
        auto_zip_enabled = os.getenv("AUTO_ZIP", "false").lower() in ("true", "1")
        zip_threshold = int(os.getenv("ZIP_THRESHOLD", "5"))
        
        # Decide if we defer queue registration for zipping
        defer_queue = (upload_queue is not None) and auto_zip_enabled

        for msg in msgs:
            if msg.id in processed:
                continue
            processed.add(msg.id)

            if not msg.media:
                continue

            mt = _mtype(msg.media)
            if not getattr(dh.CFG, "super_grabber_mode", False) and mt not in media_set_dyn:
                continue

            fname = _media_name(msg.media, msg.date, msg.id)
            fpath = ddir / fname
            fsize = getattr(getattr(msg.media, "document", None), "size", 0) or 0

            fpath = _resolve_download_path(fpath, fsize or None, msg.id)
            if fpath is None:
                continue

            download_targets.append((msg, fpath, mt, original_caption, fsize))
            
            # Pass None for upload_queue if deferring
            active_q = None if defer_queue else upload_queue
            
            tasks.append(
                _do_download(
                    client, msg, fpath, fpath.parent, mt, sender, username,
                    group_name, original_caption, grouped_id, fsize,
                    active_q, dh.CFG.dedup_method, dh.CFG.show_speed,
                )
            )

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for idx, ok in enumerate(results):
                if isinstance(ok, Exception):
                    log.error("Album error: %s", ok)
            
            # Process zipping or deferred queue enqueuing
            if defer_queue:
                # Find all successfully downloaded files
                downloaded_files = []
                for _, fpath, _, _, _ in download_targets:
                    if fpath.exists() and fpath.stat().st_size > 0:
                        downloaded_files.append(fpath)
                
                if len(downloaded_files) >= zip_threshold:
                    # Perform zipping!
                    zip_name = f"{first_msg.date:%Y%m%d_%H%M%S}_{sanitize_group(group_name)}_Album_{grouped_id}.zip"
                    zip_path = ddir / zip_name
                    
                    log.info(f"Auto-Zip: Compressing {len(downloaded_files)} files into archive: {zip_name}")
                    try:
                        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                            for f in downloaded_files:
                                zipf.write(f, arcname=f.name)
                                
                        # Delete original sub-files
                        for f in downloaded_files:
                            try:
                                f.unlink()
                            except Exception:
                                pass
                        
                        # Register the single ZIP file
                        sz = zip_path.stat().st_size
                        zip_hash = await _file_hash_async(zip_path)
                        
                        # Custom caption detailing contents
                        zip_caption = f"{original_caption} (Compressed Album Archive containing {len(downloaded_files)} items)"
                        
                        mark_pending(str(zip_path), source_group=group_name, sender_name=sender, caption=zip_caption, file_hash=zip_hash)
                        ACTIVE_UPLOADS.add(str(zip_path))
                        
                        # Enqueue ZIP
                        pkey = compute_priority_key(sz, GLOBAL_STATUS.get("processed", 0))
                        payload = (str(zip_path), sender, username, first_msg.date, group_name, zip_caption, None)
                        await upload_queue.put((pkey, first_msg.id, payload))
                        log.info(f"Auto-Zip complete: Enqueued archive {zip_name}")
                    except Exception as ze:
                        log.error(f"Auto-Zip failed: {ze}. Falling back to individual queueing.")
                        # Fallback: Enqueue individually
                        await _enqueue_album_items_individually(download_targets, group_name, sender, username, grouped_id, upload_queue)
                else:
                    # Did not meet threshold: Register and Enqueue individually
                    await _enqueue_album_items_individually(download_targets, group_name, sender, username, grouped_id, upload_queue)

    @client.on(events.NewMessage)
    async def _on_msg(event) -> None:
        if _cmd_handler.is_paused() or GLOBAL_STATUS["paused"]:
            return

        msg = event.message

        # Intercept and buffer albums robustly in-memory
        grouped_id = getattr(msg, "grouped_id", None)
        if grouped_id is not None:
            if msg.id in processed:
                return
            if grouped_id not in ALBUM_BUFFER:
                ALBUM_BUFFER[grouped_id] = {
                    "messages": [msg],
                    "event": event,
                    "task": None
                }
            else:
                if msg.id not in [m.id for m in ALBUM_BUFFER[grouped_id]["messages"]]:
                    ALBUM_BUFFER[grouped_id]["messages"].append(msg)
            
            # Debounce: Cancel previous scheduled flush to extend the sliding window
            old_task = ALBUM_BUFFER[grouped_id].get("task")
            if old_task and not old_task.done():
                old_task.cancel()
                
            new_task = asyncio.create_task(_flush_album_after_delay(grouped_id, 1.5))
            ALBUM_BUFFER[grouped_id]["task"] = new_task
            return

        if msg.id in processed:
            return
        processed.add(msg.id)

        if _cmd_handler.is_paused() or GLOBAL_STATUS["paused"]:
            return

        media_set_dyn = {t.strip() for t in dh.CFG.media_types.split(",") if t.strip()}
        blocked_dyn = [s.strip().lower() for s in dh.CFG.blocked_senders.split(",") if s.strip()] if dh.CFG.blocked_senders else []

        r = await _pre_check(event, msg, peer_ids, media_set_dyn, blocked_dyn, dh.CFG.min_file_size)
        if r is None:
            return
        sender, username, group_name, mt, file_size = r

        if getattr(dh.CFG, "processing_mode", "download") == "forward":
            if not getattr(dh.CFG, "storage_group_id", None):
                log.error("Forwarding failed: STORAGE_GROUP_ID is not configured.")
                return
            try:
                storage_id = int(dh.CFG.storage_group_id)
                storage_entity = await client.get_entity(storage_id)
                source_entity = await event.get_input_chat()
                log.info(f"Instant Single Forward: Forwarding message {msg.id} to storage group {storage_id}")
                async with FORWARD_LOCK:
                    global _last_forward_time
                    elapsed = time.time() - _last_forward_time
                    if elapsed < 1.0:
                        await asyncio.sleep(1.0 - elapsed)
                    _last_forward_time = time.time()
                    await client.forward_messages(storage_entity, msg.id, source_entity)
                return
            except Exception as fe:
                log.error(f"Instant Single Forward failed: {fe}")
                return

        # Build download path
        fname = _media_name(msg.media, msg.date, msg.id)
        fpath = Path(dh.CFG.download_dir) / _sanitize_group(group_name) / sender / fname
        original_caption = (getattr(msg, "message", None) or "").strip()

        fpath = _resolve_download_path(fpath, file_size or None, msg.id)
        if fpath is None:
            return

        album_group = None

        # Fire-and-forget with pending task limiter
        if len(_pending_tasks) >= MAX_PENDING:
            done, _ = await asyncio.wait(_pending_tasks, return_when=asyncio.FIRST_COMPLETED)
            _pending_tasks -= done
        task = asyncio.create_task(_do_download(
            client, msg, fpath, fpath.parent, mt, sender, username,
            group_name, original_caption, album_group, file_size,
            upload_queue, dh.CFG.dedup_method, dh.CFG.show_speed,
        ))
        _pending_tasks.add(task)
        task.add_done_callback(_pending_tasks.discard)

    # Initialization and runtime

    me = await client.get_me()
    _cmd_handler.set_user(me.id)
    print(f"\n  Logged in as: {me.first_name}")

    GLOBAL_STATUS["user"] = me.first_name
    log.info(f"Listener active (User: {me.first_name})")

    if not await client.is_user_authorized():
        log.error("Session not authorized")
        print("  Session not authorized")
        GLOBAL_STATUS["running"] = False
        return

    shutdown = asyncio.Event()

    def _sig_handler(sig, frame):
        shutdown.set()

    try:
        _signal.signal(_signal.SIGINT, _sig_handler)
        _signal.signal(_signal.SIGTERM, _sig_handler)
    except (ValueError, OSError):
        pass

    # If the client is provided, we do not call run_until_disconnected here;
    # TUI will manage the client runtime directly.
    if provided_client is not None:
        # Keep background uploader running
        try:
            # Sleep indefinitely or until shutdown
            await shutdown.wait()
        except asyncio.CancelledError:
            pass
        finally:
            if upload_queue is not None:
                await upload_queue.put((float('inf'), 0, None))
            if upload_task is not None:
                try:
                    await asyncio.wait_for(upload_task, timeout=30)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    upload_task.cancel()
            _persist()
            GLOBAL_STATUS["running"] = False
            log.info("Stopped. Total processed: %d", GLOBAL_STATUS["processed"])
    else:
        print("  Listening... (Ctrl+C to stop)\n")
        sys.stdout.flush()
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
                await upload_queue.put((float('inf'), 0, None))
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
            GLOBAL_STATUS["running"] = False
            log.info("Stopped. Total processed: %d", GLOBAL_STATUS["processed"])

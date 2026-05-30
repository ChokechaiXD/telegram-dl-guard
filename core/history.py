# -*- coding: utf-8 -*-
"""
History scanner — scans past messages in target groups and downloads media.

Modes:
  - list: print found media without downloading
  - auto: download automatically
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from telethon import TelegramClient

from config import AppConfig
from core.download_handler import (
    _ensure_dir, _file_hash_async, _hashes,
    _media_name, _mtype, _resolve_download_path,
    _resolve_sender_info, compute_priority_key,
)
from core.state import (
    ACTIVE_UPLOADS, GLOBAL_STATUS, mark_pending,
)
from core.utils import format_bytes, sanitize_group

log = logging.getLogger("guard.history")


async def run_history_scan(
    client: TelegramClient,
    peer_ids: set[int],
    cfg: AppConfig,
    upload_queue,
    download_sem,
    show_speed: bool = True,
) -> int:
    """Scan historical messages in target groups and download media.

    Returns the total number of files downloaded (or listed).
    """
    if not cfg.history_enabled:
        return 0

    hours = max(cfg.history_hours, 1)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    mode = cfg.history_mode  # "list" or "auto"
    reverse = cfg.history_reverse
    is_super = cfg.super_grabber_mode

    media_set = {t.strip() for t in cfg.media_types.split(",") if t.strip()}
    blocked = [s.strip().lower() for s in cfg.blocked_senders.split(",") if s.strip()] if cfg.blocked_senders else []
    min_size = cfg.min_file_size
    max_size_mb = cfg.max_file_size

    total_found = 0
    total_downloaded = 0

    log.info(
        "History scan: mode=%s, hours=%d, reverse=%s, super=%s, peers=%d",
        mode, hours, reverse, is_super, len(peer_ids),
    )
    print(f"  [History] Scanning last {hours}h (mode={mode}, groups={len(peer_ids)})")

    for pid in peer_ids:
        try:
            entity = await client.get_entity(pid)
            group_title = getattr(entity, "title", str(pid))
        except Exception as e:
            log.warning("History: cannot resolve peer %s: %s", pid, e)
            continue

        log.info("History: scanning %s (id=%d)", group_title, pid)
        scanned = 0

        try:
            async for msg in client.iter_messages(
                entity,
                offset_date=None if reverse else cutoff,
                reverse=reverse,
                limit=None,
            ):
                # Stop condition
                if msg.date is not None:
                    msg_dt = msg.date if msg.date.tzinfo else msg.date.replace(tzinfo=timezone.utc)
                    if reverse and msg_dt > datetime.now(timezone.utc):
                        break
                    if not reverse and msg_dt < cutoff:
                        break
                    if reverse and msg_dt < cutoff:
                        continue

                scanned += 1

                if not msg.media:
                    continue

                mt = _mtype(msg.media)

                # Filter checks (bypass all in super grabber mode)
                if not is_super:
                    if mt not in media_set:
                        continue

                file_size = getattr(getattr(msg.media, "document", None), "size", 0) or 0

                if not is_super:
                    if min_size > 0 and mt != "photo" and file_size < min_size * 1024:
                        continue
                    if max_size_mb > 0 and file_size > max_size_mb * 1_048_576:
                        continue

                # Resolve sender
                sender, username = await _resolve_sender_info(msg)

                if not is_super and blocked and sender.lower() in blocked:
                    continue

                fname = _media_name(msg.media, msg.date, msg.id)
                total_found += 1

                if mode == "list":
                    size_str = format_bytes(file_size) if file_size else "?"
                    print(f"    [{mt}] {sender}/{fname} ({size_str})")
                    continue

                # mode == "auto": download
                ddir = Path(cfg.download_dir) / sanitize_group(group_title) / sender
                fpath = ddir / fname
                original_caption = (getattr(msg, "message", None) or "").strip()

                fpath = _resolve_download_path(fpath, file_size or None, msg.id)
                if fpath is None:
                    continue  # duplicate

                _ensure_dir(fpath.parent)

                # Download with semaphore
                async with download_sem:
                    try:
                        t0 = asyncio.get_event_loop().time()
                        await client.download_media(msg, file=str(fpath))

                        if fpath.exists():
                            sz = fpath.stat().st_size
                            elapsed = asyncio.get_event_loop().time() - t0
                            speed = sz / elapsed if elapsed > 0 else 0
                            speed_str = f" ({format_bytes(int(speed))}/s)" if speed > 0 else ""

                            # Hash for dedup
                            fh = None
                            if cfg.dedup_method == "hash":
                                fh = await _file_hash_async(fpath)
                                if fh:
                                    _hashes.put(fh, str(fpath))

                            log.info("[history][%s] %s/%s (%.1fMB%s)", mt, sender, fname, sz / 1_048_576, speed_str)
                            total_downloaded += 1
                            GLOBAL_STATUS["processed"] += 1
                            GLOBAL_STATUS["today_downloaded"] = GLOBAL_STATUS.get("today_downloaded", 0) + 1

                            # Enqueue for upload
                            if upload_queue is not None:
                                mark_pending(str(fpath), source_group=group_title, sender_name=sender, caption=original_caption, file_hash=fh)
                                ACTIVE_UPLOADS.add(str(fpath))
                                pkey = compute_priority_key(sz, total_downloaded)
                                dt = datetime.fromtimestamp(fpath.stat().st_mtime)
                                payload = (str(fpath), sender, username, dt, group_title, original_caption, None)
                                upload_queue.put_nowait((pkey, 900000 + total_downloaded, payload))
                    except Exception as e:
                        log.error("History download error %s: %s", fname, e)

                # Yield control periodically
                if total_downloaded % 10 == 0:
                    await asyncio.sleep(0.1)

        except Exception as e:
            log.error("History scan error for %s: %s", group_title, e)

        log.info("History: %s — scanned %d msgs, found %d media", group_title, scanned, total_found)

    action = "listed" if mode == "list" else "downloaded"
    print(f"  [History] Done: {total_found} found, {total_downloaded} {action}")
    log.info("History scan complete: found=%d, downloaded=%d", total_found, total_downloaded)
    return total_downloaded

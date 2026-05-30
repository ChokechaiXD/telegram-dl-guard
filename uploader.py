# -*- coding: utf-8 -*-
"""
Uploader — Smart Mode album-aware uploader.
Queue item: (filepath, sender, sender_username, dt, group_name, caption, album_group)
"""
from __future__ import annotations

import asyncio
import logging
import random
from collections import defaultdict

from datetime import datetime
from pathlib import Path
from typing import Any
import re
from config import AppConfig

from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.tl.types import (
    InputMediaUploadedPhoto,
    InputMediaUploadedDocument,
    DocumentAttributeFilename,
    DocumentAttributeVideo,
)

from core.state import is_uploaded, mark_uploaded, mark_pending, ACTIVE_UPLOADS, GLOBAL_STATUS
from core.download_handler import _file_hash_async
from core.utils import format_bytes, detect_send_type, guess_mime

log = logging.getLogger("guard.uploader")

ALBUM_SIZE = 10
BATCH_DELAY = 1.0
ALBUM_GAP = 2.0
FLUSH_TIMEOUT = 60


def _parse_date(date_str: str | None) -> datetime:
    if not date_str:
        return datetime.now()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(date_str)
    except Exception:
        return datetime.now()


_webhook_queue: asyncio.Queue = asyncio.Queue()
_webhook_task: asyncio.Task | None = None


def _send_webhook_sync(url: str, payload: dict) -> None:
    import urllib.request
    import urllib.error
    import json
    import time
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "Telegram-DL-Guard"},
            method="POST"
        )
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=10) as response:
                    response.read()
                    return
            except urllib.error.HTTPError as he:
                if he.code == 429:
                    retry_after = he.headers.get("Retry-After")
                    wait_time = int(retry_after) if (retry_after and retry_after.isdigit()) else (2 ** attempt * 5)
                    log.warning(f"Webhook rate limited (HTTP 429). Retrying after {wait_time}s...")
                    time.sleep(wait_time)
                elif he.code >= 500:
                    wait_time = 2 ** attempt * 2
                    log.warning(f"Webhook error (HTTP {he.code}). Retrying after {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    log.error(f"Webhook failed with terminal HTTP error {he.code}")
                    break
            except Exception as ex:
                wait_time = 2 ** attempt * 2
                log.warning(f"Webhook network error: {ex}. Retrying after {wait_time}s...")
                time.sleep(wait_time)
    except Exception as ex:
        log.error(f"Webhook initialization failed: {ex}")


async def _webhook_dispatcher() -> None:
    while True:
        try:
            url, payload = await _webhook_queue.get()
            await asyncio.to_thread(_send_webhook_sync, url, payload)
            _webhook_queue.task_done()
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.error("Error in webhook dispatcher: %s", e)


async def dispatch_webhook_notification(filename: str, file_size: int, sender: str, group: str, caption: str) -> None:
    global _webhook_task
    cfg = AppConfig.load()
    if not cfg.webhook_enabled or not cfg.webhook_url:
        return
    
    if _webhook_task is None or _webhook_task.done():
        _webhook_task = asyncio.create_task(_webhook_dispatcher())
        
    size_str = format_bytes(file_size) if file_size > 0 else "Unknown"
    
    payload = {
        "embeds": [
            {
                "title": "New File Uploaded to Storage",
                "color": 5814783,
                "fields": [
                    {"name": "Filename", "value": filename[:100] or "unknown", "inline": True},
                    {"name": "Size", "value": size_str, "inline": True},
                    {"name": "Sender", "value": sender or "unknown", "inline": True},
                    {"name": "Source", "value": group or "unknown", "inline": True}
                ],
                "description": caption[:300] if caption else "No description",
                "timestamp": datetime.now().isoformat()
            }
        ]
    }
    _webhook_queue.put_nowait((cfg.webhook_url, payload))


# Caption logic


def build_caption(
    sender_name: str,
    sender_username: str | None,
    dt: datetime,
    filename: str = "",
    source_group_name: str = "",
    file_size: int = 0,
    original_caption: str = "",
    file_idx: int = 0,
    file_total: int = 0,
    for_album: bool = False,
) -> str:
    """Build caption: plain-text search tag line + emoji-labeled detail lines.

    Search tag: '#group sender_name' (Telegram search hits this first).
    Detail: one label per line.
    """
    def _tag(text: str) -> str:
        t = re.sub(r"[^\w\u0E00-\u0E7F\-]", "_", text).strip()
        t = re.sub(r"_+", "_", t)
        return t.strip("_")

    date_str = dt.strftime("%Y-%m-%d %H:%M")
    lines: list[str] = []

    # Line 0: search tags — #group sender
    tags = []
    if source_group_name:
        g = _tag(source_group_name)
        if g:
            tags.append(f"#{g}")
    s = _tag(sender_name)
    if s:
        tags.append(f"#{s}")
    if original_caption:
        for word in original_caption.split():
            if word.startswith("#") and len(word) > 1:
                cleaned_tag = _tag(word[1:])
                if cleaned_tag:
                    formatted_tag = f"#{cleaned_tag}"
                    if formatted_tag not in tags:
                        tags.append(formatted_tag)
    if tags:
        lines.append(" ".join(tags))

    # Detail lines
    sender_clean = sender_name.replace(" ", "_")
    sender_clean = re.sub(r"[^\w\u0E00-\u0E7F\-]", "", sender_clean)
    if sender_clean:
        lines.append(f"Sender: #{sender_clean}")
    else:
        lines.append(f"Sender: #{sender_name}")
    if sender_username:
        lines.append(f"Username: @{sender_username}")
    if for_album:
        if file_total > 0:
            lines.append(f"Total: {file_total} files")
    else:
        if filename:
            lines.append(f"Filename: {filename}")
        if file_size:
            lines.append(f"Size: {format_bytes(file_size)}")
    if original_caption:
        lines.append(f"Caption: {original_caption[:300]}")
    if source_group_name:
        lines.append(f"Source: {source_group_name}")
    lines.append(f"Date: {date_str}")
    if file_total > 0 and not for_album:
        lines.append(f"Index: {file_idx}/{file_total}")

    return "\n".join(lines)





def _build_doc_attributes(filepath: Path, send_type: str) -> list:
    """Build Telethon document attributes so Telegram can identify the file."""
    attrs = [DocumentAttributeFilename(file_name=filepath.name)]
    if send_type == "video":
        # Provide basic video attribute; Telegram will fill in real
        # dimensions from the actual stream when it processes the file.
        attrs.append(DocumentAttributeVideo(
            duration=0,
            w=1920,
            h=1080,
            supports_streaming=True,
        ))
    return attrs


# Upload single file


async def upload_single(
    client: TelegramClient,
    storage_group_id: int,
    filepath: Path,
    caption: str = "",
    send_type: str | None = None,
    reply_to: int | None = None,
) -> int | None:
    if not filepath.exists():
        return None
    stype = send_type or detect_send_type(filepath)
    log.info("upload_single: %s (%s)", filepath.name, stype)

    for attempt in range(4):
        try:
            kwargs: dict[str, Any] = {"file": str(filepath)}
            if caption:
                kwargs["caption"] = caption[:1024]
            if reply_to:
                kwargs["reply_to"] = reply_to
            if stype == "video":
                kwargs["supports_streaming"] = True
                kwargs["attributes"] = _build_doc_attributes(filepath, "video")
                kwargs["mime_type"] = guess_mime(filepath)
            elif stype != "photo":
                kwargs["force_document"] = True
                kwargs["attributes"] = [DocumentAttributeFilename(file_name=filepath.name)]
                kwargs["mime_type"] = guess_mime(filepath)
            msg = await client.send_file(storage_group_id, **kwargs)
            return msg.id
        except FloodWaitError as e:
            wait = e.seconds + random.uniform(0.5, 2.0)
            log.warning("FloodWait %ds (+jitter), attempt %d/4", e.seconds, attempt + 1)
            await asyncio.sleep(wait)
        except Exception as e:
            backoff = min(2 ** attempt + random.uniform(0, 1), 30)
            log.error("upload_single attempt %d/4: %s (backoff %.1fs)", attempt + 1, e, backoff)
            await asyncio.sleep(backoff)
    return None


# Upload album (native)


async def upload_album(
    client: TelegramClient,
    storage_group_id: int,
    items: list[tuple[Path, str]],
    caption: str = "",
) -> int | None:
    if not items:
        return None

    try:
        chunks = [items[i:i + ALBUM_SIZE] for i in range(0, len(items), ALBUM_SIZE)]
        first_msg_id = None

        for chunk_idx, chunk in enumerate(chunks):
            media_list = []
            for fpath, stype in chunk:
                if not fpath.exists():
                    continue
                # Bug Fix: Catch exceptions on client.upload_file to prevent worker crash
                try:
                    file_obj = await client.upload_file(str(fpath))
                except FloodWaitError as e:
                    log.warning("FloodWait during album file upload: sleeping %d seconds", e.seconds)
                    await asyncio.sleep(e.seconds)
                    file_obj = await client.upload_file(str(fpath))

                if stype == "photo":
                    media_list.append(InputMediaUploadedPhoto(file=file_obj))
                else:
                    mime = guess_mime(fpath)
                    attrs = _build_doc_attributes(fpath, stype)
                    media_list.append(InputMediaUploadedDocument(
                        file=file_obj,
                        mime_type=mime,
                        attributes=attrs,
                    ))

            if not media_list:
                continue

            kwargs: dict[str, Any] = {}
            if chunk_idx == 0 and caption:
                kwargs["caption"] = caption[:1024]

            log.info("upload_album: %d files (chunk %d/%d)", len(media_list), chunk_idx + 1, len(chunks))
            msgs = await client.send_file(storage_group_id, file=media_list, **kwargs)
            if msgs:
                first_msg_id = msgs[0].id if isinstance(msgs, list) else msgs.id

            if chunk_idx < len(chunks) - 1:
                await asyncio.sleep(ALBUM_GAP)

        return first_msg_id
    except Exception as e:
        log.error("upload_album: failed to process album: %s", e)
        return None


# Upload worker (realtime Smart Mode)


async def upload_worker(
    client: TelegramClient,
    storage_group_id: int,
    queue: asyncio.Queue,
    mode: str = "realtime_keep",
    num_workers: int = 3,
) -> None:
    """Smart Mode upload worker with parallel upload slots.
    
    Queue items are (priority, seq, payload) tuples from PriorityQueue.
    payload = (fp, sender, username, dt, group, caption, album_group)
    """
    log.info("upload_worker: Smart Mode (mode=%s, workers=%d)", mode, num_workers)
    do_delete = mode.endswith("_delete")
    ul_sem = asyncio.Semaphore(max(1, min(num_workers, 5)))
    buffer: list[tuple] = []

    async def _send_single(item: tuple) -> int | None:
        fpath_str, sender, username, dt, grp, caption, _ag = item
        fpath = Path(fpath_str)
        if not fpath.exists() or is_uploaded(fpath_str):
            ACTIVE_UPLOADS.discard(fpath_str)
            return None
        file_size = fpath.stat().st_size
        cap = build_caption(sender, username, dt, fpath.name, grp, file_size, caption)
        log.info(f"Uploading: {fpath.name}")
        
        fh = await _file_hash_async(fpath)
        
        try:
            msg_id = await upload_single(client, storage_group_id, fpath, cap)
            if msg_id:
                mark_uploaded(fpath_str, msg_id, file_hash=fh)
                await dispatch_webhook_notification(fpath.name, file_size, sender, grp, caption)
                log.info(f"Uploaded: {fpath.name}")
                # Increment actual upload counter
                GLOBAL_STATUS["today_uploaded"] += 1
                if do_delete and fpath.exists():
                    try:
                        fpath.unlink()
                    except Exception as ex:
                        log.warning("Failed to delete local file %s after upload: %s", fpath, ex)
            else:
                mark_pending(fpath_str)
                log.error(f"Upload failed: {fpath.name}")
            return msg_id
        finally:
            ACTIVE_UPLOADS.discard(fpath_str)

    async def _send_single_guarded(item: tuple) -> int | None:
        """Upload with concurrency limiter."""
        async with ul_sem:
            return await _send_single(item)

    async def _send_album(album_items: list[tuple]) -> int | None:
        if not album_items:
            return None
        media_items = []
        for item in album_items:
            fpath = Path(item[0])
            if not fpath.exists() or is_uploaded(item[0]):
                ACTIVE_UPLOADS.discard(item[0])
                continue
            media_items.append((fpath, detect_send_type(fpath), item))

        if not media_items:
            return None

        first = album_items[0]
        album_cap = build_caption(first[1], first[2], first[3], "", first[4], 0, first[5], file_total=len(media_items), for_album=True)
        pairs = [(fp, st) for fp, st, _ in media_items]
        
        log.info(f"Uploading album: {len(media_items)} items from {first[1]}")
        try:
            msg_id = await upload_album(client, storage_group_id, pairs, album_cap)

            total_album_size = 0
            for _, _, item in media_items:
                fpath_str = item[0]
                if msg_id:
                    p = Path(fpath_str)
                    total_album_size += p.stat().st_size if p.exists() else 0
                    fh = await _file_hash_async(p) if p.exists() else None
                    mark_uploaded(fpath_str, msg_id, file_hash=fh)
                    if do_delete:
                        p = Path(fpath_str)
                        try:
                            if p.exists():
                                p.unlink()
                        except Exception as ex:
                            log.warning("Failed to delete local file %s after upload: %s", p, ex)
                else:
                    mark_pending(fpath_str)
            
            if msg_id:
                first_fp = Path(first[0])
                await dispatch_webhook_notification(
                    f"Album: {len(media_items)} files (First: {first_fp.name})",
                    total_album_size, first[1], first[4], first[5]
                )
            
            if msg_id:
                log.info(f"Uploaded album successfully: {len(media_items)} items")
                GLOBAL_STATUS["today_uploaded"] += len(media_items)
            else:
                log.error(f"Upload album failed: {len(media_items)} items")
            return msg_id
        finally:
            for _, _, item in media_items:
                ACTIVE_UPLOADS.discard(item[0])

    async def _flush() -> None:
        nonlocal buffer
        if not buffer:
            return
        items = buffer
        buffer = []

        albums: dict[Any, list] = defaultdict(list)
        singles: list = []
        for item in items:
            if item[6] is not None:
                albums[item[6]].append(item)
            else:
                singles.append(item)

        for ag_items in albums.values():
            try:
                await _send_album(ag_items)
            except Exception as ae:
                log.error("Failed to upload album in flush cycle: %s", ae)
            await asyncio.sleep(ALBUM_GAP)

        # Parallel upload for singles via gather + semaphore
        if singles:
            upload_tasks = [_send_single_guarded(item) for item in singles]
            results = await asyncio.gather(*upload_tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, Exception):
                    log.error("Parallel upload error: %s", r)

    is_batch = mode.startswith("batch")

    while True:
        try:
            timeout = FLUSH_TIMEOUT if is_batch else 5.0
            try:
                raw_item = await asyncio.wait_for(queue.get(), timeout=timeout)
            except asyncio.TimeoutError:
                if buffer:
                    await _flush()
                continue

            # Unpack PriorityQueue tuple: (priority_key, seq, payload)
            if isinstance(raw_item, tuple) and len(raw_item) == 3:
                _, _, item = raw_item
                if item is None:
                    # Sentinel — shutdown signal
                    if buffer:
                        await _flush()
                    queue.task_done()
                    break
            else:
                item = raw_item  # backward compat with plain Queue
                if item is None:
                    if buffer:
                        await _flush()
                    queue.task_done()
                    break

            buffer.append(item)
            queue.task_done()

            if not is_batch and item[6] is None:
                await _flush()
            if len(buffer) >= ALBUM_SIZE * 2:
                await _flush()

        except asyncio.CancelledError:
            if buffer:
                await _flush()
            break
        except Exception as e:
            log.error("upload_worker: %s", e)
            try:
                queue.task_done()
            except Exception:
                pass


# Batch upload (manual)


async def batch_upload_files(
    client: TelegramClient,
    storage_group_id: int,
    files: list[dict[str, Any]],
    on_progress=None,
) -> dict[str, int]:
    """Upload pending files: album groups → native album, singles → individual."""
    success = failed = skipped = total_size = 0
    total = len(files)

    valid = []
    for bf in files:
        if not Path(bf["filepath"]).exists():
            skipped += 1
            if on_progress:
                on_progress(success + failed + skipped, total, bf.get("filename", "?"), "skipped")
            continue
        if is_uploaded(bf["filepath"]):
            skipped += 1
            if on_progress:
                on_progress(success + failed + skipped, total, bf.get("filename", "?"), "already uploaded")
            continue
        valid.append(bf)

    albums: dict[Any, list[dict]] = defaultdict(list)
    singles: list[dict] = []
    for bf in valid:
        ag = bf.get("album_group")
        if ag is not None:
            albums[ag].append(bf)
        else:
            singles.append(bf)

    processed = 0

    for ag_items in albums.values():
        r = await _upload_album_batch(client, storage_group_id, ag_items, on_progress, processed, total)
        success += r["success"]
        failed += r["failed"]
        total_size += r.get("total_size", 0)
        processed += len(ag_items)
        await asyncio.sleep(ALBUM_GAP)

    for bf in singles:
        r = await _upload_one(client, storage_group_id, bf, on_progress, processed, total)
        if r is not None:
            if r >= 0:
                success += 1
                total_size += r
            else:
                failed += 1
        processed += 1
        await asyncio.sleep(BATCH_DELAY)

    return {"success": success, "failed": failed, "skipped": skipped, "total_size": total_size}


async def _upload_one(client, storage_group_id, bf, on_progress, current, total):
    filepath = Path(bf["filepath"])
    filename = bf.get("filename", filepath.name)
    if not filepath.exists():
        if on_progress:
            on_progress(current + 1, total, filename, "skipped")
        return None

    dt = _parse_date(bf.get("date"))
    file_size = filepath.stat().st_size if filepath.exists() else 0
    cap = build_caption(bf.get("sender_name", "unknown"), bf.get("sender_username"), dt, filename, bf.get("source_group_name", ""), file_size, bf.get("original_caption", ""))

    fh = await _file_hash_async(filepath) if filepath.exists() else None
    
    msg_id = await upload_single(client, storage_group_id, filepath, cap)
    if msg_id:
        mark_uploaded(bf["filepath"], msg_id, file_hash=fh)
        await dispatch_webhook_notification(filename, file_size, bf.get("sender_name", "unknown"), bf.get("source_group_name", ""), bf.get("original_caption", ""))
        if on_progress:
            on_progress(current + 1, total, filename, "ok")
        return file_size
    mark_pending(bf["filepath"])
    if on_progress:
        on_progress(current + 1, total, filename, "failed")
    return -1


async def _upload_album_batch(client, storage_group_id, files, on_progress, base_count, total):
    success = failed = total_size = 0
    media_items = []
    for bf in files:
        fpath = Path(bf["filepath"])
        if not fpath.exists() or is_uploaded(bf["filepath"]):
            continue
        media_items.append((fpath, bf["filepath"], detect_send_type(fpath), bf))

    if not media_items:
        return {"success": 0, "failed": 0, "total_size": 0}

    first_bf = media_items[0][3]
    dt = _parse_date(first_bf.get("date"))
    album_cap = build_caption(first_bf.get("sender_name", "unknown"), first_bf.get("sender_username"), dt, "", first_bf.get("source_group_name", ""), 0, first_bf.get("original_caption", ""), file_total=len(media_items), for_album=True)

    pairs = [(fp, st) for fp, _, st, _ in media_items]
    msg_id = await upload_album(client, storage_group_id, pairs, album_cap)

    total_album_size = 0
    for i, (_, fpath_str, _, bf) in enumerate(media_items):
        if msg_id:
            p = Path(fpath_str)
            total_album_size += p.stat().st_size if p.exists() else 0
            fh = await _file_hash_async(p) if p.exists() else None
            mark_uploaded(fpath_str, msg_id, file_hash=fh)
            sz = Path(fpath_str).stat().st_size if Path(fpath_str).exists() else 0
            total_size += sz
            success += 1
            if on_progress:
                on_progress(base_count + i + 1, total, bf.get("filename", "?"), "ok")
        else:
            mark_pending(fpath_str)
            failed += 1
            if on_progress:
                on_progress(base_count + i + 1, total, bf.get("filename", "?"), "failed")

    if msg_id:
        await dispatch_webhook_notification(
            f"Batch Album: {len(media_items)} files",
            total_album_size, first_bf.get("sender_name", "unknown"), first_bf.get("source_group_name", ""), first_bf.get("original_caption", "")
        )

    return {"success": success, "failed": failed, "total_size": total_size}

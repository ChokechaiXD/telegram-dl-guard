# -*- coding: utf-8 -*-
"""
Uploader — Smart Mode album-aware uploader.
Queue item: (filepath, sender, sender_username, dt, group_name, caption, album_group)
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.tl.types import InputMediaUploadedPhoto, InputMediaUploadedDocument

from upload_tracker import is_uploaded, mark_uploaded, mark_pending
from utils import format_bytes

log = logging.getLogger("guard.uploader")

ALBUM_SIZE = 10
BATCH_DELAY = 1.0
ALBUM_GAP = 2.0
FLUSH_TIMEOUT = 60


# ── Caption ────────────────────────────────────────────────────


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
    import re

    def _tag(text: str) -> str:
        return re.sub(r"[^\w\u0E00-\u0E7F\-]", " ", text).strip()

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
        tags.append(s)
    if tags:
        lines.append(" ".join(tags))

    # Detail lines
    lines.append(f"👤 {sender_name}")
    if sender_username:
        lines.append(f"💬 @{sender_username}")
    if for_album:
        if file_total > 0:
            lines.append(f"🔢 {file_total} รูป")
    else:
        if filename:
            lines.append(f"📁 {filename}")
        if file_size:
            lines.append(f"📦 {format_bytes(file_size)}")
    if original_caption:
        lines.append(f"💬 {original_caption[:300]}")
    if source_group_name:
        lines.append(f"📌 {source_group_name}")
    lines.append(f"📅 {date_str}")
    if file_total > 0 and not for_album:
        lines.append(f"🔢 {file_idx}/{file_total}")

    return "\n".join(lines)


# ── Media type ─────────────────────────────────────────────────


def _detect_send_type(filepath: Path) -> str:
    ext = filepath.suffix.lower()
    if ext in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".svg"}:
        return "photo"
    if ext in {".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv", ".m4v", ".3gp"}:
        return "video"
    return "document"


# ── Upload single ──────────────────────────────────────────────


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
    stype = send_type or _detect_send_type(filepath)
    log.info("upload_single: %s (%s)", filepath.name, stype)

    for attempt in range(3):
        try:
            kwargs: dict[str, Any] = {"file": str(filepath)}
            if caption:
                kwargs["caption"] = caption[:1024]
            if reply_to:
                kwargs["reply_to"] = reply_to
            if stype == "video":
                kwargs["supports_streaming"] = True
            elif stype != "photo":
                kwargs["force_document"] = True
            msg = await client.send_file(storage_group_id, **kwargs)
            return msg.id
        except FloodWaitError as e:
            await asyncio.sleep(e.seconds)
            if attempt == 2:
                return None
        except Exception as e:
            log.error("upload_single: %s", e)
            await asyncio.sleep(2 * (attempt + 1))
            if attempt == 2:
                return None
    return None


# ── Upload album (native) ──────────────────────────────────────


async def upload_album(
    client: TelegramClient,
    storage_group_id: int,
    items: list[tuple[Path, str]],
    caption: str = "",
) -> int | None:
    if not items:
        return None

    chunks = [items[i:i + ALBUM_SIZE] for i in range(0, len(items), ALBUM_SIZE)]
    first_msg_id = None

    for chunk_idx, chunk in enumerate(chunks):
        media_list = []
        for fpath, stype in chunk:
            if not fpath.exists():
                continue
            file_obj = await client.upload_file(str(fpath))
            if stype == "photo":
                media_list.append(InputMediaUploadedPhoto(file=file_obj))
            else:
                media_list.append(InputMediaUploadedDocument(file=file_obj, mime_type="application/octet-stream", attributes=[]))

        if not media_list:
            continue

        kwargs: dict[str, Any] = {}
        if chunk_idx == 0 and caption:
            kwargs["caption"] = caption[:1024]

        try:
            log.info("upload_album: %d files (chunk %d/%d)", len(media_list), chunk_idx + 1, len(chunks))
            msgs = await client.send_file(storage_group_id, file=media_list, **kwargs)
            if msgs:
                first_msg_id = msgs[0].id if isinstance(msgs, list) else msgs.id
        except FloodWaitError as e:
            await asyncio.sleep(e.seconds)
            return None
        except Exception as e:
            log.error("upload_album: %s", e)
            return None

        if chunk_idx < len(chunks) - 1:
            await asyncio.sleep(ALBUM_GAP)

    return first_msg_id


# ── Upload worker (realtime Smart Mode) ───────────────────────


async def upload_worker(
    client: TelegramClient,
    storage_group_id: int,
    queue: asyncio.Queue,
    mode: str = "realtime_keep",
) -> None:
    """Smart Mode upload worker. Queue item: (fp, sender, username, dt, group, caption, album_group)."""
    log.info("upload_worker: Smart Mode (mode=%s)", mode)
    do_delete = mode.endswith("_delete")
    buffer: list[tuple] = []

    async def _send_single(item: tuple) -> int | None:
        fpath_str, sender, username, dt, grp, caption, _ag = item
        fpath = Path(fpath_str)
        if not fpath.exists() or is_uploaded(fpath_str):
            return None
        file_size = fpath.stat().st_size if fpath.exists() else 0
        cap = build_caption(sender, username, dt, fpath.name, grp, file_size, caption)
        msg_id = await upload_single(client, storage_group_id, fpath, cap)
        if msg_id:
            mark_uploaded(fpath_str, msg_id)
            if do_delete and fpath.exists():
                fpath.unlink()
        else:
            mark_pending(fpath_str)
        return msg_id

    async def _send_album(album_items: list[tuple]) -> int | None:
        if not album_items:
            return None
        media_items = []
        for item in album_items:
            fpath = Path(item[0])
            if not fpath.exists() or is_uploaded(item[0]):
                continue
            media_items.append((fpath, _detect_send_type(fpath), item))

        if not media_items:
            return None

        first = album_items[0]
        album_cap = build_caption(first[1], first[2], first[3], "", first[4], 0, first[5], file_total=len(media_items), for_album=True)
        pairs = [(fp, st) for fp, st, _ in media_items]
        msg_id = await upload_album(client, storage_group_id, pairs, album_cap)

        for _, _, item in media_items:
            fpath_str = item[0]
            if msg_id:
                mark_uploaded(fpath_str, msg_id)
                if do_delete:
                    p = Path(fpath_str)
                    if p.exists():
                        p.unlink()
            else:
                mark_pending(fpath_str)
        return msg_id

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
            await _send_album(ag_items)
            await asyncio.sleep(ALBUM_GAP)
        for item in singles:
            await _send_single(item)
            await asyncio.sleep(BATCH_DELAY)

    is_batch = mode.startswith("batch")

    while True:
        try:
            timeout = FLUSH_TIMEOUT if is_batch else 5.0
            try:
                item = await asyncio.wait_for(queue.get(), timeout=timeout)
            except asyncio.TimeoutError:
                if buffer:
                    await _flush()
                continue

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


# ── Batch upload (manual) ─────────────────────────────────────


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

    dt = datetime.strptime(bf.get("date", "2026-01-01 00:00"), "%Y-%m-%d %H:%M") if bf.get("date") else datetime.now()
    file_size = filepath.stat().st_size if filepath.exists() else 0
    cap = build_caption(bf.get("sender_name", "unknown"), bf.get("sender_username"), dt, filename, bf.get("source_group_name", ""), file_size, bf.get("original_caption", ""))

    msg_id = await upload_single(client, storage_group_id, filepath, cap)
    if msg_id:
        mark_uploaded(bf["filepath"], msg_id)
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
        media_items.append((fpath, bf["filepath"], _detect_send_type(fpath), bf))

    if not media_items:
        return {"success": 0, "failed": 0, "total_size": 0}

    first_bf = media_items[0][3]
    dt = datetime.strptime(first_bf.get("date", "2026-01-01 00:00"), "%Y-%m-%d %H:%M") if first_bf.get("date") else datetime.now()
    album_cap = build_caption(first_bf.get("sender_name", "unknown"), first_bf.get("sender_username"), dt, "", first_bf.get("source_group_name", ""), 0, first_bf.get("original_caption", ""), file_total=len(media_items), for_album=True)

    pairs = [(fp, st) for fp, _, st, _ in media_items]
    msg_id = await upload_album(client, storage_group_id, pairs, album_cap)

    for i, (_, fpath_str, _, bf) in enumerate(media_items):
        if msg_id:
            mark_uploaded(fpath_str, msg_id)
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

    return {"success": success, "failed": failed, "total_size": total_size}

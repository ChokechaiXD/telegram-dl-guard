# -*- coding: utf-8 -*-
"""
Download handler — pure helpers for listener.

Module-level globals (DL_DIR, DL_SEM, CFG, _group_name_cache) are set
by listener.run() before any handler fires.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import mimetypes
from datetime import datetime
from pathlib import Path

from telethon.tl.types import (
    DocumentAttributeFilename,
    DocumentAttributeVideo,
    MessageMediaDocument,
    MessageMediaPhoto,
)

from core.state import HashCache, is_hash_exists
from core.utils import sanitize_filename

log = logging.getLogger("guard.listener")

# ── Shared globals (set by listener.run()) ─────────────────────

_hashes = HashCache(max_size=2048)
_sender_cache: dict[int, tuple[str, str | None]] = {}  # sid -> (name, username)
_group_name_cache: dict[int, str] = {}
DL_DIR: Path = Path("downloads")

DL_SEM = None  # type: ignore
CFG = None  # type: ignore


def _cfg():
    assert CFG is not None, "Listener not initialized"
    return CFG


def compute_priority_key(file_size: int, seq: int) -> int:
    prio = CFG.download_priority if CFG else "fifo"
    if prio == "size_asc":
        return file_size
    elif prio == "size_desc":
        return -file_size
    return seq


# ── Helpers ────────────────────────────────────────────────────


def _file_hash(path: Path) -> str | None:
    """SHA256 of file content, cached by path+mtime."""
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    key = f"{path}:{mtime}"
    cached = _hashes.get(key)
    if cached:
        return cached
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        digest = h.hexdigest()
        _hashes.put(key, digest)
        return digest
    except OSError:
        return None


async def _file_hash_async(path: Path) -> str | None:
    """Non-blocking SHA256 hash computation via thread pool."""
    return await asyncio.to_thread(_file_hash, path)


def _dhash(path: Path) -> str | None:
    """Compute 64-bit Difference Hash (dHash) of an image using Pillow."""
    try:
        from PIL import Image
        with Image.open(path) as img:
            img = img.convert("L").resize((9, 8), Image.Resampling.BILINEAR)
            pixels = list(img.getdata())
            diff = []
            for row in range(8):
                for col in range(8):
                    left = pixels[row * 9 + col]
                    right = pixels[row * 9 + col + 1]
                    diff.append(left > right)
            val = 0
            for bit in diff:
                val = (val << 1) | bit
            return f"{val:016x}"
    except Exception:
        return None


async def _dhash_async(path: Path) -> str | None:
    """Non-blocking Difference Hash computation via thread pool."""
    return await asyncio.to_thread(_dhash, path)


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _media_ext(media) -> str:
    if isinstance(media, MessageMediaPhoto):
        return ".jpg"
    if isinstance(media, MessageMediaDocument):
        mt = getattr(media.document, "mime_type", "") or ""
        ext = mimetypes.guess_extension(mt)
        if ext:
            return ext
    return ".mp4"


def _media_name(media, dt: datetime, msg_id: int = 0) -> str:
    """Generate filename from media metadata + timestamp."""
    if isinstance(media, MessageMediaDocument):
        for a in media.document.attributes:
            if isinstance(a, DocumentAttributeFilename):
                return a.file_name
    ext = _media_ext(media)
    did = media.document.id if isinstance(media, MessageMediaDocument) else (msg_id or 0)
    return f"{dt:%Y%m%d_%H%M%S}_{did}{ext}"


def _is_video(m) -> bool:
    return isinstance(m, MessageMediaDocument) and any(
        isinstance(a, DocumentAttributeVideo) for a in m.document.attributes
    )


def _mtype(m) -> str:
    if isinstance(m, MessageMediaPhoto):
        return "photo"
    if _is_video(m):
        return "video"
    if isinstance(m, MessageMediaDocument):
        return "doc"
    return "?"


def _sanitize(s: str) -> str:
    return sanitize_filename(s)




async def _resolve_sender_info(event) -> tuple[str, str | None]:
    """Resolve sender name + username. Cache by sender ID."""
    try:
        s = await event.get_sender()
        if s is None:
            return "unknown", None
        sid = getattr(s, "id", None)

        # Cache hit — return (name, username)
        if sid is not None and sid in _sender_cache:
            return _sender_cache[sid]

        first = getattr(s, "first_name", None) or ""
        last = getattr(s, "last_name", None) or ""
        name = _sanitize(f"{first} {last}".strip())
        if not name:
            name = f"unknown_{sid}" if sid is not None else "unknown"
        username = getattr(s, "username", None)
        username_str = str(username) if username else None

        if sid is not None:
            _sender_cache[sid] = (name, username_str)
        return name, username_str
    except Exception:
        return "unknown", None


def _extract_peer_id(msg) -> int | None:
    try:
        p = msg.peer_id
        return getattr(p, "channel_id", None) or getattr(p, "chat_id", None)
    except Exception:
        return None


async def _resolve_group_name(event) -> str:
    """Resolve group/channel name with caching."""
    try:
        chat = await event.get_chat()
        if chat is None:
            return ""
        gid = getattr(chat, "id", None)
        if gid is not None and gid in _group_name_cache:
            return _group_name_cache[gid]
        name = getattr(chat, "title", "") or ""
        if name and gid is not None:
            _group_name_cache[gid] = name
        return name
    except Exception:
        return ""


async def _resolve_peer_ids(client, groups_str: str) -> set[int]:
    ids: set[int] = set()
    for g in groups_str.split(","):
        g = g.strip()
        if not g:
            continue
        try:
            try:
                entity_key = int(g)
            except ValueError:
                entity_key = g
            e = await client.get_entity(entity_key)
            ids.add(e.id)
            log.info("Group: %s", getattr(e, "title", g))
        except Exception as ex:
            log.warning("Cannot resolve %s: %s", g, ex)
    return ids


def _resolve_download_path(fpath: Path, msize: int | None, msg_id: int) -> Path | None:
    """Decide whether/where to download. Returns None to skip, or Path to write to."""
    cfg = _cfg()
    _ensure_dir(fpath.parent)
    if not fpath.exists():
        return fpath

    # Check duplicate
    is_dup = False
    if fpath.exists():
        if cfg.dedup_method == "hash":
            # Check in-memory cache only (no blocking disk I/O)
            # Full hash is computed async during download, so cache is warm
            fh = _hashes.get(f"{fpath}:{fpath.stat().st_mtime}")
            if fh:
                is_dup = is_hash_exists(fh) or (fh in _hashes) or _hashes.has_value(fh)
            else:
                # Fallback to size check if cache is cold (extremely safe and avoids download)
                if msize is not None:
                    is_dup = fpath.stat().st_size == msize
        elif msize is not None:
            is_dup = fpath.stat().st_size == msize


    if cfg.dedownload == "always":
        fpath.unlink(missing_ok=True)
        return fpath
    if cfg.dedownload == "smart":
        if is_dup:
            return None
        fpath.unlink(missing_ok=True)
        return fpath
    # never
    if is_dup:
        return None
    if cfg.filename_format == "unique":
        return fpath.parent / f"{fpath.stem}_{msg_id}{fpath.suffix}"
    return fpath  # overwrite

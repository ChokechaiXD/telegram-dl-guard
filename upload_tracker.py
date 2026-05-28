"""
Upload tracker — JSON-backed database tracking which files have been uploaded.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from pathlib import Path

log = logging.getLogger("guard.upload_tracker")

_TRACKER_FILE = Path("logs/upload_tracker.json")

# In-memory cache
_cache: dict | None = None
_cache_lock = threading.Lock()

# Debounce save
_save_timer: threading.Timer | None = None
_save_lock = threading.Lock()
_DEBOUNCE_SECONDS = 30


def _data_dir() -> None:
    _TRACKER_FILE.parent.mkdir(parents=True, exist_ok=True)


def _load() -> dict:
    global _cache
    with _cache_lock:
        if _cache is not None:
            return _cache
        if _TRACKER_FILE.exists():
            try:
                _cache = json.loads(_TRACKER_FILE.read_text(encoding="utf-8"))
                return _cache
            except Exception:
                pass
        _cache = {}
        return _cache


def _save(data: dict) -> None:
    global _cache, _save_timer
    with _cache_lock:
        _cache = data

    def _do_save() -> None:
        _data_dir()
        try:
            with _cache_lock:
                current = _cache
            if current is not None:
                _TRACKER_FILE.write_text(json.dumps(current, indent=2, default=str), encoding="utf-8")
        except Exception as e:
            log.error(f"tracker save: {e}")

    with _save_lock:
        if _save_timer is not None:
            _save_timer.cancel()
        _save_timer = threading.Timer(_DEBOUNCE_SECONDS, _do_save)
        _save_timer.daemon = True
        _save_timer.start()


def flush_save() -> None:
    """Force immediate save, cancelling any pending debounced save."""
    global _save_timer
    with _save_lock:
        if _save_timer is not None:
            _save_timer.cancel()
            _save_timer = None
    _data_dir()
    with _cache_lock:
        if _cache is not None:
            try:
                _TRACKER_FILE.write_text(json.dumps(_cache, indent=2, default=str), encoding="utf-8")
            except Exception as e:
                log.error(f"tracker flush save: {e}")


def _key(filepath: str) -> str:
    return str(Path(filepath).resolve())


def is_uploaded(filepath: str) -> bool:
    data = _load()
    entry = data.get(_key(filepath))
    return bool(entry and entry.get("uploaded"))


def mark_uploaded(filepath: str, storage_msg_id: int) -> None:
    data = _load()
    k = _key(filepath)
    data[k] = {
        "uploaded": True,
        "storage_msg_id": storage_msg_id,
        "uploaded_at": datetime.now().isoformat(),
    }
    _save(data)
    log.info(f"upload_tracker: marked uploaded: {Path(filepath).name}")


def mark_pending(filepath: str) -> None:
    data = _load()
    k = _key(filepath)
    if k in data:
        data[k]["uploaded"] = False
    else:
        data[k] = {"uploaded": False, "storage_msg_id": None, "uploaded_at": None}
    _save(data)


def get_pending() -> list[str]:
    data = _load()
    return [k for k, v in data.items() if not v.get("uploaded")]


def get_uploaded() -> list[dict]:
    data = _load()
    results = []
    for filepath, info in data.items():
        if info.get("uploaded"):
            p = Path(filepath)
            size = p.stat().st_size if p.exists() else 0
            results.append({
                "filepath": filepath,
                "filename": p.name,
                "size": size,
                "storage_msg_id": info.get("storage_msg_id"),
                "uploaded_at": info.get("uploaded_at"),
            })
    return results


def remove_entry(filepath: str) -> None:
    data = _load()
    data.pop(_key(filepath), None)
    _save(data)


def cleanup_missing() -> int:
    data = _load()
    to_remove = [k for k in data if not Path(k).exists()]
    for k in to_remove:
        del data[k]
    if to_remove:
        _save(data)
        log.info(f"upload_tracker: cleaned {len(to_remove)} missing entries")
    return len(to_remove)


def scan_downloads(download_dir: str = "downloads") -> list[dict]:
    """
    Scan downloads folder and return all files with upload status.
    Each record: {filepath, filename, size, uploaded, date, storage_msg_id}
    Marks untracked files as pending in tracker.
    """
    data = _load()
    results = []
    dl_path = Path(download_dir)
    if not dl_path.exists():
        return results

    for f in dl_path.rglob("*"):
        if not f.is_file():
            continue
        k = _key(str(f))
        info = data.get(k)
        stat = f.stat()

        # Auto-register untracked files as pending
        if info is None:
            info = {"uploaded": False, "storage_msg_id": None, "uploaded_at": None}
            data[k] = info

        results.append({
            "filepath": str(f),
            "filename": f.name,
            "size": stat.st_size,
            "uploaded": info.get("uploaded", False),
            "date": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
            "storage_msg_id": info.get("storage_msg_id"),
        })

    _save(data)
    return results


def get_all() -> list[dict]:
    """Return all tracked records."""
    data = _load()
    results = []
    for filepath, info in data.items():
        p = Path(filepath)
        size = p.stat().st_size if p.exists() else 0
        results.append({
            "filepath": filepath,
            "filename": p.name,
            "size": size,
            "uploaded": info.get("uploaded", False),
            "date": info.get("uploaded_at", ""),
            "storage_msg_id": info.get("storage_msg_id"),
        })
    return results


def get_stats() -> dict:
    """Return summary: {total, uploaded, pending, total_size}."""
    data = _load()
    uploaded = sum(1 for v in data.values() if v.get("uploaded"))
    pending = sum(1 for v in data.values() if not v.get("uploaded"))
    total_size = sum(Path(k).stat().st_size for k in data if Path(k).exists())
    return {"total": len(data), "uploaded": uploaded, "pending": pending, "total_size": total_size}

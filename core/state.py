"""
State module — persistence for processed message IDs and group cache.
"""

import json
import logging
from collections import OrderedDict
from pathlib import Path

_LOGS_DIR: Path = Path("logs")
_MAX_PROCESSED_IDS: int = 50000

_PROCESSED_IDS_PATH: Path = _LOGS_DIR / "processed_ids.json"
_GROUP_CACHE_PATH: Path = _LOGS_DIR / "group_cache.json"

log = logging.getLogger("guard.state")


def _load_json(path: Path) -> dict | list:
    """Safely load a JSON file; return an empty container on failure."""
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        log.warning("Could not load %s — starting fresh.", path)
        return {}


def _save_json(path: Path, data: dict | list) -> None:
    """Atomically write JSON data to *path*."""
    _LOGS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        tmp.replace(path)
    except Exception:
        log.exception("Failed to save state to %s.", path)
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def load_state() -> tuple[OrderedDict[int, bool], dict[int, str]]:
    """Return *(processed_ids, group_cache)* loaded from disk.

    *processed_ids* is an **OrderedDict** mapping message-id → True,
    capped at *_MAX_PROCESSED_IDS* entries.
    *group_cache* maps group-id → last-known title.
    """
    raw_ids = _load_json(_PROCESSED_IDS_PATH)

    processed_ids: OrderedDict[int, bool] = OrderedDict()
    if isinstance(raw_ids, list):
        for mid in raw_ids:
            processed_ids[int(mid)] = True
    elif isinstance(raw_ids, dict):
        for k, v in raw_ids.items():
            if v:
                processed_ids[int(k)] = True

    # Cap to most recent entries
    while len(processed_ids) > _MAX_PROCESSED_IDS:
        processed_ids.popitem(last=False)

    raw_cache = _load_json(_GROUP_CACHE_PATH)
    group_cache: dict[int, str] = {}
    if isinstance(raw_cache, dict):
        for k, v in raw_cache.items():
            group_cache[int(k)] = str(v)

    log.info(
        "Loaded state — %d processed IDs, %d group entries.",
        len(processed_ids),
        len(group_cache),
    )
    return processed_ids, group_cache


def persist_state(processed_ids: OrderedDict[int, bool], group_cache: dict[int, str]) -> None:
    """Persist *processed_ids* and *group_cache* to disk.

    *processed_ids* is capped to *_MAX_PROCESSED_IDS* before saving
    to prevent unbounded growth.
    """
    # Cap before saving
    ids_list: list[int] = list(processed_ids.keys())
    if len(ids_list) > _MAX_PROCESSED_IDS:
        ids_list = ids_list[-_MAX_PROCESSED_IDS:]

    _save_json(_PROCESSED_IDS_PATH, ids_list)
    _save_json(_GROUP_CACHE_PATH, {str(k): v for k, v in group_cache.items()})

    log.info(
        "Persisted state — %d processed IDs, %d group entries.",
        len(ids_list),
        len(group_cache),
    )

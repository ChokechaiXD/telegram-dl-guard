# -*- coding: utf-8 -*-
"""
State module — SQLite database persistence for processed message IDs, group cache, and upload tracker.
Provides direct callback logging and active download status sharing in memory.
"""
from __future__ import annotations

import os
import json
import sqlite3
import logging
import threading
from datetime import datetime, timedelta
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable

_LOGS_DIR = Path("logs")
_DB_PATH = _LOGS_DIR / "guard.db"

_PROCESSED_IDS_JSON = _LOGS_DIR / "processed_ids.json"
_GROUP_CACHE_JSON = _LOGS_DIR / "group_cache.json"
_TRACKER_JSON = _LOGS_DIR / "upload_tracker.json"

log = logging.getLogger("guard.state")

# Thread safety lock for all SQLite operations
_db_lock = threading.Lock()


def _get_conn() -> sqlite3.Connection:
    """Return a thread-safe connection to the SQLite database with table initialization."""
    _LOGS_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)

    # Performance PRAGMAs
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-2000")    # 2MB RAM cache cap
    conn.execute("PRAGMA temp_store=MEMORY")   # temp tables in RAM

    # Initialize tables if they do not exist
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS processed_messages (
                message_id INTEGER PRIMARY KEY,
                processed_at TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS group_cache (
                group_id INTEGER PRIMARY KEY,
                group_title TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS download_tracker (
                filepath TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                size INTEGER NOT NULL,
                uploaded INTEGER NOT NULL DEFAULT 0,
                storage_msg_id INTEGER,
                uploaded_at TEXT,
                source_group TEXT,
                sender_name TEXT,
                original_caption TEXT,
                file_hash TEXT,
                p_hash TEXT
            )
        """)

        # Migration: Add file_hash if it doesn't exist
        try:
            conn.execute("ALTER TABLE download_tracker ADD COLUMN file_hash TEXT")
        except sqlite3.OperationalError:
            pass

        # Migration: Add p_hash if it doesn't exist
        try:
            conn.execute("ALTER TABLE download_tracker ADD COLUMN p_hash TEXT")
        except sqlite3.OperationalError:
            pass

        # Indexes for fast lookups
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tracker_hash ON download_tracker (file_hash)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tracker_phash ON download_tracker (p_hash)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tracker_uploaded ON download_tracker (uploaded)")

    return conn


# Initialize DB Connection
_conn = _get_conn()


# ── SQLite Auto-Migration from JSON ────────────────────────────

def run_auto_migration() -> None:
    """Read legacy JSON state files, migrate them to SQLite, and safely remove the JSONs."""
    global _conn
    with _db_lock:
        migrated = False
        
        # 1. Migrate Processed IDs
        if _PROCESSED_IDS_JSON.exists():
            try:
                log.info("Migrating legacy processed_ids.json to SQLite...")
                raw_ids = json.loads(_PROCESSED_IDS_JSON.read_text(encoding="utf-8"))
                processed_list = []
                if isinstance(raw_ids, list):
                    processed_list = raw_ids
                elif isinstance(raw_ids, dict):
                    processed_list = [int(k) for k, v in raw_ids.items() if v]
                
                now_str = datetime.now().isoformat()
                with _conn:
                    for mid in processed_list:
                        _conn.execute(
                            "INSERT OR IGNORE INTO processed_messages (message_id, processed_at) VALUES (?, ?)",
                            (int(mid), now_str)
                        )
                _PROCESSED_IDS_JSON.unlink(missing_ok=True)
                log.info("Successfully migrated %d processed IDs.", len(processed_list))
                migrated = True
            except Exception as e:
                log.error("Failed to migrate processed_ids.json: %s", e)

        # 2. Migrate Group Cache
        if _GROUP_CACHE_JSON.exists():
            try:
                log.info("Migrating legacy group_cache.json to SQLite...")
                raw_cache = json.loads(_GROUP_CACHE_JSON.read_text(encoding="utf-8"))
                with _conn:
                    for k, v in raw_cache.items():
                        _conn.execute(
                            "INSERT OR REPLACE INTO group_cache (group_id, group_title) VALUES (?, ?)",
                            (int(k), str(v))
                        )
                _GROUP_CACHE_JSON.unlink(missing_ok=True)
                log.info("Successfully migrated group cache.")
                migrated = True
            except Exception as e:
                log.error("Failed to migrate group_cache.json: %s", e)

        # 3. Migrate Upload Tracker
        if _TRACKER_JSON.exists():
            try:
                log.info("Migrating legacy upload_tracker.json to SQLite...")
                raw_tracker = json.loads(_TRACKER_JSON.read_text(encoding="utf-8"))
                with _conn:
                    for filepath, info in raw_tracker.items():
                        p = Path(filepath)
                        filename = p.name
                        size = p.stat().st_size if p.exists() else 0
                        uploaded = 1 if info.get("uploaded") else 0
                        storage_msg_id = info.get("storage_msg_id")
                        uploaded_at = info.get("uploaded_at")
                        
                        _conn.execute("""
                            INSERT OR REPLACE INTO download_tracker 
                            (filepath, filename, size, uploaded, storage_msg_id, uploaded_at, source_group, sender_name, original_caption)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            str(p.resolve()), filename, size, uploaded, storage_msg_id, uploaded_at,
                            info.get("source_group_name", "unknown"),
                            info.get("sender_name", "unknown"),
                            info.get("original_caption", "")
                        ))
                _TRACKER_JSON.unlink(missing_ok=True)
                log.info("Successfully migrated upload tracker database.")
                migrated = True
            except Exception as e:
                log.error("Failed to migrate upload_tracker.json: %s", e)

        if migrated:
            log.info("Auto-migration complete! Database logs/guard.db is fully populated.")


# Run migration automatically when imported
run_auto_migration()


# ── Processed Message IDs & Group Cache (State) ──────────────

def load_state() -> tuple[OrderedDict[int, bool], dict[int, str]]:
    """Return *(processed_ids, group_cache)* loaded from SQLite."""
    global _conn
    processed_ids: OrderedDict[int, bool] = OrderedDict()
    group_cache: dict[int, str] = {}
    
    with _db_lock:
        try:
            # Load processed IDs
            cursor = _conn.execute("SELECT message_id FROM processed_messages ORDER BY processed_at ASC")
            for row in cursor.fetchall():
                processed_ids[row[0]] = True
                
            # Load group cache
            cursor = _conn.execute("SELECT group_id, group_title FROM group_cache")
            for row in cursor.fetchall():
                group_cache[row[0]] = row[1]
        except Exception as e:
            log.error("Failed to load state from SQLite: %s", e)
            
    log.info("Loaded state from SQLite — %d processed IDs, %d group cache entries.", len(processed_ids), len(group_cache))
    return processed_ids, group_cache


def persist_state(processed_ids: OrderedDict[int, bool], group_cache: dict[int, str]) -> None:
    """Persist processed_ids and group_cache into SQLite."""
    global _conn
    with _db_lock:
        try:
            now_str = datetime.now().isoformat()
            with _conn:
                # Save processed IDs (cap to most recent 50000 in DB to avoid unlimited growth)
                _conn.execute("DELETE FROM processed_messages WHERE message_id NOT IN (SELECT message_id FROM processed_messages ORDER BY processed_at DESC LIMIT 50000)")
                
                # High-performance bulk insert
                mids_data = [(int(mid), now_str) for mid in processed_ids.keys()]
                if mids_data:
                    _conn.executemany(
                        "INSERT OR IGNORE INTO processed_messages (message_id, processed_at) VALUES (?, ?)",
                        mids_data
                    )
                
                # Save group cache in bulk
                groups_data = [(int(gid), str(title)) for gid, title in group_cache.items()]
                if groups_data:
                    _conn.executemany(
                        "INSERT OR REPLACE INTO group_cache (group_id, group_title) VALUES (?, ?)",
                        groups_data
                    )
        except Exception as e:
            log.error("Failed to persist state to SQLite: %s", e)


# ── Single-process In-memory Logging & Status sharing ──────────

# Global shared status updated by listener/uploader and read directly by TUI
GLOBAL_STATUS = {
    "running": False,
    "paused": False,
    "uptime_start": 0.0,
    "processed": 0,
    "user": "?",
    "today_downloaded": 0,
    "today_uploaded": 0,
    "today_failed": 0,
    "today_bytes": 0,
    "recent_activity": []  # List of activity dicts e.g. {"ok": bool, "msg": str}
}

# Shared Asynchronous downloads tracking (msg_id -> progress details)
# Format: {msg_id: {"filename": str, "current": int, "total": int, "speed": str, "eta": str}}
ACTIVE_DOWNLOADS: dict[int, dict[str, Any]] = {}

# In-memory set of filepaths currently in the upload pipeline (downloaded but not yet uploaded/deleted)
ACTIVE_UPLOADS: set[str] = set()

# In-memory mapping of running download tasks (msg_id -> asyncio.Task)
ACTIVE_TASKS: dict[int, Any] = {}


def cancel_active_download(msg_id: int) -> bool:
    """Safely cancel a running download task by message ID."""
    task = ACTIVE_TASKS.get(msg_id)
    if task:
        task.cancel()
        return True
    return False


# Global callback variable to route logs into Textual RichLog
tui_log_callback: Callable[[str, str], None] | None = None


class TuiLogHandler(logging.Handler):
    """Custom logging handler to redirect 'guard' logs straight into Textual RichLog via a callback."""
    def __init__(self) -> None:
        super().__init__()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            level = record.levelname.lower()
            if tui_log_callback:
                tui_log_callback(msg, level)
        except Exception:
            self.handleError(record)


# ── Hash Cache (Evicted LRU) ───────────────────────────────────

class HashCache:
    """Thread-safe LRU cache for file hashes.

    Tracks key -> value mappings with automatic eviction.
    """

    def __init__(self, max_size: int = 2048):
        self._max = max_size
        self._cache: OrderedDict[str, str] = OrderedDict()
        self._lock = threading.Lock()

    def put(self, key: str, value: str) -> None:
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            self._cache[key] = value
            if len(self._cache) > self._max:
                self._cache.popitem(last=False)

    def get(self, key: str) -> str | None:
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
            return None

    def has_value(self, value: str) -> bool:
        with self._lock:
            return value in self._cache.values()

    def __contains__(self, key: str) -> bool:
        with self._lock:
            return key in self._cache

    def __len__(self) -> int:
        with self._lock:
            return len(self._cache)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()


# ── Upload Tracker SQLite Database Engine ───────────────────────


def is_uploaded(filepath: str) -> bool:
    global _conn
    try:
        k = str(Path(filepath).resolve())
        cursor = _conn.execute("SELECT uploaded FROM download_tracker WHERE filepath = ?", (k,))
        row = cursor.fetchone()
        return bool(row and row[0] == 1)
    except Exception as e:
        log.error("SQLite is_uploaded check failed: %s", e)
        return False


def is_hash_exists(file_hash: str) -> bool:
    global _conn
    if not file_hash:
        return False
    try:
        cursor = _conn.execute("SELECT 1 FROM download_tracker WHERE file_hash = ? LIMIT 1", (file_hash,))
        return cursor.fetchone() is not None
    except Exception as e:
        log.error("SQLite is_hash_exists failed: %s", e)
        return False


def is_phash_exists(p_hash: str) -> bool:
    global _conn
    if not p_hash:
        return False
    try:
        cursor = _conn.execute("SELECT 1 FROM download_tracker WHERE p_hash = ? LIMIT 1", (p_hash,))
        return cursor.fetchone() is not None
    except Exception as e:
        log.error("SQLite is_phash_exists failed: %s", e)
        return False


def get_phash_match(p_hash: str, max_distance: int = 3) -> str | None:
    """Find a similar photo in the database based on Hamming distance.
    Returns the filepath of the matched record if found, else None.
    """
    global _conn
    if not p_hash:
        return None
    try:
        cursor = _conn.execute("SELECT filepath, p_hash FROM download_tracker WHERE p_hash IS NOT NULL")
        records = cursor.fetchall()
        for filepath, db_ph in records:
            try:
                dist = bin(int(p_hash, 16) ^ int(db_ph, 16)).count("1")
                if dist <= max_distance:
                    return filepath
            except Exception:
                continue
        return None
    except Exception as e:
        log.error("SQLite get_phash_match failed: %s", e)
        return None


def mark_uploaded(filepath: str, storage_msg_id: int, file_hash: str | None = None, p_hash: str | None = None) -> None:
    global _conn
    with _db_lock:
        try:
            k = str(Path(filepath).resolve())
            p = Path(filepath)
            filename = p.name
            size = p.stat().st_size if p.exists() else 0
            now_str = datetime.now().isoformat()
            
            with _conn:
                _conn.execute("""
                    INSERT OR REPLACE INTO download_tracker 
                    (filepath, filename, size, uploaded, storage_msg_id, uploaded_at, file_hash, p_hash)
                    VALUES (?, ?, ?, 1, ?, ?, COALESCE(?, (SELECT file_hash FROM download_tracker WHERE filepath = ?)), COALESCE(?, (SELECT p_hash FROM download_tracker WHERE filepath = ?)))
                """, (k, filename, size, storage_msg_id, now_str, file_hash, k, p_hash, k))
            log.info(f"upload_tracker SQLite: marked uploaded: {filename}")
        except Exception as e:
            log.error("SQLite mark_uploaded failed: %s", e)


def mark_pending(filepath: str, source_group: str = "unknown", sender_name: str = "unknown", caption: str = "", file_hash: str | None = None, p_hash: str | None = None) -> None:
    global _conn
    with _db_lock:
        try:
            k = str(Path(filepath).resolve())
            p = Path(filepath)
            filename = p.name
            size = p.stat().st_size if p.exists() else 0
            
            with _conn:
                _conn.execute("""
                    INSERT OR REPLACE INTO download_tracker 
                    (filepath, filename, size, uploaded, source_group, sender_name, original_caption, file_hash, p_hash)
                    VALUES (?, ?, ?, 0, ?, ?, ?, COALESCE(?, (SELECT file_hash FROM download_tracker WHERE filepath = ?)), COALESCE(?, (SELECT p_hash FROM download_tracker WHERE filepath = ?)))
                """, (k, filename, size, source_group, sender_name, caption, file_hash, k, p_hash, k))
        except Exception as e:
            log.error("SQLite mark_pending failed: %s", e)


def get_pending() -> list[str]:
    global _conn
    try:
        cursor = _conn.execute("SELECT filepath FROM download_tracker WHERE uploaded = 0")
        return [row[0] for row in cursor.fetchall()]
    except Exception as e:
        log.error("SQLite get_pending failed: %s", e)
        return []


def get_pending_details() -> list[dict]:
    global _conn
    try:
        cursor = _conn.execute("SELECT filepath, sender_name, source_group, original_caption, size, file_hash FROM download_tracker WHERE uploaded = 0")
        results = []
        for row in cursor.fetchall():
            results.append({
                "filepath": row[0],
                "sender_name": row[1] or "unknown",
                "source_group": row[2] or "unknown",
                "original_caption": row[3] or "",
                "size": row[4] or 0,
                "file_hash": row[5]
            })
        return results
    except Exception as e:
        log.error("SQLite get_pending_details failed: %s", e)
        return []



def get_uploaded() -> list[dict]:
    global _conn
    try:
        cursor = _conn.execute("SELECT filepath, filename, size, storage_msg_id, uploaded_at, file_hash FROM download_tracker WHERE uploaded = 1")
        results = []
        for row in cursor.fetchall():
            results.append({
                "filepath": row[0],
                "filename": row[1],
                "size": row[2],
                "storage_msg_id": row[3],
                "uploaded_at": row[4],
                "file_hash": row[5] or ""
            })
        return results
    except Exception as e:
        log.error("SQLite get_uploaded failed: %s", e)
        return []


def remove_entry(filepath: str) -> None:
    global _conn
    with _db_lock:
        try:
            k = str(Path(filepath).resolve())
            with _conn:
                _conn.execute("DELETE FROM download_tracker WHERE filepath = ?", (k,))
        except Exception as e:
            log.error("SQLite remove_entry failed: %s", e)


def cleanup_missing() -> int:
    global _conn
    with _db_lock:
        try:
            cursor = _conn.execute("SELECT filepath FROM download_tracker")
            missing = []
            for row in cursor.fetchall():
                if not Path(row[0]).exists():
                    missing.append(row[0])
                    
            if missing:
                with _conn:
                    _conn.executemany("DELETE FROM download_tracker WHERE filepath = ?", [(k,) for k in missing])
                log.info(f"upload_tracker SQLite: cleaned {len(missing)} missing entries")
            return len(missing)
        except Exception as e:
            log.error("SQLite cleanup_missing failed: %s", e)
            return 0


def scan_downloads(download_dir: str = "downloads") -> list[dict]:
    """Scan downloads directory and sync database records, auto-registering untracked files as pending."""
    global _conn
    dl_path = Path(download_dir)
    results = []
    if not dl_path.exists():
        return results

    # Get a list of all files currently on disk
    files_on_disk = []
    for f in dl_path.rglob("*"):
        if f.is_file():
            files_on_disk.append(f)

    with _db_lock:
        try:
            with _conn:
                for f in files_on_disk:
                    k = str(f.resolve())
                    cursor = _conn.execute("SELECT uploaded, storage_msg_id, uploaded_at FROM download_tracker WHERE filepath = ?", (k,))
                    row = cursor.fetchone()
                    stat = f.stat()
                    
                    if row is None:
                        # Auto-register untracked files as pending
                        _conn.execute("""
                            INSERT INTO download_tracker 
                            (filepath, filename, size, uploaded)
                            VALUES (?, ?, ?, 0)
                        """, (k, f.name, stat.st_size))
                        uploaded = False
                        storage_msg_id = None
                        uploaded_at = None
                    else:
                        uploaded = bool(row[0] == 1)
                        storage_msg_id = row[1]
                        uploaded_at = row[2]

                    results.append({
                        "filepath": k,
                        "filename": f.name,
                        "size": stat.st_size,
                        "uploaded": uploaded,
                        "date": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                        "storage_msg_id": storage_msg_id
                    })
        except Exception as e:
            log.error("SQLite scan_downloads failed: %s", e)
            
    return results


def get_all() -> list[dict]:
    global _conn
    try:
        cursor = _conn.execute("SELECT filepath, filename, size, uploaded, uploaded_at, storage_msg_id, file_hash FROM download_tracker")
        results = []
        for row in cursor.fetchall():
            results.append({
                "filepath": row[0],
                "filename": row[1],
                "size": row[2],
                "uploaded": bool(row[3] == 1),
                "date": row[4] or "",
                "storage_msg_id": row[5],
                "file_hash": row[6] or ""
            })
        return results
    except Exception as e:
        log.error("SQLite get_all failed: %s", e)
        return []


def get_stats() -> dict:
    global _conn
    try:
        cursor = _conn.execute("""
            SELECT 
                COUNT(*),
                SUM(CASE WHEN uploaded = 1 THEN 1 ELSE 0 END),
                SUM(CASE WHEN uploaded = 0 THEN 1 ELSE 0 END),
                COALESCE(SUM(size), 0)
            FROM download_tracker
        """)
        row = cursor.fetchone()
        total = row[0] or 0
        uploaded = row[1] or 0
        pending = row[2] or 0
        total_size = row[3] or 0
                
        return {"total": total, "uploaded": uploaded, "pending": pending, "total_size": total_size}
    except Exception as e:
        log.error("SQLite get_stats failed: %s", e)
        return {"total": 0, "uploaded": 0, "pending": 0, "total_size": 0}


def purge_old_records(msg_days: int = 7, tracker_days: int = 30) -> dict:
    """Delete stale records and VACUUM the database.

    Args:
        msg_days: Remove processed_messages older than this many days.
        tracker_days: Remove uploaded tracker entries older than this many days.

    Returns:
        Dict with counts of purged rows.
    """
    global _conn
    cutoff_msg = (datetime.now() - timedelta(days=msg_days)).isoformat()
    cutoff_tracker = (datetime.now() - timedelta(days=tracker_days)).isoformat()
    purged = {"messages": 0, "tracker": 0}

    with _db_lock:
        try:
            cur = _conn.execute(
                "DELETE FROM processed_messages WHERE processed_at < ?",
                (cutoff_msg,),
            )
            purged["messages"] = cur.rowcount

            cur = _conn.execute(
                "DELETE FROM download_tracker WHERE uploaded = 1 AND uploaded_at < ?",
                (cutoff_tracker,),
            )
            purged["tracker"] = cur.rowcount

            _conn.commit()
            _conn.execute("VACUUM")
            log.info("DB purge done: %s", purged)
        except Exception as e:
            log.error("purge_old_records failed: %s", e)

    return purged

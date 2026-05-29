"""
Cleanup module — periodic removal of old downloaded files.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Callable

from config import AppConfig
from core.state import remove_entry, get_uploaded, purge_old_records

log = logging.getLogger("guard.cleanup")

DL_DIR: Path = Path("downloads")


def sweep_empty_folders(download_dir: str | Path) -> int:
    """Sweep and remove all empty directory hierarchies under download_dir bottom-up."""
    dl_dir = Path(download_dir)
    if not dl_dir.is_dir():
        return 0
    empty_dirs = 0
    for root, dirs, files in os.walk(str(dl_dir), topdown=False):
        for d in dirs:
            dpath = Path(root) / d
            try:
                if not os.listdir(dpath):
                    dpath.rmdir()
                    empty_dirs += 1
            except OSError:
                continue
    return empty_dirs


async def _cleanup_task(get_cfg: Callable) -> None:
    """Periodic cleanup coroutine.

    Sleeps for cleanup_interval_hours then sweeps DL_DIR for files
    older than cleanup_retention_days, unlinking them.
    Runs indefinitely until cancelled.
    """
    cfg: AppConfig = get_cfg()
    if not cfg.cleanup_enabled:
        log.info("Cleanup disabled")
        return

    interval = cfg.cleanup_interval_hours * 3600
    retention = cfg.cleanup_retention_days * 86400.0
    dl_dir = Path(cfg.download_dir)

    log.info(
        "Cleanup: >%sd, every %sh, dir=%s",
        cfg.cleanup_retention_days, cfg.cleanup_interval_hours, dl_dir,
    )

    while True:
        await asyncio.sleep(interval)
        try:
            now = time.time()
            removed = 0
            if not dl_dir.is_dir():
                continue

            # Remove expired files
            for path in dl_dir.rglob("*"):
                if not path.is_file():
                    continue
                try:
                    age = now - path.stat().st_mtime
                    if age > retention:
                        path.unlink()
                        removed += 1
                        try:
                            remove_entry(str(path.resolve()))
                        except Exception as dbe:
                            log.warning("Failed to remove DB entry for deleted file %s: %s", path, dbe)
                except OSError:
                    continue
            
            # Clean up empty directories
            empty_dirs = sweep_empty_folders(dl_dir)
            
            if removed or empty_dirs:
                log.info("Cleanup: removed %d files and %d empty folders", removed, empty_dirs)

            # Purge stale DB records
            purge_old_records()
        except Exception:
            log.exception("Cleanup error")


async def _aggressive_uploaded_cleanup_task() -> None:
    """Aggressively and periodically sweep the disk for files that are already uploaded, 
    deleting them to keep local disk footprint as small as possible.
    """
    await asyncio.sleep(10)  # Let startup settle
    while True:
        try:
            upload_mode = os.getenv("UPLOAD_MODE", "realtime_keep")
            do_delete = os.getenv("UPLOAD_ENABLED", "false") == "true" and upload_mode.endswith("_delete")
            
            if do_delete:
                uploaded_entries = get_uploaded()
                removed = 0
                for entry in uploaded_entries:
                    p = Path(entry["filepath"])
                    if p.exists() and p.is_file():
                        try:
                            p.unlink()
                            removed += 1
                        except OSError as e:
                            # Silently log as debug if locked, will retry next sweep
                            log.debug("Failed to delete uploaded file %s during sweep: %s", p, e)
                
                if removed > 0:
                    log.info("Aggressive cleanup sweep: removed %d uploaded files from local disk", removed)
                    
                    # Also sweep empty directories
                    cfg = AppConfig.load()
                    empty_dirs = sweep_empty_folders(cfg.download_dir)
                    if empty_dirs > 0:
                        log.info("Aggressive cleanup sweep: removed %d empty folders", empty_dirs)
        except Exception:
            log.exception("Error in aggressive uploaded cleanup task")
            
        await asyncio.sleep(300)  # Run every 5 minutes

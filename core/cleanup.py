"""
Cleanup module — periodic removal of old downloaded files.
"""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from config import AppConfig

log = logging.getLogger("guard.cleanup")

DL_DIR: Path = Path("downloads")


async def _cleanup_task(get_cfg: callable) -> None:
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
            for path in dl_dir.rglob("*"):
                if not path.is_file():
                    continue
                age = now - path.stat().st_mtime
                if age > retention:
                    path.unlink()
                    removed += 1
            if removed:
                log.info("Cleanup: removed %d files", removed)
        except Exception:
            log.exception("Cleanup error")

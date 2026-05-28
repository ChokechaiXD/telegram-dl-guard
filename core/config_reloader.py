# -*- coding: utf-8 -*-
"""
Config hot-reload — polls .env/config.yaml and updates shared state.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path

from config import AppConfig

log = logging.getLogger("guard.config_reloader")

_FILES = [Path(".env"), Path("config.yaml")]
_INTERVAL = 5


def _sha(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        return hashlib.md5(path.read_bytes()).hexdigest()
    except OSError:
        return None


class ConfigReloader:
    """Poll config files and update shared state on change."""

    def __init__(self):
        self._prev: dict[str, str | None] = {str(f): _sha(f) for f in _FILES}

    async def start(self) -> None:
        import core.download_handler as dh
        log.info("Config hot-reload active (interval=%ds)", _INTERVAL)

        while True:
            await asyncio.sleep(_INTERVAL)
            for f in _FILES:
                cur = _sha(f)
                if cur is None or cur == self._prev.get(str(f)):
                    continue
                self._prev[str(f)] = cur
                try:
                    new_cfg = AppConfig.load()
                    old_queue = dh.CFG.queue_size if dh.CFG else 3
                    dh.CFG = new_cfg
                    dh.DL_DIR = Path(new_cfg.download_dir)
                    if new_cfg.queue_size != old_queue:
                        dh.DL_SEM = asyncio.Semaphore(max(new_cfg.queue_size, 10))
                    log.info("Hot-reload: queue=%d", new_cfg.queue_size)
                except Exception as e:
                    log.error("Config reload failed: %s", e)

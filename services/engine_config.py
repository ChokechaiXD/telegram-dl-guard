# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EngineConfig:
    target_groups: str
    processing_mode: str
    queue_size: int
    upload_workers: int
    media_types: str
    download_dir: str

    @classmethod
    def from_app_config(cls, cfg) -> "EngineConfig":
        return cls(
            target_groups=cfg.target_groups,
            processing_mode=cfg.processing_mode,
            queue_size=max(1, min(cfg.queue_size, 10)),
            upload_workers=max(1, min(cfg.upload_workers, 5)),
            media_types=cfg.media_types,
            download_dir=cfg.download_dir,
        )

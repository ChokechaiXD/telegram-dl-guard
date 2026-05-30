# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from core.utils import sanitize_group


def build_transfer_path(download_dir: str | Path, group_name: str, sender: str, filename: str) -> Path:
    return Path(download_dir) / sanitize_group(group_name) / sender / filename


def build_transfer_dir(download_dir: str | Path, group_name: str, sender: str) -> Path:
    return Path(download_dir) / sanitize_group(group_name) / sender

"""
Config module — centralizes all configuration loading.
Secrets from .env, non-secrets from config.yaml.
YAML is cached after first read.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

load_dotenv()

_logger = logging.getLogger("guard.config")


def _load_yaml() -> dict[str, Any]:
    """Load YAML once and cache. Returns empty dict on failure."""
    p = Path("config.yaml")
    if not p.exists():
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            return data if isinstance(data, dict) else {}
    except Exception as e:
        _logger.warning("Could not load config.yaml: %s", e)
        return {}


_CFG: dict[str, Any] = _load_yaml()


def _get(env_key: str, yaml_key: str, default: Any = None) -> Any:
    """Read config: .env takes priority over yaml, then default."""
    v = os.getenv(env_key)
    if v is not None:
        return v.strip().strip("'\"")
    return _CFG.get(yaml_key, default)


def _get_bool(env_key: str, yaml_key: str, default: bool = False) -> bool:
    v = _get(env_key, yaml_key, None)
    if v is None:
        return default
    return str(v).lower() in ("true", "1", "yes", "on")


def _F(key: str, default: Any) -> Any:
    """Read nested YAML key using dot notation: 'dedup.method'."""
    keys = key.split(".")
    v = _CFG
    for k in keys:
        if isinstance(v, dict):
            v = v.get(k, default)
        else:
            return default
    return v if v is not None else default


def _safe_int(value: Any, default: int = 0) -> int:
    """Safely convert to int, returns default on failure."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class AppConfig:
    # Secrets (from .env)
    api_id: int = 0
    api_hash: str = ""
    session_string: str = ""

    # Telegram
    target_groups: str = ""
    media_types: str = "photo,video"

    # Paths
    download_dir: str = "./downloads"
    folder_date_format: str = "%Y%m%d_%H%M"

    # Dedup
    dedup_enabled: bool = True
    dedup_method: str = "size"
    dedownload: str = "never"
    filename_format: str = "datetime"

    # History scan
    history_enabled: bool = False
    history_hours: int = 24
    history_mode: str = "list"
    history_reverse: bool = True

    # Queue
    queue_size: int = 3

    # Cleanup
    cleanup_enabled: bool = False
    cleanup_retention_days: int = 30
    cleanup_interval_hours: int = 6

    # Upload
    storage_group_id: str = ""
    upload_enabled: bool = False

    # Filter
    min_file_size: int = 0  # 0 = no filter, in KB
    blocked_senders: str = ""  # comma-separated sender names

    # Display
    show_speed: bool = True
    show_eta: bool = True

    # Log
    log_level: str = "INFO"
    log_file: bool = True

    @classmethod
    def load(cls) -> AppConfig:
        return cls(
            api_id=_safe_int(_get("API_ID", "api_id", 0)),
            api_hash=_get("API_HASH", "api_hash", ""),
            session_string=_get("SESSION_STRING", "session_string", ""),
            target_groups=_get("TARGET_GROUPS", "target_groups", ""),
            media_types=_get("MEDIA_TYPES", "media_types", "photo,video"),
            download_dir=_get("DOWNLOAD_DIR", "download_dir", "./downloads"),
            folder_date_format=_F("folder_date_format", "%Y%m%d_%H%M"),
            dedup_enabled=_F("dedup.enabled", True),
            dedup_method=_F("dedup.method", "size"),
            dedownload=_F("dedup.redownload", "never"),
            filename_format=_F("filename_format", "datetime"),
            history_enabled=_F("history.enabled", False),
            history_hours=_safe_int(_F("history.hours", 24)),
            history_mode=_F("history.mode", "list"),
            history_reverse=_F("history.reverse", True),
            queue_size=_safe_int(_F("download.max_concurrent", 3), 3),
            cleanup_enabled=_F("cleanup.enabled", False),
            cleanup_retention_days=_safe_int(_F("cleanup.retention_days", 30), 30),
            cleanup_interval_hours=_safe_int(_F("cleanup.interval_hours", 6), 6),
            storage_group_id=_get("STORAGE_GROUP_ID", "storage_group_id", ""),
            upload_enabled=_get_bool("UPLOAD_ENABLED", "upload.enabled", False),
            min_file_size=_safe_int(_get("MIN_FILE_SIZE_KB", "filter.min_file_size", 0)),
            blocked_senders=_get("BLOCKED_SENDERS", "filter.blocked_senders", ""),
            show_speed=_get_bool("SHOW_SPEED", _F("display.show_speed", True)),
            show_eta=_get_bool("SHOW_ETA", _F("display.show_eta", True)),
            log_level=_F("log.level", "INFO"),
            log_file=_get_bool("LOG_FILE", _F("log.file", True)),
        )

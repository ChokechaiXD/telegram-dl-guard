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


_yaml_mtime: float = 0.0
_yaml_cache: dict[str, Any] = {}


def _load_yaml() -> dict[str, Any]:
    """Load YAML once and cache, checking file modification time."""
    global _yaml_mtime, _yaml_cache
    p = Path("config.yaml")
    if not p.exists():
        return {}
    try:
        mt = p.stat().st_mtime
        if mt == _yaml_mtime:
            return _yaml_cache
        with open(p, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        _yaml_mtime = mt
        _yaml_cache = data if isinstance(data, dict) else {}
        return _yaml_cache
    except Exception as e:
        _logger.warning("Could not load config.yaml: %s", e)
        return _yaml_cache


_CFG: dict[str, Any] = _load_yaml()


def _get(env_key: str, yaml_key: str, default: Any = None) -> Any:
    """Read config: .env takes priority over yaml, then default."""
    v = os.getenv(env_key)
    if v is not None:
        return v.strip().strip("'\"")
    # Resolve dot-notation into nested dict (e.g. "dedup.enabled" -> _CFG["dedup"]["enabled"])
    node = _CFG
    for part in yaml_key.split("."):
        if isinstance(node, dict):
            node = node.get(part)
        else:
            return default
    return node if node is not None else default


def _get_bool(env_key: str, yaml_key: str, default: bool = False) -> bool:
    v = _get(env_key, yaml_key, None)
    if v is None:
        return default
    return str(v).lower() in ("true", "1", "yes", "on")


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
    
    # Webhook
    webhook_enabled: bool = False
    webhook_url: str = ""

    # Filter
    min_file_size: int = 0  # 0 = no filter, in KB
    max_file_size: int = 0  # 0 = no limit, in MB
    blocked_senders: str = ""  # comma-separated sender names
    super_grabber_mode: bool = False

    # Display
    show_speed: bool = True
    show_eta: bool = True

    # Performance
    upload_workers: int = 3  # concurrent upload slots (1-5)
    download_priority: str = "fifo"  # fifo, size_asc, size_desc

    # Log
    log_level: str = "INFO"
    log_file: bool = True

    @classmethod
    def load(cls) -> AppConfig:
        global _CFG
        _CFG = _load_yaml()
        return cls(
            api_id=_safe_int(_get("API_ID", "api_id", 0)),
            api_hash=_get("API_HASH", "api_hash", ""),
            session_string=_get("SESSION_STRING", "session_string", ""),
            target_groups=_get("TARGET_GROUPS", "target_groups", ""),
            media_types=_get("MEDIA_TYPES", "media_types", "photo,video"),
            download_dir=_get("DOWNLOAD_DIR", "download_dir", "./downloads"),
            folder_date_format=_get("FOLDER_DATE_FORMAT", "folder_date_format", "%Y%m%d_%H%M"),
            dedup_enabled=_get_bool("DEDUP_ENABLED", "dedup.enabled", True),
            dedup_method=_get("DEDUP_METHOD", "dedup.method", "size"),
            dedownload=_get("REDOWNLOAD", "dedup.redownload", "never"),
            filename_format=_get("FILENAME_FORMAT", "filename_format", "datetime"),
            history_enabled=_get_bool("HISTORY_ENABLED", "history.enabled", False),
            history_hours=_safe_int(_get("HISTORY_HOURS", "history.hours", 24)),
            history_mode=_get("HISTORY_MODE", "history.mode", "list"),
            history_reverse=_get_bool("HISTORY_REVERSE", "history.reverse", True),
            queue_size=_safe_int(_get("QUEUE_SIZE", "download.max_concurrent", 3), 3),
            cleanup_enabled=_get_bool("CLEANUP_ENABLED", "cleanup.enabled", False),
            cleanup_retention_days=_safe_int(_get("CLEANUP_RETENTION_DAYS", "cleanup.retention_days", 30), 30),
            cleanup_interval_hours=_safe_int(_get("CLEANUP_INTERVAL_HOURS", "cleanup.interval_hours", 6), 6),
            storage_group_id=_get("STORAGE_GROUP_ID", "storage_group_id", ""),
            upload_enabled=_get_bool("UPLOAD_ENABLED", "upload.enabled", False),
            webhook_enabled=_get_bool("WEBHOOK_ENABLED", "webhook.enabled", False),
            webhook_url=_get("WEBHOOK_URL", "webhook.url", ""),
            min_file_size=_safe_int(_get("MIN_FILE_SIZE_KB", "filter.min_file_size", 0)),
            max_file_size=_safe_int(_get("MAX_FILE_SIZE_MB", "filter.max_file_size", 0)),
            blocked_senders=_get("BLOCKED_SENDERS", "filter.blocked_senders", ""),
            super_grabber_mode=_get_bool("SUPER_GRABBER_MODE", "filter.super_grabber", False),
            show_speed=_get_bool("SHOW_SPEED", "display.show_speed", True),
            show_eta=_get_bool("SHOW_ETA", "display.show_eta", True),
            upload_workers=_safe_int(_get("UPLOAD_WORKERS", "upload.workers", 3), 3),
            download_priority=_get("DOWNLOAD_PRIORITY", "download.priority", "fifo"),
            log_level=_get("LOG_LEVEL", "log.level", "INFO"),
            log_file=_get_bool("LOG_FILE", "log.file", True),
        )

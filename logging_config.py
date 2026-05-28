"""
Logging setup — rotating file handler + console handler.
Levels per module via config.
"""
from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path


def setup_logging(level: str = "INFO", log_file: bool = True, log_dir: str = "logs") -> None:
    """
    Configure root logger for the application.
    - Console: stderr, clean format
    - File: rotating, 5MB x 3 backups, detailed format
    """
    root = logging.getLogger("guard")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove existing handlers to avoid duplicates on re-init
    root.handlers.clear()

    # Console handler
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console_fmt = logging.Formatter("%(asctime)s [%(name)s] %(message)s", datefmt="%H:%M:%S")
    console.setFormatter(console_fmt)
    root.addHandler(console)

    if log_file:
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            Path(log_dir) / "guard.log",
            maxBytes=5 * 1024 * 1024,  # 5MB
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_fmt = logging.Formatter(
            "%(asctime)s [%(name)s] %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )
        file_handler.setFormatter(file_fmt)
        root.addHandler(file_handler)

    # Reduce Telethon noise
    logging.getLogger("telethon").setLevel(logging.WARNING)

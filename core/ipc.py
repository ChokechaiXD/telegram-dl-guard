# -*- coding: utf-8 -*-
"""
IPC module — file-based communication between TUI and listener.
Files live in ~/.hermes/guard/:
  status.json  — listener writes, TUI reads
  command.json — TUI writes, listener reads
  log.json     — listener appends, TUI reads
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

IPC_DIR = Path.home() / ".hermes" / "guard"
STATUS_FILE = IPC_DIR / "status.json"
COMMAND_FILE = IPC_DIR / "command.json"
LOG_FILE = IPC_DIR / "log.json"
MAX_LOG_LINES = 500


def _ensure_dir() -> None:
    IPC_DIR.mkdir(parents=True, exist_ok=True)


# ── Status (listener → TUI) ───────────────────────────────────


def write_status(data: dict[str, Any]) -> None:
    _ensure_dir()
    tmp = STATUS_FILE.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(data, default=str), encoding="utf-8")
        tmp.replace(STATUS_FILE)
    except Exception:
        pass


def read_status() -> dict[str, Any]:
    if not STATUS_FILE.exists():
        return {}
    try:
        data = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


# ── Command (TUI → listener) ──────────────────────────────────


def read_command() -> dict[str, Any] | None:
    if not COMMAND_FILE.exists():
        return None
    try:
        data = json.loads(COMMAND_FILE.read_text(encoding="utf-8"))
        # Consume: delete after read
        COMMAND_FILE.unlink(missing_ok=True)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def write_command(cmd: dict[str, Any]) -> None:
    _ensure_dir()
    try:
        COMMAND_FILE.write_text(json.dumps(cmd, default=str), encoding="utf-8")
    except Exception:
        pass


# ── Log (listener → TUI, append-only) ─────────────────────────


def append_log(message: str, level: str = "info") -> None:
    _ensure_dir()
    try:
        lines = []
        if LOG_FILE.exists():
            raw = LOG_FILE.read_text(encoding="utf-8").strip()
            if raw:
                lines = raw.split("\n")
        entry = json.dumps({"t": time.time(), "level": level, "msg": message}, default=str, ensure_ascii=False)
        lines.append(entry)
        # Trim to max
        if len(lines) > MAX_LOG_LINES:
            lines = lines[-MAX_LOG_LINES:]
        LOG_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception:
        pass


def read_logs(limit: int = 50) -> list[dict[str, Any]]:
    try:
        if not LOG_FILE.is_file():
            return []
        lines = LOG_FILE.read_text(encoding="utf-8").strip().split("\n")
        result = []
        for line in reversed(lines[-limit:]):
            try:
                result.append(json.loads(line))
            except Exception:
                continue
        return list(reversed(result))
    except Exception:
        return []


def clear_log() -> None:
    if LOG_FILE.exists():
        LOG_FILE.unlink(missing_ok=True)

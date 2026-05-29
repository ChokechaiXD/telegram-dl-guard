# -*- coding: utf-8 -*-
"""
Telegram command handler — listener responds to /status /stats /pause /resume.
User sends commands via Telegram DM to themselves.
"""
from __future__ import annotations

import logging
import os
import time

from telethon import events

from config import AppConfig
from core.state import get_stats, GLOBAL_STATUS
from core.utils import format_bytes

log = logging.getLogger("guard.commands")


class CommandHandler:
    """Handles Telegram commands. Register with start(client)."""

    def __init__(self):
        self._paused = False
        self._paused_at: float = 0
        self._processed_total = 0
        self._start_time: float = 0
        self._me_id: int = 0

    def set_user(self, me_id: int) -> None:
        self._me_id = me_id
        self._start_time = time.time()

    def is_paused(self) -> bool:
        return self._paused

    def mark_processed(self) -> None:
        self._processed_total += 1

    async def start(self, client) -> None:
        """Register command handlers on client."""
        @client.on(events.NewMessage(pattern=r"^/(status|stats|pause|resume)\b"))
        async def _on_cmd(event) -> None:
            if event.sender_id != self._me_id:
                return

            cmd = event.pattern_match.group(1)

            if cmd == "status":
                uptime = int(time.time() - self._start_time)
                h, m = divmod(uptime // 60, 60)
                cfg = AppConfig.load()
                status = "Paused" if self._paused else "Running"
                mode = os.getenv("UPLOAD_MODE", "realtime_keep") if cfg.upload_enabled else "OFF"
                await event.reply(
                    f"{status}\n"
                    f"Uptime: {h}h {m}m\n"
                    f"Processed: {self._processed_total}\n"
                    f"Mode: {mode}"
                )

            elif cmd == "stats":
                stats = get_stats()
                await event.reply(
                    f"Storage Stats\n"
                    f"Total: {stats['total']}\n"
                    f"Uploaded: {stats['uploaded']}\n"
                    f"Pending: {stats['pending']}\n"
                    f"Size: {format_bytes(stats['total_size'])}"
                )

            elif cmd == "pause":
                if self._paused:
                    await event.reply("Already paused")
                else:
                    self._paused = True
                    self._paused_at = time.time()
                    GLOBAL_STATUS["paused"] = True
                    await event.reply("Paused")

            elif cmd == "resume":
                if not self._paused:
                    await event.reply("Already running")
                else:
                    self._paused = False
                    GLOBAL_STATUS["paused"] = False
                    paused_for = int(time.time() - self._paused_at)
                    await event.reply(f"Resumed (was paused for {paused_for}s)")

        log.info("Command handlers registered (owner: %s)", self._me_id)

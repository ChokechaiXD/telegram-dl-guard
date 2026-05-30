# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable


FlushCallback = Callable[[int], Awaitable[None]]


class AlbumBuffer:
    def __init__(self, delay: float = 1.5):
        self.delay = delay
        self._items: dict[int, dict] = {}

    def has_group(self, grouped_id: int) -> bool:
        return grouped_id in self._items

    def pop_sorted(self, grouped_id: int) -> tuple[list, object | None]:
        data = self._items.pop(grouped_id, None)
        if not data:
            return [], None
        messages = sorted(data["messages"].values(), key=lambda msg: msg.id)
        return messages, data.get("event")

    def add(self, grouped_id: int, msg, event, flush_callback: FlushCallback) -> None:
        data = self._items.setdefault(grouped_id, {"messages": {}, "event": event, "task": None})
        data["event"] = event
        data["messages"][msg.id] = msg

        old_task = data.get("task")
        if old_task and not old_task.done():
            old_task.cancel()

        data["task"] = asyncio.create_task(self._flush_later(grouped_id, flush_callback))

    async def _flush_later(self, grouped_id: int, flush_callback: FlushCallback) -> None:
        try:
            await asyncio.sleep(self.delay)
            await flush_callback(grouped_id)
        except asyncio.CancelledError:
            return

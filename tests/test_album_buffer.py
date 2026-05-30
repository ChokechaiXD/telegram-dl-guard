# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace

from services.album_buffer import AlbumBuffer


class AlbumBufferTests(unittest.TestCase):
    def test_pop_sorted_deduplicates_message_ids(self) -> None:
        async def run_case():
            buffer = AlbumBuffer(delay=60)

            async def flush(grouped_id: int) -> None:
                return None

            buffer.add(99, SimpleNamespace(id=3), "event", flush)
            buffer.add(99, SimpleNamespace(id=1), "event", flush)
            buffer.add(99, SimpleNamespace(id=3), "event", flush)

            messages, event = buffer.pop_sorted(99)
            for task in asyncio.all_tasks():
                if task is not asyncio.current_task() and not task.done():
                    task.cancel()

            return [msg.id for msg in messages], event

        ids, event = asyncio.run(run_case())

        self.assertEqual(ids, [1, 3])
        self.assertEqual(event, "event")

    def test_flush_callback_runs_after_delay(self) -> None:
        async def run_case():
            buffer = AlbumBuffer(delay=0.01)
            called = []

            async def flush(grouped_id: int) -> None:
                called.append(grouped_id)

            buffer.add(7, SimpleNamespace(id=1), "event", flush)
            await asyncio.sleep(0.05)
            return called

        self.assertEqual(asyncio.run(run_case()), [7])


if __name__ == "__main__":
    unittest.main(verbosity=2)

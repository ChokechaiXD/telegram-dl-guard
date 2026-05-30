# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from core.history import run_history_scan


class FakeHistoryClient:
    def __init__(self) -> None:
        self.yielded = 0

    async def get_entity(self, pid: int):
        return SimpleNamespace(id=pid, title="Group")

    async def iter_messages(self, entity, offset_date=None, reverse=True, limit=None):
        for idx in range(10):
            self.yielded += 1
            yield SimpleNamespace(id=idx, date=datetime.now(timezone.utc), media=None)


class HistoryLimitTests(unittest.TestCase):
    def test_history_scan_stops_at_configured_cap(self) -> None:
        client = FakeHistoryClient()
        cfg = SimpleNamespace(
            history_enabled=True,
            history_hours=24,
            history_mode="list",
            history_reverse=True,
            history_max_messages=2,
            super_grabber_mode=False,
            media_types="photo,video",
            blocked_senders="",
            min_file_size=0,
            max_file_size=0,
            download_dir="./downloads",
            dedup_method="size",
        )

        result = asyncio.run(run_history_scan(
            client=client,
            peer_ids={1},
            cfg=cfg,
            upload_queue=None,
            download_sem=asyncio.Semaphore(1),
            show_speed=False,
        ))

        self.assertEqual(result, 0)
        self.assertLessEqual(client.yielded, 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)

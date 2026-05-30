# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace

from services.group_sync import fetch_group_choices, to_api_rows, to_cache_rows


class FakeClient:
    async def get_dialogs(self, limit=None):
        return [
            SimpleNamespace(id=3, title="zeta", is_group=True, is_channel=False),
            SimpleNamespace(id=-1002, title="Alpha", is_group=False, is_channel=True),
            SimpleNamespace(id=1, title="Direct", is_group=False, is_channel=False),
            SimpleNamespace(id=4, title="", is_group=True, is_channel=False),
        ]


class GroupSyncTests(unittest.TestCase):
    def test_fetch_group_choices_filters_and_sorts(self) -> None:
        groups = asyncio.run(fetch_group_choices(FakeClient()))

        self.assertEqual([g.title for g in groups], ["Alpha", "Untitled", "zeta"])
        self.assertEqual([g.id for g in groups], [-1002, 4, 3])

    def test_group_rows_for_cache_and_api(self) -> None:
        groups = asyncio.run(fetch_group_choices(FakeClient()))

        self.assertEqual(to_cache_rows(groups)[0], (-1002, "Alpha"))
        self.assertEqual(to_api_rows(groups)[0], {"id": "-1002", "title": "Alpha"})


if __name__ == "__main__":
    unittest.main(verbosity=2)

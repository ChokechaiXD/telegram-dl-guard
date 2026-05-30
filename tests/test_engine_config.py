# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest
from types import SimpleNamespace

from services.engine_config import EngineConfig


class EngineConfigTests(unittest.TestCase):
    def test_from_app_config_clamps_worker_counts(self) -> None:
        cfg = SimpleNamespace(
            target_groups="-1001",
            processing_mode="forward",
            queue_size=99,
            upload_workers=99,
            media_types="photo",
            download_dir="./downloads",
        )

        engine = EngineConfig.from_app_config(cfg)

        self.assertEqual(engine.queue_size, 10)
        self.assertEqual(engine.upload_workers, 5)
        self.assertEqual(engine.target_groups, "-1001")

    def test_from_app_config_never_goes_below_one(self) -> None:
        cfg = SimpleNamespace(
            target_groups="",
            processing_mode="download",
            queue_size=0,
            upload_workers=0,
            media_types="photo,video",
            download_dir="./downloads",
        )

        engine = EngineConfig.from_app_config(cfg)

        self.assertEqual(engine.queue_size, 1)
        self.assertEqual(engine.upload_workers, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)

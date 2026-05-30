# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class RegressionTests(unittest.TestCase):
    def test_config_load_reloads_env_overrides(self) -> None:
        import config

        with tempfile.TemporaryDirectory() as td:
            old_cwd = Path.cwd()
            old_env = os.environ.copy()
            try:
                os.chdir(td)
                Path("config.yaml").write_text("download:\n  max_concurrent: 2\n", encoding="utf-8")
                Path(".env").write_text("QUEUE_SIZE=1\n", encoding="utf-8")
                importlib.reload(config)
                self.assertEqual(config.AppConfig.load().queue_size, 1)

                Path(".env").write_text("QUEUE_SIZE=4\n", encoding="utf-8")
                self.assertEqual(config.AppConfig.load().queue_size, 4)
            finally:
                os.chdir(old_cwd)
                os.environ.clear()
                os.environ.update(old_env)
                importlib.reload(config)

    def test_download_path_dedup_and_unique_naming(self) -> None:
        import core.download_handler as dh

        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "file.jpg"
            target.write_bytes(b"abc")

            dh.CFG = SimpleNamespace(dedup_method="size", dedownload="never", filename_format="datetime")
            self.assertIsNone(dh._resolve_download_path(target, 3, 10))

            dh.CFG = SimpleNamespace(dedup_method="size", dedownload="never", filename_format="unique")
            unique = dh._resolve_download_path(target, 4, 10)
            self.assertEqual(unique, target.parent / "file_10.jpg")

            dh.CFG = SimpleNamespace(dedup_method="size", dedownload="always", filename_format="datetime")
            overwrite = dh._resolve_download_path(target, 3, 10)
            self.assertEqual(overwrite, target)
            self.assertFalse(target.exists())

    def test_do_download_respects_low_end_semaphore_and_records_progress(self) -> None:
        import core.download_handler as dh
        import core.state as state
        import listener

        class FakeClient:
            async def download_media(self, media, file, progress_callback=None):
                if progress_callback:
                    progress_callback(1, 3)
                    progress_callback(3, 3)
                Path(file).write_bytes(b"abc")
                return file

        async def run_case() -> bool:
            with tempfile.TemporaryDirectory() as td:
                dh.CFG = SimpleNamespace(
                    dedup_enabled=False,
                    upload_workers=1,
                    download_priority="fifo",
                )
                dh.DL_SEM = asyncio.Semaphore(1)
                state.ACTIVE_DOWNLOADS.clear()
                state.ACTIVE_TASKS.clear()
                before = dict(state.GLOBAL_STATUS)
                try:
                    state.GLOBAL_STATUS["today_downloaded"] = 0
                    state.GLOBAL_STATUS["today_bytes"] = 0
                    state.GLOBAL_STATUS["processed"] = 0
                    state.GLOBAL_STATUS["recent_activity"] = []
                    msg = SimpleNamespace(id=123, media=object(), date=None)
                    ok = await listener._do_download(
                        FakeClient(),
                        msg,
                        Path(td) / "out.jpg",
                        Path(td),
                        "photo",
                        "sender",
                        None,
                        "group",
                        "",
                        None,
                        3,
                        None,
                        "size",
                        False,
                    )
                    self.assertTrue(ok)
                    self.assertEqual(state.GLOBAL_STATUS["today_downloaded"], 1)
                    self.assertEqual(state.GLOBAL_STATUS["today_bytes"], 3)
                    self.assertEqual(state.ACTIVE_DOWNLOADS, {})
                    self.assertEqual(state.ACTIVE_TASKS, {})
                    return ok
                finally:
                    state.GLOBAL_STATUS.clear()
                    state.GLOBAL_STATUS.update(before)

        self.assertTrue(asyncio.run(run_case()))

    def test_static_failure_patterns_do_not_reappear(self) -> None:
        listener_text = (REPO_ROOT / "listener.py").read_text(encoding="utf-8")
        web_text = (REPO_ROOT / "web_server.py").read_text(encoding="utf-8")
        tui_text = (REPO_ROOT / "tui" / "app.py").read_text(encoding="utf-8")

        self.assertNotIn("_sanitize_group", listener_text)
        self.assertNotIn("_pending_tasks -= done", listener_text)
        self.assertNotIn("max(dh.CFG.queue_size, 10)", listener_text)
        self.assertNotIn("max(cfg.queue_size, 10)", web_text)
        self.assertNotIn("priority=True", web_text)
        self.assertNotIn("priority=rule_priority", tui_text)


if __name__ == "__main__":
    unittest.main(verbosity=2)

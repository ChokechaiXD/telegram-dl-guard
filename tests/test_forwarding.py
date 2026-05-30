# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
from types import SimpleNamespace

from telethon.errors import ChatForwardsRestrictedError

from services.forwarding import forward_or_upload, summarize_forward_results


class FakeClient:
    def __init__(self, protected: bool = False, download_ok: bool = True):
        self.protected = protected
        self.download_ok = download_ok

    async def forward_messages(self, storage_entity, msg_id, source_entity):
        if self.protected:
            raise ChatForwardsRestrictedError(request=None)
        return SimpleNamespace(id=777)

    async def download_media(self, media, file):
        if not self.download_ok:
            return None
        path = Path(file) / "media.bin"
        path.write_bytes(b"abc")
        return str(path)


async def fake_upload_single(client, storage_id: int, fpath: Path, caption: str) -> int:
    return 888


class ForwardingTests(unittest.TestCase):
    def test_successful_forward_returns_forward_mode(self) -> None:
        result = asyncio.run(forward_or_upload(
            FakeClient(),
            SimpleNamespace(id=1),
            SimpleNamespace(id=2),
            SimpleNamespace(id=10, media=object()),
            fake_upload_single,
            "caption",
            storage_upload_target=2,
        ))

        self.assertEqual(result, {"mode": "forward", "message_id": 777})

    def test_protected_forward_downloads_and_uploads(self) -> None:
        result = asyncio.run(forward_or_upload(
            FakeClient(protected=True),
            SimpleNamespace(id=1),
            SimpleNamespace(id=2),
            SimpleNamespace(id=10, media=object()),
            fake_upload_single,
            "caption",
            storage_upload_target=2,
        ))

        self.assertEqual(result, {"mode": "fallback", "message_id": 888})

    def test_missing_download_returns_failed_fallback(self) -> None:
        result = asyncio.run(forward_or_upload(
            FakeClient(protected=True, download_ok=False),
            SimpleNamespace(id=1),
            SimpleNamespace(id=2),
            SimpleNamespace(id=10, media=object()),
            fake_upload_single,
            "caption",
        ))

        self.assertEqual(result, {"mode": "fallback", "message_id": None})

    def test_summarize_forward_results(self) -> None:
        summary = summarize_forward_results([
            {"mode": "forward", "message_id": 1},
            {"mode": "fallback", "message_id": 2},
            {"mode": "fallback", "message_id": None},
        ])

        self.assertEqual(summary, {
            "forwarded_items": 1,
            "fallback_uploaded_items": 1,
            "failed_items": 1,
        })


if __name__ == "__main__":
    unittest.main(verbosity=2)

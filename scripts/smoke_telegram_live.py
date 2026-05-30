# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import asyncio
import tempfile
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from telethon import TelegramClient
from telethon.sessions import StringSession

from config import AppConfig
from core.download_handler import _resolve_peer_ids
from services.forwarding import upload_protected_media
from services.group_sync import fetch_group_choices
from uploader import upload_single


async def _connect(cfg: AppConfig) -> TelegramClient:
    client = TelegramClient(
        StringSession(cfg.session_string) if cfg.session_string else StringSession(),
        cfg.api_id,
        cfg.api_hash,
        connection_retries=2,
        retry_delay=1,
        auto_reconnect=False,
    )
    await client.connect()
    if not await client.is_user_authorized():
        raise RuntimeError("Telegram session is not authorized.")
    return client


async def _read_only(client: TelegramClient, cfg: AppConfig) -> None:
    groups = await fetch_group_choices(client)
    print(f"groups_fetched={len(groups)}")
    if cfg.target_groups:
        peer_ids = await _resolve_peer_ids(client, cfg.target_groups)
        print(f"target_groups_resolved={len(peer_ids)}")
    if cfg.storage_group_id:
        storage = await client.get_entity(int(cfg.storage_group_id))
        print(f"storage_group_resolved={getattr(storage, 'id', '?')}")


async def _transfer(client: TelegramClient, cfg: AppConfig) -> None:
    if not cfg.storage_group_id:
        raise RuntimeError("STORAGE_GROUP_ID is required for transfer smoke.")
    storage_id = int(cfg.storage_group_id)
    with tempfile.TemporaryDirectory() as td:
        test_file = Path(td) / "telegram_dl_guard_smoke.txt"
        test_file.write_text("telegram dl guard smoke test\n", encoding="utf-8")
        msg_id = await upload_single(client, storage_id, test_file, "telegram-dl-guard smoke test")
        print(f"upload_ok={bool(msg_id)} message_id={msg_id}")
        if msg_id:
            await client.delete_messages(storage_id, [msg_id])
            print(f"cleanup_deleted={[msg_id]}")


async def _fallback(client: TelegramClient, cfg: AppConfig) -> None:
    if not cfg.storage_group_id:
        raise RuntimeError("STORAGE_GROUP_ID is required for fallback smoke.")
    if not cfg.target_groups:
        raise RuntimeError("TARGET_GROUPS is required for fallback smoke.")

    peer_ids = await _resolve_peer_ids(client, cfg.target_groups)
    if not peer_ids:
        raise RuntimeError("No target groups resolved.")

    storage_id = int(cfg.storage_group_id)
    await client.get_entity(storage_id)
    for peer_id in peer_ids:
        source = await client.get_entity(peer_id)
        async for msg in client.iter_messages(source, limit=50):
            if not msg.media:
                continue
            result = await upload_protected_media(client, storage_id, msg, upload_single, "telegram-dl-guard fallback smoke")
            msg_id = result.get("message_id")
            print(f"fallback_upload_ok={bool(msg_id)} source_peer={peer_id} message_id={msg_id}")
            if msg_id:
                await client.delete_messages(storage_id, [int(msg_id)])
                print(f"cleanup_deleted={[int(msg_id)]}")
            return
    raise RuntimeError("No media message found in TARGET_GROUPS sample.")


async def amain(mode: str) -> int:
    cfg = AppConfig.load()
    client = await _connect(cfg)
    try:
        if mode == "read-only":
            await _read_only(client, cfg)
        elif mode == "transfer":
            await _transfer(client, cfg)
        elif mode == "fallback":
            await _fallback(client, cfg)
        else:
            raise RuntimeError(f"Unknown mode: {mode}")
        return 0
    finally:
        await client.disconnect()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["read-only", "transfer", "fallback"])
    args = parser.parse_args()
    return asyncio.run(amain(args.mode))


if __name__ == "__main__":
    raise SystemExit(main())

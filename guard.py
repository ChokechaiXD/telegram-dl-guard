# -*- coding: utf-8 -*-
"""
Telegram DL Guard — CLI entry point.
Entry point: guard.py [--listen] [--setup]
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

from config import AppConfig
from dotenv import set_key
from core.utils import setup_logging, format_bytes
from telethon import TelegramClient
from telethon.sessions import StringSession

log = logging.getLogger("guard")


def _is_logged_in() -> bool:
    return bool(AppConfig.load().session_string)


def _fmt_groups(target_groups: str) -> str:
    if not target_groups or target_groups == "not set":
        return "not set"
    count = len([g for g in target_groups.split(",") if g.strip()])
    return f"{count} group{'s' if count != 1 else ''}"


def _fmt_upload_mode() -> str:
    enabled = os.getenv("UPLOAD_ENABLED", "false") == "true"
    if not enabled:
        return "OFF"
    mode = os.getenv("UPLOAD_MODE", "realtime_keep")
    labels = {
        "realtime_keep": "RT+Keep",
        "realtime_delete": "RT+Delete",
        "batch_keep": "Batch+Keep",
        "batch_delete": "Batch+Delete",
    }
    return labels.get(mode, mode)


# ── Login ─────────────────────────────────────────────────


async def _do_login() -> None:
    cfg = AppConfig.load()
    phone = input("  Phone (+66...): ").strip()
    if not phone:
        return
    cli = TelegramClient(StringSession(), cfg.api_id, cfg.api_hash)
    await cli.start(phone=phone)
    me = await cli.get_me()
    set_key(".env", "SESSION_STRING", str(cli.session.save()))
    print(f"  [OK] Logged in successfully as: {me.first_name}")
    await cli.disconnect()
    print("  Please restart DL Guard to use new session.")


# ── Start Daemon Listener ───────────────────────────────────


async def _start_listener() -> None:
    from listener import run
    cfg = AppConfig.load()
    print(f"\n{'=' * 40}\n  Telegram DL Guard -- Headless Listener\n{'=' * 40}")
    print(f"  Groups:   {cfg.target_groups}")
    print(f"  Media:    {cfg.media_types}")
    print(f"  Dedup:    {cfg.dedup_method} / redownload={cfg.dedownload}")
    print(f"  Storage:  {cfg.storage_group_id or 'not set'}")
    print(f"  Upload:   {_fmt_upload_mode()}")
    print(f"{'--' * 40}")

    is_interactive = sys.stdin.isatty() and "--listen" not in sys.argv
    while True:
        try:
            await run()
            if not is_interactive:
                print("  Listener exited cleanly. Restarting in 2s...")
                await asyncio.sleep(2)
                continue
        except KeyboardInterrupt:
            print("\n  Stopped.")
            break
        except Exception as e:
            log.error("Listener crashed: %s", e)
            if not is_interactive:
                await asyncio.sleep(5)
                continue

        if not is_interactive:
            break


# ── First Run Setup Wizard ──────────────────────────────────


async def _first_run_wizard() -> None:
    """Guide user through initial setup step by step."""
    print(f"\n{'=' * 45}")
    print("  First-Run Setup Wizard")
    print(f"{'=' * 45}\n")

    cfg = AppConfig.load()

    # Step 1: API credentials
    if not cfg.api_id or not cfg.api_hash:
        print("  Step 1: API Credentials")
        print("  Go to https://my.telegram.org/apps to get API_ID and API_HASH")
        aid = input("  API_ID: ").strip()
        ahash = input("  API_HASH: ").strip()
        if aid and ahash:
            set_key(".env", "API_ID", aid)
            set_key(".env", "API_HASH", ahash)
            print("  [OK] Saved Credentials")
        cfg = AppConfig.load()

    # Step 2: Login
    if not _is_logged_in():
        print("\n  Step 2: Login to Telegram")
        await _do_login()
        cfg = AppConfig.load()

    # Step 3: Storage group
    if not cfg.storage_group_id:
        print("\n  Step 3: Storage Group (where files get uploaded)")
        cli = TelegramClient(StringSession(cfg.session_string), cfg.api_id, cfg.api_hash)
        await cli.start()
        groups = [d async for d in cli.iter_dialogs() if d.is_group or d.is_channel]
        print(f"  Found {len(groups)} groups/channels:")
        for i, g in enumerate(groups):
            mark = " *" if g.is_channel else ""
            title = g.title[:40] if g.title else "(no title)"
            print(f"    [{i + 1:3d}] {g.id}  {title}{mark}")
        sel = input("  Select storage group (number): ").strip()
        if sel.isdigit() and 1 <= int(sel) <= len(groups):
            sid = groups[int(sel) - 1].id
            set_key(".env", "STORAGE_GROUP_ID", str(sid))
            print(f"  [OK] Storage Group Saved: {groups[int(sel) - 1].title}")
        await cli.disconnect()

    # Step 4: Source groups
    if not cfg.target_groups:
        print("\n  Step 4: Source Groups (where to download from)")
        cli = TelegramClient(StringSession(cfg.session_string), cfg.api_id, cfg.api_hash)
        await cli.start()
        groups = [d async for d in cli.iter_dialogs() if d.is_group or d.is_channel]
        print(f"  Toggle groups (comma-separated numbers):")
        for i, g in enumerate(groups):
            title = g.title[:40] if g.title else "(no title)"
            print(f"    [{i + 1:3d}] {g.id}  {title}")
        sel = input("  Select: ").strip()
        ids = []
        for s in sel.split(","):
            s = s.strip()
            if s.isdigit() and 1 <= int(s) <= len(groups):
                ids.append(str(groups[int(s) - 1].id))
        if ids:
            set_key(".env", "TARGET_GROUPS", ",".join(ids))
            print(f"  [OK] {len(ids)} source groups saved")
        await cli.disconnect()

    # Step 5: Upload mode
    mode = os.getenv("UPLOAD_ENABLED", "false")
    if mode != "true":
        print("\n  Step 5: Enable auto-upload?")
        print("  [1] Yes (realtime + keep)  [2] Yes (realtime + delete)")
        print("  [3] Yes (batch + keep)     [4] Yes (batch + delete)")
        print("  [0] No (manual only)")
        sel = input("  > ").strip()
        modes = {"1": "realtime_keep", "2": "realtime_delete", "3": "batch_keep", "4": "batch_delete"}
        if sel in modes:
            set_key(".env", "UPLOAD_ENABLED", "true")
            set_key(".env", "UPLOAD_MODE", modes[sel])
            print(f"  [OK] Upload enabled: {modes[sel]}")

    print(f"\n{'=' * 45}")
    print("  Setup complete! Starting Headless Listener...\n")
    await _start_listener()


async def main() -> None:
    cfg = AppConfig.load()
    if not cfg.api_id or not cfg.api_hash:
        print("Please configure API_ID / API_HASH in your setup or .env")
        await _first_run_wizard()
        return

    if "--listen" in sys.argv or not sys.stdin.isatty():
        await _start_listener()
        return

    if "--setup" in sys.argv:
        await _first_run_wizard()
        return

    # CLI menu cleanup - Redirects directly to start listener
    if not _is_logged_in():
        print("  Initial Login is required. Starting Setup Wizard...")
        await _first_run_wizard()
    else:
        await _start_listener()


if __name__ == "__main__":
    _cfg = AppConfig.load()
    setup_logging(level=_cfg.log_level, log_file=_cfg.log_file)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

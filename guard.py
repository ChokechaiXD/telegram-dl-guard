"""
Telegram DL Guard — CLI entry point.
Entry point: guard.py [--listen]
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

from config import AppConfig
from dotenv import set_key
from logging_config import setup_logging
from utils import format_bytes
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
    from telethon.sync import TelegramClient as TC
    cfg = AppConfig.load()
    phone = input("  Phone (+66...): ").strip()
    if not phone:
        return
    cli = TC(StringSession(), cfg.api_id, cfg.api_hash)
    await cli.start(phone=phone)
    me = await cli.get_me()
    set_key(".env", "SESSION_STRING", str(cli.session.save()))
    print(f"  [OK] {me.first_name}")
    await cli.disconnect()
    print("  Restart to use new session")


# ── Source Groups ──────────────────────────────────────────


async def _list_groups() -> None:
    """Select multiple source groups with checkbox UI."""
    from telethon import TelegramClient
    cfg = AppConfig.load()
    if not cfg.session_string:
        print("  Login first")
        return
    cli = TelegramClient(StringSession(cfg.session_string), cfg.api_id, cfg.api_hash)
    await cli.start()
    groups = [d async for d in cli.iter_dialogs() if d.is_group or d.is_channel]
    if not groups:
        print("  No groups/channels found")
        await cli.disconnect()
        return

    current_ids = set(cfg.target_groups.split(",")) if cfg.target_groups else set()
    selected: set[int] = set()
    for i, g in enumerate(groups):
        if str(g.id) in current_ids:
            selected.add(i)

    while True:
        print("\n  Select source groups (toggle number, Enter = done, c = cancel):\n")
        for i, g in enumerate(groups):
            mark = "x" if i in selected else " "
            title = g.title[:30] if g.title else "(no title)"
            print(f"    [{mark}] [{i + 1:3d}] {g.id}  {title}")

        sel_count = len(selected)
        print(f"\n  Selected: {sel_count} group{'s' if sel_count != 1 else ''}")
        v = input("  Toggle (e.g. 1,3,5) | Enter = done | c = cancel: ").strip()

        if v == "c":
            print("  Cancelled")
            await cli.disconnect()
            return

        if v == "":
            if not selected:
                print("  No groups selected")
                await cli.disconnect()
                return
            print(f"\n  Selected {len(selected)} groups:")
            sel_ids = []
            for i in sorted(selected):
                g = groups[i]
                title = g.title[:30] if g.title else "(no title)"
                print(f"    {g.id}  {title}")
                sel_ids.append(str(g.id))
            confirm = input("\n  Save? [Y/n]: ").strip().lower()
            if confirm == "n":
                print("  Cancelled")
                await cli.disconnect()
                return
            set_key(".env", "TARGET_GROUPS", ",".join(sel_ids))
            print(f"  -> {len(sel_ids)} groups saved")
            await cli.disconnect()
            return

        for p in v.split(","):
            p = p.strip()
            if p.isdigit():
                idx = int(p) - 1
                if 0 <= idx < len(groups):
                    if idx in selected:
                        selected.discard(idx)
                    else:
                        selected.add(idx)


# ── Settings ────────────────────────────────────────────────


def _main_settings() -> None:
    while True:
        cfg = AppConfig.load()
        print(f"\n{'=' * 45}")
        print(f"  Settings")
        print(f"{'=' * 45}")
        print(f"  [1] Source Groups       {_fmt_groups(cfg.target_groups)}")
        print(f"  [2] Storage & Upload    {_fmt_upload_mode()}")
        print(f"  [3] Media & Filters     {cfg.media_types}")
        print(f"  [4] Cleanup             {'ON' if cfg.cleanup_enabled else 'OFF'}")
        print(f"  [b] Batch Upload        upload pending files")
        print(f"  [t] Tinder Picker       pick files with preview")
        print(f"{'--' * 45}")
        print(f"  [0] Back")
        v = input("  > ").strip().lower()

        if v == "0":
            return
        elif v == "1":
            _settings_source_groups()
        elif v == "2":
            _settings_storage_upload()
        elif v == "3":
            _settings_media_filters()
        elif v == "4":
            _settings_cleanup_page()
        elif v == "b":
            _batch_upload_all()
        elif v == "t":
            _tinder_picker()


def _settings_source_groups() -> None:
    cfg = AppConfig.load()
    while True:
        print(f"\n{'--' * 45}")
        print(f"  Source Groups & Queue")
        print(f"{'--' * 45}")
        groups = [g.strip() for g in cfg.target_groups.split(",") if g.strip()]
        print(f"  Groups:   {', '.join(groups) if groups else 'not set'}")
        print(f"  Queue:    {cfg.queue_size} concurrent downloads")
        print(f"")
        print(f"  [1] Change Groups (use main menu [2])")
        print(f"  [2] Change Queue Size (1-10)")
        print(f"  [0] Back")
        v = input("  > ").strip().lower()
        if v == "0":
            return
        elif v == "1":
            print("  Go to main menu > [2] Groups to select source groups.")
            input("  Enter to continue...")
        elif v == "2":
            q = input("  Queue size (1-10): ").strip()
            if q.isdigit() and 1 <= int(q) <= 10:
                set_key(".env", "QUEUE_SIZE", q)
                print(f"  -> {q}")
            else:
                print("  Invalid")


def _settings_storage_upload() -> None:
    cfg = AppConfig.load()
    while True:
        print(f"\n{'--' * 45}")
        print(f"  Storage & Upload")
        print(f"{'--' * 45}")
        print(f"  Storage:  {cfg.storage_group_id or 'not set'}")
        print(f"  Mode:     {_fmt_upload_mode()}")
        print(f"")
        print(f"  [1] Storage Group ID")
        print(f"  [2] Upload Mode")
        print(f"  [0] Back")
        v = input("  > ").strip().lower()
        if v == "0":
            return
        elif v == "1":
            _settings_storage()
        elif v == "2":
            _settings_upload_mode()


def _settings_media_filters() -> None:
    cfg = AppConfig.load()
    while True:
        print(f"\n{'--' * 45}")
        print(f"  Media & Filters")
        print(f"{'--' * 45}")
        print(f"  Media:          {cfg.media_types}")
        print(f"  Dedup:          {cfg.dedup_method}")
        print(f"  Redownload:     {cfg.dedownload}")
        print(f"  Min File Size:  {cfg.min_file_size}KB {'(disabled)' if cfg.min_file_size == 0 else ''}")
        print(f"  Blocked:        {cfg.blocked_senders or 'none'}")
        print(f"")
        print(f"  [1] Media Types")
        print(f"  [2] Dedup Method")
        print(f"  [3] Redownload")
        print(f"  [4] Min File Size")
        print(f"  [5] Blocked Senders")
        print(f"  [0] Back")
        v = input("  > ").strip().lower()
        if v == "0":
            return
        elif v == "1":
            _settings_media_types()
        elif v == "2":
            _settings_dedup()
        elif v == "3":
            _settings_redownload()
        elif v == "4":
            _settings_min_file_size()
        elif v == "5":
            _settings_blocked_senders()


def _settings_cleanup_page() -> None:
    cfg = AppConfig.load()
    while True:
        print(f"\n{'--' * 45}")
        print(f"  Cleanup")
        print(f"{'--' * 45}")
        print(f"  Auto-Cleanup:  {'ON' if cfg.cleanup_enabled else 'OFF'} >{cfg.cleanup_retention_days}d")
        print(f"")
        print(f"  [1] Auto-Cleanup Settings")
        print(f"  [2] Clean Uploaded Files (delete local)")
        print(f"  [0] Back")
        v = input("  > ").strip().lower()
        if v == "0":
            return
        elif v == "1":
            _settings_cleanup()
        elif v == "2":
            _cleanup_local_files()


def _settings_storage() -> None:
    v = input("\n  Storage group/channel ID: ").strip()
    if not v:
        return
    try:
        int(v)
        set_key(".env", "STORAGE_GROUP_ID", v)
        print(f"  -> {v}")
    except ValueError:
        print("  Invalid ID")


def _settings_upload_mode() -> None:
    print(f"\n  [1] Real-time + Keep   [2] Real-time + Delete")
    print(f"  [3] Batch + Keep       [4] Batch + Delete")
    v = input("  > ").strip()
    modes = {"1": "realtime_keep", "2": "realtime_delete", "3": "batch_keep", "4": "batch_delete"}
    if v in modes:
        set_key(".env", "UPLOAD_MODE", modes[v])
        set_key(".env", "UPLOAD_ENABLED", "true")
        print(f"  -> {modes[v]}")


def _settings_media_types() -> None:
    print(f"\n  [1] Photo  [2] Photo+Video  [3] All")
    v = input("  > ").strip()
    p = {"1": "photo", "2": "photo,video", "3": "photo,video,doc"}
    if v in p:
        set_key(".env", "MEDIA_TYPES", p[v])
        print(f"  -> {p[v]}")


def _settings_dedup() -> None:
    print(f"\n  [1] Size (fast)  [2] Hash (accurate)")
    v = input("  > ").strip()
    if v in ("1", "2"):
        m = "size" if v == "1" else "hash"
        set_key(".env", "DEDUP_METHOD", m)
        print(f"  -> {m}")


def _settings_redownload() -> None:
    print(f"\n  [1] Never  [2] Always  [3] Smart")
    v = input("  > ").strip()
    m = {"1": "never", "2": "always", "3": "smart"}
    if v in m:
        set_key(".env", "REDOWNLOAD", m[v])
        print(f"  -> {m[v]}")


def _settings_min_file_size() -> None:
    v = input("  Min file size in KB (0=disabled): ").strip()
    if v.isdigit():
        set_key(".env", "MIN_FILE_SIZE_KB", v)
        print(f"  -> {v}KB")


def _settings_blocked_senders() -> None:
    v = input("  Blocked senders (comma-separated, empty=none): ").strip()
    set_key(".env", "BLOCKED_SENDERS", v)
    print(f"  -> {v or 'none'}")


def _settings_cleanup() -> None:
    v = input("  Enable? [y/N]: ").strip().lower()
    if v == "y":
        set_key(".env", "CLEANUP_ENABLED", "true")
        d = input("  Retention days: ").strip()
        if d.isdigit():
            set_key(".env", "CLEANUP_RETENTION_DAYS", d)
        print("  Enabled")
    else:
        set_key(".env", "CLEANUP_ENABLED", "false")
        print("  Disabled")


def _cleanup_local_files() -> None:
    from upload_tracker import get_uploaded, cleanup_missing, remove_entry
    cleanup_missing()
    uploaded = get_uploaded()
    if not uploaded:
        print("  No uploaded files to clean")
        return
    total = sum(f["size"] for f in uploaded)
    print(f"\n  {len(uploaded)} files ({format_bytes(total)}):")
    for i, f in enumerate(uploaded, 1):
        print(f"    [{i}] {f['filename'][:40]} ({format_bytes(f['size'])})")
    if input(f"  Delete {len(uploaded)} files? [y/N]: ").strip().lower() != "y":
        return
    ok = fail = 0
    for f in uploaded:
        try:
            p = Path(f["filepath"])
            if p.exists():
                p.unlink()
            remove_entry(f["filepath"])
            ok += 1
        except Exception as e:
            print(f"  Failed: {f['filename']}: {e}")
            fail += 1
    print(f"  Deleted {ok}, failed {fail}")


# ── Batch Upload ────────────────────────────────────────────


def _batch_upload_all() -> None:
    """Batch upload all pending files to storage with summary."""
    from upload_tracker import scan_downloads, cleanup_missing
    from config import AppConfig

    cfg = AppConfig.load()
    if not cfg.storage_group_id:
        print("  Storage not set. Settings > Storage & Upload.")
        return

    cleanup_missing()
    files = scan_downloads()
    pending = [f for f in files if not f["uploaded"]]
    if not pending:
        print("  No pending files.")
        return

    # Group by sender for summary
    by_sender: dict[str, list] = {}
    for f in pending:
        p = Path(f["filepath"])
        sender = p.parts[1] if len(p.parts) > 2 else "unknown"
        by_sender.setdefault(sender, []).append(f)

    # Show summary
    print(f"\n{'=' * 50}")
    print(f"  Batch Upload to Storage")
    print(f"{'=' * 50}")
    print(f"  {len(pending)} files ({format_bytes(sum(f['size'] for f in pending))})")
    print(f"  from {len(by_sender)} users:")
    for sender, items in sorted(by_sender.items()):
        sz = format_bytes(sum(f["size"] for f in items))
        print(f"    {sender:<20} {len(items):3d} files  {sz}")
    print(f"{'--' * 50}")
    print(f"  Storage: {cfg.storage_group_id}")
    print(f"")
    print(f"  [1] Upload All    [2] Upload by User    [3] Cancel")
    v = input("  > ").strip()

    if v == "2":
        print(f"\n  Select user:")
        senders = list(by_sender.keys())
        for i, s in enumerate(senders, 1):
            print(f"    [{i}] {s} ({len(by_sender[s])} files)")
        print(f"    [0] Back")
        u = input("  > ").strip()
        if u.isdigit() and 1 <= int(u) <= len(senders):
            _upload_files_list(by_sender[senders[int(u) - 1]], cfg)
        return

    if v != "1":
        print("  Cancelled")
        return

    _upload_files_list(pending, cfg)


def _upload_files_list(files: list[dict], cfg: AppConfig) -> None:
    """Upload a list of files with progress."""
    total_sz = sum(f["size"] for f in files)
    print(f"\n  Uploading {len(files)} files ({format_bytes(total_sz)}) -> {cfg.storage_group_id}")

    def on_progress(cur, total, name, status):
        pct = cur / total * 100 if total else 0
        bar = "#" * int(pct // 5) + "-" * (20 - int(pct // 5))
        icon = {"ok": "[OK]", "failed": "[FAIL]", "skipped": "[SKIP]"}.get(status, "[..]")
        print(f"\r  [{bar}] {cur}/{total} {icon} {name[:30]}", end="", flush=True)

    import asyncio as aio
    from telethon import TelegramClient
    from uploader import batch_upload_files

    async def _do():
        cli = TelegramClient(StringSession(cfg.session_string), cfg.api_id, cfg.api_hash)
        await cli.connect()
        try:
            return await batch_upload_files(cli, int(cfg.storage_group_id), files, on_progress)
        finally:
            await cli.disconnect()

    print()
    result = aio.run(_do())
    print()
    if result:
        print(f"  {result['success']} ok, {result['failed']} failed, {result['skipped']} skipped")
        if result.get("total_size"):
            print(f"  Uploaded: {format_bytes(result['total_size'])}")


# ── Tinder Picker ───────────────────────────────────────────


def _tinder_picker() -> None:
    print("\n  Tinder Picker -- select files with preview")
    if input("  Open browser? [y/N]: ").strip().lower() != "y":
        return
    try:
        from picker import start_picker
        start_picker()
    except ImportError:
        print("  Flask required: pip install Flask")


# ── Listener ────────────────────────────────────────────────


async def _start_listener() -> None:
    from listener import run
    cfg = AppConfig.load()
    print(f"\n{'=' * 40}\n  Telegram DL Guard -- Listener\n{'=' * 40}")
    print(f"  Groups:   {cfg.target_groups}")
    print(f"  Media:    {cfg.media_types}")
    print(f"  Dedup:    {cfg.dedup_method} / redownload={cfg.dedownload}")
    print(f"  Storage:  {cfg.storage_group_id or 'not set'}")
    print(f"  Upload:   {_fmt_upload_mode()}")
    print(f"{'--' * 40}")
    while True:
        try:
            await run()
        except KeyboardInterrupt:
            print("\n  Stopped.")
            break
        except Exception as e:
            log.error("Listener crashed: %s", e)
        print("\n  [r] Restart  [x] Exit")
        if input("  > ").strip().lower() != "r":
            break


# ── Main Menu ───────────────────────────────────────────────


def _show_menu() -> None:
    cfg = AppConfig.load()
    print(f"\n{'=' * 40}\n  Telegram DL Guard\n{'=' * 40}")
    print(f"  Login:    {'[OK]' if _is_logged_in() else '[--]'}")
    print(f"  Groups:   {_fmt_groups(cfg.target_groups)}")
    print(f"  Storage:  {cfg.storage_group_id or 'not set'}")
    print(f"  Upload:   {_fmt_upload_mode()}")
    print(f"{'--' * 40}")
    print("  [1] Login    [2] Groups   [3] Start")
    print("  [4] Settings [5] Restart  [0] Exit")
    if not _is_logged_in() or not cfg.target_groups or not cfg.storage_group_id:
        print("  --- Run: guard.py setup  ---")


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
            from dotenv import set_key
            set_key(".env", "API_ID", aid)
            set_key(".env", "API_HASH", ahash)
            print("  [OK] Saved")
        cfg = AppConfig.load()

    # Step 2: Login
    if not _is_logged_in():
        print("\n  Step 2: Login to Telegram")
        await _do_login()
        cfg = AppConfig.load()

    # Step 3: Storage group
    if not cfg.storage_group_id:
        print("\n  Step 3: Storage Group (where files get uploaded)")
        from telethon.sync import TelegramClient as TC
        cli = TC(StringSession(cfg.session_string), cfg.api_id, cfg.api_hash)
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
            from dotenv import set_key
            set_key(".env", "STORAGE_GROUP_ID", str(sid))
            print(f"  [OK] Storage: {groups[int(sel) - 1].title}")
        await cli.disconnect()

    # Step 4: Source groups
    if not cfg.target_groups:
        print("\n  Step 4: Source Groups (where to download from)")
        from telethon import TelegramClient
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
            from dotenv import set_key
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
            from dotenv import set_key
            set_key(".env", "UPLOAD_ENABLED", "true")
            set_key(".env", "UPLOAD_MODE", modes[sel])
            print(f"  [OK] Upload enabled: {modes[sel]}")

    print(f"\n{'=' * 45}")
    print("  Setup complete! Starting listener...\n")
    await _start_listener()


async def main() -> None:
    cfg = AppConfig.load()
    if not cfg.api_id or not cfg.api_hash:
        print("Set API_ID / API_HASH in .env")
        return
    if "--listen" in sys.argv or not sys.stdin.isatty():
        await _start_listener()
        return
    if "--setup" in sys.argv:
        await _first_run_wizard()
        return
    while True:
        _show_menu()
        c = input("  > ").strip()
        if c == "1":
            await _do_login()
        elif c == "2":
            await _list_groups()
        elif c == "3":
            if not _is_logged_in():
                print("  Login first")
                continue
            await _start_listener()
        elif c == "4":
            _main_settings()
        elif c == "5":
            await _start_listener()
        elif c == "s" or c == "setup":
            await _first_run_wizard()
        elif c == "0":
            return


if __name__ == "__main__":
    # Setup logging before anything else
    _cfg = AppConfig.load()
    setup_logging(level=_cfg.log_level, log_file=_cfg.log_file)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

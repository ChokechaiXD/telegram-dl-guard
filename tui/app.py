# -*- coding: utf-8 -*-
import os
import sys
import time
import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Header, Footer, Static, Button, RichLog, Input, Select, Switch, DirectoryTree, TextArea, Checkbox
from textual.binding import Binding

from config import AppConfig
from dotenv import set_key
from core.state import GLOBAL_STATUS, ACTIVE_DOWNLOADS
from core.utils import format_bytes

from tui.screens import DashboardContainer, SettingsContainer, GalleryContainer, AnalyticsContainer, RulesBuilderContainer, SelectiveDownloaderContainer

class GuardApp(App):
    """Telegram DL Guard — Interactive TUI with dynamic dashboard, gallery, and setup."""

    TITLE = "Telegram DL Guard Dashboard"
    SUB_TITLE = "v3.9 [Premium Mode]"
    CSS_PATH = "styles.css"

    BINDINGS = [
        Binding("s", "cmd_start", "Start"),
        Binding("p", "cmd_pause", "Pause"),
        Binding("r", "cmd_restart", "Restart"),
        Binding("c", "cmd_config", "Toggle Settings"),
        Binding("g", "cmd_gallery", "Toggle Media Gallery"),
        Binding("a", "cmd_analytics", "Toggle Analytics"),
        Binding("l", "cmd_rules", "Toggle Rules Manager"),
        Binding("m", "cmd_selective", "Manual Browser"),
        Binding("q", "quit", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield DashboardContainer(id="dashboard-container")
        yield SettingsContainer(id="settings-container")
        yield GalleryContainer(id="gallery-container")
        yield AnalyticsContainer(id="analytics-container")
        yield RulesBuilderContainer(id="rules-container")
        yield SelectiveDownloaderContainer(id="selective-container")
        yield Footer()

    def on_mount(self) -> None:
        # Guarantee initial state using correct Textual style properties
        self.query_one("#dashboard-container").styles.display = "block"
        self.query_one("#settings-container").styles.display = "none"
        self.query_one("#gallery-container").styles.display = "none"
        self.query_one("#analytics-container").styles.display = "none"
        self.query_one("#rules-container").styles.display = "none"
        self.query_one("#selective-container").styles.display = "none"

        # Bind log callback
        import core.state as cs
        cs.tui_log_callback = self._on_log_received

        # Setup TuiLogHandler for standard logging redirects
        handler = cs.TuiLogHandler()
        formatter = logging.Formatter("%(message)s")
        handler.setFormatter(formatter)
        logging.getLogger("guard").addHandler(handler)
        logging.getLogger("guard").setLevel(logging.INFO)

        # Cache widget references for fast refresh (avoid DOM queries every cycle)
        self._status_widget = self.query_one("#status-text", Static)
        self._stats_widget = self.query_one("#stats-text", Static)
        self._prog_panel = self.query_one("#progress-panel")
        self._prog_box = self.query_one("#active-downloads-box")
        self._log_panel = self.query_one("#log-panel", RichLog)

        # Analytics speed sliding logs
        self._recent_speed_history: list[float] = []

        # Fetched history messages buffer
        self._fetched_messages: dict = {}

        # Rule Editor attributes
        self._rules_list: list = []
        self._editing_rule_index: int | None = None

        # Dirty-check state
        self._last_status = ""
        self._last_stats = ""
        self._prog_visible = False
        self._prog_was_empty = True

        self._refresh_dashboard()
        self.set_interval(2, self._refresh_dashboard)

        # Populate rules.yaml into GUI builder
        self.load_rules_to_ui()

        # Background thread properties
        self._listener_thread = None
        self._background_loop = None
        self.listener_task: asyncio.Task | None = None
        self.client: Any | None = None
        self._is_online = False
        asyncio.create_task(self._monitor_connection())

    async def _monitor_connection(self) -> None:
        while True:
            try:
                if self.client and self._background_loop and self._background_loop.is_running():
                    future = asyncio.run_coroutine_threadsafe(self.client.is_connected(), self._background_loop)
                    self._is_online = await asyncio.wrap_future(future)
                else:
                    self._is_online = False
            except Exception:
                self._is_online = False
            await asyncio.sleep(5)

    def start_listener_engine(self) -> None:
        import threading
        if self._listener_thread and self._listener_thread.is_alive():
            return
            
        self._is_online = False
        
        def run_in_thread():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._background_loop = loop
            try:
                loop.run_until_complete(self.start_listener_engine_async())
            except Exception as ex:
                logging.getLogger("guard").error(f"Background thread loop crashed: {ex}")
            finally:
                loop.close()
                self._background_loop = None
                self._is_online = False
                
        self._listener_thread = threading.Thread(target=run_in_thread, name="TelegramDLGuardEngine", daemon=True)
        self._listener_thread.start()

    async def start_listener_engine_async(self) -> None:
        from telethon import TelegramClient
        from telethon.sessions import StringSession
        from listener import run as run_listener

        cfg = AppConfig.load()
        if not cfg.session_string:
            logging.getLogger("guard").error("No session found. Please log in first via CLI ('python run.py' -> Option 2)")
            return

        self.client = TelegramClient(
            StringSession(cfg.session_string),
            cfg.api_id, cfg.api_hash,
            connection_retries=10, retry_delay=5, auto_reconnect=True,
        )

        try:
            logging.getLogger("guard").info("Connecting to Telegram...")
            await self.client.connect()
            if not await self.client.is_user_authorized():
                logging.getLogger("guard").error("Telegram session is not authorized. Please run login setup first.")
                return

            logging.getLogger("guard").info("Telegram successfully connected!")
            self._is_online = True
            
            # Spawn background listener
            self.listener_task = asyncio.create_task(run_listener(self.client))
            
            # Keep client running in background
            await self.client.run_until_disconnected()
        except asyncio.CancelledError:
            logging.getLogger("guard").info("Listener engine stopped cleanly.")
        except Exception as e:
            logging.getLogger("guard").error(f"Listener engine crashed: {e}")
        finally:
            self._is_online = False
            self.listener_task = None
            if self.client:
                try:
                    await self.client.disconnect()
                except Exception:
                    pass

    async def restart_listener_engine(self) -> None:
        logging.getLogger("guard").info("Restarting Telegram DL Guard Engine...")
        if self.client:
            try:
                if self._background_loop and self._background_loop.is_running():
                    future = asyncio.run_coroutine_threadsafe(self.client.disconnect(), self._background_loop)
                    await asyncio.wrap_future(future)
            except Exception as ex:
                logging.getLogger("guard").warning(f"Error while disconnecting: {ex}")
            self.client = None
            
        self.listener_task = None
        self._background_loop = None
        
        await asyncio.sleep(1.0)
        self.start_listener_engine()

    async def sync_telegram_groups(self) -> None:
        """Fetch all groups/channels Asynchronously, save names to cache and print to Log Panel."""
        if not self.client or not self._background_loop or not self._background_loop.is_running():
            self.notify("Telegram client not connected or logged in.", severity="error", title="Sync Failed")
            return
            
        self.notify("Fetching dialogs from Telegram... (Please check Log Panel)", title="Syncing Groups")
        logging.getLogger("guard").info("🔍 Fetching target groups from Telegram dialogs Asynchronously...")
        
        try:
            # Fetch all dialogues thread-safely
            future = asyncio.run_coroutine_threadsafe(self.client.get_dialogs(), self._background_loop)
            dialogs = await asyncio.wrap_future(future)
            groups = [d for d in dialogs if d.is_group or d.is_channel]
            
            if not groups:
                logging.getLogger("guard").warning("No groups or channels found on this account.")
                return
                
            logging.getLogger("guard").info(f"✨ Found {len(groups)} groups/channels on your Telegram:")
            
            from core.state import _conn, _db_lock
            with _db_lock:
                with _conn:
                    for g in groups:
                        logging.getLogger("guard").info(f"   Group: [bold cyan]{g.title}[/] | ID: [green]{g.id}[/]")
                        _conn.execute("INSERT OR REPLACE INTO group_cache (group_id, group_title) VALUES (?, ?)", (g.id, g.title))
            
            self.notify("Sync complete! Group list printed in the Logs panel.", title="Groups Synced")
        except Exception as e:
            self.notify(f"Sync failed: {e}", severity="error", title="Sync Failed")

    _LOG_STYLES = {
        "error": "bold red",
        "warning": "bold yellow",
        "debug": "dim cyan",
    }

    def _on_log_received(self, msg: str, level: str) -> None:
        try:
            ts = datetime.now().strftime("%H:%M:%S")
            style = self._LOG_STYLES.get(level, "green")
            self.call_from_thread(self._log_panel.write, Text(f"[{ts}] {msg}", style=style))
        except Exception:
            pass

    async def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        """Trigger dynamic preview rendering and details inspector inside the TUI gallery."""
        event.stop()
        fpath = event.path
        
        def generate_ansi_preview(file_p, width: int = 42) -> tuple[Any, str]:
            res_str = ""
            try:
                from PIL import Image
                from rich.text import Text
                img = Image.open(file_p)
                w, h = img.size
                res_str = f"Resolution: {w} x {h}\n"
                aspect = h / w
                height = int(width * aspect * 0.5)
                height = max(height, 5)
                height = min(height, 16)  # Keep it clean
                
                # Resize to target dimensions
                img = img.resize((width, height * 2), Image.Resampling.BILINEAR)
                img = img.convert("RGB")
                
                # Build Rich Text with per-character RGB styles
                preview = Text()
                for y in range(0, height * 2, 2):
                    for x in range(width):
                        r1, g1, b1 = img.getpixel((x, y))
                        r2, g2, b2 = img.getpixel((x, y + 1))
                        preview.append(
                            "\u2580",
                            style=f"rgb({r1},{g1},{b1}) on rgb({r2},{g2},{b2})"
                        )
                    preview.append("\n")
                return preview, res_str
            except Exception as e:
                return f"\n[dim yellow]Preview not available: {e}[/]\n", res_str

        ext = fpath.suffix.lower()
        is_image = ext in (".jpg", ".jpeg", ".png", ".webp", ".bmp")
        is_video = ext in (".mp4", ".mov", ".avi", ".mkv", ".webm")
        
        size_bytes = fpath.stat().st_size
        size_mb = size_bytes / 1_048_576
        
        # Build metadata header
        meta_lines = (
            f"[bold cyan]File Metadata Inspector[/]\n\n"
            f"Filename: [bold]{fpath.name}[/]\n"
            f"Path: {fpath}\n"
            f"Size: {size_mb:.2f} MB ({size_bytes:,} bytes)\n"
            f"Type: {'Image' if is_image else 'Video' if is_video else ext.upper().lstrip('.')}\n"
        )
        
        gallery_info = self.query_one("#gallery-info", Static)
        
        if is_image:
            preview_obj, res_str = await asyncio.to_thread(generate_ansi_preview, fpath)
            meta_lines += res_str
            if isinstance(preview_obj, str):
                # Fallback string (error message)
                gallery_info.update(meta_lines + preview_obj + "\nClick file to open in system viewer.")
            else:
                # Rich Text object -- compose via RichLog-style approach
                from rich.text import Text
                combined = Text()
                combined.append_text(Text.from_markup(meta_lines))
                combined.append("\n")
                combined.append_text(preview_obj)
                combined.append("\nClick file to open in system viewer.")
                gallery_info.update(combined)
        else:
            gallery_info.update(
                meta_lines + "\nClick file to open in system viewer."
            )
        
        def open_file_sync(p):
            import platform
            import subprocess
            import os
            system = platform.system()
            if system == "Windows":
                os.startfile(p)
            elif system == "Darwin":  # macOS
                subprocess.run(["open", str(p)], check=True)
            else:  # Linux / Unix
                subprocess.run(["xdg-open", str(p)], check=True)

        try:
            await asyncio.to_thread(open_file_sync, fpath)
            self.notify(f"Opening: {fpath.name}", title="Media Launcher")
        except Exception as e:
            self.notify(f"Failed to open: {e}", severity="error", title="Launcher Error")

    def toggle_settings(self) -> None:
        dash = self.query_one("#dashboard-container")
        settings = self.query_one("#settings-container")
        gallery = self.query_one("#gallery-container")
        
        if dash.styles.display == "block":
            dash.styles.display = "none"
            gallery.styles.display = "none"
            settings.styles.display = "block"
            self.load_config_to_ui()
            self.title = "Telegram DL Guard Settings"
        else:
            settings.styles.display = "none"
            gallery.styles.display = "none"
            dash.styles.display = "block"
            self.title = "Telegram DL Guard Dashboard"

    async def toggle_gallery(self) -> None:
        dash = self.query_one("#dashboard-container")
        settings = self.query_one("#settings-container")
        gallery = self.query_one("#gallery-container")
        
        if dash.styles.display == "block":
            dash.styles.display = "none"
            settings.styles.display = "none"
            gallery.styles.display = "block"
            
            # Auto-refresh directory tree
            try:
                from core.cleanup import sweep_empty_folders
                cfg = AppConfig.load()
                await asyncio.to_thread(sweep_empty_folders, cfg.download_dir)
                
                tree = self.query_one("#media-tree", DirectoryTree)
                tree.path = cfg.download_dir
            except Exception:
                pass
                
            self.title = "Telegram DL Guard Media Gallery"
        else:
            gallery.styles.display = "none"
            settings.styles.display = "none"
            dash.styles.display = "block"
            self.title = "Telegram DL Guard Dashboard"

    def toggle_analytics(self) -> None:
        dash = self.query_one("#dashboard-container")
        settings = self.query_one("#settings-container")
        gallery = self.query_one("#gallery-container")
        analytics = self.query_one("#analytics-container")
        rules = self.query_one("#rules-container")
        
        if dash.styles.display == "block":
            dash.styles.display = "none"
            settings.styles.display = "none"
            gallery.styles.display = "none"
            rules.styles.display = "none"
            analytics.styles.display = "block"
            self.title = "Telegram DL Guard Visual Analytics"
            asyncio.create_task(self.refresh_analytics_screen())
        else:
            analytics.styles.display = "none"
            settings.styles.display = "none"
            gallery.styles.display = "none"
            rules.styles.display = "none"
            dash.styles.display = "block"
            self.title = "Telegram DL Guard Dashboard"

    def toggle_rules(self) -> None:
        dash = self.query_one("#dashboard-container")
        settings = self.query_one("#settings-container")
        gallery = self.query_one("#gallery-container")
        analytics = self.query_one("#analytics-container")
        rules = self.query_one("#rules-container")
        
        if dash.styles.display == "block":
            dash.styles.display = "none"
            settings.styles.display = "none"
            gallery.styles.display = "none"
            analytics.styles.display = "none"
            rules.styles.display = "block"
            self.title = "Telegram DL Guard Rule Builder"
            self.load_rules_to_ui()
        else:
            rules.styles.display = "none"
            settings.styles.display = "none"
            gallery.styles.display = "none"
            analytics.styles.display = "none"
            dash.styles.display = "block"
            self.title = "Telegram DL Guard Dashboard"

    def toggle_selective(self) -> None:
        dash = self.query_one("#dashboard-container")
        settings = self.query_one("#settings-container")
        gallery = self.query_one("#gallery-container")
        analytics = self.query_one("#analytics-container")
        rules = self.query_one("#rules-container")
        selective = self.query_one("#selective-container")
        
        if dash.styles.display == "block":
            dash.styles.display = "none"
            settings.styles.display = "none"
            gallery.styles.display = "none"
            analytics.styles.display = "none"
            rules.styles.display = "none"
            selective.styles.display = "block"
            self.title = "Telegram DL Guard Manual Browser"
            
            # Populate Target Groups dropdown inside history browser screen
            try:
                import sqlite3
                conn = sqlite3.connect("logs/guard.db")
                cursor = conn.execute("SELECT group_id, group_title FROM group_cache")
                db_groups = cursor.fetchall()
                conn.close()
                
                options = []
                for gid, title in db_groups:
                    options.append((f"{title} ({gid})", str(gid)))
                
                # Also read config groups in case some are not cached yet
                cfg = AppConfig.load()
                active_gids = [g.strip() for g in (cfg.target_groups or "").split(",") if g.strip()]
                cached_gids = [opt[1] for opt in options]
                for gid_str in active_gids:
                    if gid_str not in cached_gids:
                        options.append((f"Group ID: {gid_str}", gid_str))
                
                sel_group = self.query_one("#selective-group-id", Select)
                sel_group.set_options(options)
            except Exception as ex:
                logging.getLogger("guard").warning(f"Failed to populate Target Groups dropdown in manual browser: {ex}")
        else:
            selective.styles.display = "none"
            settings.styles.display = "none"
            gallery.styles.display = "none"
            analytics.styles.display = "none"
            rules.styles.display = "none"
            dash.styles.display = "block"
            self.title = "Telegram DL Guard Dashboard"

    def load_rules_to_ui(self) -> None:
        try:
            from core.rules import load_rules
            self._rules_list = load_rules()
            self.render_rules_list()
        except Exception as ex:
            self.notify(f"Failed to load rules: {ex}", severity="error")

    def render_rules_list(self) -> None:
        try:
            box = self.query_one("#rules-list-box")
            box.remove_children()
            
            if not self._rules_list:
                box.mount(Static("\n[dim]No rules found. Construct one using the editor on the right![/]\n", id="empty-rules-label"))
                return
                
            for idx, r in enumerate(self._rules_list):
                status_text = "Enabled" if r.enabled else "Disabled"
                
                conds = []
                c = r.condition
                if c.media_type: conds.append(f"media={c.media_type}")
                if c.sender: conds.append(f"sender={c.sender}")
                if c.sender_contains: conds.append(f"contains={c.sender_contains}")
                if c.filename_regex: conds.append(f"regex={c.filename_regex}")
                if c.file_size_gt is not None: conds.append(f"size>{c.file_size_gt//1024}KB")
                if c.file_size_lt is not None: conds.append(f"size<{c.file_size_lt//1024}KB")
                if c.source_group: conds.append(f"group={c.source_group}")
                
                acts = []
                a = r.action
                if a.skip: acts.append("SKIP")
                if a.priority: acts.append("PRIORITY")
                if a.tag: acts.append(f"tag={a.tag}")
                if a.move_to: acts.append(f"move={a.move_to}")
                if a.album: acts.append("album")
                
                cond_str = ", ".join(conds) or "Any"
                act_str = ", ".join(acts) or "None"
                
                card_content = (
                    f"[bold cyan]{idx + 1}. {r.name}[/] [dim]({status_text})[/]\n"
                    f"[dim]WHEN:[/] {cond_str} ──> [bold yellow]THEN:[/] {act_str}"
                )
                
                card_text = Static(card_content, classes="rule-card-info")
                btn_up = Button("▲", variant="default", id=f"rule-up-{idx}", classes="btn-rule-arrow")
                btn_down = Button("▼", variant="default", id=f"rule-down-{idx}", classes="btn-rule-arrow")
                btn_edit = Button("Edit", variant="primary", id=f"rule-edit-{idx}", classes="btn-rule-action")
                btn_del = Button("Del", variant="error", id=f"rule-del-{idx}", classes="btn-rule-action")
                
                card_row = Horizontal(
                    card_text, btn_up, btn_down, btn_edit, btn_del,
                    classes="rule-card-row", id=f"rule-card-row-{idx}"
                )
                box.mount(card_row)
        except Exception as e:
            logging.getLogger("guard").error(f"Rule render error: {e}")

    def edit_rule(self, idx: int) -> None:
        try:
            self._editing_rule_index = idx
            rule = self._rules_list[idx]
            
            self.query_one("#rule-name", Input).value = rule.name
            self.query_one("#rule-enabled", Switch).value = rule.enabled
            
            self.query_one("#rule-cond-media", Select).value = rule.condition.media_type or "any"
            self.query_one("#rule-cond-sender", Input).value = rule.condition.sender or ""
            self.query_one("#rule-cond-sender-contains", Input).value = rule.condition.sender_contains or ""
            self.query_one("#rule-cond-regex", Input).value = rule.condition.filename_regex or ""
            
            if rule.condition.file_size_gt is not None:
                self.query_one("#rule-cond-size-op", Select).value = "gt"
                self.query_one("#rule-cond-size-val", Input).value = str(rule.condition.file_size_gt // 1024)
            elif rule.condition.file_size_lt is not None:
                self.query_one("#rule-cond-size-op", Select).value = "lt"
                self.query_one("#rule-cond-size-val", Input).value = str(rule.condition.file_size_lt // 1024)
            else:
                self.query_one("#rule-cond-size-op", Select).value = "any"
                self.query_one("#rule-cond-size-val", Input).value = ""
                
            self.query_one("#rule-cond-group", Input).value = rule.condition.source_group or ""
            
            self.query_one("#rule-act-skip", Switch).value = rule.action.skip
            self.query_one("#rule-act-priority", Switch).value = rule.action.priority
            self.query_one("#rule-act-tag", Input).value = rule.action.tag or ""
            self.query_one("#rule-act-move", Input).value = rule.action.move_to or ""
            self.query_one("#rule-act-album", Switch).value = rule.action.album
            
            self.notify(f"Loaded rule: {rule.name} for editing.")
        except Exception as e:
            self.notify(f"Failed to load rule details: {e}", severity="error")

    def clear_rule_form(self) -> None:
        self._editing_rule_index = None
        self.query_one("#rule-name", Input).value = ""
        self.query_one("#rule-enabled", Switch).value = True
        self.query_one("#rule-cond-media", Select).value = "any"
        self.query_one("#rule-cond-sender", Input).value = ""
        self.query_one("#rule-cond-sender-contains", Input).value = ""
        self.query_one("#rule-cond-regex", Input).value = ""
        self.query_one("#rule-cond-size-op", Select).value = "any"
        self.query_one("#rule-cond-size-val", Input).value = ""
        self.query_one("#rule-cond-group", Input).value = ""
        
        self.query_one("#rule-act-skip", Switch).value = False
        self.query_one("#rule-act-priority", Switch).value = False
        self.query_one("#rule-act-tag", Input).value = ""
        self.query_one("#rule-act-move", Input).value = ""
        self.query_one("#rule-act-album", Switch).value = False

    def save_rule_form(self) -> None:
        name = self.query_one("#rule-name", Input).value.strip()
        if not name:
            self.notify("Rule name cannot be empty.", severity="error")
            return
            
        enabled = self.query_one("#rule-enabled", Switch).value
        
        from core.rules import Rule, RuleCondition, RuleAction
        
        media = self.query_one("#rule-cond-media", Select).value
        media_val = str(media).strip() if (media and str(media) != "Select.BLANK" and media != "any") else None
        
        sender = self.query_one("#rule-cond-sender", Input).value.strip() or None
        sender_contains = self.query_one("#rule-cond-sender-contains", Input).value.strip() or None
        regex = self.query_one("#rule-cond-regex", Input).value.strip() or None
        
        size_op = self.query_one("#rule-cond-size-op", Select).value
        size_val_str = self.query_one("#rule-cond-size-val", Input).value.strip()
        size_bytes = None
        if size_val_str.isdigit():
            size_bytes = int(size_val_str) * 1024
            
        size_gt = size_bytes if size_op == "gt" else None
        size_lt = size_bytes if size_op == "lt" else None
        
        group = self.query_one("#rule-cond-group", Input).value.strip() or None
        
        cond = RuleCondition(
            sender=sender,
            sender_contains=sender_contains,
            filename_regex=regex,
            media_type=media_val,
            file_size_gt=size_gt,
            file_size_lt=size_lt,
            source_group=group
        )
        
        skip = self.query_one("#rule-act-skip", Switch).value
        priority = self.query_one("#rule-act-priority", Switch).value
        tag = self.query_one("#rule-act-tag", Input).value.strip() or None
        move = self.query_one("#rule-act-move", Input).value.strip() or None
        album = self.query_one("#rule-act-album", Switch).value
        
        act = RuleAction(
            skip=skip,
            tag=tag,
            album=album,
            priority=priority,
            move_to=move
        )
        
        new_rule = Rule(name=name, condition=cond, action=act, enabled=enabled)
        
        if self._editing_rule_index is None:
            self._rules_list.append(new_rule)
            self.notify(f"Added new rule: {name}")
        else:
            self._rules_list[self._editing_rule_index] = new_rule
            self.notify(f"Updated rule: {name}")
            self._editing_rule_index = None
            
        self.clear_rule_form()
        self.render_rules_list()

    def apply_rules_to_yaml(self) -> None:
        try:
            from core.rules import save_rules_to_yaml
            save_rules_to_yaml(self._rules_list)
            self.notify("Rules saved successfully! Restarting engine...", title="Rules Builder")
            asyncio.create_task(self.restart_listener_engine())
            self.toggle_rules()
        except Exception as e:
            self.notify(f"Failed to apply rules: {e}", severity="error", title="Rules Builder")

    async def refresh_analytics_screen(self) -> None:
        try:
            import core.state as cs
            from tui.screens.analytics import draw_speed_chart, draw_mime_distribution, draw_7day_volume_chart, draw_system_ratio_metrics
            
            mime_stats = await asyncio.to_thread(cs.get_mime_type_stats)
            daily_stats = await asyncio.to_thread(cs.get_daily_stats_last_7_days)
            ratio_stats = await asyncio.to_thread(cs.get_system_ratio_stats)
            
            speed_spark = draw_speed_chart(self._recent_speed_history)
            mime_content = draw_mime_distribution(mime_stats)
            volume_content = draw_7day_volume_chart(daily_stats)
            ratio_content = draw_system_ratio_metrics(ratio_stats)
            
            self.query_one("#chart-speed-spark", Static).update(speed_spark)
            self.query_one("#chart-mime-dist", Static).update(mime_content)
            self.query_one("#chart-volume-history", Static).update(volume_content)
            self.query_one("#chart-ratio-metrics", Static).update(ratio_content)
        except Exception as e:
            logging.getLogger("guard").error(f"Failed to refresh analytics screen: {e}")

    async def fetch_history_media(self) -> None:
        if not self.client or not self._background_loop or not self._background_loop.is_running():
            self.notify("Telegram client not connected or logged in.", severity="error", title="Fetch Failed")
            return
            
        group_id_val = self.query_one("#selective-group-id", Select).value
        group_id_str = str(group_id_val).strip() if (group_id_val and str(group_id_val) != "Select.BLANK" and group_id_val != getattr(Select, "BLANK", None)) else ""
        if not group_id_str:
            self.notify("Please select a target group first.", severity="warning", title="Fetch Failed")
            return
            
        try:
            group_id = int(group_id_str)
        except ValueError:
            self.notify("Invalid group ID format.", severity="error")
            return

        limit_str = self.query_one("#selective-limit", Input).value.strip()
        limit = int(limit_str) if (limit_str.isdigit() and int(limit_str) > 0) else 50

        media_filter = self.query_one("#selective-media-filter", Select).value
        media_filter_str = str(media_filter).strip() if (media_filter and str(media_filter) != "Select.BLANK" and media_filter != getattr(Select, "BLANK", None)) else "all"

        search_query = self.query_one("#selective-search-query", Input).value.strip() or None

        self.notify("Fetching history media... Check log panel for details.", title="History Browser")
        logging.getLogger("guard").info(f"🔍 Fetching past {limit} messages from group ID: {group_id}...")

        # Run history fetching thread-safely
        async def fetch_messages_async():
            entity = await self.client.get_entity(group_id)
            messages = []
            
            # Map Telethon client messages
            async for msg in self.client.iter_messages(entity, limit=limit, search=search_query):
                if not msg.media:
                    continue
                
                from core.download_handler import _mtype
                mt = _mtype(msg.media)
                if media_filter_str != "all" and mt != media_filter_str:
                    continue
                    
                messages.append(msg)
            return messages

        try:
            future = asyncio.run_coroutine_threadsafe(fetch_messages_async(), self._background_loop)
            messages = await asyncio.wrap_future(future)
            
            box = self.query_one("#selective-media-list")
            box.remove_children()
            
            self._fetched_messages = {}
            
            if not messages:
                box.mount(Static("\n[dim]No matching media messages found in this group.[/]\n"))
                self.notify("Fetch completed. No media found.", severity="warning", title="History Browser")
                return
                
            from core.download_handler import _media_name, _resolve_sender_info
            from core.utils import format_bytes
            
            for idx, msg in enumerate(messages):
                self._fetched_messages[msg.id] = msg
                
                from core.download_handler import _mtype
                mt = _mtype(msg.media)
                
                # Fetch sender info safely
                sender, _ = await _resolve_sender_info(msg)
                
                # Filename and size
                fname = _media_name(msg.media, msg.date, msg.id)
                fsize = getattr(getattr(msg.media, "document", None), "size", 0) or 0
                size_str = format_bytes(fsize) if fsize else "Unknown"
                
                date_str = msg.date.strftime("%Y-%m-%d %H:%M") if msg.date else "?"
                
                content = (
                    f"[bold cyan]{idx + 1}. {fname[:36]}[/] [dim]({size_str})[/]\n"
                    f"[dim]Sender:[/] {sender} | [dim]Date:[/] {date_str} | [dim]Format:[/] {mt.upper()}"
                )
                
                card_text = Static(content, classes="rule-card-info")
                checkbox = Checkbox(value=False, id=f"grp_check_{msg.id}")
                
                row = Horizontal(
                    checkbox, card_text,
                    classes="rule-card-row selective-row", id=f"sel-row-{msg.id}"
                )
                box.mount(row)
                
            self.notify(f"Successfully fetched {len(messages)} media files!", title="History Browser")
            logging.getLogger("guard").info(f"✨ Successfully retrieved {len(messages)} media messages from group.")
        except Exception as e:
            self.notify(f"Fetch failed: {e}", severity="error", title="History Browser")
            logging.getLogger("guard").error(f"Failed to fetch history: {e}")

    async def download_selected_media(self) -> None:
        if not self.client or not self._background_loop or not self._background_loop.is_running():
            self.notify("Telegram client not connected.", severity="error")
            return
            
        box = self.query_one("#selective-media-list")
        checked_ids = []
        for chk in box.query(Checkbox):
            if chk.value:
                msg_id = int(chk.id.replace("grp_check_", ""))
                checked_ids.append(msg_id)
                
        if not checked_ids:
            self.notify("Please select at least one media file to download.", severity="warning", title="Selective Downloader")
            return
            
        self.notify(f"Queueing {len(checked_ids)} manual downloads...", title="Selective Downloader")
        logging.getLogger("guard").info(f"📥 Queueing {len(checked_ids)} manual historical downloads...")
        
        # Load CFG and directories
        import core.download_handler as dh
        from listener import _do_download
        
        cfg = dh.CFG or AppConfig.load()
        ddir = Path(cfg.download_dir)
        
        # Retrieve target group details
        group_id_val = self.query_one("#selective-group-id", Select).value
        group_id_str = str(group_id_val).strip() if (group_id_val and str(group_id_val) != "Select.BLANK" and group_id_val != getattr(Select, "BLANK", None)) else ""
        
        try:
            import sqlite3
            conn = sqlite3.connect("logs/guard.db")
            cursor = conn.execute("SELECT group_title FROM group_cache WHERE group_id = ?", (group_id_str,))
            row = cursor.fetchone()
            conn.close()
            group_title = row[0] if row else group_id_str
        except Exception:
            group_title = group_id_str
            
        from core.utils import sanitize_group
        from core.state import UPLOAD_QUEUE
        
        # Run downloading in the background thread safely
        async def run_manual_downloads():
            downloaded = 0
            for mid in checked_ids:
                msg = self._fetched_messages.get(mid)
                if not msg:
                    continue
                    
                from core.download_handler import _mtype, _media_name, _resolve_sender_info, _resolve_download_path
                mt = _mtype(msg.media)
                sender, username = await _resolve_sender_info(msg)
                
                # Check target path
                target_dir = ddir / sanitize_group(group_title) / sender
                fname = _media_name(msg.media, msg.date, msg.id)
                fpath = target_dir / fname
                
                # Check rules or standard paths
                original_caption = (getattr(msg, "message", None) or "").strip()
                rule_priority = False
                
                if dh._rules and not getattr(cfg, "super_grabber_mode", False):
                    from core.rules import evaluate_rules
                    fsize = getattr(getattr(msg.media, "document", None), "size", 0) or 0
                    rule_action = evaluate_rules(dh._rules, sender, fname, mt, fsize, group_title)
                    if rule_action:
                        if rule_action.skip:
                            continue
                        rule_priority = rule_action.priority
                        if rule_action.tag:
                            if original_caption and f"#{rule_action.tag}" not in original_caption:
                                original_caption = f"{original_caption} #{rule_action.tag}".strip()
                        if rule_action.move_to:
                            from core.rules import move_to_folder
                            fpath = move_to_folder(fpath, rule_action.move_to)
                            
                fpath = _resolve_download_path(fpath, getattr(getattr(msg.media, "document", None), "size", 0) or None, msg.id)
                if fpath is None:
                    continue  # duplicate
                    
                # Standard download
                ok = await _do_download(
                    self.client, msg, fpath, fpath.parent, mt, sender, username,
                    group_title, original_caption, None,
                    getattr(getattr(msg.media, "document", None), "size", 0) or 0,
                    UPLOAD_QUEUE, cfg.dedup_method, cfg.show_speed,
                    priority=rule_priority
                )
                if ok:
                    downloaded += 1
            return downloaded

        try:
            # Dispatch to background thread safely
            asyncio.run_coroutine_threadsafe(run_manual_downloads(), self._background_loop)
            self.notify("Selective downloads started. Progress bars will appear in the dashboard.")
            self.toggle_selective()
        except Exception as e:
            self.notify(f"Failed to start downloads: {e}", severity="error")

    def load_config_to_ui(self) -> None:
        try:
            cfg = AppConfig.load()
            
            # Group 1: Auth
            self.query_one("#setting-api-id", Input).value = str(cfg.api_id or "")
            self.query_one("#setting-api-hash", Input).value = str(cfg.api_hash or "")
            # Target Groups Checkbox list row
            try:
                import sqlite3
                conn = sqlite3.connect("logs/guard.db")
                cursor = conn.execute("SELECT group_id, group_title FROM group_cache")
                db_groups = cursor.fetchall()
                conn.close()
                
                active_gids = {g.strip() for g in (cfg.target_groups or "").split(",") if g.strip()}
                
                container = self.query_one("#setting-target-groups-container")
                container.remove_children()
                
                # Populated Checkboxes from cache
                matched_gids = set()
                for gid, title in db_groups:
                    gid_str = str(gid)
                    val = gid_str in active_gids
                    if val:
                        matched_gids.add(gid_str)
                    check_id = f"grp_check_{gid_str.replace('-', 'neg')}"
                    container.mount(Checkbox(label=f"{title} ({gid})", value=val, id=check_id))
                    
                # Put custom/fallback target IDs that aren't matched in the checkboxes into the Custom input field
                custom_gids = [g for g in active_gids if g not in matched_gids]
                self.query_one("#setting-target-groups", Input).value = ",".join(custom_gids)
            except Exception as ex:
                logging.getLogger("guard").warning(f"Failed to populate Target Groups checkboxes: {ex}")
                self.query_one("#setting-target-groups", Input).value = str(cfg.target_groups or "")
            
            # Populate Storage Group Select options from SQLite
            try:
                import sqlite3
                conn = sqlite3.connect("logs/guard.db")
                cursor = conn.execute("SELECT group_id, group_title FROM group_cache")
                db_groups = cursor.fetchall()
                conn.close()
                
                options = []
                for gid, title in db_groups:
                    options.append((f"{title} ({gid})", str(gid)))
                    
                curr_storage = str(cfg.storage_group_id or "").strip()
                if curr_storage and curr_storage not in [opt[1] for opt in options]:
                    options.append((f"Custom ID: {curr_storage}", curr_storage))
                    
                storage_select = self.query_one("#setting-storage-id", Select)
                storage_select.set_options(options)
                if curr_storage:
                    storage_select.value = curr_storage
            except Exception as ex:
                logging.getLogger("guard").warning(f"Failed to load storage group dropdown: {ex}")
            
            # Group 2: Download
            self.query_one("#setting-download-dir", Input).value = str(cfg.download_dir or "./downloads")
            
            curr_media = str(cfg.media_types or "photo,video").strip()
            media_select = self.query_one("#setting-media-types", Select)
            valid_medias = ["photo,video", "photo", "video", "photo,video,doc"]
            if curr_media in valid_medias:
                media_select.value = curr_media
            else:
                # Custom media types fallback
                opts = [
                    ("Photo & Video", "photo,video"),
                    ("Photo Only", "photo"),
                    ("Video Only", "video"),
                    ("All Media (Photo, Video, Doc)", "photo,video,doc")
                ]
                opts.append((f"Custom: {curr_media}", curr_media))
                media_select.set_options(opts)
                media_select.value = curr_media
                
            curr_qs = str(cfg.queue_size or "3").strip()
            self.query_one("#setting-queue-size", Select).value = curr_qs if curr_qs in [str(i) for i in range(1, 11)] else "3"
            
            # Group 3: Dedup
            self.query_one("#setting-dedup-enabled", Switch).value = cfg.dedup_enabled
            self.query_one("#setting-dedup-method", Select).value = cfg.dedup_method if cfg.dedup_method in ("size", "hash") else "size"
            self.query_one("#setting-redownload", Select).value = cfg.dedownload if cfg.dedownload in ("never", "always", "smart") else "never"
            self.query_one("#setting-super-grabber", Switch).value = cfg.super_grabber_mode
            
            # Group 4: Performance & Filters
            curr_min = str(cfg.min_file_size or "0").strip()
            min_select = self.query_one("#setting-min-size", Select)
            base_mins = [
                ("No Limit (0 KB)", "0"),
                ("100 KB", "100"),
                ("500 KB", "500"),
                ("1 MB", "1024"),
                ("5 MB", "5120"),
                ("10 MB", "10240"),
                ("50 MB", "51200"),
                ("100 MB", "102400"),
                ("500 MB", "512000"),
                ("1 GB", "1048576")
            ]
            if curr_min not in [opt[1] for opt in base_mins]:
                from core.utils import format_bytes
                try:
                    formatted_size = format_bytes(int(curr_min) * 1024)
                except Exception:
                    formatted_size = f"{curr_min} KB"
                base_mins.append((f"Custom: {formatted_size}", curr_min))
            min_select.set_options(base_mins)
            min_select.value = curr_min
            
            self.query_one("#setting-blocked", Input).value = str(cfg.blocked_senders or "")

            curr_max = str(cfg.max_file_size or "0").strip()
            max_select = self.query_one("#setting-max-size", Select)
            base_maxes = [
                ("No Limit", "0"),
                ("50 MB", "50"),
                ("100 MB", "100"),
                ("200 MB", "200"),
                ("500 MB", "500"),
                ("1 GB", "1024"),
                ("2 GB", "2048")
            ]
            if curr_max not in [opt[1] for opt in base_maxes]:
                base_maxes.append((f"Custom: {curr_max} MB", curr_max))
            max_select.set_options(base_maxes)
            max_select.value = curr_max

            curr_workers = str(cfg.upload_workers or "3").strip()
            workers_select = self.query_one("#setting-upload-workers", Select)
            base_workers = [(str(i), str(i)) for i in range(1, 6)]
            if curr_workers not in [opt[1] for opt in base_workers]:
                base_workers.append((f"Custom: {curr_workers}", curr_workers))
            workers_select.set_options(base_workers)
            workers_select.value = curr_workers

            curr_priority = str(cfg.download_priority or "fifo").strip()
            priority_select = self.query_one("#setting-download-priority", Select)
            base_priorities = [
                ("FIFO (Order)", "fifo"),
                ("Small First", "size_asc"),
                ("Large First", "size_desc")
            ]
            if curr_priority not in [opt[1] for opt in base_priorities]:
                base_priorities.append((f"Custom: {curr_priority}", curr_priority))
            priority_select.set_options(base_priorities)
            priority_select.value = curr_priority
            
            # Group 5: Cleanup & Logs
            self.query_one("#setting-cleanup-enabled", Switch).value = cfg.cleanup_enabled
            
            curr_days = str(cfg.cleanup_retention_days or "30").strip()
            days_select = self.query_one("#setting-cleanup-days", Select)
            base_days = [
                ("7 Days", "7"),
                ("14 Days", "14"),
                ("30 Days", "30"),
                ("60 Days", "60"),
                ("90 Days", "90"),
                ("180 Days", "180"),
                ("365 Days", "365")
            ]
            if curr_days not in [opt[1] for opt in base_days]:
                base_days.append((f"Custom: {curr_days} Days", curr_days))
            days_select.set_options(base_days)
            days_select.value = curr_days
            
            curr_interval = str(cfg.cleanup_interval_hours or "6").strip()
            interval_select = self.query_one("#setting-cleanup-interval", Select)
            valid_intervals = ["1", "3", "6", "12", "24"]
            if curr_interval in valid_intervals:
                interval_select.value = curr_interval
            else:
                interval_select.value = "6"
            
            self.query_one("#setting-log-level", Select).value = cfg.log_level if cfg.log_level in ("INFO", "DEBUG", "WARNING", "ERROR") else "INFO"
            self.query_one("#setting-log-file", Switch).value = cfg.log_file
            self.query_one("#setting-show-speed", Switch).value = cfg.show_speed
            self.query_one("#setting-show-eta", Switch).value = cfg.show_eta

            # GROUP 6: Naming & History Scan
            self.query_one("#setting-history-enabled", Switch).value = cfg.history_enabled
            
            curr_h_hours = str(cfg.history_hours or "24").strip()
            h_hours_select = self.query_one("#setting-history-hours", Select)
            valid_h_hours = ["6", "12", "24", "48", "72"]
            if curr_h_hours in valid_h_hours:
                h_hours_select.value = curr_h_hours
            else:
                h_hours_select.value = "24"
                
            curr_fn_fmt = str(cfg.filename_format or "datetime").strip()
            fn_fmt_select = self.query_one("#setting-filename-format", Select)
            valid_fn_fmt = ["datetime", "unique", "original"]
            if curr_fn_fmt in valid_fn_fmt:
                fn_fmt_select.value = curr_fn_fmt
            else:
                fn_fmt_select.value = "datetime"
                
            self.query_one("#setting-folder-date-format", Input).value = str(cfg.folder_date_format or "%Y%m%d_%H%M")
            
            curr_h_mode = str(cfg.history_mode or "list").strip()
            self.query_one("#setting-history-mode", Select).value = curr_h_mode if curr_h_mode in ("list", "auto") else "list"
            
            self.query_one("#setting-history-reverse", Select).value = "true" if cfg.history_reverse else "false"

            # GROUP 7: Webhooks
            self.query_one("#setting-webhook-enabled", Switch).value = cfg.webhook_enabled
            self.query_one("#setting-webhook-url", Input).value = str(cfg.webhook_url or "")

            # Upload Mode
            upload_mode_val = "disabled"
            if cfg.upload_enabled:
                upload_mode_val = os.getenv("UPLOAD_MODE", "realtime_keep")
            self.query_one("#setting-upload-mode", Select).value = upload_mode_val
        except Exception as e:
            self.notify(f"Failed to load config: {e}", severity="error")

    def save_config_from_ui(self) -> None:
        try:
            # Group 1: Auth
            api_id = self.query_one("#setting-api-id", Input).value.strip()
            api_hash = self.query_one("#setting-api-hash", Input).value.strip()
            
            storage_select_val = self.query_one("#setting-storage-id", Select).value
            storage_id = str(storage_select_val).strip() if (storage_select_val and str(storage_select_val) != "Select.BLANK" and storage_select_val != getattr(Select, "BLANK", None)) else ""
            
            # Retrieve target groups from checkboxes and custom text input field
            checked_gids = []
            try:
                container = self.query_one("#setting-target-groups-container")
                for chk in container.query(Checkbox):
                    if chk.value:
                        chk_id = chk.id
                        gid_str = chk_id.replace("grp_check_", "").replace("neg", "-")
                        checked_gids.append(gid_str)
            except Exception as chk_ex:
                logging.getLogger("guard").warning(f"Failed to read target group checkboxes during save: {chk_ex}")

            custom_gids_str = self.query_one("#setting-target-groups", Input).value.strip()
            custom_gids = [g.strip() for g in custom_gids_str.split(",") if g.strip()]
            
            all_gids = []
            seen = set()
            for g in checked_gids + custom_gids:
                if g not in seen:
                    seen.add(g)
                    all_gids.append(g)
            target_groups = ",".join(all_gids)
            
            # Group 2: Download
            download_dir = self.query_one("#setting-download-dir", Input).value.strip()
            
            media_select_val = self.query_one("#setting-media-types", Select).value
            media_types = str(media_select_val).strip() if (media_select_val and str(media_select_val) != "Select.BLANK" and media_select_val != getattr(Select, "BLANK", None)) else "photo,video"
            
            queue_select_val = self.query_one("#setting-queue-size", Select).value
            queue_size = str(queue_select_val).strip() if (queue_select_val and str(queue_select_val) != "Select.BLANK" and queue_select_val != getattr(Select, "BLANK", None)) else "3"
            
            # Group 3: Dedup
            dedup_enabled = self.query_one("#setting-dedup-enabled", Switch).value
            dedup_method = self.query_one("#setting-dedup-method", Select).value
            redownload = self.query_one("#setting-redownload", Select).value
            super_grabber = self.query_one("#setting-super-grabber", Switch).value
            
            # Group 4: Performance & Filters
            upload_mode = self.query_one("#setting-upload-mode", Select).value
            
            min_size_val = self.query_one("#setting-min-size", Select).value
            min_size = str(min_size_val).strip() if (min_size_val and str(min_size_val) != "Select.BLANK" and min_size_val != getattr(Select, "BLANK", None)) else "0"
            
            blocked = self.query_one("#setting-blocked", Input).value.strip()

            max_size_val = self.query_one("#setting-max-size", Select).value
            max_size = str(max_size_val).strip() if (max_size_val and str(max_size_val) != "Select.BLANK" and max_size_val != getattr(Select, "BLANK", None)) else "0"

            upload_workers_val = self.query_one("#setting-upload-workers", Select).value
            upload_workers = str(upload_workers_val).strip() if (upload_workers_val and str(upload_workers_val) != "Select.BLANK" and upload_workers_val != getattr(Select, "BLANK", None)) else "3"

            download_priority_val = self.query_one("#setting-download-priority", Select).value
            download_priority = str(download_priority_val).strip() if (download_priority_val and str(download_priority_val) != "Select.BLANK" and download_priority_val != getattr(Select, "BLANK", None)) else "fifo"
            
            # Group 5: Cleanup & Logs
            cleanup_enabled = self.query_one("#setting-cleanup-enabled", Switch).value
            
            cleanup_days_val = self.query_one("#setting-cleanup-days", Select).value
            cleanup_days = str(cleanup_days_val).strip() if (cleanup_days_val and str(cleanup_days_val) != "Select.BLANK" and cleanup_days_val != getattr(Select, "BLANK", None)) else "30"
            
            cleanup_interval_val = self.query_one("#setting-cleanup-interval", Select).value
            cleanup_interval = str(cleanup_interval_val).strip() if (cleanup_interval_val and str(cleanup_interval_val) != "Select.BLANK" and cleanup_interval_val != getattr(Select, "BLANK", None)) else "6"
            
            log_level = self.query_one("#setting-log-level", Select).value
            log_file = self.query_one("#setting-log-file", Switch).value
            show_speed = self.query_one("#setting-show-speed", Switch).value
            show_eta = self.query_one("#setting-show-eta", Switch).value

            # Group 6: Naming & History Scan
            history_enabled = self.query_one("#setting-history-enabled", Switch).value
            
            history_hours_val = self.query_one("#setting-history-hours", Select).value
            history_hours = str(history_hours_val).strip() if (history_hours_val and str(history_hours_val) != "Select.BLANK" and history_hours_val != getattr(Select, "BLANK", None)) else "24"
            
            filename_format_val = self.query_one("#setting-filename-format", Select).value
            filename_format = str(filename_format_val).strip() if (filename_format_val and str(filename_format_val) != "Select.BLANK" and filename_format_val != getattr(Select, "BLANK", None)) else "datetime"
            
            folder_date_format = self.query_one("#setting-folder-date-format", Input).value.strip()
            
            history_mode_val = self.query_one("#setting-history-mode", Select).value
            history_mode = str(history_mode_val).strip() if (history_mode_val and str(history_mode_val) != "Select.BLANK" and history_mode_val != getattr(Select, "BLANK", None)) else "list"
            
            history_reverse_val = self.query_one("#setting-history-reverse", Select).value
            history_reverse = str(history_reverse_val).strip() if (history_reverse_val and str(history_reverse_val) != "Select.BLANK" and history_reverse_val != getattr(Select, "BLANK", None)) else "true"

            # Group 7: Webhooks
            webhook_enabled = self.query_one("#setting-webhook-enabled", Switch).value
            webhook_url = self.query_one("#setting-webhook-url", Input).value.strip()

            # Validations
            if api_id and not api_id.isdigit():
                self.notify("API ID must be a number.", severity="error", title="Validation Error")
                return

            # Save to env
            if api_id:
                set_key(".env", "API_ID", api_id)
            if api_hash:
                set_key(".env", "API_HASH", api_hash)
                
            set_key(".env", "STORAGE_GROUP_ID", storage_id)
            set_key(".env", "TARGET_GROUPS", target_groups)
            set_key(".env", "DOWNLOAD_DIR", download_dir)
            set_key(".env", "MEDIA_TYPES", media_types)
            set_key(".env", "QUEUE_SIZE", queue_size)
            set_key(".env", "DEDUP_ENABLED", "true" if dedup_enabled else "false")
            set_key(".env", "DEDUP_METHOD", str(dedup_method))
            set_key(".env", "REDOWNLOAD", str(redownload))
            set_key(".env", "SUPER_GRABBER_MODE", "true" if super_grabber else "false")
            set_key(".env", "MIN_FILE_SIZE_KB", min_size)
            set_key(".env", "BLOCKED_SENDERS", blocked)
            set_key(".env", "MAX_FILE_SIZE_MB", max_size)
            set_key(".env", "UPLOAD_WORKERS", upload_workers)
            set_key(".env", "DOWNLOAD_PRIORITY", download_priority)
            set_key(".env", "CLEANUP_RETENTION_DAYS", cleanup_days)
            set_key(".env", "CLEANUP_INTERVAL_HOURS", cleanup_interval)
            set_key(".env", "CLEANUP_ENABLED", "true" if cleanup_enabled else "false")
            set_key(".env", "LOG_LEVEL", str(log_level))
            set_key(".env", "LOG_FILE", "true" if log_file else "false")
            set_key(".env", "SHOW_SPEED", "true" if show_speed else "false")
            set_key(".env", "SHOW_ETA", "true" if show_eta else "false")
            set_key(".env", "HISTORY_ENABLED", "true" if history_enabled else "false")
            set_key(".env", "HISTORY_HOURS", history_hours)
            set_key(".env", "HISTORY_MODE", history_mode)
            set_key(".env", "HISTORY_REVERSE", history_reverse)
            set_key(".env", "FILENAME_FORMAT", filename_format)
            set_key(".env", "FOLDER_DATE_FORMAT", folder_date_format)
            set_key(".env", "WEBHOOK_ENABLED", "true" if webhook_enabled else "false")
            set_key(".env", "WEBHOOK_URL", webhook_url)

            if upload_mode == "disabled":
                set_key(".env", "UPLOAD_ENABLED", "false")
            else:
                set_key(".env", "UPLOAD_ENABLED", "true")
                set_key(".env", "UPLOAD_MODE", str(upload_mode))

            self.notify("Configuration saved successfully! Restarting engine...", title="Settings")
            asyncio.create_task(self.restart_listener_engine())
            
            # Toggle back to dashboard
            self.toggle_settings()
        except Exception as e:
            self.notify(f"Failed to save config: {e}", severity="error", title="Error")

    def reset_to_defaults(self) -> None:
        try:
            self.query_one("#setting-download-dir", Input).value = "./downloads"
            self.query_one("#setting-media-types", Select).value = "photo,video"
            self.query_one("#setting-queue-size", Select).value = "3"
            
            self.query_one("#setting-dedup-enabled", Switch).value = True
            self.query_one("#setting-dedup-method", Select).value = "size"
            self.query_one("#setting-redownload", Select).value = "never"
            self.query_one("#setting-super-grabber", Switch).value = False
            
            self.query_one("#setting-upload-mode", Select).value = "realtime_keep"
            self.query_one("#setting-min-size", Select).value = "0"
            self.query_one("#setting-blocked", Input).value = ""
            self.query_one("#setting-max-size", Select).value = "0"
            self.query_one("#setting-upload-workers", Select).value = "3"
            self.query_one("#setting-download-priority", Select).value = "fifo"
            
            self.query_one("#setting-cleanup-enabled", Switch).value = False
            self.query_one("#setting-cleanup-days", Select).value = "30"
            self.query_one("#setting-cleanup-interval", Select).value = "6"
            self.query_one("#setting-log-level", Select).value = "INFO"
            self.query_one("#setting-log-file", Switch).value = True
            self.query_one("#setting-show-speed", Switch).value = True
            self.query_one("#setting-show-eta", Switch).value = True
            
            self.query_one("#setting-history-enabled", Switch).value = False
            self.query_one("#setting-history-hours", Select).value = "24"
            self.query_one("#setting-history-mode", Select).value = "list"
            self.query_one("#setting-history-reverse", Select).value = "true"
            self.query_one("#setting-filename-format", Select).value = "datetime"
            self.query_one("#setting-folder-date-format", Input).value = "%Y%m%d_%H%M"
            self.query_one("#setting-webhook-enabled", Switch).value = False
            self.query_one("#setting-webhook-url", Input).value = ""
            
            self.notify("Inputs reset to default templates. Click 'Save' to apply changes.", title="Reset Defaults", severity="warning")
        except Exception as e:
            self.notify(f"Reset failed: {e}", severity="error")

    def _refresh_dashboard(self) -> None:
        try:
            running = GLOBAL_STATUS.get("running", False)
            paused = GLOBAL_STATUS.get("paused", False)
            uptime_start = GLOBAL_STATUS.get("uptime_start", 0.0)
            
            uptime = time.time() - uptime_start if running and uptime_start else 0.0
            h, m = divmod(int(uptime) // 60, 60)
            
            if running:
                net_status = " [bold green][Online][/]" if getattr(self, "_is_online", False) else " [bold red][Offline][/]"
                status_str = "[bold green]Running[/]" + net_status + ("[bold yellow] (Paused)[/]" if paused else "")
            else:
                status_str = "[bold red]Stopped[/]"

            status_text = (
                f"Status: {status_str}\n"
                f"Uptime: {h}h {m}m\n"
                f"User Account: [cyan]{GLOBAL_STATUS.get('user', '?')}[/]"
            )
            if status_text != self._last_status:
                self._last_status = status_text
                self._status_widget.update(status_text)

            import core.download_handler as dh
            cfg = dh.CFG or AppConfig.load()
            if not cfg.upload_enabled:
                up_mode_str = "[bold red]Disabled[/]"
            else:
                raw_mode = os.getenv("UPLOAD_MODE", "realtime_keep")
                if raw_mode == "realtime_keep":
                    up_mode_str = "[bold green]RT + Keep[/]"
                elif raw_mode == "realtime_delete":
                    up_mode_str = "[bold green]RT + Delete[/]"
                elif raw_mode == "cron_delete":
                    up_mode_str = "[bold green]Cron + Delete[/]"
                else:
                    up_mode_str = f"[bold green]{raw_mode.replace('_', ' ').title()}[/]"

            stats_text = (
                f"Processed: [cyan]{GLOBAL_STATUS.get('processed', 0)}[/] files\n"
                f"Today Downloaded: [green]{GLOBAL_STATUS.get('today_downloaded', 0)}[/]\n"
                f"Today Uploaded: [green]{GLOBAL_STATUS.get('today_uploaded', 0)}[/]\n"
                f"Today Failed: [red]{GLOBAL_STATUS.get('today_failed', 0)}[/]\n"
                f"Today Data Size: [cyan]{format_bytes(GLOBAL_STATUS.get('today_bytes', 0))}[/]\n"
                f"Upload Mode: {up_mode_str}"
            )
            if stats_text != self._last_stats:
                self._last_stats = stats_text
                self._stats_widget.update(stats_text)
            
            # --- Dynamic Progress Bars Render ---
            prog_panel = self._prog_panel
            prog_box = self._prog_box
            
            if ACTIVE_DOWNLOADS:
                self._prog_was_empty = False
                if not self._prog_visible:
                    prog_panel.styles.display = "block"
                    self._prog_visible = True
                
                mounted_ids = {child.id for child in prog_box.children}
                active_ids = {f"dl-row-{msg_id}" for msg_id in ACTIVE_DOWNLOADS}
                
                for child_id in list(mounted_ids):
                    if child_id not in active_ids:
                        try:
                            prog_box.query_one(f"#{child_id}").remove()
                        except Exception:
                            pass
                
                for msg_id, info in list(ACTIVE_DOWNLOADS.items()):
                    row_id = f"dl-row-{msg_id}"
                    fname = info["filename"]
                    cur = info["current"]
                    tot = info["total"]
                    speed = info["speed"]
                    eta = info["eta"]
                    pct = int(cur / tot * 100) if tot else 0
                    
                    bar_len = 20
                    filled = int(pct / 100 * bar_len)
                    bar_chars = "[green]" + ("\u2588" * filled) + "[/][dim]" + ("\u2591" * (bar_len - filled)) + "[/]"
                    
                    content = (
                        f"[bold cyan]{fname[:36]}[/]\n"
                        f"{bar_chars} {pct}% | {format_bytes(cur)} / {format_bytes(tot)} | {speed} ({eta})"
                    )
                    
                    if row_id in mounted_ids:
                        try:
                            row = prog_box.query_one(f"#{row_id}")
                            info_static = row.query_one(".dl-info", Static)
                            info_static.update(content)
                        except Exception:
                            pass
                    else:
                        try:
                            dl_info = Static(content, classes="dl-info")
                            dl_cancel = Button("Cancel", variant="error", id=f"cancel-{msg_id}", classes="btn-dl-cancel")
                            dl_row = Horizontal(dl_info, dl_cancel, classes="download-row", id=row_id)
                            prog_box.mount(dl_row)
                        except Exception:
                            pass
            else:
                if self._prog_visible:
                    prog_panel.styles.display = "none"
                    self._prog_visible = False
                if not self._prog_was_empty:
                    prog_box.remove_children()
                    self._prog_was_empty = True
            
            # Calculate aggregate active download speed
            curr_speed = sum(info.get("speed_bps", 0.0) for info in ACTIVE_DOWNLOADS.values())
            
            self._recent_speed_history.append(curr_speed)
            if len(self._recent_speed_history) > 30:
                self._recent_speed_history.pop(0)
                
            # If the Visual Analytics tab is open, automatically refresh charts
            analytics_screen = self.query_one("#analytics-container")
            if analytics_screen.styles.display == "block":
                asyncio.create_task(self.refresh_analytics_screen())
            
        except Exception:
            self._status_widget.update("Status: [bold red]Stopped[/]\nUptime: 0h 0m\nUser Account: ?")
            self._stats_widget.update("Processed: 0 files\nToday Downloaded: 0\nToday Uploaded: 0\nToday Failed: 0\nToday Data Size: 0 B")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id

        # Dynamic cancel buttons: cancel-{msg_id}
        if btn_id and btn_id.startswith("cancel-"):
            try:
                msg_id = int(btn_id.split("-", 1)[1])
                from core.state import cancel_active_download
                if cancel_active_download(msg_id):
                    self.notify("Download cancellation requested.", title="Queue Controller", severity="warning")
                else:
                    self.notify("Task not found or already finished.", severity="error", title="Queue Controller")
            except (ValueError, IndexError):
                self.notify("Invalid cancel target.", severity="error")
            return

        # Rule Builder Arrow Up Action
        if btn_id and btn_id.startswith("rule-up-"):
            try:
                idx = int(btn_id.split("-")[-1])
                if idx > 0:
                    self._rules_list[idx], self._rules_list[idx - 1] = self._rules_list[idx - 1], self._rules_list[idx]
                    self.render_rules_list()
                    self.notify("Rule priority increased.")
            except Exception as e:
                self.notify(f"Error moving rule up: {e}", severity="error")
            return

        # Rule Builder Arrow Down Action
        if btn_id and btn_id.startswith("rule-down-"):
            try:
                idx = int(btn_id.split("-")[-1])
                if idx < len(self._rules_list) - 1:
                    self._rules_list[idx], self._rules_list[idx + 1] = self._rules_list[idx + 1], self._rules_list[idx]
                    self.render_rules_list()
                    self.notify("Rule priority decreased.")
            except Exception as e:
                self.notify(f"Error moving rule down: {e}", severity="error")
            return

        # Rule Builder Edit Action
        if btn_id and btn_id.startswith("rule-edit-"):
            try:
                idx = int(btn_id.split("-")[-1])
                self.edit_rule(idx)
            except Exception as e:
                self.notify(f"Error editing rule: {e}", severity="error")
            return

        # Rule Builder Delete Action
        if btn_id and btn_id.startswith("rule-del-"):
            try:
                idx = int(btn_id.split("-")[-1])
                rule_name = self._rules_list[idx].name
                del self._rules_list[idx]
                if self._editing_rule_index == idx:
                    self.clear_rule_form()
                elif self._editing_rule_index is not None and self._editing_rule_index > idx:
                    self._editing_rule_index -= 1
                self.render_rules_list()
                self.notify(f"Deleted rule: {rule_name}", severity="warning")
            except Exception as e:
                self.notify(f"Error deleting rule: {e}", severity="error")
            return

        if btn_id == "btn-start":
            if not self.listener_task:
                self.notify("Starting Telegram DL Guard Listener Engine...", title="Status Update")
                self.start_listener_engine()
            else:
                GLOBAL_STATUS["paused"] = False
                self.notify("Resumed Telegram DL Guard Listener.", title="Status Update")
        elif btn_id == "btn-pause":
            GLOBAL_STATUS["paused"] = True
            self.notify("Paused Telegram DL Guard Listener.", title="Status Update", severity="warning")
        elif btn_id == "btn-restart":
            asyncio.create_task(self.restart_listener_engine())
            self.notify("Sent Restart command to listener engine.", title="Status Update")
        elif btn_id == "btn-goto-settings" or btn_id == "btn-back-dashboard":
            self.toggle_settings()
        elif btn_id == "btn-goto-gallery" or btn_id == "btn-back-gallery":
            asyncio.create_task(self.toggle_gallery())
        elif btn_id == "btn-save-settings":
            self.save_config_from_ui()
        elif btn_id == "btn-reset-settings":
            self.reset_to_defaults()
        elif btn_id == "btn-sync-groups":
            asyncio.create_task(self.sync_telegram_groups())
        elif btn_id == "btn-load-raw-file":
            self.load_raw_file_to_ui()
        elif btn_id == "btn-save-raw-file":
            self.save_raw_file_from_ui()
        elif btn_id == "btn-rule-new":
            self.clear_rule_form()
            self.notify("Form cleared. Input details for new rule.")
        elif btn_id == "btn-rule-reload":
            self.load_rules_to_ui()
            self.notify("Reloaded rules from disk.")
        elif btn_id == "btn-rule-save":
            self.save_rule_form()
        elif btn_id == "btn-rule-cancel":
            self.clear_rule_form()
            self.notify("Edit cancelled.")
        elif btn_id == "btn-apply-rules-yaml":
            self.apply_rules_to_yaml()
        elif btn_id == "btn-refresh-analytics":
            asyncio.create_task(self.refresh_analytics_screen())
            self.notify("Refreshed system metrics.")
        elif btn_id == "btn-back-rules":
            self.toggle_rules()
        elif btn_id == "btn-back-analytics":
            self.toggle_analytics()
        elif btn_id == "btn-fetch-history":
            asyncio.create_task(self.fetch_history_media())
        elif btn_id == "btn-download-selected":
            asyncio.create_task(self.download_selected_media())
        elif btn_id == "btn-select-all":
            try:
                box = self.query_one("#selective-media-list")
                for chk in box.query(Checkbox):
                    chk.value = True
                self.notify("All files selected.")
            except Exception:
                pass
        elif btn_id == "btn-clear-selection":
            try:
                box = self.query_one("#selective-media-list")
                for chk in box.query(Checkbox):
                    chk.value = False
                self.notify("Selection cleared.")
            except Exception:
                pass
        elif btn_id == "btn-back-selective":
            self.toggle_selective()

    def action_cmd_start(self) -> None:
        if not self.listener_task:
            self.notify("Starting Telegram DL Guard Listener Engine...", title="Status Update")
            self.start_listener_engine()
        else:
            GLOBAL_STATUS["paused"] = False
            self.notify("Resumed Telegram DL Guard Listener.", title="Status Update")

    def action_cmd_pause(self) -> None:
        GLOBAL_STATUS["paused"] = True
        self.notify("Paused Telegram DL Guard Listener.", title="Status Update", severity="warning")

    def action_cmd_restart(self) -> None:
        asyncio.create_task(self.restart_listener_engine())
        self.notify("Sent Restart command to listener engine.", title="Status Update")

    def action_cmd_config(self) -> None:
        self.toggle_settings()

    async def action_cmd_gallery(self) -> None:
        await self.toggle_gallery()

    def action_cmd_analytics(self) -> None:
        self.toggle_analytics()

    def action_cmd_rules(self) -> None:
        self.toggle_rules()

    def action_cmd_selective(self) -> None:
        self.toggle_selective()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "setting-raw-file-select":
            self.load_raw_file_to_ui()

    def load_raw_file_to_ui(self) -> None:
        try:
            select_val = self.query_one("#setting-raw-file-select", Select).value
            file_name = str(select_val).strip() if (select_val and str(select_val) != "Select.BLANK" and select_val != getattr(Select, "BLANK", None)) else ""
            if not file_name or file_name == "None":
                return
            
            p = Path(file_name)
            if not p.exists():
                self.query_one("#setting-raw-text-area", TextArea).text = ""
                self.notify(f"File {file_name} does not exist yet.", severity="warning", title="Raw Editor")
                return
            
            with open(p, "r", encoding="utf-8") as f:
                content = f.read()
                
            self.query_one("#setting-raw-text-area", TextArea).text = content
            self.notify(f"Loaded {file_name} successfully!", title="Raw Editor")
        except Exception as e:
            self.notify(f"Failed to load file: {e}", severity="error", title="Raw Editor")

    def save_raw_file_from_ui(self) -> None:
        try:
            select_val = self.query_one("#setting-raw-file-select", Select).value
            file_name = str(select_val).strip() if (select_val and str(select_val) != "Select.BLANK" and select_val != getattr(Select, "BLANK", None)) else ""
            if not file_name or file_name == "None":
                self.notify("Please select a file to save.", severity="warning", title="Raw Editor")
                return
            
            content = self.query_one("#setting-raw-text-area", TextArea).text
            
            p = Path(file_name)
            with open(p, "w", encoding="utf-8") as f:
                f.write(content)
                
            self.notify(f"Saved {file_name} successfully! Restarting engine...", title="Raw Editor")
            
            # If the edited file is .env or config.yaml, restart the engine
            if file_name in (".env", "config.yaml"):
                asyncio.create_task(self.restart_listener_engine())
        except Exception as e:
            self.notify(f"Failed to save file: {e}", severity="error", title="Raw Editor")

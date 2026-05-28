# -*- coding: utf-8 -*-
"""
Interactive TUI — Textual Dashboard for Telegram DL Guard.
Usage: python tui.py
"""
from __future__ import annotations

from datetime import datetime

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    Header, Footer, Static, Button, RichLog,
)
from textual.binding import Binding
from textual.timer import Timer

from core.ipc import read_status, write_command, read_logs


# ── Status Panel ──────────────────────────────────────────────


class StatusPanel(Static):
    """Shows current listener status."""

    timer: Timer | None = None

    def compose(self) -> ComposeResult:
        yield Static("", id="status-text")

    def on_mount(self) -> None:
        self.refresh()
        self.timer = self.set_interval(2, self.refresh)

    def refresh(self) -> None:
        s = read_status()
        running = s.get("running", False)
        paused = s.get("paused", False)
        uptime = s.get("uptime", 0)
        h, m = divmod(int(uptime) // 60, 60)
        self.query_one("#status-text", Static).update(
            f"{'Running' if running else 'Stopped'}"
            f"{' (Paused)' if paused else ''}\n"
            f"Uptime: {h}h {m}m\n"
            f"Processed: {s.get('processed', 0)}\n"
            f"User: {s.get('user', '?')}"
        )


# ── Activity Panel ────────────────────────────────────────────


class ActivityPanel(RichLog):
    """Shows recent activity log."""

    timer: Timer | None = None

    def on_mount(self) -> None:
        self.wrap = True
        self.refresh()
        self.timer = self.set_interval(1, self.refresh)

    def refresh(self) -> None:
        logs = read_logs(50)
        try:
            self._line_cache.clear()
        except Exception:
            pass
        from rich.text import Text
        for entry in logs:
            ts = datetime.fromtimestamp(entry.get("t", 0)).strftime("%H:%M:%S")
            msg = entry.get("msg", "")
            level = entry.get("level", "info")
            style = "red" if level == "error" else ("yellow" if level == "warning" else "green")
            line = Text(f"[{ts}] {msg}\n", style=style)
            self.write(line)


# ── Controls ──────────────────────────────────────────────────


class Controls(Static):
    """Action buttons."""

    def compose(self) -> ComposeResult:
        yield Button("Start", id="btn-start", variant="success")
        yield Button("Pause", id="btn-pause", variant="warning")
        yield Button("Restart", id="btn-restart", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "btn-start":
            write_command({"action": "resume"})
        elif btn_id == "btn-pause":
            write_command({"action": "pause"})
        elif btn_id == "btn-restart":
            write_command({"action": "restart"})


# ── Main App ──────────────────────────────────────────────────


class GuardApp(App):
    """Telegram DL Guard — Interactive TUI."""

    CSS = """
    #main-layout { height: 100%; }
    #left-panel { width: 40%; }
    #right-panel { width: 60%; }
    StatusPanel, ActivityPanel, Controls {
        border: solid $primary;
        padding: 1;
        margin: 0 1;
    }
    Controls { height: auto; }
    Button { margin: 0 1; }
    """

    BINDINGS = [
        Binding("s", "cmd_start", "Start"),
        Binding("p", "cmd_pause", "Pause"),
        Binding("r", "cmd_restart", "Restart"),
        Binding("q", "quit", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="main-layout"):
            with Vertical(id="left-panel"):
                yield StatusPanel()
                yield Controls()
            with Vertical(id="right-panel"):
                yield ActivityPanel()
        yield Footer()

    def action_cmd_start(self) -> None:
        write_command({"action": "resume"})

    def action_cmd_pause(self) -> None:
        write_command({"action": "pause"})

    def action_cmd_restart(self) -> None:
        write_command({"action": "restart"})


if __name__ == "__main__":
    GuardApp().run()

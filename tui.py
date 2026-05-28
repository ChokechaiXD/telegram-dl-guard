# -*- coding: utf-8 -*-
"""
Interactive TUI — Textual Dashboard for Telegram DL Guard.
Usage: python tui.py
"""
from __future__ import annotations

from datetime import datetime

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, Container
from textual.widgets import Header, Footer, Static, Button, RichLog
from textual.binding import Binding
from textual.timer import Timer

from core.ipc import read_status, write_command, read_logs


class StatusPanel(Static):
    """Shows current listener status."""

    timer: Timer | None = None

    def compose(self) -> ComposeResult:
        yield Static("", id="status-text")

    def on_mount(self) -> None:
        self._refresh()
        self.timer = self.set_interval(3, self._refresh)

    def _refresh(self, **kwargs) -> None:
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


class ActivityPanel(RichLog):
    """Shows recent activity log."""

    timer: Timer | None = None

    def on_mount(self) -> None:
        self.wrap = True
        self._update_log()
        self.timer = self.set_interval(2, self._update_log)

    def _update_log(self, **kwargs) -> None:
        logs = read_logs(50)
        self.clear()
        from rich.text import Text
        for entry in logs:
            ts = datetime.fromtimestamp(entry.get("t", 0)).strftime("%H:%M:%S")
            msg = entry.get("msg", "")
            level = entry.get("level", "info")
            style = "red" if level == "error" else ("yellow" if level == "warning" else "green")
            line = Text(f"[{ts}] {msg}\n", style=style)
            self.write(line)


class Controls(Horizontal):
    """Action buttons."""

    def compose(self) -> ComposeResult:
        yield Button("Start", id="btn-start", variant="success")
        yield Button("Pause", id="btn-pause", variant="warning")
        yield Button("Restart", id="btn-restart", variant="primary")

    def on_button_pressed(self, event) -> None:
        btn = event.button
        btn_id = getattr(btn, 'id', '')
        print(f"DEBUG: button pressed id={btn_id}")
        if btn_id == "btn-start":
            write_command({"action": "resume"})
        elif btn_id == "btn-pause":
            write_command({"action": "pause"})
        elif btn_id == "btn-restart":
            write_command({"action": "restart"})


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
        Binding("c", "cmd_config", "Config"),
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
        print("KEY: resume")

    def action_cmd_pause(self) -> None:
        write_command({"action": "pause"})
        print("KEY: pause")

    def action_cmd_restart(self) -> None:
        write_command({"action": "restart"})
        print("KEY: restart")

    def action_cmd_config(self) -> None:
        self.bell()  # placeholder


if __name__ == "__main__":
    GuardApp().run()

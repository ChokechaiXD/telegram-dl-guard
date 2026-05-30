# -*- coding: utf-8 -*-
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.widgets import Static, Label, Button, RichLog

class DashboardContainer(Container):
    """Container holding the primary monitoring dashboard (Status, Stats, Downloads, Logs)."""
    
    def compose(self) -> ComposeResult:
        with Horizontal(id="main-layout"):
            with VerticalScroll(id="left-panel"):
                with Vertical(classes="card"):
                    yield Label("SYSTEM STATUS", classes="card-title")
                    yield Static("Loading status...", id="status-text")
                
                with Vertical(id="progress-panel"):
                    yield Label("ACTIVE DOWNLOADS", classes="card-title")
                    yield Container(id="active-downloads-box")
                
                with Vertical(classes="card"):
                    yield Label("TODAY'S STATISTICS", classes="card-title")
                    yield Static("Loading statistics...", id="stats-text")
                
                with Vertical(classes="controls-grid"):
                    with Horizontal(classes="controls-row"):
                        yield Button("Start", id="btn-start", variant="success")
                        yield Button("Pause", id="btn-pause", variant="warning")
                        yield Button("Restart", id="btn-restart", variant="primary")
                    with Horizontal(classes="controls-row"):
                        yield Button("Settings", id="btn-goto-settings", variant="default")
                        yield Button("Media Gallery", id="btn-goto-gallery", variant="default")
                    with Horizontal(classes="controls-row"):
                        yield Button("Visual Analytics", id="btn-goto-analytics", variant="default")
                        yield Button("Manual DL", id="btn-goto-selective", variant="default")
            
            with Vertical(id="right-panel"):
                yield RichLog(id="log-panel", wrap=True, highlight=True)

# -*- coding: utf-8 -*-
from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal, VerticalScroll, Container
from textual.widgets import Label, Button, Input, Select

class SelectiveDownloaderContainer(VerticalScroll):
    """Container holding the interactive history media browser and selective downloader."""
    
    def compose(self) -> ComposeResult:
        with Vertical(classes="settings-group"):
            yield Label("VISUAL HISTORY BROWSER & SELECTIVE DOWNLOADER", classes="card-title")
            
            # Filters block
            with Vertical(classes="card"):
                yield Label("FETCH FILTER CRITERIA", classes="card-title")
                with Horizontal(classes="setting-row"):
                    yield Label("Target Group:")
                    yield Select(options=[], id="selective-group-id", prompt="Select Target Group")
                with Horizontal(classes="setting-row"):
                    yield Label("Fetch Depth:")
                    yield Input(placeholder="e.g. 50 (number of messages to scan)", id="selective-limit", value="50")
                with Horizontal(classes="setting-row"):
                    yield Label("Media Filter:")
                    yield Select(
                        options=[
                            ("All Media (Photo/Video/Doc)", "all"),
                            ("Photo Only", "photo"),
                            ("Video Only", "video"),
                            ("Document Only", "doc")
                        ],
                        id="selective-media-filter",
                        value="all"
                    )
                with Horizontal(classes="setting-row"):
                    yield Label("Keyword Query:")
                    yield Input(placeholder="e.g. search keyword inside caption...", id="selective-search-query")
                
                with Horizontal(classes="settings-raw-actions"):
                    yield Button("Fetch Group Media", variant="primary", id="btn-fetch-history")
            
            # Actions and Media Panel
            with Vertical(classes="card"):
                yield Label("FETCHED MEDIA & TARGET SELECTION", classes="card-title")
                
                with Horizontal(classes="settings-raw-actions"):
                    yield Button("Download Selected", variant="success", id="btn-download-selected")
                    yield Button("Select All", variant="default", id="btn-select-all")
                    yield Button("Clear Selection", variant="default", id="btn-clear-selection")
                
                # Dynamic selective checkboxes list box
                yield Container(id="selective-media-list")
            
            with Horizontal(classes="settings-actions"):
                yield Button("Back to Dashboard", variant="default", id="btn-back-selective")

# -*- coding: utf-8 -*-
from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.widgets import Label, Static, Button, DirectoryTree

class GalleryContainer(Container):
    """Container holding the Local Media Gallery explorer and inspector."""
    
    def compose(self) -> ComposeResult:
        with Vertical(id="gallery-left"):
            yield Label("DOWNLOADED FILES", classes="card-title")
            yield DirectoryTree("./downloads", id="media-tree")
        with Vertical(id="gallery-right"):
            with Vertical(classes="card"):
                yield Label("MEDIA ACTIONS & INFO", classes="card-title")
                yield Static(
                    "[bold cyan]📁 Local Media Gallery & Launcher[/]\n\n"
                    "Double-click or press [bold]Enter[/] on any file to open it directly with your default OS player (Windows Photos, VLC, etc.)!\n\n"
                    "Use the tree view on the left to browse downloaded folders grouped by group/channel name and sender.",
                    id="gallery-info"
                )
                yield Button("Back to Dashboard", variant="default", id="btn-back-gallery")

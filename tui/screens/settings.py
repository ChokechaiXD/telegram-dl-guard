# -*- coding: utf-8 -*-
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Label, Button, Input, Select, Switch, TextArea, Checkbox

class SettingsContainer(VerticalScroll):
    """Container holding all the dynamic forms for system configuration."""
    
    def compose(self) -> ComposeResult:
        # GROUP 1: Connection & Authentication
        with Vertical(classes="settings-group"):
            yield Label("Telegram Connection & Auth", classes="card-title")
            with Horizontal(classes="setting-row"):
                yield Label("API ID:")
                yield Input(placeholder="Get from my.telegram.org", id="setting-api-id")
            with Horizontal(classes="setting-row"):
                yield Label("API HASH:")
                yield Input(placeholder="Get from my.telegram.org", id="setting-api-hash", password=True)
            with Horizontal(classes="setting-row"):
                yield Label("Storage Group:")
                yield Select(options=[], id="setting-storage-id", prompt="Select Storage Group")
            with Horizontal(classes="setting-row", id="target-groups-checkbox-row"):
                yield Label("Select Target Groups:")
                yield Vertical(id="setting-target-groups-container")
                yield Button("Sync Groups", variant="default", id="btn-sync-groups")
            with Horizontal(classes="setting-row"):
                yield Label("Custom Target IDs:")
                yield Input(placeholder="Comma-separated group/channel IDs (e.g. -100123456)", id="setting-target-groups")
        
        # GROUP 2: Download & Directories
        with Vertical(classes="settings-group"):
            yield Label("Download & File Paths", classes="card-title")
            with Horizontal(classes="setting-row"):
                yield Label("Download Directory:")
                yield Input(placeholder="e.g. ./downloads", id="setting-download-dir")
            with Horizontal(classes="setting-row"):
                yield Label("Media Types:")
                yield Select(
                    options=[
                        ("Photo & Video", "photo,video"),
                        ("Photo Only", "photo"),
                        ("Video Only", "video"),
                        ("All Media (Photo, Video, Doc)", "photo,video,doc")
                    ],
                    id="setting-media-types",
                    prompt="Select Media Types"
                )
            with Horizontal(classes="setting-row"):
                yield Label("Queue Size (1-10):")
                yield Select(
                    options=[(str(i), str(i)) for i in range(1, 11)],
                    id="setting-queue-size",
                    prompt="Select Queue Size"
                )
        
        # GROUP 3: Deduplication & Smart Settings
        with Vertical(classes="settings-group"):
            yield Label("Deduplication & Smart Rules", classes="card-title")
            with Horizontal(classes="setting-row"):
                yield Label("Enable Deduplication:")
                yield Switch(id="setting-dedup-enabled")
            with Horizontal(classes="setting-row"):
                yield Label("Deduplication Method:")
                yield Select(
                    options=[
                        ("Size (Fast)", "size"),
                        ("Hash (Accurate)", "hash")
                    ],
                    id="setting-dedup-method"
                )
            with Horizontal(classes="setting-row"):
                yield Label("Redownload Mode:")
                yield Select(
                    options=[
                        ("Never", "never"),
                        ("Always", "always"),
                        ("Smart", "smart")
                    ],
                    id="setting-redownload"
                )
            with Horizontal(classes="setting-row"):
                yield Label("Super Grabber Mode:")
                yield Switch(id="setting-super-grabber")
        
        # GROUP 4: Performance, Upload & Anti-Spam Filters
        with Vertical(classes="settings-group"):
            yield Label("Upload & Filters", classes="card-title")
            with Horizontal(classes="setting-row"):
                yield Label("Upload Mode:")
                yield Select(
                    options=[
                        ("Real-time + Keep", "realtime_keep"),
                        ("Real-time + Delete", "realtime_delete"),
                        ("Batch + Keep", "batch_keep"),
                        ("Batch + Delete", "batch_delete"),
                        ("Disabled", "disabled")
                    ],
                    id="setting-upload-mode"
                )
            with Horizontal(classes="setting-row"):
                yield Label("Min File Size:")
                yield Select(
                    options=[
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
                    ],
                    id="setting-min-size",
                    prompt="Select Min Size"
                )
            with Horizontal(classes="setting-row"):
                yield Label("Blocked Senders:")
                yield Input(placeholder="Comma-separated names", id="setting-blocked")
            with Horizontal(classes="setting-row"):
                yield Label("Max File Size:")
                yield Select(
                    options=[
                        ("No Limit", "0"),
                        ("50 MB", "50"),
                        ("100 MB", "100"),
                        ("200 MB", "200"),
                        ("500 MB", "500"),
                        ("1 GB", "1024"),
                        ("2 GB", "2048")
                    ],
                    id="setting-max-size",
                    prompt="Select Max Size"
                )
            with Horizontal(classes="setting-row"):
                yield Label("Upload Workers:")
                yield Select(
                    options=[(str(i), str(i)) for i in range(1, 6)],
                    id="setting-upload-workers",
                    prompt="Select Workers"
                )
            with Horizontal(classes="setting-row"):
                yield Label("Download Priority:")
                yield Select(
                    options=[
                        ("FIFO (Order)", "fifo"),
                        ("Small First", "size_asc"),
                        ("Large First", "size_desc")
                    ],
                    id="setting-download-priority",
                    prompt="Select Priority"
                )
        
        # GROUP 5: Auto Maintenance & Logs
        with Vertical(classes="settings-group"):
            yield Label("System, Cleanup & Logs", classes="card-title")
            with Horizontal(classes="setting-row"):
                yield Label("Enable Auto Cleanup:")
                yield Switch(id="setting-cleanup-enabled")
            with Horizontal(classes="setting-row"):
                yield Label("Retention Days:")
                yield Select(
                    options=[
                        ("7 Days", "7"),
                        ("14 Days", "14"),
                        ("30 Days", "30"),
                        ("60 Days", "60"),
                        ("90 Days", "90"),
                        ("180 Days", "180"),
                        ("365 Days", "365")
                    ],
                    id="setting-cleanup-days",
                    prompt="Select Retention Days"
                )
            with Horizontal(classes="setting-row"):
                yield Label("Cleanup Scan Interval:")
                yield Select(
                    options=[
                        ("Every Hour", "1"),
                        ("Every 3 Hours", "3"),
                        ("Every 6 Hours", "6"),
                        ("Every 12 Hours", "12"),
                        ("Every 24 Hours", "24")
                    ],
                    id="setting-cleanup-interval",
                    prompt="Select Cleanup Interval"
                )
            with Horizontal(classes="setting-row"):
                yield Label("Log Level:")
                yield Select(
                    options=[
                        ("INFO (Standard)", "INFO"),
                        ("DEBUG (Detailed)", "DEBUG"),
                        ("WARNING (Errors only)", "WARNING"),
                        ("ERROR (Critical only)", "ERROR")
                    ],
                    id="setting-log-level"
                )
            with Horizontal(classes="setting-row"):
                yield Label("Log File Backup:")
                yield Switch(id="setting-log-file")
            with Horizontal(classes="setting-row"):
                yield Label("Show Download Speed:")
                yield Switch(id="setting-show-speed")
            with Horizontal(classes="setting-row"):
                yield Label("Show Estimated Time (ETA):")
                yield Switch(id="setting-show-eta")

        # GROUP 6: Naming Format & History Scan Settings
        with Vertical(classes="settings-group"):
            yield Label("File Naming & History Scanner", classes="card-title")
            with Horizontal(classes="setting-row"):
                yield Label("Enable History Scan:")
                yield Switch(id="setting-history-enabled")
            with Horizontal(classes="setting-row"):
                yield Label("History Timeframe:")
                yield Select(
                    options=[
                        ("6 Hours", "6"),
                        ("12 Hours", "12"),
                        ("24 Hours (1d)", "24"),
                        ("48 Hours (2d)", "48"),
                        ("72 Hours (3d)", "72")
                    ],
                    id="setting-history-hours",
                    prompt="Select Timeframe"
                )
            with Horizontal(classes="setting-row"):
                yield Label("Filename Format:")
                yield Select(
                    options=[
                        ("Date-Time Unique (Default)", "datetime"),
                        ("Original Name + Msg ID", "unique"),
                        ("Raw Telegram Filename", "original")
                    ],
                    id="setting-filename-format",
                    prompt="Select Format"
                )
            with Horizontal(classes="setting-row"):
                yield Label("Group Folder Date Format:")
                yield Input(placeholder="e.g. %Y%m%d_%H%M", id="setting-folder-date-format")
            with Horizontal(classes="setting-row"):
                yield Label("History Scan Mode:")
                yield Select(
                    options=[
                        ("List Only (Dry-run)", "list"),
                        ("Download & Sync (Auto)", "auto")
                    ],
                    id="setting-history-mode",
                    prompt="Select History Mode"
                )
            with Horizontal(classes="setting-row"):
                yield Label("History Scan Direction:")
                yield Select(
                    options=[
                        ("Oldest First (Chronological)", "true"),
                        ("Newest First (Reverse)", "false")
                    ],
                    id="setting-history-reverse",
                    prompt="Select Direction"
                )

        # GROUP 7: Discord/Telegram Webhooks
        with Vertical(classes="settings-group"):
            yield Label("Discord/Telegram Webhook Logs", classes="card-title")
            with Horizontal(classes="setting-row"):
                yield Label("Enable Webhook:")
                yield Switch(id="setting-webhook-enabled")
            with Horizontal(classes="setting-row"):
                yield Label("Webhook URL:")
                yield Input(placeholder="Paste Discord/Telegram Webhook URL here", id="setting-webhook-url")
        
        # GROUP 8: Advanced Raw Config Editors
        with Vertical(classes="settings-group"):
            yield Label("Advanced Config Files (Raw Direct Edit)", classes="card-title")
            with Horizontal(classes="setting-row"):
                yield Label("Select File to Edit:")
                yield Select(
                    options=[
                        (".env (Secrets & Overrides)", ".env"),
                        ("config.yaml (Non-secrets)", "config.yaml"),
                        ("rules.yaml (Rule Engine Definitions)", "rules.yaml")
                    ],
                    id="setting-raw-file-select",
                    prompt="Choose file to edit"
                )
            
            yield TextArea(show_line_numbers=True, id="setting-raw-text-area", classes="raw-text-area")
            
            with Horizontal(classes="settings-raw-actions"):
                yield Button("Load Content", variant="default", id="btn-load-raw-file")
                yield Button("Save Raw File", variant="error", id="btn-save-raw-file")
        
        # Action Buttons
        with Horizontal(classes="settings-actions"):
            yield Button("Save Configuration", variant="success", id="btn-save-settings")
            yield Button("Reset to Defaults", variant="warning", id="btn-reset-settings")
            yield Button("Back to Dashboard", variant="default", id="btn-back-dashboard")

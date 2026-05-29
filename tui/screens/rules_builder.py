# -*- coding: utf-8 -*-
from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal, VerticalScroll, Container
from textual.widgets import Label, Button, Input, Select, Switch, Static

class RulesBuilderContainer(VerticalScroll):
    """Container holding the interactive Rule Builder panel and rule order registry."""
    
    def compose(self) -> ComposeResult:
        with Vertical(classes="settings-group"):
            yield Label("VISUAL RULE BUILDER & MANAGER", classes="card-title")
            
            with Horizontal(id="rules-layout"):
                # Left Column: Active Rules List and registry ordering
                with Vertical(id="rules-registry-column"):
                    yield Label("ACTIVE PROCESSING RULES (PRIORITY ORDER)", classes="card-title")
                    yield Container(id="rules-list-box")
                    
                    with Horizontal(classes="settings-raw-actions"):
                        yield Button("New Rule", variant="success", id="btn-rule-new")
                        yield Button("Reload Rules", variant="primary", id="btn-rule-reload")
                
                # Right Column: Interactive Parameter Editor Form
                with Vertical(id="rules-editor-column"):
                    yield Label("RULE PARAMETERS EDITOR", classes="card-title")
                    
                    # Rule Header
                    with Horizontal(classes="setting-row"):
                        yield Label("Rule Name:")
                        yield Input(placeholder="e.g. Skip Small Pictures", id="rule-name")
                    with Horizontal(classes="setting-row"):
                        yield Label("Rule Enabled:")
                        yield Switch(id="rule-enabled", value=True)
                        
                    # Conditions Group
                    yield Label("WHEN Conditions (All must match):", classes="rule-form-section")
                    with Horizontal(classes="setting-row"):
                        yield Label("Media Type:")
                        yield Select(
                            options=[
                                ("Any Media", "any"),
                                ("Photo Only", "photo"),
                                ("Video Only", "video"),
                                ("Document Only", "doc")
                            ],
                            id="rule-cond-media",
                            value="any"
                        )
                    with Horizontal(classes="setting-row"):
                        yield Label("Sender Name (Exact):")
                        yield Input(placeholder="e.g. John Doe", id="rule-cond-sender")
                    with Horizontal(classes="setting-row"):
                        yield Label("Sender Name Contains:")
                        yield Input(placeholder="e.g. bot", id="rule-cond-sender-contains")
                    with Horizontal(classes="setting-row"):
                        yield Label("Filename Regex:")
                        yield Input(placeholder="e.g. (nsfw|xxx|18\\+)", id="rule-cond-regex")
                    with Horizontal(classes="setting-row"):
                        yield Label("File Size Comparison:")
                        yield Select(
                            options=[
                                ("No Size Constraint", "any"),
                                ("Greater Than (>) ", "gt"),
                                ("Less Than (<)", "lt")
                            ],
                            id="rule-cond-size-op",
                            value="any"
                        )
                    with Horizontal(classes="setting-row"):
                        yield Label("File Size Limit (KB):")
                        yield Input(placeholder="e.g. 51200 for 50MB", id="rule-cond-size-val")
                    with Horizontal(classes="setting-row"):
                        yield Label("Source Group Title:")
                        yield Input(placeholder="e.g. VIP Channel", id="rule-cond-group")
                        
                    # Actions Group
                    yield Label("THEN Actions (Executes if conditions match):", classes="rule-form-section")
                    with Horizontal(classes="setting-row"):
                        yield Label("Skip Download/Upload:")
                        yield Switch(id="rule-act-skip")
                    with Horizontal(classes="setting-row"):
                        yield Label("Immediate Priority:")
                        yield Switch(id="rule-act-priority")
                    with Horizontal(classes="setting-row"):
                        yield Label("Append Tag:")
                        yield Input(placeholder="e.g. vip (appends #vip to caption)", id="rule-act-tag")
                    with Horizontal(classes="setting-row"):
                        yield Label("Move to Folder:")
                        yield Input(placeholder="e.g. C:/VIP_Downloads", id="rule-act-move")
                    with Horizontal(classes="setting-row"):
                        yield Label("Upload as Album:")
                        yield Switch(id="rule-act-album")
                        
                    with Horizontal(classes="settings-raw-actions"):
                        yield Button("Save Rule Changes", variant="success", id="btn-rule-save")
                        yield Button("Cancel Edit", variant="warning", id="btn-rule-cancel")
            
            with Horizontal(classes="settings-actions"):
                yield Button("Save & Apply Rules", variant="success", id="btn-apply-rules-yaml")
                yield Button("Back to Dashboard", variant="default", id="btn-back-rules")

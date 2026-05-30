# -*- coding: utf-8 -*-
from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal, VerticalScroll
from textual.widgets import Label, Static, Button

class AnalyticsContainer(VerticalScroll):
    """Container holding the premium real-time charts and historical database volume statistics."""
    
    def compose(self) -> ComposeResult:
        with Vertical(classes="settings-group"):
            yield Label("VISUAL SYSTEM ANALYTICS & CHARTS", classes="card-title")
            
            with Horizontal(id="analytics-top-row"):
                with Vertical(classes="card", id="card-speed-chart"):
                    yield Label("REAL-TIME SPEED SPARKLINE (PAST 30s)", classes="card-title")
                    yield Static("Analyzing speeds...", id="chart-speed-spark")
                    
                with Vertical(classes="card", id="card-mime-dist"):
                    yield Label("TRAFFIC BY MEDIA CATEGORY", classes="card-title")
                    yield Static("Calculating categories...", id="chart-mime-dist")
            
            with Horizontal(id="analytics-bottom-row"):
                with Vertical(classes="card", id="card-volume-history"):
                    yield Label("7-DAY HISTORICAL DATA VOLUME", classes="card-title")
                    yield Static("Querying historical database...", id="chart-volume-history")
                    
                with Vertical(classes="card", id="card-system-ratios"):
                    yield Label("SYSTEM RATIO & METRICS", classes="card-title")
                    yield Static("Retrieving database counters...", id="chart-ratio-metrics")
            
            with Horizontal(classes="settings-raw-actions"):
                yield Button("Refresh Analytics", variant="success", id="btn-refresh-analytics")
                yield Button("Back to Dashboard", variant="default", id="btn-back-analytics")


def draw_speed_chart(history: list[float], height: int = 7) -> str:
    """Render a vertical block chart representing historical speed logs."""
    if not history:
        return "\n\n[dim]Waiting for active downloads to measure speeds...[/]\n\n"
    
    max_val = max(history) or 1.0
    blocks = [" ", " ", "▂", "▃", "▄", "▅", "▆", "▇", "█"]
    
    # We pad the history with 0s to standard width 32 to keep chart stable
    padded = [0.0] * (32 - len(history)) + history
    padded = padded[-32:]
    
    chart_lines = []
    for r in range(height, 0, -1):
        line = ""
        threshold = (r / height) * max_val
        prev_threshold = ((r - 1) / height) * max_val
        for val in padded:
            if val >= threshold:
                line += "█"
            elif val > prev_threshold:
                ratio = (val - prev_threshold) / (threshold - prev_threshold)
                idx = min(int(ratio * 8), 8)
                line += blocks[idx]
            else:
                line += " "
        chart_lines.append(line)
        
    # Speed unit formatting helper
    def fmt_spd(b):
        if b >= 1_048_576:
            return f"{b/1_048_576:.1f}M"
        if b >= 1024:
            return f"{b/1024:.0f}K"
        return f"{b:.0f}B"
        
    combined = []
    for i, line in enumerate(chart_lines):
        val = ((height - i) / height) * max_val
        combined.append(f"[dim]{fmt_spd(val):>5} |[/] [bold green]{line}[/]")
    combined.append(" " * 6 + "+" + "-" * 32)
    combined.append(" " * 7 + "[dim]30s ago                     Now[/]")
    
    return "\n".join(combined)


def draw_mime_distribution(stats: dict[str, int]) -> str:
    """Render a horizontal ANSI progress bar block breakdown by MIME category."""
    total = sum(stats.values())
    if not total:
        return "\n\n[dim]No downloaded files registered in SQLite yet.[/]\n\n"
        
    lines = []
    colors = {"photo": "green", "video": "cyan", "doc": "yellow", "other": "magenta"}
    bar_width = 24
    
    for category, count in stats.items():
        pct = (count / total) * 100
        filled = int((count / total) * bar_width)
        bar = f"[{colors[category]}]" + ("█" * filled) + "[/][dim]" + ("░" * (bar_width - filled)) + "[/]"
        lines.append(
            f"[bold {colors[category]}]{category.upper():5}[/] {bar} [bold]{count}[/] [dim]({pct:.1f}%)[/]"
        )
    return "\n" + "\n\n".join(lines) + "\n"


def draw_7day_volume_chart(daily_data: list[tuple[str, int, int]], height: int = 7) -> str:
    """Render a beautiful colored vertical bar chart showing total download size over 7 days."""
    if not daily_data:
        return "\n\n[dim]No download records found.[/]\n\n"
        
    sizes_mb = [size_bytes / 1_048_576 for _, _, size_bytes in daily_data]
    max_mb = max(sizes_mb) or 1.0
    
    blocks = [" ", " ", "▂", "▃", "▄", "▅", "▆", "▇", "█"]
    chart_lines = []
    
    for r in range(height, 0, -1):
        line = "   "
        threshold = (r / height) * max_mb
        prev_threshold = ((r - 1) / height) * max_mb
        for sz in sizes_mb:
            if sz >= threshold:
                line += " [bold cyan]███[/] "
            elif sz > prev_threshold:
                ratio = (sz - prev_threshold) / (threshold - prev_threshold)
                idx = min(int(ratio * 8), 8)
                ch = blocks[idx] * 3
                line += f" [bold cyan]{ch}[/] "
            else:
                line += "     "
        chart_lines.append(line)
        
    label_line = "   "
    for date_str, _, _ in daily_data:
        short_date = date_str[-5:]  # "MM-DD"
        label_line += f" [dim]{short_date}[/] "
        
    mb_labels = []
    for r in range(height, 0, -1):
        val = (r / height) * max_mb
        mb_labels.append(f"{val:4.1f}M")
        
    combined_lines = []
    for i, line in enumerate(chart_lines):
        combined_lines.append(f"[dim]{mb_labels[i]} |[/]{line}")
    combined_lines.append(" " * 6 + "+" + "-" * 7 * 5)
    combined_lines.append(" " * 7 + label_line)
    
    return "\n" + "\n".join(combined_lines)


def draw_system_ratio_metrics(stats: dict[str, int]) -> str:
    """Render metrics table and upload success ratio details."""
    total = stats.get("total", 0)
    uploaded = stats.get("uploaded", 0)
    pending = stats.get("pending", 0)
    
    ratio = (uploaded / total * 100) if total else 0.0
    bar_len = 20
    filled = int(ratio / 100 * bar_len)
    bar_chars = "[green]" + ("█" * filled) + "[/][dim]" + ("░" * (bar_len - filled)) + "[/]"
    
    content = (
        f"\n"
        f"Total Registered : [bold cyan]{total}[/] files\n\n"
        f"Uploaded Files   : [bold green]{uploaded}[/] items\n\n"
        f"Pending Uploads  : [bold yellow]{pending}[/] queued\n\n"
        f"Completion Ratio : {bar_chars} [bold]{ratio:.1f}%[/]\n"
    )
    return content

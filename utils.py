"""Shared utility functions."""
from __future__ import annotations


def format_bytes(n: int) -> str:
    """Format bytes to human-readable string."""
    if n >= 1_073_741_824:
        return f"{n / 1_073_741_824:.1f} GB"
    if n >= 1_048_576:
        return f"{n / 1_048_576:.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n} B"


def sanitize_filename(s: str) -> str:
    """Remove invalid filename characters."""
    return "".join(c for c in s if c not in r'<>:"/\|?*' and c.isprintable()).strip() or "unknown"


def parse_boolean(v) -> bool:
    """Parse a boolean from various formats."""
    if isinstance(v, bool):
        return v
    return str(v).lower() in ("true", "1", "yes", "on")


def sanitize_group(name: str) -> str:
    """Sanitize group name for use as folder name."""
    s = sanitize_filename(name) if name else ""
    return s[:60] or "unknown_group"

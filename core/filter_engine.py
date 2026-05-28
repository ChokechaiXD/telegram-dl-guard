# -*- coding: utf-8 -*-
"""Filter engine — check if chat or media type matches config."""
from __future__ import annotations

from typing import Any


class FilterEngine:
    def __init__(self, target_groups: str, media_types: str) -> None:
        # Normalize: strip "-" for supergroup IDs, keep as-is for usernames
        self.target_groups = []
        for g in target_groups.split(","):
            g = g.strip()
            if not g:
                continue
            # Strip leading "-" for numeric IDs (supergroup format: -100xxx)
            self.target_groups.append(g.lstrip("-"))
        self.media_types = {m.strip().lower() for m in media_types.split(",") if m.strip()}

    def check_group(self, chat: Any) -> bool:
        """Match by normalized chat ID or @username."""
        if hasattr(chat, "id") and chat.id is not None:
            cid = str(chat.id).lstrip("-")
            for g in self.target_groups:
                if g == cid or g == str(chat.id):
                    return True
        if hasattr(chat, "username") and chat.username:
            uname = chat.username
            if not uname.startswith("@"):
                uname = "@" + uname
            if uname.lstrip("@") in {g.lstrip("@") for g in self.target_groups}:
                return True
        return False

    def check_media_type(self, mtype: str) -> bool:
        return mtype.strip().lower() in self.media_types

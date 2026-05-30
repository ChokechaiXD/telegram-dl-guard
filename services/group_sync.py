# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GroupChoice:
    id: int
    title: str


async def fetch_group_choices(client) -> list[GroupChoice]:
    dialogs = await client.get_dialogs(limit=None)
    groups = [
        GroupChoice(id=d.id, title=d.title or "Untitled")
        for d in dialogs
        if getattr(d, "is_group", False) or getattr(d, "is_channel", False)
    ]
    return sorted(groups, key=lambda g: g.title.casefold())


def to_cache_rows(groups: list[GroupChoice]) -> list[tuple[int, str]]:
    return [(group.id, group.title) for group in groups]


def to_api_rows(groups: list[GroupChoice]) -> list[dict[str, str]]:
    return [{"id": str(group.id), "title": group.title} for group in groups]

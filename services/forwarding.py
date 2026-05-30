# -*- coding: utf-8 -*-
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Awaitable, Callable

from telethon.errors import ChatForwardsRestrictedError


UploadSingle = Callable[[Any, int, Path, str], Awaitable[int | None]]


async def forward_or_upload(
    client,
    source_entity,
    storage_entity,
    msg,
    upload_single_func: UploadSingle,
    caption: str = "",
    storage_upload_target: int | None = None,
) -> dict[str, int | str | None]:
    try:
        forwarded = await client.forward_messages(storage_entity, msg.id, source_entity)
        return {
            "mode": "forward",
            "message_id": getattr(forwarded, "id", None) if forwarded else None,
        }
    except ChatForwardsRestrictedError:
        return await upload_protected_media(
            client,
            storage_upload_target if storage_upload_target is not None else storage_entity,
            msg,
            upload_single_func,
            caption,
        )


async def upload_protected_media(
    client,
    storage_entity,
    msg,
    upload_single_func: UploadSingle,
    caption: str = "",
) -> dict[str, int | str | None]:
    with tempfile.TemporaryDirectory() as td:
        downloaded = await client.download_media(msg.media, file=td)
        if not downloaded:
            return {"mode": "fallback", "message_id": None}

        fpath = Path(downloaded)
        if not fpath.exists() or fpath.stat().st_size <= 0:
            return {"mode": "fallback", "message_id": None}

        uploaded_id = await upload_single_func(client, int(storage_entity), fpath, caption)
        return {"mode": "fallback", "message_id": uploaded_id}


def summarize_forward_results(results: list[dict[str, int | str | None]]) -> dict[str, int]:
    forwarded_items = 0
    fallback_uploaded_items = 0
    failed_items = 0

    for result in results:
        mode = result.get("mode")
        message_id = result.get("message_id")
        if mode == "forward" and message_id:
            forwarded_items += 1
        elif mode == "fallback" and message_id:
            fallback_uploaded_items += 1
        else:
            failed_items += 1

    return {
        "forwarded_items": forwarded_items,
        "fallback_uploaded_items": fallback_uploaded_items,
        "failed_items": failed_items,
    }

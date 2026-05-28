"""
Smart File Picker — web UI for selecting files to upload to storage.

Features:
- Search by filename
- Filter by file type (image/video/doc)
- Sort by date/size/name
- Pagination (50 per page)
- Batch upload mode (album thread)
- O(n) via id() based index map
"""
from __future__ import annotations

import logging
import threading
import webbrowser
from pathlib import Path

from flask import Flask, render_template, request, jsonify, send_file

from utils import format_bytes

from config import AppConfig
from upload_tracker import scan_downloads, cleanup_missing

log = logging.getLogger("guard.tinder_picker")

app = Flask(__name__)

# State
_state = {
    "files": [],
    "by_user": {},
    "users": [],
    "current_user": "",
    "selected": set(),
    "uploaded": set(),
    "failed": set(),
    "done": False,
    "_scan_cache": None,
    "_cache_dirty": True,
    "_tags": {},  # filepath -> tag (from rules engine)
}

PAGE_SIZE = 50


def _get_file_type(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg"}:
        return "image"
    if ext in {".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv", ".m4v", ".3gp"}:
        return "video"
    return "document"


def _get_file_icon(filename: str) -> str:
    t = _get_file_type(filename)
    return {"image": "[IMG]", "video": "[VID]", "document": "[DOC]"}[t]


# ── Index map (O(n) fix) ────────────────────────────────────


def _file_idx_map() -> dict[int, int]:
    """Build id(file_dict) -> index map in O(n) once per request."""
    return {id(f): i for i, f in enumerate(_state["files"])}


# ── File loading ────────────────────────────────────────────


def _load_files(force: bool = False):
    """Load pending files grouped by sender (cached)."""
    if not force and not _state["_cache_dirty"] and _state["_scan_cache"] is not None:
        _state["files"] = _state["_scan_cache"]
        _state["by_user"] = _state.get("_by_user_cache", {})
        _state["users"] = sorted(_state["by_user"].keys())
        if _state["current_user"] not in _state["by_user"]:
            _state["current_user"] = _state["users"][0] if _state["users"] else ""
        return

    cleanup_missing()
    all_files = scan_downloads()
    pending = [f for f in all_files if not f["uploaded"]]

    by_user = {}
    for f in pending:
        p = Path(f["filepath"])
        parts = p.parts
        sender = parts[1] if len(parts) > 2 else (parts[0] if len(parts) > 1 else "unknown")
        f["sender"] = sender
        f["file_type"] = _get_file_type(f["filename"])
        f["file_icon"] = _get_file_icon(f["filename"])
        f["size_fmt"] = format_bytes(f["size"])
        f["tag"] = _state["_tags"].get(f["filepath"], "")
        by_user.setdefault(sender, []).append(f)

    _state["files"] = pending
    _state["by_user"] = by_user
    _state["users"] = sorted(by_user.keys())
    _state["current_user"] = _state["users"][0] if _state["users"] else ""
    _state["selected"] = set()
    _state["uploaded"] = set()
    _state["failed"] = set()
    _state["done"] = False
    _state["_scan_cache"] = pending
    _state["_by_user_cache"] = by_user
    _state["_cache_dirty"] = False


def _user_stats(user: str) -> dict:
    """O(n) using id() map."""
    files = _state["by_user"].get(user, [])
    total = len(files)
    selected = uploaded = 0
    total_size = 0
    idx_map = _file_idx_map()
    selected_set = _state["selected"]
    uploaded_set = _state["uploaded"]
    for f in files:
        idx = idx_map.get(id(f), -1)
        if idx >= 0:
            if idx in selected_set:
                selected += 1
            if idx in uploaded_set:
                uploaded += 1
        total_size += f.get("size", 0)
    return {"total": total, "selected": selected, "uploaded": uploaded, "size": format_bytes(total_size)}


# ── Search / Filter / Sort ─────────────────────────────────


def _filter_files(files: list[dict], search: str, file_type: str, sort: str) -> list[dict]:
    """Apply search, filter, and sort to file list."""
    result = list(files)

    # Search
    if search:
        q = search.lower()
        result = [f for f in result if q in f["filename"].lower()]

    # Filter by type
    if file_type and file_type != "all":
        result = [f for f in result if f["file_type"] == file_type]

    # Sort
    if sort == "date_asc":
        result.sort(key=lambda f: f.get("date", ""))
    elif sort == "date_desc":
        result.sort(key=lambda f: f.get("date", ""), reverse=True)
    elif sort == "size_asc":
        result.sort(key=lambda f: f.get("size", 0))
    elif sort == "size_desc":
        result.sort(key=lambda f: f.get("size", 0), reverse=True)
    elif sort == "name":
        result.sort(key=lambda f: f["filename"].lower())

    return result


# ── Routes ──────────────────────────────────────────────────


@app.route("/api/delete", methods=["POST"])
def api_delete():
    """Delete selected files from disk and tracker."""
    indices = request.json.get("indices", [])
    deleted = failed = 0
    for idx in indices:
        if 0 <= idx < len(_state["files"]):
            f = _state["files"][idx]
            p = Path(f["filepath"])
            try:
                if p.exists():
                    p.unlink()
                from upload_tracker import remove_entry
                remove_entry(f["filepath"])
                _state["files"][idx] = None
                deleted += 1
            except Exception:
                failed += 1
    _state["files"] = [f for f in _state["files"] if f is not None]
    by_user = {}
    for f in _state["files"]:
        by_user.setdefault(f.get("sender", "unknown"), []).append(f)
    _state["by_user"] = by_user
    _state["users"] = sorted(by_user.keys())
    _state["selected"] = set()
    _state["uploaded"] = set()
    if _state["current_user"] not in _state["by_user"]:
        _state["current_user"] = _state["users"][0] if _state["users"] else ""
    _state["_cache_dirty"] = True
    return jsonify({"deleted": deleted, "failed": failed})


@app.route("/")
def index():
    if not _state["files"]:
        _load_files()
    return render_template("picker.html")


@app.route("/api/data")
def api_data():
    """Return data with search, filter, sort, pagination."""
    idx_map = _file_idx_map()
    selected_set = _state["selected"]
    uploaded_set = _state["uploaded"]
    failed_set = _state["failed"]

    # User stats
    users = []
    for u in _state["users"]:
        stats = _user_stats(u)
        users.append({"name": u, **stats})

    # Get query params
    search = request.args.get("q", "").strip()
    file_type = request.args.get("type", "all")
    sort = request.args.get("sort", "date_desc")
    page = max(1, request.args.get("page", 1, type=int))

    # Get files for current user
    user_files = _state["by_user"].get(_state["current_user"], [])

    # Apply search/filter/sort
    filtered = _filter_files(user_files, search, file_type, sort)

    # Pagination
    total = len(filtered)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(page, total_pages)
    start = (page - 1) * PAGE_SIZE
    end = start + PAGE_SIZE
    page_files = filtered[start:end]

    current_files = []
    for f in page_files:
        idx = idx_map.get(id(f), -1)
        current_files.append({
            "idx": idx,
            "filename": f["filename"],
            "filepath": f["filepath"],
            "size": f["size"],
            "size_fmt": f["size_fmt"],
            "date": f.get("date", ""),
            "file_type": f["file_type"],
            "file_icon": f["file_icon"],
            "tag": f.get("tag", ""),
            "selected": idx in selected_set,
            "uploaded": idx in uploaded_set,
            "failed": idx in failed_set,
        })

    return jsonify({
        "users": users,
        "current_user": _state["current_user"],
        "files": current_files,
        "total_files": len(_state["files"]),
        "total_selected": len(_state["selected"]),
        # Pagination
        "page": page,
        "total_pages": total_pages,
        "page_size": PAGE_SIZE,
        "filtered_count": total,
        # Active filters
        "search": search,
        "filter_type": file_type,
        "sort": sort,
    })


@app.route("/api/set_user", methods=["POST"])
def api_set_user():
    user = request.json.get("user", "")
    if user in _state["by_user"]:
        _state["current_user"] = user
    return jsonify({"current_user": _state["current_user"]})


@app.route("/api/action", methods=["POST"])
def api_action():
    """Handle action: skip / select / select_all / clear_all."""
    data = request.json
    action = data.get("action", "")
    idx = data.get("idx")
    user = _state["current_user"]

    user_indices = set()
    if user and user in _state["by_user"]:
        idx_map = _file_idx_map()
        for f in _state["by_user"][user]:
            i = idx_map.get(id(f), -1)
            if i >= 0:
                user_indices.add(i)

    if action == "select" and idx is not None:
        _state["selected"].add(idx)
    elif action == "skip" and idx is not None:
        _state["selected"].discard(idx)
    elif action == "select_all":
        _state["selected"] |= user_indices
    elif action == "clear_all":
        _state["selected"] -= user_indices

    return jsonify({"selected": len(_state["selected"]), "total": len(_state["files"])})


@app.route("/api/preview/<int:idx>")
def api_preview(idx):
    if 0 <= idx < len(_state["files"]):
        p = Path(_state["files"][idx]["filepath"])
        if p.exists():
            return send_file(str(p))
    return "", 404


@app.route("/api/upload", methods=["POST"])
def api_upload():
    """Upload selected files. Supports batch mode (album thread)."""
    cfg = AppConfig.load()
    if not cfg.storage_group_id:
        return jsonify({"error": "Storage group not set"}), 400

    body = request.json or {}
    indices = body.get("indices", [])

    if not indices:
        indices = sorted(_state["selected"])

    if not indices:
        return jsonify({"error": "No files selected"}), 400

    files_to_upload = [_state["files"][i] for i in indices if i < len(_state["files"])]

    import asyncio

    async def _do():
        from telethon import TelegramClient
        from telethon.sessions import StringSession
        from uploader import batch_upload_files
        cli = TelegramClient(StringSession(cfg.session_string), cfg.api_id, cfg.api_hash)
        await cli.connect()
        try:
            return await batch_upload_files(cli, int(cfg.storage_group_id), files_to_upload)
        finally:
            await cli.disconnect()

    result = asyncio.run(_do())

    if result:
        for i in indices:
            if i < len(_state["files"]):
                _state["uploaded"].add(i)
        _state["selected"] = set()

    return jsonify(result or {"success": 0, "failed": 0, "skipped": 0})


@app.route("/api/tags", methods=["GET"])
def api_tags():
    """Return all unique tags."""
    tags = set()
    for f in _state["files"]:
        t = f.get("tag", "")
        if t:
            tags.add(t)
    return jsonify(sorted(tags))


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "pending_files": len(_state["files"]),
        "users": len(_state["users"]),
        "selected": len(_state["selected"]),
        "cache_dirty": _state["_cache_dirty"],
    })


@app.route("/api/stats")
def api_stats():
    return jsonify({
        "total": len(_state["files"]),
        "selected": len(_state["selected"]),
        "uploaded": len(_state["uploaded"]),
        "failed": len(_state["failed"]),
    })


def start_picker(host: str = "127.0.0.1", port: int = 7878):
    _load_files()
    url = f"http://{host}:{port}"
    print(f"\n  Smart Picker -> {url}")
    print(f"  {len(_state['files'])} pending files, {len(_state['users'])} users\n")
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host=host, port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    start_picker()

# Telegram DL Guard — System Audit & Upgrade Plan

**Date:** 2026-05-27
**Scope:** Full system review — bugs, dead code, performance, UX, architecture

---

## Current State

### What Works
- Multi-source group download with dedup (message ID + hash)
- Real-time upload to storage group (4 modes)
- Web-based Tinder picker with user tabs, keyboard shortcuts
- Persistent state (processed IDs, group cache) across restarts
- In-memory cache + debounce save for upload tracker
- LRU cache for group ID normalization

### Architecture
```
guard.py          → CLI entry point, menu, settings
listener.py       → Download listener, upload worker hook
uploader.py       → Upload queue, worker, batch upload
upload_tracker.py → JSON-backed upload state DB
filters.py        → Group/media type filtering
stats.py          → Download statistics
history.py        → History scan (past messages)
web_picker.py     → Flask web UI for file selection
config.py         → Config loading (.env + yaml)
```

---

## Issues Found

### 🔴 Bugs

| # | File | Issue | Fix |
|---|------|-------|-----|
| 1 | web_picker.py | `api_upload()` sends ALL selected files every time — no indices passed | Pass `indices` array in request body |
| 2 | static/picker.js | `doUpload()` called multiple times (no guard) + key repeat | Add `_uploading` flag + `e.repeat` check |
| 3 | static/picker.js | `doUpload()` selects all then uploads — but selection state persists → double upload on second W | Clear selection after upload |
| 4 | listener.py | `folder_date_format` still in config but no longer used in path | Remove from config or keep for filename only |
| 5 | guard.py | `_batch_upload_all()` in terminal doesn't pass indices properly | Same fix as web_picker |

### 🟡 Code Quality

| # | File | Issue | Fix |
|---|------|-------|-----|
| 6 | listener.py | `_LRUCache` class but only used for hash dedup — overkill for simple dict | Replace with plain dict + max size check |
| 7 | listener.py | `_sanitize()` called on every message — regex is slow | Cache sanitized names |
| 8 | uploader.py | `build_caption()` called for every file even in batch | Build caption once per batch |
| 9 | web_picker.py | `_format_size()` duplicate of `stats.format_bytes` | Import from stats |
| 10 | guard.py | `_menu_media()` dead code (replaced by Settings > Media Types) | Remove |
| 11 | config.py | `folder_date_format` field unused | Remove or document as "for filename only" |
| 12 | history.py | `_download_one()` calls `get_messages()` per message — very slow | Batch download |

### 🟢 Performance

| # | File | Issue | Fix |
|---|------|-------|-----|
| 13 | listener.py | `download_media()` called with `file=str(fpath)` — no progress callback | Add progress callback for large files |
| 14 | uploader.py | `send_file()` called per file in batch — should use album | Use `file=[list]` for album upload |
| 15 | web_picker.py | `scan_downloads()` called on every page load | Cache result, refresh on action |
| 16 | upload_tracker.py | `_load()` called on every `is_uploaded()` — debounce is 5s but still frequent | Increase debounce to 30s |

### 🔵 UX Improvements

| # | Area | Issue | Fix |
|---|------|-------|-----|
| 17 | Web picker | No visual feedback during upload (progress bar stuck at 0%) | Add real-time progress via polling |
| 18 | Web picker | Can't see which files are selected at a glance | Add selected count per user tab |
| 19 | Web picker | No "select all" keyboard shortcut | Add `A` = select all in current user |
| 20 | Terminal | No way to see upload queue status | Add `[q]` command in listener header |
| 21 | Terminal | No way to pause/resume listener | Add `[p]` pause, `[r]` resume |
| 22 | Settings | No way to set min file size filter | Add `MIN_FILE_SIZE_KB` setting |
| 23 | Settings | No way to block specific senders | Add `BLOCKED_SENDERS` list |

---

## Upgrade Tasks

### Phase 1: Bug Fixes (Critical)
1. Fix `api_upload()` to accept `indices` array
2. Fix `doUpload()` guard + clear selection after upload
3. Fix key repeat issue in picker
4. Remove `folder_date_format` from path building
5. Fix `_batch_upload_all()` to pass indices

### Phase 2: Code Cleanup
6. Replace `_LRUCache` with plain dict
7. Cache sanitized sender names
8. Remove dead code (`_menu_media`, duplicate `_format_size`)
9. Increase upload tracker debounce to 30s
10. Batch download in history scan

### Phase 3: Performance
11. Add progress callback for large file downloads
12. Use album upload (send multiple files in one message)
13. Cache `scan_downloads()` result in web picker
14. Optimize `is_uploaded()` calls

### Phase 4: UX
15. Real-time upload progress in web picker
16. Selected count per user tab
17. `A` = select all shortcut
18. Listener queue status display
19. Pause/resume listener
20. Min file size filter
21. Blocked senders list

---

## File Changes Summary

| File | Changes |
|------|---------|
| web_picker.py | Fix upload API, cache scan_results, dedup format_bytes |
| static/picker.js | Fix doUpload guard, clear selection, key repeat, progress polling |
| static/picker.css | Add selected count badge, progress bar animation |
| templates/picker.html | Update help panel, add progress bar |
| listener.py | Remove date folder, cache sender names, add pause/resume |
| uploader.py | Album upload, batch caption building |
| upload_tracker.py | Increase debounce to 30s |
| guard.py | Remove dead code, add queue status, add min file size setting |
| config.py | Remove folder_date_format, add min_file_size, blocked_senders |
| history.py | Batch download |
| filters.py | Cache sanitized names |

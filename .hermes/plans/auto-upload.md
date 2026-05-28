# Auto-Upload to Storage Group — Implementation Plan

**Goal:** Auto-upload downloaded files to a Telegram storage group/channel with caption (filename + sender + @username + date). Real-time on download + batch fallback. Separate cleanup command to delete local files after upload.

**Architecture:**
- New module `uploader.py` — handles all Telegram upload logic (real-time queue + batch scan)
- New module `upload_tracker.py` — tracks which files have been uploaded (JSON db)
- Modify `listener.py` — hook into download success to enqueue for upload
- Modify `guard.py` — add menu for storage group config + manual cleanup command
- Config: `STORAGE_GROUP_ID` in .env, upload settings in config.yaml

**Tech Stack:** Telethon (send_file), asyncio Queue, JSON tracker, aiofiles (optional)

---

### Task 1: upload_tracker.py — Upload state database
**Files:**
- Create: `upload_tracker.py`

- [ ] 1.1 Create `upload_tracker.py` with:
  - `logs/upload_tracker.json` — stores records: `{filepath: {uploaded: bool, msg_id: int, storage_msg_id: int, uploaded_at: str}}`
  - `is_uploaded(filepath)` → bool
  - `mark_uploaded(filepath, storage_msg_id)` → None
  - `get_pending()` → list of filepaths not yet uploaded
  - `get_uploaded_list()` → list of filepaths already uploaded

- [ ] 1.2 Verify: import test, create instance, mark one file, check is_uploaded

---

### Task 2: uploader.py — Upload engine (real-time + batch)
**Files:**
- Create: `uploader.py`

- [ ] 2.1 Build `UploadTracker` wrapper (or import from Task 1)

- [ ] 2.2 Build `UploadQueue` class:
  - `asyncio.Queue`-based
  - `enqueue(filepath, sender_name, sender_username, date, media_type)` → puts item
  - `worker(client, storage_group_id)` — dequeues and uploads one by one

- [ ] 2.3 Build `build_caption(sender_name, sender_username, date, filename)`:
  ```
  📁 filename.jpg
  👤 Sender Name (@username)
  📅 2026-05-27 22:30
  ```
  - Handle missing username: show `@unknown` or skip @ line
  - Handle missing sender_name: show `unknown`

- [ ] 2.4 Build `upload_file(client, storage_group_id, filepath, caption)`:
  - Detect media type from extension (photo/video/document)
  - Use `client.send_file()` with `file=` and `caption=` and `force_document=False`
  - Return `message.id` on success, `None` on failure
  - Handle `FloodWaitError` — sleep and retry once
  - Handle other errors — log and return None

- [ ] 2.5 Build `run_batch_upload(client, storage_group_id)`:
  - Read pending files from tracker
  - Upload each one with caption
  - Mark uploaded on success

- [ ] 2.6 Build `start_upload_worker(client, storage_group_id)`:
  - Create asyncio task running `worker()` loop
  - Return task handle for cancellation

---

### Task 3: listener.py — Hook download success → enqueue upload
**Files:**
- Modify: `listener.py` (in `_on_msg` handler, after `record_download(sz)`)

- [ ] 3.1 After download success, call `upload_queue.enqueue()`:
  - Get sender username (extend `_resolve_sender` or add new `resolve_sender_username`)
  - Pass: filepath, sender_name, sender_username, msg.date, media_type

- [ ] 3.2 Start upload worker task in `run()`:
  - Create `asyncio.Queue` at module level
  - Start worker task alongside cleanup task
  - Cancel worker in `finally` block

- [ ] 3.3 Graceful shutdown: worker finishes current item before exit

---

### Task 4: guard.py — Config menu + cleanup command
**Files:**
- Modify: `guard.py`

- [ ] 4.1 Add config for storage:
  - `STORAGE_GROUP_ID` in .env (supports group or channel ID)
  - `UPLOAD_ENABLED` in .env or config.yaml

- [ ] 4.2 Add menu option `[7] Storage Group` — set storage group ID (similar to `_list_groups()`)

- [ ] 4.3 Add menu option `[8] Cleanup Local Files` — show list of uploaded files, confirm before deleting local

- [ ] 4.4 Cleanup command:
  - Read `upload_tracker.get_uploaded_list()`
  - Show count and total size
  - Ask `Delete N files? [y/N]`
  - Delete each file, remove from tracker

---

### Task 5: config.py — New config fields
**Files:**
- Modify: `config.py`

- [ ] 5.1 Add to `AppConfig`:
  - `storage_group_id: str = ""`
  - `upload_enabled: bool = False`

- [ ] 5.2 Add to `AppConfig.load()`:
  - `storage_group_id=_get("STORAGE_GROUP_ID", "storage_group_id", "")`
  - `upload_enabled=_F("upload.enabled", False)`

- [ ] 5.3 Add to config.yaml.example:
  ```yaml
  storage_group_id: ""
  upload:
    enabled: true
    mode: "realtime"  # realtime | batch | both
  ```

---

### Task 6: Integration test
**Files:**
- Test manually (no unit test framework for Telegram API)

- [ ] 6.1 Set `STORAGE_GROUP_ID` to a test group
- [ ] 6.2 Enable upload, start listener
- [ ] 6.3 Send a photo to source group → verify download + upload with caption
- [ ] 6.4 Send a video → verify caption format
- [ ] 6.5 Kill listener, restart → verify batch upload picks up pending
- [ ] 6.6 Run cleanup → verify local files deleted after confirmation

---

## File Map

| File | Purpose |
|------|---------|
| `upload_tracker.py` | JSON-backed upload state DB |
| `uploader.py` | Upload queue, worker, caption builder |
| `listener.py` | Hook: download success → enqueue |
| `guard.py` | Menu: config storage, cleanup local |
| `config.py` | New fields: storage_group_id, upload_enabled |
| `config.yaml` | New section: upload settings |

# Code Consolidation Analysis

## Current File Structure (9 files)
```
guard.py          502 lines  — CLI entry, menu, settings, batch upload
listener.py       592 lines  — Download listener, filters, upload worker hook
uploader.py       293 lines  — Upload queue, worker, batch upload, caption
upload_tracker.py 216 lines  — JSON-backed upload state DB
web_picker.py     293 lines  — Flask web UI for file selection
config.py         135 lines  — Config loading (.env + yaml)
filters.py         51 lines  — Group/media type filtering
stats.py           70 lines  — Download statistics
history.py        ~220 lines — History scan
```

## Consolidation Opportunities

### 1. MERGE: filters.py → config.py (SAVE 1 file)
- filters.py มีแค่ 51 lines, 2 functions
- `_norm_id()` ใช้ FilterEngine → ย้ายทั้งหมดเข้า config.py
- FilterEngine ใช้ _CFG จาก config.py อยู่แล้ย

### 2. MERGE: stats.py → listener.py (SAVE 1 file)  
- stats.py มี 70 lines, 3 functions
- `format_bytes()` ใช้ใน guard.py, web_picker.py → ควรเป็น shared utility
- `record_download()`, `get_today_stats()`, `print_summary()` ใช้แค่ listener.py
- ย้าย format_bytes เป็น standalone utility, merge stats เข้า listener

### 3. EXTRACT: Shared utilities → utils.py (NEW file)
- ฟังก์ชันที่ใช้ซ้ำกัน:
  - `format_bytes()` — guard.py, web_picker.py, stats.py
  - `_sanitize()` — listener.py (ใช้ซ้ำใน _media_name, _resolve_sender)
- สร้าง `utils.html` สำหรับ shared helpers

### 4. SPLIT: guard.py → cli.py + settings.py
- guard.py ใหญ่ 502 lines — ทำหลายอย่างเกินไป
- แยก:
  - `cli.py` — main menu, listener, login, groups, batch upload
  - `settings.py` — settings sub-menus ทั้งหมด (6 sub-menus)

### 5. SIMPLIFY: upload_tracker.py
- มี 7 functions แต่ใช้จริงแค่ 3: scan_downloads, mark_uploaded, is_uploaded
- get_uploaded, get_all, get_stats → ใช้แค่ guard.py (debug/admin)
- ลดเหลือ core 3 functions + admin commands

### 6. REMOVE: history.py (or make it a mode in listener.py)
- History scan เป็น mode หนึ่งของ listener
- ย้ายเข้า listener.py เป็น `run_history_scan()` function
- ลด 1 file

### 7. RENAME: web_picker.py → picker.py
- "tinder" อยู่ในชื่อไม่จำเป็น — เป็น web picker ธรรมดา
- เปลี่ยนเป็น `picker.py`

---

## Recommended New Structure (7 files, down from 9)

```
Telegram DL Guard
├── cli.py            (~450 lines) — Main CLI, menu, listener, login
├── settings.py       (~200 lines) — All settings sub-menus  
├── listener.py       (~650 lines) — Download, filters, history, stats
├── uploader.py       (~290 lines) — Queue, worker, batch, caption
├── upload_tracker.py (~130 lines) — Core DB only (3 ops)
├── picker.py         (~290 lines) — Flask web UI
├── config.py         (~150 lines) — AppConfig + FilterEngine + utils
└── utils.py          (~30 lines) — format_bytes, sanitize
```

### Saved: 2 files eliminated
- filters.py → merged into config.py
- stats.py → merged into listener.py
- history.py → merged into listener.py (mode)

### Benefits:
- ไม่มี file เล็กกว่า 50 lines (ยกเว้น utils)
- แต่ละ file มี single responsibility
- import graph สะอาดขึ้น
- ง่ายต่อการ navigate

---

## Functions to Extract to utils.py

```python
# utils.py
def format_bytes(n: int) -> str: ...     # Used in 4 files
def sanitize_filename(s: str) -> str: ... # Used in listener
def parse_boolean(v) -> bool: ...        # Used in config, guard
```

## Functions that can be removed/merged

| Function | File | Action |
|----------|------|--------|
| get_uploaded | upload_tracker | ใช้แค่ guard.py debug → inline |
| get_all | upload_tracker | ไม่ได้ใช้ anywhere → ลบ |
| get_stats | upload_tracker | ใช้แค่ web_picker → inline scan_downloads |
| print_summary | stats | ใช้แค่ listener → inline |
| _norm_id | filters | ย้ายเข้า config.py |
| FilterEngine | filters | ย้ายเข้า listener.py (ใช้แค่ตอน listen) |

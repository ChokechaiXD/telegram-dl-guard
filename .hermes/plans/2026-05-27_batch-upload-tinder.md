# Batch Upload + Tinder-Style File Picker — Plan

**Goal:** ทำระบบ Upload ไฟล์ใน downloads ขึ้น storage group แบบเป็นชุด (batch 10 ไฟล์/ครั้ง) + มี UI แบบ Tinder ให้ user คัดเองว่าไฟล์ไหนจะ upload ไม่ใช่ upload ทั้งหมด

**Current Problem:**
- ไม่มี way upload ไฟล์เก่าที่อยู่ใน downloads แล้ว
- ถ่ายทอดทั้งหมด = ไฟล์ขยะอัพขึ้นด้วย
- UI แบบ command line ไม่เห็นหน้าตาไฟล์ → คัดไม่ได้

---

## Proposed Approach: 2 ระบบใหญ่

```
┌─────────────────────────────────────────────────────┐
│  [9] Batch Upload — ส่งไฟล์เก่าทั้งหมดขึ้น storage  │
│     └─ ส่งทีละ 10 ไฟล์ (Telegram limit)             │
│     └─ มี progress bar ว่าส่งไปแล้วกี่ไฟล์           │
│                                                     │
│  [t] Tinder Picker — คัดไฟล์ทีละไฟล์              │
│     └─ เห็น preview รูป/วิดีโอ                      │
│     └─ ปัด ← = skip, ปัด → = upload, ↑ = upload all │
│     └─ ส่งทีละ batch 10 ไฟล์                        │
└─────────────────────────────────────────────────────┘
```

---

## Step-by-Step Plan

### Phase 1: Upload All (Batch Upload)

#### Task 1.1: Scan local files
**Files:** `upload_tracker.py`

- [ ] 1.1 เพิ่ม `scan_downloads()` — scan downloads/ folder → return ทุกไฟล์ที่ยังไม่ uploaded
  ```python
  scan_downloads() → list[{filepath, filename, size, uploaded, date}]
  ```
  - อ่านจาก tracker (uploaded status) + scan จริงจาก disk
  - เทียบดูไฟล์ที่อยู่บน disk แต่ไม่มีใน tracker → mark pending

#### Task 1.2: Batch upload engine
**Files:** `uploader.py`

- [ ] 1.2 เพิ่ม `batch_upload_files(client, storage_gid, files, on_progress)`:
  - Input: list of file records
  - ส่งทีละ 10 ไฟล์ (Telegram group media limit)
  - `on_progress(current, total, filename)` callback สำหรับ UI
  - ส่งแต่ละ batch ด้วย `client.send_file()` group media
  - แต่ละ batch แอย่างน้อย 1 วินาที (avoid flood)
  - Return: `{success, failed, skipped}`

#### Task 1.3: UI สำหรับ Batch Upload
**Files:** `guard.py`

- [ ] 1.3 เพิ่ม `_batch_upload_all()`:

```
  Batch Upload to Storage
  ═══════════════════════
  Found 47 files not yet uploaded (1.2 GB)
  
  Upload mode: [1] All  [2] Photos only  [3] Videos only
  
  [Start] [Cancel]

  ┌──────────────────────┐
  │ ████████████░░░░░░░░ │ 23/47 (49%)
  │                      │
  │ ✅ photo1.jpg        │
  │ ✅ video2.mp4        │
  │ ⏳ photo3.jpg ...    │
  │ ⬜ photo4.jpg        │
  └──────────────────────┘
  
  24 OK | 2 failed | 21 remaining
```

---

### Phase 2: Tinder-Style File Picker

#### Task 2.1: Web-based Picker (Flask + HTML)
**Files:** `web_picker.py`, `templates/picker.html`, `static/picker.css`, `static/picker.js`

เหตุผล: Terminal UI ไม่สามารถแสดงรูป preview ได้ → ต้องใช้ web

- [ ] 2.1 สร้าง `web_picker.py`:
  - Flask app เล็กๆ — serve ที่ `http://localhost:7878`
  - Routes:
    - `GET /` — แสดงไฟล์ทั้งหมด + preview (grid หรือ carousel)
    - `POST /action` — รับ action: skip/upload/upload_all
    - `POST /upload_selected` — ส่งไฟล์ที่เลือกขึ้น storage
    - `GET /preview/<path>` — serve รูป/วิดีโอไฟล์
    - `GET /status` — return JSON: total, selected, uploaded
- [ ] 2.2 Auto-open browser เมื่อ user เริ่ม
  ```python
  import webbrowser, threading
  threading.Timer(1.0, lambda: webbrowser.open('http://localhost:7878')).start()
  ```

#### Task 2.2: Picker UI (HTML/CSS/JS)
**Files:** `templates/picker.html`, `static/picker.css`, `static/picker.js`

- [ ] 2.3 UI Layout:
  ```
  ┌─────────────────────────────────────────────────┐
  │  Tinder Upload Picker                   [✕]    │
  │  ─────────────────────────────────────────────  │
  │                                                  │
  │         ┌─────────────────────┐                 │
  │         │                     │                 │
  │         │    [IMAGE/VIDEO]    │  ← swipeable   │
  │         │    preview here     │                 │
  │         │                     │                 │
  │         └─────────────────────┘                 │
  │                                                  │
  │    photo_001.jpg • 2.3 MB • 2026-05-27         │
  │                                                  │
  │    ┌─────┐  ┌─────┐  ┌─────┐  ┌─────┐         │
  │    │ ←   │  │  ↑  │  │  →  │  │  ✓  │         │
  │    │skip │  │all  │  │upload│  │done │         │
  │    └─────┘  └─────┘  └─────┘  └─────┘         │
  │                                                  │
  │    Selected: 5/47  ████████░░░░░░░░░░          │
  │                                                  │
  │    ┌──────────────────────────────────────┐     │
  │    │ thumbs: [✓][✓][ ][✓][ ][ ]...[✓]    │     │
  │    └──────────────────────────────────────┘     │
  └─────────────────────────────────────────────────┘
  ```

- [ ] 2.4 Swipe mechanic:
  - ลากซ้าย (ยกเลิก swipe) = skip
  - ลากขวา = select for upload
  - ลากขึ้น = upload all remaining
  - Keyboard: ← skip, → upload, ↑ upload all, Esc = done
  - Thumbnail strip ด้านล่าง — เห็นว่าไฟล์ไหนผ่าน/ไม่ผ่านแล้ว

- [ ] 2.5 Preview:
  - รูป: serve ตรงจาก `/preview/<path>`
  - วิดีโอ: serve ตรงเป็น video player
  - เอกสาร: แสดง icon + ชื่อไฟล์ + ขนาด

#### Task 2.3: Upload selected files
**Files:** `web_picker.py` (POST /upload_selected)

- [ ] 2.6 หลัง user กด "Done":
  - รอบ files ที่ selected
  - ส่งทีละ batch 10 ไฟล์ด้วย `client.send_file(storage_gid, file=[...])`
  - Progress bar แสดง real-time (WebSocket หรือ polling)
  - สรุป: "Uploaded 23/47 files, 1.1 GB"

#### Task 2.4: Integrate เข้า guard.py
**Files:** `guard.py`

- [ ] 2.7 เพิ่มใน main menu:
  ```
  [9] Upload Old Files     — ส่งทั้งหมดทีละ batch
  [t] Tinder Picker        — คัดเองด้วย preview
  ```
  - Upload: เริ่ม app → ส่ง batch แสดง progress ใน terminal
  - Tinder: เริ่ม Flask → open browser → user คัด → upload

---

## Files to Change

| File | Purpose |
|------|---------|
| `upload_tracker.py` | + `scan_downloads()`, + `get_all()`, + `get_stats()` |
| `uploader.py` | + `batch_upload_files()` with progress callback |
| `guard.py` | + `_batch_upload_all()`, + `_tinder_picker()`, menu [9] [t] |
| `web_picker.py` | NEW — Flask web app |
| `templates/picker.html` | NEW — Tinder UI |
| `static/picker.css` | NEW — Styling |
| `static/picker.js` | NEW — Swipe logic, keyboard, upload |

---

## Options Comparison

| Approach | Pros | Cons |
|----------|------|------|
| **A: Web-based (Flask)** | Preview รูป/วิดีโอได้, UI สวย, swipe ได้ | ต้อง install Flask, เปิด browser |
| **B: Terminal only** | ไม่ต้อง install เพิ่ม, เร็ว | ไม่เห็น preview, UI จำกัด |
| **C: Desktop app (tkinter)** | Preview ได้, ไม่ต้อง browser | ต้อง install tkinter, code เยอะ |

** แนะนำ: A (Web-based)** — เพราะ:
- Flask เบามาก
- User ใช้ browser อยู่แล้ว
- Preview รูป/วิดีโอได้เต็มที่
- ต่อยอดได้ง่าย (เช่น filter, sort, search)

---

## Risks

| Risk | Mitigation |
|------|------------|
| Flask port conflict | ใช้ port 7878 (ไม่ซ้ำ common port) |
| ไฟล์ใหญ่ preview ช้า | Thumbnail เล็กๆ + lazy load |
| Upload batch ถูก block | เว้น 1 วินาที/batch, retry 3 ครั้ง |
| User ปิด browser กลางทาง | Save state, resume ได้ |

---

## Verification

1. กด [9] → scan → เห็น 47 ไฟล์ → กด Start → progress bar → upload 10/batch → สำเร็จ
2. กด [t] → browser เปิด → เห็นรูป preview → ปัด skip/upload → Done → upload selected
3. ปิด browser กลางทาง → กลับไป → resume ได้
4. Upload failed → retry auto → แสดง failed list

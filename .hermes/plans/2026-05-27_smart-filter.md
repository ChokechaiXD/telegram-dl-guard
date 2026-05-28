# Smart Download Filter & Quality Control — Plan

**Goal:** ทำให้ระบบดาวน์โหลดมีคุณภาพ — กรองไฟล์ที่ไม่ต้องการ ป้องกันไฟล์ขยะ ลดพื้นที่เสีย เพิ่ม UX ในการควบคุม

**Current Problem:**
- ดาวน์โหลดทุกอย่างที่ส่งมา ไม่มีการกรอง
- ไฟล์ขยะ (sticker, emoji, รูปเล็กๆ) เก็บเป็นหลัก
- ไฟล์ซ้ำ (dedup ไม่จับทุกกรณี)
- ไม่มี preview ก่อนดาวน์โหลด
- ไม่มี way บอกว่าไฟล์ไหนควรเก็บ ไฟล์ไหนควรข้าม

---

## Proposed Approach: Multi-Layer Filter

```
Message arrives
  │
  ├─ Layer 1: Sender Filter (block/allow list)
  ├─ Layer 2: Media Type Filter (photo/video/doc/sticker/animation)
  ├─ Layer 3: Size Filter (min/max file size)
  ├─ Layer 4: Content Filter (resolution, duration)
  ├─ Layer 5: Dedup (message ID + hash)
  │
  └─ Pass all → Download → Upload → [optional delete]
```

---

## Step-by-Step Plan

### Task 1: Media Type Filter — กรองประเทภไฟล์
**Files:** `filters.py`, `config.py`, `config.yaml`

- [ ] 1.1 เพิ่ม media type filter ใน `FilterEngine`:
  - `sticker` — ข้าม sticker ทั้งหมด (default: skip)
  - `animation` — ข้าม GIF/animation (default: skip)
  - `voice` / `video_note` — ข้าม (default: skip)
  - `photo` / `video` / `document` — เก็บ (default: keep)
- [ ] 1.2 เพิ่ม config: `SKIP_STICKERS=true`, `SKIP_ANIMATIONS=true`, `SKIP_VOICE=true`
- [ ] 1.3 เพิ่มใน Settings menu: `[b] Media Filter` — toggle แต่ละ type

### Task 2: Size Filter — กรองขนาดไฟล์
**Files:** `filters.py`, `config.py`, `config.yaml`

- [ ] 2.1 เพิ่ม size filter:
  - `MIN_FILE_SIZE_KB` — ข้ามไฟล์เล็กเกินไป (default: 10 KB, กรอง emoji/sticker ปลอม)
  - `MAX_FILE_SIZE_MB` — ข้ามไฟล์ใหญ่เกินไป (default: 500 MB)
- [ ] 2.2 Photo: กรอง resolution ต่ำ (เช่น < 100x100 = ข้าม)
- [ ] 2.3 เพิ่มใน Settings: `[c] Size Filter` — set min/max

### Task 3: Sender Filter — block/allow list
**Files:** `filters.py`, `config.py`, `config.yaml`

- [ ] 3.1 เพิ่ม sender filter:
  - `BLOCKED_SENDERS` — comma-separated user IDs (ข้ามทุก message จากคนนี้)
  - `ALLOWED_SENDERS` — ถ้า set ไว้ → รับเฉพาะคนใน list (whitelist mode)
- [ ] 3.2 เพิ่มใน Settings: `[d] Sender Filter` — add/remove blocked/allowed

### Task 4: Dedup ที่แข็งแกร่งขึ้น
**Files:** `listener.py`

- [ ] 4.1 ปัจจุบัน: `processed_ids` set — จำ message ID ที่ดาวน์โหลดแล้ว
  - ปัญหา: set หายเมื่อ restart → ดาวน์โหลดซ้ำได้
- [ ] 4.2 แก้: เก็บ `processed_ids` ลงไฟล์ (JSON) → load ตอน start
  - ช่วย history scan ด้วย — ข้ามไฟล์ที่เคยดาวน์โหลด
- [ ] 4.3 Hash-based dedup: ถ้าไฟล์เก่ามีอยู่ + hash ตรง → skip (ไม่ต้องดาวน์โหลดใหม่)

### Task 5: Download Queue แบบ Smart — ไม่ดาวน์โหลดทันที
**Files:** `listener.py`

- [ ] 5.1 เพิ่ม "smart queue":
  - Message มา → ใส่ queue → รอ 5 วินาที → ถ้ามี message ใหม่เข้ามา → ยกเลิก message เก่า (debounce)
  - ป้องกันการส่งซ้ำภายในเวลาสั้นๆ
- [ ] 5.2 เพิ่ม config: `DOWNLOAD_DELAY_SECONDS` (default: 0 = ทันที, ถ้า set = รอ)

### Task 6: Post-Download Cleanup Tools
**Files:** `guard.py`

- [ ] 6.1 เพิ่มใน Settings: `[e] Clean Duplicates`
  - Scan downloads → hash compare → แสดง list → confirm → delete
  - (script ที่ทำไปแล้ว — รวมเข้า guard.py)
- [ ] 6.2 เพิ่ม: `[f] Clean Small Files`
  - ลบไฟล์ < min_size ที่เก็บไว้โดยไม่ตั้งใจ
- [ ] 6.3 เพิ่ม: `[g] Clean by Date`
  - ลบไฟล์เก่ากว่า N วัน (แต่ยังเก็บ tracker)

### Task 7: Upload Tracker ที่สมบูรณ์
**Files:** `upload_tracker.py`

- [ ] 7.1 เพิ่ม: `get_all()` — return ทุก record (ทั้ง uploaded + pending)
- [ ] 7.2 เพิ่ม: `get_stats()` — return summary: total, uploaded, pending, total_size
- [ ] 7.3 เพิ่มใน listener header: แสดง "Upload: 45/50 done, 5 pending"

### Task 8: Settings Page ที่ครบถ้วน
**Files:** `guard.py`

- [ ] 8.1 จัดระเบียบ Settings menu ใหม่:
  ```
  [1] Storage Group
  [2] Upload Mode
  [3] Media Types
  [4] Media Filter (sticker/animation/voice)
  [5] Size Filter (min/max)
  [6] Sender Filter (block/allow)
  [7] Dedup Settings
  [8] Download Delay
  [9] Auto-Cleanup
  [a] Clean Duplicates
  [b] Clean Small Files
  [c] Upload Clean (delete local after upload)
  ```

---

## Files to Change

| File | Changes |
|------|---------|
| `filters.py` | + media type filter, + size filter, + sender filter |
| `config.py` | + new fields: skip_stickers, skip_animations, min_size, max_size, blocked_senders, allowed_senders, download_delay |
| `config.yaml` | + new sections: media_filter, size_filter, sender_filter |
| `listener.py` | + smart queue, + debounce, + persistent dedup, + better upload status |
| `upload_tracker.py` | + get_all(), get_stats() |
| `guard.py` | + settings menu reorganized, + cleanup tools |

---

## Risks & Tradeoffs

| Risk | Mitigation |
|------|------------|
| Filter เข้มเกินไป → ข้ามไฟล์ที่ต้องการ | Default เป็น "อ่อน" — skip sticker/animation อย่างเดียว, ไม่ block sender |
| Persistent dedup → ไฟล์ใหญ่ | Limit 50k entries, auto-clear เมื่อเกิน |
| Debounce delay → ดาวน์โหลดช้า | Default = 0 (ทันที), user เลือกเอง |
| Hash scan →ช้า | ทำ async, ไม่ block download |

---

## Verification

1. ส่ง sticker → ข้าม (ไม่ดาวน์โหลด)
2. ส่งรูป 50x50 → ข้าม (เล็กเกินไป)
3. ส่งรูป 2 ครั้ง → ดาวน์โหลดครั้งเดียว
4. block sender → ไม่ดาวน์โหลดจากคนนั้น
5. Clean Duplicates → ลบไฟล์ซ้ำที่เหลืออยู่
6. Settings → toggle ทุก filter → listener ใช้ค่าใหม่

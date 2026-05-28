# Multi-Group Selection — Implementation Plan

**Goal:** กด [2] Groups → เห็น list กลุ่มทั้งหมด → เลือกหลายกลุ่มได้ง่าย (checkbox style) → save เป็น comma-separated IDs

**Architecture:**
- แก้ `_list_groups()` ใน guard.py ให้เป็น multi-select UI
- ตัว config ไม่ต้องแก้ — รับ comma-separated string อยู่แล้ว
- listener.py ไม่ต้องแก้ — split(",") อยู่แล้ว

---

### Task 1: ปรับ _list_groups() ให้เป็น multi-select
**Files:**
- Modify: `guard.py` — `_list_groups()`

- [ ] 1.1 แสดง list กลุ่มพร้อม checkbox `[ ]` / `[x]`:
  ```
  Select source groups (toggle with number, then Enter):

    [ ] [  1] -1003538211705  อวดเมีย [คงเป็ดหลิม]
    [ ] [  2] -1001234567890  Another Group
    [ ] [  3] -1009876543210  Third Channel

    Toggle: 1,2,3 | Done: Enter | Cancel: c
  ```

- [ ] 1.2 Loop:
  - แสดง list พร้อม checkbox
  - รอ input (comma-separated numbers หรือ Enter เพื่อ finish)
  - Toggle selection ตามหมายเลขที่กด
  - กด Enter → save selected IDs
  - กด `c` → cancel

- [ ] 1.3 Save selected IDs เป็น comma-separated string:
  ```python
  set_key(".env", "TARGET_GROUPS", ",".join(sel))
  ```

- [ ] 1.4 แสดงสรุปก่อน save:
  ```
  Selected 2 groups:
    -1003538211705  อวดเมีย [คงเป็ดหลิม]
    -1001234567890  Another Group
  Save? [Y/n]
  ```

---

### Task 2: ปรับ _show_menu() ให้แสดงจำนวนกลุ่ม
**Files:**
- Modify: `guard.py` — `_show_menu()`

- [ ] 2.1 แสดงจำนวนกลุ่มและชื่อย่อ:
  ```
  Groups:   2 groups: อวดเมีย..., Another...
  ```
  แทนที่จะแสดง raw ID string

---

### Task 3: Verify listener รองรับหลายกลุ่ม
**Files:**
- Check: `listener.py` — `_resolve_peer_ids()` และ `_on_msg` handler

- [ ] 3.1 `_resolve_peer_ids()` — ใช้ `split(",")` อยู่แล้ว → OK
- [ ] 3.2 `_on_msg` — ใช้ `pid not in peer_ids` → OK (set lookup)
- [ ] 3.3 ไม่ต้องแก้อะไร

---

### Task 4: Integration test
**Files:**
- Manual test

- [ ] 4.1 กด [2] Groups → toggle 2-3 กลุ่ม → save
- [ ] 4.2 กด [5] Start → verify listener connect ทุกกลุ่ม
- [ ] 4.3 ส่ง media จากกลุ่มที่ 2 → verify ดาวน์โหลดได้

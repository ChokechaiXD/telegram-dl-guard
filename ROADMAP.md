# Telegram DL Guard — Feature Roadmap

This document outlines the technical design, architectural path, and execution plan for the upcoming premium features selected for future development.

---

## 1. Perceptual Hashing for Photo Deduplication

### Objective
Ensure that identical or highly similar images are recognized as duplicates even if they have been rescaled, converted to different formats (e.g., JPG to WebP), or have slightly modified metadata.

### Architectural Impact
Modifies `core/download_handler.py` and the SQLite WAL database tracking.

```
Incoming Media ──> Save Temp ──> Compute dHash (Pillow) ──> Query DB ──> [Match?] ──> Skip & Delete Temp
                                                                          └──> [New?] ──> Commit to download_dir
```

### Technical Blueprint
1. **Dependencies**: `Pillow` (already installed) for image downsampling and grayscale conversions.
2. **Algorithm**: Difference Hashing (dHash) is fast and highly effective for near-duplicate detection.
   - Downscale the image to 9 x 8 pixels.
   - Convert to grayscale.
   - Compare adjacent pixels (8 comparisons per row across 8 rows = 64-bit hash).
3. **Database Integration**:
   - Add a `p_hash` column to the `download_tracker` SQLite table.
   - Index the `p_hash` column for high-speed lookup.
4. **Logic Flow**:
   - Download the file to a temporary location.
   - If it is a photo, compute the 64-bit hexadecimal dHash.
   - Query the database: `SELECT filepath FROM download_tracker WHERE p_hash = ?`.
   - If a match is found and similarity score is >= 95% (Hamming distance <= 3), skip the download and delete the temporary file.
   - Otherwise, move the file to the final destination and record the dHash in the database.

---

## 2. Automated Smart Archiving & Zip Compression

### Objective
Group downloaded media components belonging to the same Telegram album or transaction into a single, clean `.zip` file on disk before uploading, keeping the target storage group organized.

### Architectural Impact
Modifies `listener.py` (album flushing logic) and `uploader.py`.

```
Album Buffered (2s window) ──> Download Pieces ──> Compress to ZIP ──> Enqueue ZIP to Uploader
```

### Technical Blueprint
1. **Trigger**: Executes inside the `ALBUM_BUFFER` flusher in `listener.py` once all pieces of a `grouped_id` have finished downloading.
2. **Archiver Module**:
   - Utilize Python's native `zipfile` module (requires zero external dependencies).
   - Compress with `ZIP_DEFLATED` to ensure optimal file-size reduction.
3. **Naming Convention**:
   - `[Date_Time]_[Group_Name]_Album_[Album_ID].zip`
4. **Workflow**:
   - Collect files belonging to the album.
   - Create a structured zip archive under the destination directory.
   - Add files, then compute the hash of the resulting `.zip` file for unified database entry.
   - Append the original captions of all sub-files into a combined text description inside the zip or as the main caption of the upload.
   - Delete the individual raw sub-files, leaving only the clean `.zip` archive.

---

## 3. TUI Visual Analytics & Charts

### Objective
Provide real-time graphical representations of system performance, download speeds, and data volume directly inside the Textual interface.

### Architectural Impact
Creates `tui/screens/analytics.py` and adds a Tabbed Layout inside `tui/app.py`.

### Technical Blueprint
1. **Libraries**: Use `plotext` or custom Textual Canvas widgets to render lightweight, high-performance ANSI graphs.
2. **Visual Panels**:
   - **Speed Chart**: Line graph showing download speeds over the last 60 seconds (updated dynamically).
   - **Volume Stats**: Bar chart showing data downloaded and uploaded over the last 7 days.
   - **Mime Distribution**: Horizontal progress-bar breakdown showing ratio of Photo vs. Video vs. Document traffic.
3. **Data Source**:
   - Aggregate statistics asynchronously from the WAL SQLite `download_tracker` table using time-windowed queries.

---

## 4. Visual Rule Builder UI

### Objective
Replace manual editing of `rules.yaml` with a robust, interactive form layout in the TUI Settings panel, making rule creation accessible to non-technical users.

### Architectural Impact
Modifies `tui/screens/settings.py` and `core/rules.py`.

### Technical Blueprint
1. **Interactive Widgets**:
   - Use `Select` for criteria types (Sender, Filename, Size, Type).
   - Use `Input` for matching values or regular expressions.
   - Use `Select` for actions (Skip, Tag, Priority, Redirect).
2. **List Panel**:
   - Display a list of current active rules.
   - Provide buttons to edit, duplicate, delete, or re-order rules (as priority scales with order).
3. **Serialization**:
   - Programmatically compile and serialize form inputs back to the structured `rules.yaml` format.
   - Run syntax verification checks on the output before writing to disk.

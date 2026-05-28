// Smart Picker v3 — search, filter, sort, pagination
// A/<- prev, D/-> next, W=select all, S=delete, Q=clear, Enter=upload

let data = { users: [], current_user: "", files: [], page: 1, total_pages: 1, filtered_count: 0 };
let currentIdx = 0;
let touchStartX = 0, touchStartY = 0;
let _uploading = false;
let _debounceTimer = null;
let _currentFilter = "all";

async function loadData() {
  try {
    const params = new URLSearchParams({
      q: document.getElementById("search").value,
      type: _currentFilter,
      sort: document.getElementById("sort").value,
      page: data.page || 1,
    });
    const r = await fetch("/api/data?" + params);
    data = await r.json();
    document.getElementById("loading").style.display = "none";
    if (!data.files.length && !data.users.length) {
      document.getElementById("done-screen").style.display = "block";
      document.getElementById("done-text").textContent = "No pending files!";
      return;
    }
    document.getElementById("card-container").style.display = "flex";
    currentIdx = 0;
    renderUserTabs();
    renderCard();
    renderThumbs();
    updateStats();
    updatePagination();
    updateFilterChips();
  } catch (e) {
    console.error("Load error:", e);
  }
}

function debouncedLoad() {
  clearTimeout(_debounceTimer);
  _debounceTimer = setTimeout(() => { data.page = 1; loadData(); }, 300);
}

function setFilter(type) {
  _currentFilter = type;
  data.page = 1;
  loadData();
}

function updateFilterChips() {
  document.querySelectorAll(".chip").forEach(c => {
    c.classList.toggle("active", c.dataset.type === _currentFilter);
  });
}

function changePage(delta) {
  const newPage = (data.page || 1) + delta;
  if (newPage < 1 || newPage > (data.total_pages || 1)) return;
  data.page = newPage;
  loadData();
}

function updatePagination() {
  const pag = document.getElementById("pagination");
  if (!data.total_pages || data.total_pages <= 1) {
    pag.style.display = "none";
    return;
  }
  pag.style.display = "flex";
  document.getElementById("page-info").textContent =
    "Page " + (data.page || 1) + "/" + data.total_pages;
  document.getElementById("prev-page").disabled = (data.page || 1) <= 1;
  document.getElementById("next-page").disabled = (data.page || 1) >= data.total_pages;
}

function renderUserTabs() {
  const tabs = document.getElementById("user-tabs");
  tabs.innerHTML = "";
  data.users.forEach(u => {
    const btn = document.createElement("button");
    btn.className = "user-tab" + (u.name === data.current_user ? " active" : "");
    const sel = u.selected > 0 ? '<span class="tab-count">' + u.selected + "</span>" : "";
    btn.innerHTML = u.name + sel;
    btn.title = u.total + " files, " + u.size;
    btn.onclick = () => switchUser(u.name);
    tabs.appendChild(btn);
  });
}

async function switchUser(user) {
  await fetch("/api/set_user", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user }),
  });
  data.page = 1;
  loadData();
}

function renderCard() {
  const f = data.files[currentIdx];
  if (!f) return;
  const preview = document.getElementById("preview");
  const info = document.getElementById("file-info");

  if (f.file_type === "image") {
    preview.innerHTML = '<img src="/api/preview/' + f.idx + '" alt="">';
  } else if (f.file_type === "video") {
    preview.innerHTML = '<video src="/api/preview/' + f.idx + '" controls preload="metadata" muted></video>';
  } else {
    const ext = f.filename.split(".").pop().toUpperCase();
    preview.innerHTML = '<div class="doc-icon"><div class="icon">' + f.file_icon + '</div><div class="ext">' + ext + "</div></div>";
  }

  let badge = "";
  if (f.uploaded) badge = '<span class="badge uploaded">Uploaded</span>';
  if (f.tag) badge += '<span class="badge tag">' + f.tag + "</span>";

  info.innerHTML =
    '<div class="name" title="' + f.filename + '">' + f.filename + '</div>' +
    '<div class="meta">' +
      "<span>" + f.file_icon + " " + f.file_type.toUpperCase() + "</span>" +
      "<span>" + f.size_fmt + "</span>" +
      "<span>" + f.date + "</span>" +
    "</div>" + badge;

  document.querySelectorAll(".thumb").forEach((t, i) => {
    t.classList.toggle("current", i === currentIdx);
  });
}

function renderThumbs() {
  const strip = document.getElementById("thumb-strip");
  strip.innerHTML = "";
  data.files.forEach((f, i) => {
    const div = document.createElement("div");
    div.className = "thumb" + (i === currentIdx ? " current" : "") + (f.uploaded ? " uploaded" : "");
    div.onclick = () => { currentIdx = i; renderCard(); };
    if (f.file_type === "image") {
      div.innerHTML = '<img src="/api/preview/' + i + '" alt="">';
    } else {
      div.innerHTML = '<div style="padding:6px;text-align:center;font-size:16px;">' + f.file_icon + "</div>";
    }
    strip.appendChild(div);
  });
}

function updateStats() {
  const u = data.users.find(u => u.name === data.current_user);
  if (u) {
    const filtered = data.filtered_count !== undefined ? " (" + data.filtered_count + " shown)" : "";
    document.getElementById("stats").textContent =
      u.name + " | " + u.total + " files | " + u.size + filtered;
  }
}

async function doAction(action) {
  if (!data.files.length) return;
  const f = data.files[currentIdx];
  if (!f) return;
  const card = document.getElementById("card");
  card.classList.remove("swipe-left", "swipe-right");
  if (action === "skip") card.classList.add("swipe-left");
  else if (action === "select") card.classList.add("swipe-right");
  await new Promise(r => setTimeout(r, 250));
  card.classList.remove("swipe-left", "swipe-right");
  try {
    await fetch("/api/action", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, idx: f.idx }),
    });
    await loadData();
  } catch (e) { console.error(e); }
}

async function doUpload() {
  if (_uploading) return;
  const userFiles = data.files.filter(f => !f.uploaded);
  if (!userFiles.length) { alert("No files to upload!"); return; }

  _uploading = true;
  document.getElementById("upload-modal").style.display = "flex";
  document.getElementById("upload-progress").style.width = "0%";
  document.getElementById("upload-status").textContent = "Uploading " + userFiles.length + " files...";

  try {
    const indices = userFiles.map(f => f.idx);
    const r = await fetch("/api/upload", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ indices }),
    });
    const result = await r.json();
    document.getElementById("upload-progress").style.width = "100%";
    document.getElementById("upload-status").textContent =
      (result.success || 0) + " uploaded, " + (result.failed || 0) + " failed";
    setTimeout(() => {
      document.getElementById("upload-modal").style.display = "none";
      _uploading = false;
      loadData();
    }, 1500);
  } catch (e) {
    document.getElementById("upload-status").textContent = "Error: " + e.message;
    setTimeout(() => {
      document.getElementById("upload-modal").style.display = "none";
      _uploading = false;
    }, 2000);
  }
}

async function doDelete() {
  const f = data.files[currentIdx];
  if (!f) return;
  if (f.uploaded) { alert("File already uploaded!"); return; }
  if (!confirm('Delete "' + f.filename + '" from disk?\nThis cannot be undone.')) return;
  try {
    const r = await fetch("/api/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ indices: [f.idx] }),
    });
    const result = await r.json();
    if (result.deleted) {
      data.files.splice(currentIdx, 1);
      currentIdx = Math.min(currentIdx, data.files.length - 1);
      if (!data.files.length) {
        document.getElementById("done-screen").style.display = "block";
        document.getElementById("done-text").textContent = "No more files!";
        return;
      }
      renderCard();
      renderThumbs();
      updateStats();
    }
  } catch (e) { alert("Delete error: " + e.message); }
}

function showPrev() { if (currentIdx > 0) { currentIdx--; renderCard(); } }
function showNext() { if (currentIdx < data.files.length - 1) { currentIdx++; renderCard(); } }

function touchStart(e) {
  touchStartX = e.touches[0].clientX;
  touchStartY = e.touches[0].clientY;
}
function touchEnd(e) {
  const dx = e.changedTouches[0].clientX - touchStartX;
  const dy = e.changedTouches[0].clientY - touchStartY;
  if (Math.abs(dx) > Math.abs(dy)) {
    if (dx < -40) showPrev();
    else if (dx > 40) showNext();
  }
}

document.addEventListener("keydown", (e) => {
  if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA" || e.target.tagName === "SELECT") return;
  if (e.repeat) return;
  switch (e.key.toLowerCase()) {
    case "a": case "arrowleft":
      e.preventDefault(); showPrev(); break;
    case "d": case "arrowright":
      e.preventDefault(); showNext(); break;
    case "w":
      e.preventDefault(); doAction("select_all"); break;
    case "s":
      e.preventDefault(); doDelete(); break;
    case "q":
      e.preventDefault(); doAction("clear_all"); break;
    case "enter":
      e.preventDefault(); doUpload(); break;
    case "tab":
      e.preventDefault();
      if (data.users.length > 1) {
        const ci = data.users.findIndex(u => u.name === data.current_user);
        switchUser(data.users[(ci + 1) % data.users.length].name);
      }
      break;
  }
});

loadData();

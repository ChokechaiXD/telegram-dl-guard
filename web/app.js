// --- Global Application State ---
let selectedMsgIds = new Set();
let fetchedMessages = [];
let currentGroupId = "";

// --- DOM Elements ---
const selectGroup = document.getElementById("select-group");
const sliderLimit = document.getElementById("slider-limit");
const inputLimit = document.getElementById("input-limit");
const btnFetch = document.getElementById("btn-fetch");
const mediaGrid = document.getElementById("media-grid");
const resultsCounter = document.getElementById("results-counter");
const gridContainer = document.getElementById("grid-container");
const lassoBox = document.getElementById("lasso-box");
const floatingToolbar = document.getElementById("floating-toolbar");
const selectedCountEl = document.getElementById("selected-count");

const btnSelectAll = document.getElementById("btn-select-all");
const btnClearSelection = document.getElementById("btn-clear-selection");
const btnDownload = document.getElementById("btn-download");

const videoModal = document.getElementById("video-modal");
const modalVideoPlayer = document.getElementById("modal-video-player");
const modalTitle = document.getElementById("modal-title");
const modalDesc = document.getElementById("modal-desc");

// --- Initialization ---
document.addEventListener("DOMContentLoaded", () => {
    loadGroups();
    setupLimitSync();
    setupTabFilters();
    setupFloatingToolbar();
    setupLassoSelector();
});

// --- 1. Limit Input Synchronizer ---
function setupLimitSync() {
    sliderLimit.addEventListener("input", (e) => {
        inputLimit.value = e.target.value;
    });
    inputLimit.addEventListener("input", (e) => {
        let val = parseInt(e.target.value);
        if (isNaN(val)) return;
        if (val < 10) val = 10;
        if (val > 1000) val = 1000;
        sliderLimit.value = val;
    });
}

// --- 2. Tab Filters Manager ---
let activeMediaType = "all";
function setupTabFilters() {
    const tabs = document.querySelectorAll(".tab-btn");
    tabs.forEach(tab => {
        tab.addEventListener("click", () => {
            tabs.forEach(t => t.classList.remove("active"));
            tab.classList.add("active");
            activeMediaType = tab.getAttribute("data-type");
        });
    });
}

// --- 3. Fetch Dialog Groups ---
async function loadGroups() {
    try {
        const response = await fetch("/api/groups");
        if (!response.ok) throw new Error("Failed to load Telegram groups");
        const groups = await response.json();
        
        selectGroup.innerHTML = '<option value="">-- Choose Target Group --</option>';
        groups.forEach(g => {
            const opt = document.createElement("option");
            opt.value = g.id;
            opt.textContent = `${g.title} (${g.id})`;
            selectGroup.appendChild(opt);
        });
    } catch (error) {
        console.error(error);
        alert("Failed to load Telegram groups. Check that the wizard login is active.");
    }
}

// --- 4. Fetch Media Messages ---
btnFetch.addEventListener("click", async () => {
    currentGroupId = selectGroup.value;
    if (!currentGroupId) {
        alert("Please select a target group first.");
        return;
    }
    
    const limit = inputLimit.value;
    const query = document.getElementById("input-query").value.trim();
    
    // Show Loading
    mediaGrid.innerHTML = `
        <div class="grid-placeholder">
            <span class="placeholder-icon pulse-dot" style="width:30px; height:30px; background-color:#00f2c3;"></span>
            <p>Scanning Telegram group messages... Please wait.</p>
        </div>
    `;
    resultsCounter.textContent = "Scanning...";
    selectedMsgIds.clear();
    updateToolbarState();
    
    let url = `/api/history/${currentGroupId}?limit=${limit}&type=${activeMediaType}`;
    if (query) {
        url += `&q=${encodeURIComponent(query)}`;
    }
    
    try {
        const response = await fetch(url);
        if (!response.ok) throw new Error("Failed to fetch group media history");
        fetchedMessages = await response.json();
        
        renderMediaGrid(fetchedMessages);
    } catch (error) {
        console.error(error);
        mediaGrid.innerHTML = `
            <div class="grid-placeholder">
                <span class="placeholder-icon">❌</span>
                <p>Fetch Failed: ${error.message}</p>
            </div>
        `;
        resultsCounter.textContent = "Error";
    }
});

// --- 5. Render Media Masonry Grid ---
function renderMediaGrid(messages) {
    mediaGrid.innerHTML = "";
    resultsCounter.textContent = `${messages.length} items found`;
    
    if (messages.length === 0) {
        mediaGrid.innerHTML = `
            <div class="grid-placeholder">
                <span class="placeholder-icon">🔎</span>
                <p>No media files matching the filters were found in the scanned range.</p>
            </div>
        `;
        return;
    }
    
    messages.forEach(msg => {
        const card = document.createElement("div");
        card.className = "media-card";
        card.setAttribute("data-msg-id", msg.msg_id);
        
        // Dynamic Preview Media Box
        let previewContent = "";
        const streamUrl = `/api/stream/${currentGroupId}/${msg.msg_id}`;
        
        if (msg.type === "photo") {
            previewContent = `<img src="${streamUrl}" alt="Media Preview" class="preview-img" loading="lazy">`;
        } else if (msg.type === "video") {
            // High-performance HTML5 video dynamic stream loader
            previewContent = `
                <div class="play-button-overlay">▶</div>
                <img src="data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='100' height='100' viewBox='0 0 24 24' fill='%2300b4d8'><path d='M17 10.5V7c0-.55-.45-1-1-1H4c-.55 0-1 .45-1 1v10c0 .55.45 1 1 1h12c.55 0 1-.45 1-1v-3.5l4 4v-11l-4 4z'/></svg>" class="preview-img" style="object-fit:scale-down; padding:30px; opacity:0.6;">
            `;
        } else {
            previewContent = `<span class="card-placeholder-icon">📄</span>`;
        }
        
        const badgeClass = msg.type === "photo" ? "badge-photo" : "badge-video";
        const captionText = msg.caption ? msg.caption : "(No caption)";
        
        card.innerHTML = `
            <div class="card-preview">
                <span class="card-badge ${badgeClass}">${msg.type}</span>
                <div class="card-selector"></div>
                ${previewContent}
            </div>
            <div class="card-details">
                <span class="card-title-text">${msg.filename}</span>
                <span class="card-caption">${captionText}</span>
                <div class="card-meta">
                    <span>${msg.sender}</span>
                    <span>${msg.size_str}</span>
                </div>
            </div>
        `;
        
        // Single Click to Toggle Individual Card Selection
        card.addEventListener("click", (e) => {
            // If clicking video play icon overlay, open the stream modal!
            if (msg.type === "video" && e.target.classList.contains("play-button-overlay")) {
                openVideoModal(streamUrl, msg.filename, msg.sender, msg.caption);
                return;
            }
            
            toggleCardSelection(card, msg.msg_id);
        });
        
        mediaGrid.appendChild(card);
    });
}

// Toggle Selection helper
function toggleCardSelection(cardElement, msgId) {
    if (selectedMsgIds.has(msgId)) {
        selectedMsgIds.delete(msgId);
        cardElement.classList.remove("selected");
    } else {
        selectedMsgIds.add(msgId);
        cardElement.classList.add("selected");
    }
    updateToolbarState();
}

// --- 6. Click-and-Drag Lasso Grid Selector ---
function setupLassoSelector() {
    let startX = 0, startY = 0;
    let isDragging = false;
    
    gridContainer.addEventListener("mousedown", (e) => {
        // Only trigger on left click on the grid container background or padding,
        // avoiding direct clicks on inputs, buttons, or scrollbars.
        if (e.button !== 0) return;
        if (e.target.closest("button") || e.target.closest("select") || e.target.closest("video")) return;
        
        // Get absolute boundaries
        const rect = gridContainer.getBoundingClientRect();
        
        // Ignore clicks directly inside cards to allow clean single clicks
        if (e.target.closest(".media-card")) return;
        
        isDragging = true;
        
        // Calculate coordinate relative to container
        startX = e.clientX - rect.left + gridContainer.scrollLeft;
        startY = e.clientY - rect.top + gridContainer.scrollTop;
        
        lassoBox.style.left = `${startX}px`;
        lassoBox.style.top = `${startY}px`;
        lassoBox.style.width = "0px";
        lassoBox.style.height = "0px";
        lassoBox.style.display = "block";
        
        // Prevent default cursor highlight selection behavior
        e.preventDefault();
    });
    
    gridContainer.addEventListener("mousemove", (e) => {
        if (!isDragging) return;
        
        const rect = gridContainer.getBoundingClientRect();
        
        const currentX = e.clientX - rect.left + gridContainer.scrollLeft;
        const currentY = e.clientY - rect.top + gridContainer.scrollTop;
        
        const x = Math.min(startX, currentX);
        const y = Math.min(startY, currentY);
        const w = Math.abs(startX - currentX);
        const h = Math.abs(startY - currentY);
        
        lassoBox.style.left = `${x}px`;
        lassoBox.style.top = `${y}px`;
        lassoBox.style.width = `${w}px`;
        lassoBox.style.height = `${h}px`;
        
        // Perform Real-Time overlap check on each card
        const cards = document.querySelectorAll(".media-card");
        const lassoRect = {
            left: x,
            top: y,
            right: x + w,
            bottom: y + h
        };
        
        cards.forEach(card => {
            const msgId = parseInt(card.getAttribute("data-msg-id"));
            
            // Get card positions relative to gridContainer
            const cardLeft = card.offsetLeft;
            const cardTop = card.offsetTop;
            const cardRight = cardLeft + card.offsetWidth;
            const cardBottom = cardTop + card.offsetHeight;
            
            // Check overlap
            const isOverlap = !(
                cardRight < lassoRect.left ||
                cardLeft > lassoRect.right ||
                cardBottom < lassoRect.top ||
                cardTop > lassoRect.bottom
            );
            
            if (isOverlap) {
                if (!selectedMsgIds.has(msgId)) {
                    selectedMsgIds.add(msgId);
                    card.classList.add("selected");
                }
            }
        });
        
        updateToolbarState();
    });
    
    window.addEventListener("mouseup", () => {
        if (isDragging) {
            isDragging = false;
            lassoBox.style.display = "none";
        }
    });
}

// --- 7. Floating Action Toolbar ---
function setupFloatingToolbar() {
    btnSelectAll.addEventListener("click", () => {
        const cards = document.querySelectorAll(".media-card");
        cards.forEach(card => {
            const msgId = parseInt(card.getAttribute("data-msg-id"));
            selectedMsgIds.add(msgId);
            card.classList.add("selected");
        });
        updateToolbarState();
    });
    
    btnClearSelection.addEventListener("click", () => {
        selectedMsgIds.clear();
        const cards = document.querySelectorAll(".media-card");
        cards.forEach(card => card.classList.remove("selected"));
        updateToolbarState();
    });
    
    btnDownload.addEventListener("click", async () => {
        if (selectedMsgIds.size === 0) return;
        
        const payload = {
            group_id: currentGroupId,
            message_ids: Array.from(selectedMsgIds)
        };
        
        btnDownload.disabled = true;
        btnDownload.textContent = "Queueing Downloads...";
        
        try {
            const response = await fetch("/api/download/bulk", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });
            
            if (!response.ok) throw new Error("Bulk download request failed");
            const res = await response.json();
            
            alert(`Successfully added ${res.queued_items} items into the global downloads queue! Progress will update in the console / TUI.`);
            selectedMsgIds.clear();
            const cards = document.querySelectorAll(".media-card");
            cards.forEach(card => card.classList.remove("selected"));
            updateToolbarState();
        } catch (error) {
            console.error(error);
            alert(`Download Failed: ${error.message}`);
        } finally {
            btnDownload.disabled = false;
            btnDownload.textContent = "Download Selected Files";
        }
    });
}

function updateToolbarState() {
    const count = selectedMsgIds.size;
    selectedCountEl.textContent = count;
    
    if (count > 0) {
        floatingToolbar.classList.add("visible");
    } else {
        floatingToolbar.classList.remove("visible");
    }
}

// --- 8. Video Modal Viewer ---
function openVideoModal(url, title, sender, caption) {
    modalVideoPlayer.src = url;
    modalTitle.textContent = title;
    modalDesc.textContent = `Sender: ${sender} | ${caption ? caption : 'No Caption'}`;
    videoModal.classList.add("visible");
    modalVideoPlayer.play();
}

function closeVideoModal() {
    modalVideoPlayer.pause();
    modalVideoPlayer.src = ""; // Unload stream to conserve bandwidth
    videoModal.classList.remove("visible");
}

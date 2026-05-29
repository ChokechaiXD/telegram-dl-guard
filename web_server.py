# -*- coding: utf-8 -*-
import os
import sys
import time
import socket
import asyncio
import logging
import webbrowser
import sqlite3
from pathlib import Path
from typing import List, Dict, Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from telethon import TelegramClient
from telethon.sessions import StringSession

from config import AppConfig
import core.state as cs
from uploader import upload_worker
from listener import _do_download
from core.download_handler import _mtype, _media_name, _resolve_sender_info
import core.download_handler as dh
from core.utils import format_bytes, setup_logging

# Setup Logging
setup_logging(level="INFO")
log = logging.getLogger("guard.web")

# Port Probing Logic
def find_free_port(start_port: int = 8000, max_attempts: int = 100) -> int:
    for port in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except socket.error:
                continue
    raise IOError("Could not find a free port.")

PORT = find_free_port(8000)

app = FastAPI(title="Telegram DL Guard Web Companion")

# CORS Setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global Client and Loop References
client: TelegramClient | None = None
background_tasks = set()

@app.on_event("startup")
async def startup_event():
    global client
    cfg = AppConfig.load()
    
    # Initialize download_handler globals to prevent NoneType attribute errors in _do_download
    dh.CFG = cfg
    dh.DL_DIR = Path(cfg.download_dir)
    dh.DL_SEM = asyncio.Semaphore(max(cfg.queue_size, 10))
    
    if not cfg.session_string:
        log.error("Telegram session string not found in .env. Please run Setup Wizard first.")
        return
        
    log.info("Starting Telegram client...")
    client = TelegramClient(
        StringSession(cfg.session_string),
        cfg.api_id, cfg.api_hash,
        connection_retries=10, retry_delay=5, auto_reconnect=True,
    )
    
    await client.connect()
    if not await client.is_user_authorized():
        log.error("Telegram session is not authorized.")
        return
        
    log.info("Telegram successfully connected!")
    
    # Initialize global UPLOAD_QUEUE
    cs.UPLOAD_QUEUE = asyncio.Queue()
    
    # Resolve storage group ID
    storage_id = None
    if cfg.storage_group_id:
        try:
            storage_id = int(cfg.storage_group_id)
        except ValueError:
            pass
            
    if storage_id:
        # Spawn upload worker daemon
        up_mode = os.getenv("UPLOAD_MODE", "realtime_keep")
        up_workers = cfg.upload_workers
        log.info(f"Starting background upload worker (mode={up_mode}, workers={up_workers})...")
        upload_task = asyncio.create_task(upload_worker(
            client, storage_id, cs.UPLOAD_QUEUE,
            mode=up_mode, num_workers=up_workers
        ))
        background_tasks.add(upload_task)
        upload_task.add_done_callback(background_tasks.discard)

    # Open default browser automatically
    def open_browser():
        time.sleep(1.5)
        webbrowser.open(f"http://localhost:{PORT}")
        
    import threading
    threading.Thread(target=open_browser, daemon=True).start()

@app.on_event("shutdown")
async def shutdown_event():
    global client
    if client:
        log.info("Disconnecting Telegram client...")
        await client.disconnect()

# --- API Endpoints ---

@app.get("/api/groups")
async def get_groups():
    """Load groups from SQLite cache. If empty, sync and cache dialogs on the fly."""
    if not client:
        raise HTTPException(status_code=500, detail="Telegram client not initialized.")
        
    db_path = Path("logs/guard.db")
    groups = []
    
    try:
        if db_path.exists():
            conn = sqlite3.connect(db_path)
            cursor = conn.execute("SELECT group_id, group_title FROM group_cache")
            db_groups = cursor.fetchall()
            conn.close()
            for gid, title in db_groups:
                groups.append({"id": str(gid), "title": title})
    except Exception as e:
        log.error(f"Error loading group cache: {e}")
        
    # If cache is empty, query live dialogs and populate cache
    if not groups:
        try:
            log.info("Group cache is empty. Fetching live dialogs from Telegram...")
            live_dialogs = [d async for d in client.iter_dialogs() if d.is_group or d.is_channel]
            
            # Persist to SQLite
            db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE IF NOT EXISTS group_cache (group_id INTEGER PRIMARY KEY, group_title TEXT)")
            for g in live_dialogs:
                title = g.title or "Untitled"
                conn.execute("INSERT OR REPLACE INTO group_cache (group_id, group_title) VALUES (?, ?)", (g.id, title))
                groups.append({"id": str(g.id), "title": title})
            conn.commit()
            conn.close()
        except Exception as e:
            log.error(f"Failed to fetch live dialogs: {e}")
            raise HTTPException(status_code=500, detail="Failed to fetch channels from Telegram.")
            
    return JSONResponse(content=groups)

@app.get("/api/history/{group_id}")
async def get_history(group_id: str, limit: int = 100, q: str = None, type: str = "all"):
    """Fetch message history containing media with filters."""
    if not client:
        raise HTTPException(status_code=500, detail="Telegram client not connected.")
        
    try:
        gid = int(group_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid group ID format.")
        
    try:
        entity = await client.get_entity(gid)
    except Exception as e:
        log.error(f"Failed to get entity: {e}")
        raise HTTPException(status_code=404, detail="Group entity not found. Make sure the ID is correct.")
        
    results = []
    
    try:
        async for msg in client.iter_messages(entity, limit=limit, search=q):
            if not msg.media:
                continue
                
            mt = _mtype(msg.media)
            if type != "all" and mt != type:
                continue
                
            sender, _ = await _resolve_sender_info(msg)
            fname = _media_name(msg.media, msg.date, msg.id)
            fsize = getattr(getattr(msg.media, "document", None), "size", 0) or 0
            
            results.append({
                "msg_id": msg.id,
                "date": msg.date.strftime("%Y-%m-%d %H:%M") if msg.date else "?",
                "sender": sender,
                "filename": fname,
                "size": fsize,
                "size_str": format_bytes(fsize) if fsize else "Unknown",
                "type": mt,
                "caption": msg.message.strip() if msg.message else ""
            })
    except Exception as e:
        log.error(f"Error fetching history: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch history: {e}")
        
    return JSONResponse(content=results)

@app.get("/api/stream/{group_id}/{msg_id}")
async def stream_media(group_id: str, msg_id: int):
    """Dynamic Telegram Chunk Streaming: streams external media directly from Telegram's servers chunk-by-chunk."""
    if not client:
        raise HTTPException(status_code=500, detail="Telegram client not connected.")
        
    try:
        gid = int(group_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid group ID.")
        
    try:
        entity = await client.get_entity(gid)
        msg = await client.get_messages(entity, ids=msg_id)
    except Exception as e:
        log.error(f"Failed to fetch message {msg_id}: {e}")
        raise HTTPException(status_code=404, detail="Media message not found.")
        
    if not msg or not msg.media:
        raise HTTPException(status_code=404, detail="Message does not contain media.")
        
    # Detect mime type
    mt = _mtype(msg.media)
    if mt == "photo":
        mime = "image/jpeg"
    elif mt == "video":
        mime = "video/mp4"
    else:
        # Fallback to document attributes
        doc = getattr(msg.media, "document", None)
        mime = doc.mime_type if (doc and doc.mime_type) else "application/octet-stream"
        
    # High-performance chunk-by-chunk streaming generator
    async def chunk_generator():
        try:
            async for chunk in client.iter_download(msg.media):
                yield chunk
        except Exception as ex:
            log.error(f"Streaming interrupted for message {msg_id}: {ex}")
            
    return StreamingResponse(chunk_generator(), media_type=mime)

class BulkDownloadRequest(BaseModel):
    group_id: str
    message_ids: List[int]

@app.post("/api/download/bulk")
async def bulk_download(req: BulkDownloadRequest):
    """Queue bulk manual downloads in the background, utilizing existing _do_download pipeline."""
    if not client:
        raise HTTPException(status_code=500, detail="Telegram client not connected.")
        
    try:
        gid = int(req.group_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid group ID.")
        
    try:
        entity = await client.get_entity(gid)
    except Exception as e:
        log.error(f"Failed to resolve group entity: {e}")
        raise HTTPException(status_code=404, detail="Target group not found.")
        
    # Fetch all requested message objects
    try:
        messages = await client.get_messages(entity, ids=req.message_ids)
    except Exception as e:
        log.error(f"Failed to fetch media messages: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch media messages from Telegram.")
        
    if not messages:
        raise HTTPException(status_code=400, detail="No messages found.")
        
    # If single message returned instead of list
    if not isinstance(messages, list):
        messages = [messages]
        
    cfg = AppConfig.load()
    ddir = Path(cfg.download_dir)
    
    # Retrieve target group title for logging/captions
    group_title = req.group_id
    try:
        db_path = Path("logs/guard.db")
        if db_path.exists():
            conn = sqlite3.connect(db_path)
            cursor = conn.execute("SELECT group_title FROM group_cache WHERE group_id = ?", (req.group_id,))
            row = cursor.fetchone()
            conn.close()
            if row:
                group_title = row[0]
    except Exception:
        pass
        
    queued_count = 0
    
    for msg in messages:
        if not msg or not msg.media:
            continue
            
        mt = _mtype(msg.media)
        sender, username = await _resolve_sender_info(msg)
        fname = _media_name(msg.media, msg.date, msg.id)
        fsize = getattr(getattr(msg.media, "document", None), "size", 0) or 0
        
        # Build path based on date folder structure
        date_folder = msg.date.strftime(cfg.folder_date_format) if msg.date else "manual_download"
        target_dir = ddir / date_folder
        fpath = target_dir / fname
        
        caption = msg.message or ""
        album_group = getattr(msg, "grouped_id", None)
        
        # Spawn _do_download in the background safely
        task = asyncio.create_task(_do_download(
            client, msg, fpath, target_dir, mt, sender, username,
            group_title, caption, album_group, fsize,
            cs.UPLOAD_QUEUE, cfg.dedup_method, cfg.show_speed,
            priority=True # Manual downloads get immediate priority
        ))
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)
        queued_count += 1
        
    return JSONResponse(content={"status": "ok", "queued_items": queued_count})

# Serve Static Frontend Files
web_dir = Path("web")
if web_dir.exists():
    app.mount("/", StaticFiles(directory=web_dir, html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    log.info(f"Launching Web Companion Dashboard on http://localhost:{PORT}...")
    uvicorn.run("web_server:app", host="127.0.0.1", port=PORT, reload=False)

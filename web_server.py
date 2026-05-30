# -*- coding: utf-8 -*-
import os
import sys
import time
import socket
import asyncio
import logging
import webbrowser
from pathlib import Path
from typing import List, Dict, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from telethon import TelegramClient
from telethon.sessions import StringSession

from config import AppConfig
import core.state as cs
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

# Global Client and Loop References
client: TelegramClient | None = None
background_tasks = set()

@asynccontextmanager
async def lifespan(app: FastAPI):
    global client
    cfg = AppConfig.load()
    
    # Initialize download_handler globals to prevent NoneType attribute errors in _do_download
    dh.CFG = cfg
    dh.DL_DIR = Path(cfg.download_dir)
    dh.DL_SEM = asyncio.Semaphore(max(cfg.queue_size, 10))
    
    if not cfg.session_string:
        log.error("Telegram session string not found in .env. Please run Setup Wizard first.")
        yield
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
        yield
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
        # Spawn upload worker daemon (lazy import)
        from uploader import upload_worker
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

    yield

    if client:
        log.info("Disconnecting Telegram client...")
        await client.disconnect()

app = FastAPI(title="Telegram DL Guard Web Companion", lifespan=lifespan)

# CORS Setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- API Endpoints ---

@app.get("/api/groups")
async def get_groups():
    """Load groups from SQLite cache. If empty, sync and cache dialogs on the fly."""
    if not client:
        raise HTTPException(status_code=500, detail="Telegram client not initialized.")
        
    groups = cs.get_cached_groups()
    
    # If cache is empty, query live dialogs and populate cache
    if not groups:
        try:
            log.info("Group cache is empty. Fetching live dialogs from Telegram...")
            live_dialogs = [d async for d in client.iter_dialogs() if d.is_group or d.is_channel]
            
            # Persist to SQLite using centralized helper
            groups_to_save = [(g.id, g.title or "Untitled") for g in live_dialogs]
            cs.save_cached_groups(groups_to_save)
            
            groups = [{"id": str(g[0]), "title": g[1]} for g in groups_to_save]
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
                "caption": msg.message.strip() if msg.message else "",
                "grouped_id": getattr(msg, "grouped_id", None),
                "has_thumb": bool(getattr(getattr(msg.media, "document", None), "thumbs", None))
            })
    except Exception as e:
        log.error(f"Error fetching history: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch history: {e}")
        
    return JSONResponse(content=results)

@app.get("/api/stream/{group_id}/{msg_id}")
async def stream_media(group_id: str, msg_id: int, request: Request):
    """Dynamic Telegram Chunk Streaming: streams external media directly from Telegram's servers chunk-by-chunk with HTTP Range request support."""
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
        
    # Get total file size to process range headers accurately
    file_size = getattr(getattr(msg.media, "document", None), "size", 0) or 0
    if not file_size and mt == "photo":
        photo = getattr(msg.media, "photo", None)
        if photo and getattr(photo, "sizes", None):
            file_size = photo.sizes[-1].size or 0
            
    range_header = request.headers.get("Range") or request.headers.get("range")
    start = 0
    end = file_size - 1 if file_size > 0 else 0
    is_range = False
    
    if range_header and file_size > 0:
        try:
            range_val = range_header.replace("bytes=", "").strip()
            parts = range_val.split("-")
            if parts[0]:
                start = int(parts[0])
            if len(parts) > 1 and parts[1]:
                end = int(parts[1])
            
            # Bound boundaries within valid file size limits
            if start < 0:
                start = 0
            if end >= file_size:
                end = file_size - 1
            if start <= end:
                is_range = True
        except Exception as ex:
            log.warning(f"Failed parsing range header {range_header} for message {msg_id}: {ex}")
            
    # High-performance chunk-by-chunk streaming generator supporting range boundaries
    async def chunk_generator(offset: int, total_to_read: int):
        bytes_read = 0
        try:
            async for chunk in client.iter_download(msg.media, offset=offset):
                if bytes_read >= total_to_read:
                    break
                
                remaining = total_to_read - bytes_read
                if len(chunk) > remaining:
                    yield chunk[:remaining]
                    bytes_read += remaining
                    break
                else:
                    yield chunk
                    bytes_read += len(chunk)
        except Exception as ex:
            log.error(f"Streaming interrupted for message {msg_id} at offset {offset}: {ex}")
            
    headers = {
        "Accept-Ranges": "bytes",
    }
    
    if is_range:
        total_to_read = end - start + 1
        headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
        headers["Content-Length"] = str(total_to_read)
        status_code = 206
    else:
        total_to_read = file_size - start if file_size > 0 else 0
        if file_size > 0:
            headers["Content-Length"] = str(total_to_read)
        status_code = 200
        
    return StreamingResponse(
        chunk_generator(start, total_to_read) if total_to_read > 0 else chunk_generator(0, 0),
        media_type=mime,
        headers=headers,
        status_code=status_code
    )

@app.get("/api/stream/{group_id}/{msg_id}/thumb")
async def stream_media_thumb(group_id: str, msg_id: int):
    """Streams the thumbnail of a video/document directly from Telegram's servers Asynchronously."""
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
        
    doc = getattr(msg.media, "document", None)
    if not doc or not getattr(doc, "thumbs", None):
        raise HTTPException(status_code=404, detail="No thumbnail available for this document.")
        
    # Get the best/largest thumbnail
    thumb = doc.thumbs[-1]
    
    try:
        # Direct download of thumbnail bytes to support stripped and cached sizes natively
        data = await client.download_media(msg.media, thumb=thumb)
        if data and isinstance(data, bytes):
            return Response(content=data, media_type="image/jpeg")
    except Exception as ex:
        log.error(f"Thumbnail download failed via download_media: {ex}")
    
    # High-performance chunk-by-chunk streaming generator for thumbnail (Fallback)
    async def chunk_generator():
        try:
            async for chunk in client.iter_download(msg.media, thumb=thumb):
                yield chunk
        except Exception as ex:
            log.error(f"Thumbnail streaming interrupted for message {msg_id}: {ex}")
            
    return StreamingResponse(chunk_generator(), media_type="image/jpeg")

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
    group_title = cs.get_group_title(req.group_id) or req.group_id
        
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

class BulkForwardRequest(BaseModel):
    group_id: str
    message_ids: List[int]

@app.post("/api/forward/bulk")
async def bulk_forward(req: BulkForwardRequest):
    """Forward selected messages directly to the configured storage group on Telegram's servers."""
    if not client:
        raise HTTPException(status_code=500, detail="Telegram client not connected.")
        
    cfg = AppConfig.load()
    if not cfg.storage_group_id:
        raise HTTPException(status_code=400, detail="Storage group ID is not configured in configuration.")
        
    try:
        storage_id = int(cfg.storage_group_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid storage group ID format in configuration.")
        
    try:
        from_gid = int(req.group_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid source group ID.")
        
    try:
        source_entity = await client.get_entity(from_gid)
        storage_entity = await client.get_entity(storage_id)
    except Exception as e:
        log.error(f"Failed to resolve entity: {e}")
        raise HTTPException(status_code=404, detail="Could not resolve source or storage group entity.")
        
    try:
        forwarded = await client.forward_messages(storage_entity, req.message_ids, source_entity)
        if isinstance(forwarded, list):
            success_count = sum(1 for m in forwarded if m is not None)
        else:
            success_count = 1 if forwarded is not None else 0
            
        return JSONResponse(content={"status": "ok", "forwarded_items": success_count})
    except Exception as e:
        log.error(f"Failed to forward messages: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to forward messages: {str(e)}")

# Serve Static Frontend Files
web_dir = Path("web")
if web_dir.exists():
    app.mount("/", StaticFiles(directory=web_dir, html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    log.info(f"Launching Web Companion Dashboard on http://localhost:{PORT}...")
    uvicorn.run("web_server:app", host="127.0.0.1", port=PORT, reload=False)

"""FastAPI server — serves the web client and handles WebSocket signaling."""

import os
import logging
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware

from .meeting_manager import meetings
from .websocket_manager import manager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Video Conferencing")

# ── CORS (allow Vercel frontend to call this backend) ──────────────────────
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Resolve static dir relative to this file
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


# ── Pages ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def home():
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/join/{meeting_id}", response_class=HTMLResponse)
async def join_page(meeting_id: str):
    """Direct join link — serves the same page, JS reads the meeting ID from URL."""
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


# ── REST API ─────────────────────────────────────────────────────────────────

@app.post("/api/create")
async def create_meeting(data: dict):
    username = data.get("username", "").strip()
    if not username:
        return {"error": "Username required"}
    meeting = meetings.create(username)
    return {"meeting_id": meeting.meeting_id, "host": username}


@app.post("/api/join")
async def join_meeting(data: dict):
    meeting_id = data.get("meeting_id", "").strip().upper()
    username = data.get("username", "").strip()
    if not username or not meeting_id:
        return {"error": "Username and meeting ID required"}
    meeting = meetings.get(meeting_id)
    if not meeting:
        return {"error": "Meeting not found"}
    meeting.add(username)
    return {"meeting_id": meeting.meeting_id, "participants": meeting.usernames()}


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/api/ice-servers")
async def ice_servers():
    """Return ICE servers for WebRTC."""
    return {"iceServers": [
        {"urls": "stun:stun.l.google.com:19302"},
        {"urls": "stun:stun1.l.google.com:19302"},
    ]}


# ── WebSocket signaling ─────────────────────────────────────────────────────

@app.websocket("/ws/{meeting_id}/{username}")
async def ws_endpoint(websocket: WebSocket, meeting_id: str, username: str):
    meeting = meetings.get(meeting_id)
    if not meeting:
        await websocket.close(code=4004, reason="Meeting not found")
        return

    await manager.connect(websocket, meeting_id, username)

    # Tell newcomer who is already here + who is host
    existing = [u for u in manager.get_users(meeting_id) if u != username]
    await websocket.send_json({"type": "room_users", "users": existing, "host": meeting.host})

    # Tell others that someone joined
    await manager.broadcast(
        meeting_id,
        {"type": "user_joined", "username": username},
        exclude=username,
    )

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if msg_type == "chat":
                await manager.broadcast(
                    meeting_id,
                    {"type": "chat", "sender": username, "message": data.get("message", "")},
                    exclude=username,
                )

            elif msg_type in ("offer", "answer", "ice-candidate"):
                target = data.get("target")
                if target:
                    await manager.send_to(meeting_id, target, {
                        "type": msg_type,
                        "sender": username,
                        "data": data.get("data", {}),
                    })

            elif msg_type == "caption":
                await manager.broadcast(
                    meeting_id,
                    {"type": "caption", "username": username, "text": data.get("text", ""), "final": data.get("final", False)},
                    exclude=username,
                )

            elif msg_type == "whiteboard":
                await manager.broadcast(
                    meeting_id,
                    {"type": "whiteboard", "username": username, "action": data.get("action"), "data": data.get("data", {})},
                    exclude=username,
                )

            elif msg_type == "poll":
                await manager.broadcast(
                    meeting_id,
                    {"type": "poll", "username": username, "action": data.get("action"), "data": data.get("data", {})},
                    exclude=None if data.get("action") == "result" else username,
                )

            elif msg_type == "screen-share":
                await manager.broadcast(
                    meeting_id,
                    {"type": "screen-share", "username": username, "active": data.get("active", False)},
                    exclude=username,
                )

            elif msg_type == "hand-raise":
                await manager.broadcast(
                    meeting_id,
                    {"type": "hand-raise", "username": username, "raised": data.get("raised", False)},
                    exclude=username,
                )

            elif msg_type == "reaction":
                await manager.broadcast(
                    meeting_id,
                    {"type": "reaction", "username": username, "emoji": data.get("emoji", "")},
                    exclude=username,
                )

            elif msg_type == "kick":
                # Only host can kick
                if username == meeting.host:
                    target = data.get("target")
                    if target:
                        await manager.send_to(meeting_id, target, {"type": "kicked"})

            elif msg_type == "end-meeting":
                if username == meeting.host:
                    await manager.broadcast(meeting_id, {"type": "meeting-ended"}, exclude=username)

    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("WebSocket error for %s", username)
    finally:
        manager.disconnect(meeting_id, username)
        meeting.remove(username)
        meetings.remove_if_empty(meeting_id)
        await manager.broadcast(
            meeting_id,
            {"type": "user_left", "username": username},
        )


# Mount static files LAST (catch-all)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

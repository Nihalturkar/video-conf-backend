"""WebSocket connection registry — tracks who is in which meeting."""

import asyncio
import json
import logging
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        # meeting_id -> {username -> WebSocket}
        self._rooms: dict[str, dict[str, WebSocket]] = {}

    async def connect(self, ws: WebSocket, meeting_id: str, username: str):
        await ws.accept()
        if meeting_id not in self._rooms:
            self._rooms[meeting_id] = {}
        self._rooms[meeting_id][username] = ws
        logger.info("%s connected to %s", username, meeting_id)

    def disconnect(self, meeting_id: str, username: str):
        room = self._rooms.get(meeting_id, {})
        room.pop(username, None)
        if not room:
            self._rooms.pop(meeting_id, None)
        logger.info("%s disconnected from %s", username, meeting_id)

    def get_users(self, meeting_id: str) -> list[str]:
        return list(self._rooms.get(meeting_id, {}).keys())

    async def send_to(self, meeting_id: str, username: str, data: dict):
        room = self._rooms.get(meeting_id, {})
        ws = room.get(username)
        if ws:
            try:
                await ws.send_json(data)
            except Exception:
                logger.warning("Failed to send to %s", username)

    async def broadcast(self, meeting_id: str, data: dict, exclude: str | None = None):
        room = self._rooms.get(meeting_id, {})
        for name, ws in list(room.items()):
            if name != exclude:
                try:
                    await ws.send_json(data)
                except Exception:
                    logger.warning("Failed to broadcast to %s", name)


manager = ConnectionManager()

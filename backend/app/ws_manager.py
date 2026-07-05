import asyncio
import json
import logging

from fastapi import WebSocket

logger = logging.getLogger("ws")


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._connections.add(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(ws)

    async def broadcast(self, message: dict) -> None:
        payload = json.dumps(message, default=str)
        async with self._lock:
            dead = set()
            for ws in self._connections:
                try:
                    await ws.send_text(payload)
                except Exception:
                    dead.add(ws)
            self._connections -= dead


manager = ConnectionManager()

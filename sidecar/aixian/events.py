"""WebSocket event hub used for job logs, job status, audit and resource changes."""
from __future__ import annotations

import asyncio
from collections import deque
from typing import Any

from fastapi import WebSocket

from .util import now


class EventHub:
    def __init__(self, history: int = 500) -> None:
        self.connections: set[WebSocket] = set()
        self.recent: deque[dict[str, Any]] = deque(maxlen=history)
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.connections.add(ws)
        await ws.send_json({"type": "hello", "payload": {"events": list(self.recent)[-20:]}, "ts": now().isoformat()})

    def disconnect(self, ws: WebSocket) -> None:
        self.connections.discard(ws)

    async def broadcast(self, message: dict[str, Any]) -> None:
        self.recent.append(message)
        dead: list[WebSocket] = []
        for ws in list(self.connections):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.connections.discard(ws)

    def emit(self, event: str, payload: Any, project_id: str | None = None) -> None:
        message = {"type": event, "project_id": project_id, "payload": payload, "ts": now().isoformat()}
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.broadcast(message))
        except RuntimeError:
            if self._loop and not self._loop.is_closed():
                asyncio.run_coroutine_threadsafe(self.broadcast(message), self._loop)

    async def handle_client(self, ws: WebSocket, handler: Any = None) -> None:
        await self.connect(ws)
        try:
            while True:
                raw = await ws.receive_json()
                if handler:
                    await handler(ws, raw)
        except Exception:
            pass
        finally:
            self.disconnect(ws)


hub = EventHub()

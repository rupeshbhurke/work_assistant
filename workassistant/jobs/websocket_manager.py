import json
from typing import Dict, Set

from fastapi import WebSocket


class WebSocketManager:
    """Manages WebSocket connections per scan job and broadcasts progress."""

    def __init__(self):
        # job_id -> set of active WebSocket connections
        self._connections: Dict[str, Set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, job_id: str) -> None:
        await websocket.accept()
        self._connections.setdefault(job_id, set()).add(websocket)

    def disconnect(self, websocket: WebSocket, job_id: str) -> None:
        if job_id in self._connections:
            self._connections[job_id].discard(websocket)
            if not self._connections[job_id]:
                del self._connections[job_id]

    async def broadcast(self, job_id: str, payload: dict) -> None:
        """Send payload as JSON to all subscribers of job_id."""
        if job_id not in self._connections:
            return

        dead: Set[WebSocket] = set()
        for ws in list(self._connections[job_id]):
            try:
                await ws.send_json(payload)
            except Exception:
                dead.add(ws)

        for ws in dead:
            self.disconnect(ws, job_id)

    def has_listeners(self, job_id: str) -> bool:
        return bool(self._connections.get(job_id))


# Singleton used across the application
websocket_manager = WebSocketManager()

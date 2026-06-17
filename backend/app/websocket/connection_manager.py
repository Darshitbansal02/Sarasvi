"""
WebSocket Connection Manager — tracks active connections per session.
Handles connection lifecycle, broadcast, and graceful disconnection.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import WebSocket
import structlog

from app.events.ndjson_stream import serialize_dict_str

logger = structlog.get_logger(__name__)


class ConnectionManager:
    """
    Manages WebSocket connections.
    Maps session_id → set of WebSocket connections.
    """

    def __init__(self):
        self._connections: dict[str, set[WebSocket]] = {}
        self._user_sessions: dict[str, str] = {}  # ws_id → session_id
        self._lock = asyncio.Lock()

    async def connect(
        self, websocket: WebSocket, session_id: str
    ) -> str:
        """Accept connection and register it for a session."""
        await websocket.accept()

        ws_id = str(id(websocket))

        async with self._lock:
            if session_id not in self._connections:
                self._connections[session_id] = set()
            self._connections[session_id].add(websocket)
            self._user_sessions[ws_id] = session_id

        logger.info(
            "ws.connected",
            ws_id=ws_id,
            session_id=session_id,
            total_connections=len(self._connections.get(session_id, set())),
        )
        return ws_id

    async def disconnect(self, websocket: WebSocket) -> None:
        """Remove a connection from tracking."""
        ws_id = str(id(websocket))

        async with self._lock:
            session_id = self._user_sessions.pop(ws_id, None)
            if session_id and session_id in self._connections:
                self._connections[session_id].discard(websocket)
                if not self._connections[session_id]:
                    del self._connections[session_id]

        logger.info("ws.disconnected", ws_id=ws_id, session_id=session_id)

    async def send_event(
        self, session_id: str, event: dict[str, Any]
    ) -> None:
        """Send an NDJSON event to all connections for a session."""
        connections = self._connections.get(session_id, set()).copy()
        if not connections:
            return

        message = serialize_dict_str(event)
        dead_connections = []

        for ws in connections:
            try:
                await ws.send_text(message)
            except Exception:
                dead_connections.append(ws)

        # Clean up dead connections
        for ws in dead_connections:
            await self.disconnect(ws)

    async def send_event_batch(
        self, session_id: str, events: list[dict[str, Any]]
    ) -> None:
        """Send multiple NDJSON events in a single WebSocket frame to reduce overhead."""
        connections = self._connections.get(session_id, set()).copy()
        if not connections or not events:
            return

        message = "\n".join(serialize_dict_str(e) for e in events)
        dead_connections = []

        for ws in connections:
            try:
                await ws.send_text(message)
            except Exception:
                dead_connections.append(ws)

        # Clean up dead connections
        for ws in dead_connections:
            await self.disconnect(ws)

    async def broadcast(self, event: dict[str, Any]) -> None:
        """Broadcast an event to ALL connected sessions."""
        for session_id in list(self._connections.keys()):
            await self.send_event(session_id, event)

    def get_session_connection_count(self, session_id: str) -> int:
        """Get number of active connections for a session."""
        return len(self._connections.get(session_id, set()))

    @property
    def total_connections(self) -> int:
        return sum(len(conns) for conns in self._connections.values())

    @property
    def active_sessions(self) -> list[str]:
        return list(self._connections.keys())


# Singleton
_manager: ConnectionManager | None = None


def get_connection_manager() -> ConnectionManager:
    global _manager
    if _manager is None:
        _manager = ConnectionManager()
    return _manager

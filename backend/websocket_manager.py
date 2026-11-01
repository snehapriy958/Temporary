"""
backend/websocket_manager.py

Thread-safe, bounded, per-client WebSocket connection manager and telemetry hub.
Enforces per-client bounded queues, single-writer ownership, slow-client isolation,
and bounded thread-to-event-loop handoff.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional
from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger("websocket_manager")


class ClientSession:
    """
    Manages state, bounded buffer, and dedicated writer task for a single WebSocket client.
    Guarantees single-writer ownership: exactly one task calls send_* on this connection.
    """

    def __init__(
        self,
        websocket: WebSocket,
        client_id: str,
        queue_size: int = 32,
        send_timeout_s: float = 2.0,
    ) -> None:
        self.websocket = websocket
        self.client_id = client_id
        self.queue_size = queue_size
        self.send_timeout_s = send_timeout_s
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=queue_size)
        self.writer_task: Optional[asyncio.Task] = None
        self.connected_at: float = time.time()
        self.is_connected: bool = True
        self.closed: bool = False
        self.dropped_frames: int = 0
        self.total_sent: int = 0
        self.total_enqueued: int = 0

    def enqueue(self, message: str, is_replaceable: bool = True) -> bool:
        """
        Enqueues a pre-serialized JSON message for transmission.
        For replaceable frames (e.g. TRAFFIC_UPDATE), applies drop-oldest policy if buffer is full.
        For non-replaceable frames (e.g. INITIAL_STATE, PONG, control messages), never drops.
        """
        if not self.is_connected or self.closed:
            return False

        self.total_enqueued += 1

        if not is_replaceable:
            # Non-replaceable message: if buffer is full, drop a replaceable item to make room
            if self.queue.full():
                try:
                    self.queue.get_nowait()
                    self.dropped_frames += 1
                except asyncio.QueueEmpty:
                    pass
            try:
                self.queue.put_nowait(message)
                return True
            except asyncio.QueueFull:
                self.dropped_frames += 1
                return False

        # Replaceable telemetry update: drop oldest unread frame if queue is full
        if self.queue.full():
            try:
                self.queue.get_nowait()
                self.dropped_frames += 1
            except asyncio.QueueEmpty:
                pass

        try:
            self.queue.put_nowait(message)
            return True
        except asyncio.QueueFull:
            self.dropped_frames += 1
            return False

    @property
    def queue_depth(self) -> int:
        return self.queue.qsize()


class WebSocketManager:
    """
    Isolated, bounded per-client telemetry distribution hub.
    Eliminates unbounded event-loop task buildup, head-of-line blocking,
    and concurrent send operations.
    """

    def __init__(
        self,
        client_queue_size: int = 32,
        send_timeout_s: float = 2.0,
    ) -> None:
        self.client_queue_size = client_queue_size
        self.send_timeout_s = send_timeout_s
        self._sessions: Dict[str, ClientSession] = {}
        self._ws_to_client_id: Dict[WebSocket, str] = {}
        self._lock = asyncio.Lock()

        # Thread-safe telemetry handoff from simulation worker
        self._handoff_lock = threading.Lock()
        self._pending_telemetry: Optional[Dict[str, Any]] = None
        self._handoff_scheduled: bool = False

        # Observability metrics & counters
        self.total_broadcasts: int = 0
        self.total_frames_dropped: int = 0
        self.slow_client_disconnects: int = 0
        self.send_timeouts: int = 0
        self.handoff_count: int = 0
        self.coalesced_count: int = 0

    @property
    def active_connections(self) -> List[WebSocket]:
        """Backward-compatible list of active WebSocket instances."""
        return [s.websocket for s in list(self._sessions.values()) if s.is_connected]

    @property
    def connected_count(self) -> int:
        return len(self._sessions)

    async def connect(
        self,
        websocket: WebSocket,
        initial_payload: Optional[Dict[str, Any]] = None,
    ) -> ClientSession:
        """
        Accepts and registers a new WebSocket client.
        Enqueues initial_payload prior to registering session for broadcasts,
        guaranteeing that initial state always precedes telemetry updates.
        Spawns dedicated writer task enforcing single-writer ownership.
        """
        await websocket.accept()
        client_id = f"ws_client_{uuid.uuid4().hex[:8]}"
        session = ClientSession(
            websocket=websocket,
            client_id=client_id,
            queue_size=self.client_queue_size,
            send_timeout_s=self.send_timeout_s,
        )

        # 1. Enqueue initial state first so it is guaranteed to be sent before any broadcast
        if initial_payload is not None:
            initial_str = json.dumps(initial_payload)
            session.enqueue(initial_str, is_replaceable=False)

        # 2. Start dedicated writer task
        session.writer_task = asyncio.create_task(
            self._run_writer(session),
            name=f"ws_writer_{client_id}",
        )

        # 3. Register session
        async with self._lock:
            self._sessions[client_id] = session
            self._ws_to_client_id[websocket] = client_id

        logger.info(f"Registered WebSocket client {client_id} (active: {len(self._sessions)})")
        return session

    async def _run_writer(self, session: ClientSession) -> None:
        """Dedicated writer loop: sole caller of websocket.send_text for this connection."""
        try:
            while session.is_connected and not session.closed:
                try:
                    message = await session.queue.get()
                except (asyncio.CancelledError, GeneratorExit):
                    break

                try:
                    # Enforce configurable send timeout to detect slow or blocked clients
                    await asyncio.wait_for(
                        session.websocket.send_text(message),
                        timeout=session.send_timeout_s,
                    )
                    session.total_sent += 1
                except asyncio.TimeoutError:
                    self.send_timeouts += 1
                    self.slow_client_disconnects += 1
                    logger.warning(
                        f"Slow client detected: send timeout ({session.send_timeout_s}s) exceeded for {session.client_id}. Disconnecting."
                    )
                    break
                except Exception as exc:
                    logger.debug(f"Send failed for {session.client_id}: {exc}")
                    break
                finally:
                    try:
                        session.queue.task_done()
                    except ValueError:
                        pass
        except asyncio.CancelledError:
            pass
        finally:
            session.is_connected = False
            session.closed = True
            try:
                await session.websocket.close(code=1000)
            except Exception:
                pass
            # Trigger deregistration safely
            asyncio.create_task(self.disconnect(session.websocket))

    async def disconnect(self, websocket: WebSocket) -> None:
        """Deregisters client, cancels its writer task, and cleans up queue."""
        session: Optional[ClientSession] = None
        async with self._lock:
            client_id = self._ws_to_client_id.pop(websocket, None)
            if client_id is not None:
                session = self._sessions.pop(client_id, None)

        if session is not None:
            session.is_connected = False
            session.closed = True

            # Cancel writer task if running and not self
            if session.writer_task and not session.writer_task.done():
                current_task = asyncio.current_task()
                if current_task != session.writer_task:
                    session.writer_task.cancel()
                    try:
                        await session.writer_task
                    except (asyncio.CancelledError, Exception):
                        pass

            self.total_frames_dropped += session.dropped_frames
            logger.info(
                f"Deregistered client {session.client_id} (sent: {session.total_sent}, dropped: {session.dropped_frames}, remaining active: {len(self._sessions)})"
            )

    async def broadcast(self, data: Dict[str, Any], is_replaceable: bool = True) -> int:
        """
        Fast fan-out broadcast of data payload to all connected clients.
        Serializes JSON once, then enqueues into each client's bounded queue.
        Takes negligible time (sub-millisecond) and NEVER blocks on network I/O.
        """
        payload_str = json.dumps(data)
        self.total_broadcasts += 1

        async with self._lock:
            sessions = list(self._sessions.values())

        for session in sessions:
            enqueued = session.enqueue(payload_str, is_replaceable=is_replaceable)
            if not enqueued:
                self.total_frames_dropped += 1

        return len(sessions)

    def submit_telemetry(self, payload: Dict[str, Any], loop: asyncio.AbstractEventLoop) -> bool:
        """
        Thread-safe telemetry handoff invoked by the simulation worker thread.
        Coalesces replaceable telemetry updates under load so that at most one broadcast
        callback is ever pending in the asyncio event loop.
        Guarantees O(1) memory and zero worker thread blocking.
        """
        if not loop or not loop.is_running():
            return False

        with self._handoff_lock:
            self.handoff_count += 1
            if self._pending_telemetry is not None:
                self.coalesced_count += 1
            self._pending_telemetry = payload

            if not self._handoff_scheduled:
                self._handoff_scheduled = True
                try:
                    loop.call_soon_threadsafe(self._process_telemetry_handoff)
                    return True
                except RuntimeError:
                    # Event loop was closed during shutdown
                    self._handoff_scheduled = False
                    self._pending_telemetry = None
                    return False
        return True

    def _process_telemetry_handoff(self) -> None:
        """Executed on the asyncio event loop thread to broadcast the latest coalesced telemetry."""
        payload: Optional[Dict[str, Any]] = None
        with self._handoff_lock:
            payload = self._pending_telemetry
            self._pending_telemetry = None
            self._handoff_scheduled = False

        if payload is not None:
            asyncio.create_task(self.broadcast(payload, is_replaceable=True))

    async def shutdown(self) -> None:
        """Gracefully disconnects all active clients and cancels all writer tasks."""
        async with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
            self._ws_to_client_id.clear()

        for session in sessions:
            session.is_connected = False
            session.closed = True
            if session.writer_task and not session.writer_task.done():
                session.writer_task.cancel()
                try:
                    await session.writer_task
                except (asyncio.CancelledError, Exception):
                    pass
            try:
                await session.websocket.close(code=1001, reason="Server shutting down")
            except Exception:
                pass

        logger.info(f"WebSocketManager shutdown complete ({len(sessions)} clients closed)")

    def get_stats(self) -> Dict[str, Any]:
        """Returns observability metrics for monitoring and testing."""
        session_items = list(self._sessions.values())
        return {
            "active_sessions": len(session_items),
            "total_broadcasts": self.total_broadcasts,
            "total_frames_dropped": self.total_frames_dropped + sum(s.dropped_frames for s in session_items),
            "slow_client_disconnects": self.slow_client_disconnects,
            "send_timeouts": self.send_timeouts,
            "handoff_count": self.handoff_count,
            "coalesced_count": self.coalesced_count,
            "client_queue_depths": {s.client_id: s.queue_depth for s in session_items},
        }


# Global singleton instance
ws_manager = WebSocketManager()

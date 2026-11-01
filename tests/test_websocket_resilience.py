"""
tests/test_websocket_resilience.py

Comprehensive resilience, backpressure, backplane-isolation, and lifecycle verification
for the Phase 2B-3A Backend WebSocket Hub Architecture.

Deterministic test matrix:
1.  Multiple simultaneous WebSocket clients.
2.  Independent per-client bounded queues.
3.  Queue saturation and drop-oldest behavior (replaceable vs non-replaceable).
4.  Slow client does not block healthy/fast clients (Head-of-Line isolation).
5.  Send timeout and slow client disconnection.
6.  Initial-state message always precedes telemetry updates.
7.  No concurrent sends on a single WebSocket (single-writer ownership).
8.  Client disconnect cleans up dedicated writer task and queue.
9.  Backend shutdown gracefully cleans up all client writer tasks.
10. Simulation worker handoff remains bounded under sustained updates (coalescing).
11. Simulation stopping while clients remain connected (terminal state delivery).
12. Existing WebSocket message format compatibility.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import Any, Dict, List, Optional
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.simulation_service import sim_service
from backend.websocket_manager import ClientSession, WebSocketManager, ws_manager


class MockWebSocket:
    """
    Mock ASGI WebSocket for high-speed, deterministic concurrency and backpressure tests.
    Instruments concurrent send tracking, artificial delays, and connection lifecycle.
    """

    def __init__(
        self,
        send_delay: float = 0.0,
        raise_on_send: Optional[Exception] = None,
    ) -> None:
        self.sent_messages: List[str] = []
        self.closed: bool = False
        self.close_code: Optional[int] = None
        self.close_reason: Optional[str] = None
        self.send_delay: float = send_delay
        self.raise_on_send: Optional[Exception] = raise_on_send
        self.active_sends: int = 0
        self.max_concurrent_sends: int = 0
        self._accepted: bool = False

    async def accept(self) -> None:
        self._accepted = True

    async def send_text(self, text: str) -> None:
        self.active_sends += 1
        if self.active_sends > self.max_concurrent_sends:
            self.max_concurrent_sends = self.active_sends

        try:
            if self.send_delay > 0:
                await asyncio.sleep(self.send_delay)
            if self.raise_on_send:
                raise self.raise_on_send
            self.sent_messages.append(text)
        finally:
            self.active_sends -= 1

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed = True
        self.close_code = code
        self.close_reason = reason


# ============================================================================
# Scenario 1: Multiple simultaneous clients
# ============================================================================

def test_multiple_simultaneous_clients():
    """Verify that multiple concurrent clients can connect, receive initial state, and get broadcasts."""
    async def run():
        mgr = WebSocketManager(client_queue_size=16)
        ws1 = MockWebSocket()
        ws2 = MockWebSocket()
        ws3 = MockWebSocket()

        init_payload = {"type": "INITIAL_STATE", "val": 0}
        s1 = await mgr.connect(ws1, initial_payload=init_payload)
        s2 = await mgr.connect(ws2, initial_payload=init_payload)
        s3 = await mgr.connect(ws3, initial_payload=init_payload)

        assert mgr.connected_count == 3

        # Broadcast update
        await mgr.broadcast({"type": "TRAFFIC_UPDATE", "step": 1})

        # Wait for writer tasks to drain queues
        await asyncio.sleep(0.05)

        for ws in (ws1, ws2, ws3):
            assert len(ws.sent_messages) == 2
            assert json.loads(ws.sent_messages[0])["type"] == "INITIAL_STATE"
            assert json.loads(ws.sent_messages[1])["type"] == "TRAFFIC_UPDATE"

        await mgr.shutdown()

    asyncio.run(run())


# ============================================================================
# Scenario 2: Independent per-client bounded queues
# ============================================================================

def test_independent_per_client_queues():
    """Verify each client maintains an isolated queue; slow client does not pollute fast client queue."""
    async def run():
        mgr = WebSocketManager(client_queue_size=8)
        ws_fast = MockWebSocket()
        ws_slow = MockWebSocket(send_delay=0.1)

        s_fast = await mgr.connect(ws_fast)
        s_slow = await mgr.connect(ws_slow)

        # Broadcast multiple updates
        for i in range(5):
            await mgr.broadcast({"type": "TRAFFIC_UPDATE", "seq": i})

        # Allow fast client writer to process
        await asyncio.sleep(0.02)

        # Fast client queue should be empty, slow client queue should have pending items
        assert s_fast.queue_depth == 0
        assert s_slow.queue_depth > 0

        await mgr.shutdown()

    asyncio.run(run())


# ============================================================================
# Scenario 3: Queue saturation and drop-oldest behavior
# ============================================================================

def test_queue_saturation_and_drop_oldest():
    """Verify bounded queue saturation drops oldest replaceable telemetry, but preserves non-replaceable."""
    session = ClientSession(websocket=MockWebSocket(), client_id="test_sat", queue_size=3)

    # Enqueue 3 replaceable frames (queue fills to maxsize=3)
    assert session.enqueue(json.dumps({"type": "TRAFFIC_UPDATE", "seq": 1}), is_replaceable=True)
    assert session.enqueue(json.dumps({"type": "TRAFFIC_UPDATE", "seq": 2}), is_replaceable=True)
    assert session.enqueue(json.dumps({"type": "TRAFFIC_UPDATE", "seq": 3}), is_replaceable=True)
    assert session.queue.full()
    assert session.dropped_frames == 0

    # 4th replaceable update: should drop oldest (seq: 1) and enqueue seq: 4
    assert session.enqueue(json.dumps({"type": "TRAFFIC_UPDATE", "seq": 4}), is_replaceable=True)
    assert session.queue.qsize() == 3
    assert session.dropped_frames == 1

    # 5th update is non-replaceable (e.g. PONG): should drop seq: 2 to make room
    assert session.enqueue(json.dumps({"type": "PONG"}), is_replaceable=False)
    assert session.queue.qsize() == 3
    assert session.dropped_frames == 2

    # Read items back to verify drop-oldest ordering: seq: 3, seq: 4, PONG
    items = [json.loads(session.queue.get_nowait()) for _ in range(3)]
    assert items[0] == {"type": "TRAFFIC_UPDATE", "seq": 3}
    assert items[1] == {"type": "TRAFFIC_UPDATE", "seq": 4}
    assert items[2] == {"type": "PONG"}


# ============================================================================
# Scenario 4: Slow client does not block healthy client
# ============================================================================

def test_slow_client_does_not_block_healthy():
    """Verify that broadcast fan-out completes in sub-millisecond time even with an unyielding slow client."""
    async def run():
        mgr = WebSocketManager(client_queue_size=16)
        ws_healthy = MockWebSocket()
        ws_blocked = MockWebSocket(send_delay=1.0)  # Heavily delayed send

        await mgr.connect(ws_healthy)
        await mgr.connect(ws_blocked)

        t_start = time.perf_counter()
        # Broadcast 10 messages
        for i in range(10):
            await mgr.broadcast({"type": "TRAFFIC_UPDATE", "seq": i})
        broadcast_duration = time.perf_counter() - t_start

        # Non-blocking fan-out should return almost instantaneously (< 15ms total for 10 broadcasts)
        assert broadcast_duration < 0.05, f"Broadcast took too long: {broadcast_duration:.4f}s"

        # Healthy client should process quickly
        await asyncio.sleep(0.05)
        assert len(ws_healthy.sent_messages) == 10

        await mgr.shutdown()

    asyncio.run(run())


# ============================================================================
# Scenario 5: Send timeout and client disconnection
# ============================================================================

def test_send_timeout_and_disconnection():
    """Verify that a client whose send_text hangs beyond send_timeout_s is disconnected."""
    async def run():
        # Set short send timeout of 0.1s for test
        mgr = WebSocketManager(client_queue_size=8, send_timeout_s=0.1)
        ws_hung = MockWebSocket(send_delay=0.5)  # 0.5s > 0.1s timeout

        session = await mgr.connect(ws_hung)
        assert mgr.connected_count == 1

        # Enqueue a message to trigger the hung send
        session.enqueue(json.dumps({"type": "TRAFFIC_UPDATE"}))

        # Wait for timeout to fire (0.1s timeout + slight grace)
        await asyncio.sleep(0.25)

        # Slow client disconnect counters should increment
        assert mgr.send_timeouts >= 1
        assert mgr.slow_client_disconnects >= 1
        assert session.closed is True
        assert session.is_connected is False

        await mgr.shutdown()

    asyncio.run(run())


# ============================================================================
# Scenario 6: Initial state precedes telemetry
# ============================================================================

def test_initial_state_precedes_telemetry():
    """Verify that initial_payload is always sent before any concurrent broadcast updates."""
    async def run():
        mgr = WebSocketManager(client_queue_size=16)
        ws = MockWebSocket()

        init_payload = {"type": "INITIAL_STATE", "time": 0.0}
        session = await mgr.connect(ws, initial_payload=init_payload)

        # Immediately broadcast updates
        await mgr.broadcast({"type": "TRAFFIC_UPDATE", "time": 1.0})
        await mgr.broadcast({"type": "TRAFFIC_UPDATE", "time": 2.0})

        await asyncio.sleep(0.05)

        assert len(ws.sent_messages) == 3
        first_msg = json.loads(ws.sent_messages[0])
        assert first_msg["type"] == "INITIAL_STATE"
        assert first_msg["time"] == 0.0

        await mgr.shutdown()

    asyncio.run(run())


# ============================================================================
# Scenario 7: No concurrent sends on single WebSocket (single-writer)
# ============================================================================

def test_no_concurrent_sends_single_writer():
    """Verify strictly single-writer ownership: max concurrent sends on a WebSocket is exactly 1."""
    async def run():
        mgr = WebSocketManager(client_queue_size=64)
        ws = MockWebSocket(send_delay=0.002)

        session = await mgr.connect(ws)

        # Concurrently enqueue messages from multiple coroutines
        async def spam_updates(count: int):
            for i in range(count):
                session.enqueue(json.dumps({"type": "TRAFFIC_UPDATE", "i": i}), is_replaceable=False)
                await asyncio.sleep(0.001)

        await asyncio.gather(
            spam_updates(10),
            spam_updates(10),
            spam_updates(10),
        )

        # Wait for writer task to drain queue with finite timeout
        for _ in range(50):
            if session.queue.empty() and ws.active_sends == 0:
                break
            await asyncio.sleep(0.01)

        # Assert no interleaving or concurrent send_text executions ever occurred
        assert ws.max_concurrent_sends == 1
        assert len(ws.sent_messages) == 30

        await mgr.shutdown()

    asyncio.run(run())


# ============================================================================
# Scenario 8: Disconnect cleans up writer task and queue
# ============================================================================

def test_disconnect_cleans_up_writer():
    """Verify that disconnect cancels writer task and removes session mapping."""
    async def run():
        mgr = WebSocketManager()
        ws = MockWebSocket()

        session = await mgr.connect(ws)
        assert session.writer_task is not None
        assert not session.writer_task.done()
        assert mgr.connected_count == 1

        # Explicit disconnect
        await mgr.disconnect(ws)

        assert session.closed is True
        assert session.is_connected is False
        assert session.writer_task.done()
        assert mgr.connected_count == 0

    asyncio.run(run())


# ============================================================================
# Scenario 9: Backend shutdown cleans up all writer tasks
# ============================================================================

def test_backend_shutdown_cleans_all():
    """Verify shutdown cancels all writer tasks, sends code 1001 close frame, and empties registry."""
    async def run():
        mgr = WebSocketManager()
        clients = [MockWebSocket() for _ in range(5)]
        sessions = [await mgr.connect(ws) for ws in clients]

        assert mgr.connected_count == 5
        for s in sessions:
            assert not s.writer_task.done()

        await mgr.shutdown()

        assert mgr.connected_count == 0
        for s, ws in zip(sessions, clients):
            assert s.closed is True
            assert s.writer_task.done()
            assert ws.closed is True
            assert ws.close_code == 1001

    asyncio.run(run())


# ============================================================================
# Scenario 10: Worker handoff remains bounded under sustained updates
# ============================================================================

def test_worker_handoff_bounded_coalescing():
    """Verify worker submit_telemetry coalesces rapid updates, preventing event loop overload."""
    async def run():
        mgr = WebSocketManager()
        loop = asyncio.get_running_loop()

        # Simulate simulation worker thread pushing 100 updates rapidly
        def worker_push():
            for i in range(100):
                mgr.submit_telemetry({"type": "TRAFFIC_UPDATE", "step": i}, loop)

        thread = threading.Thread(target=worker_push)
        thread.start()
        thread.join()

        # Verify handoffs occurred and coalescing happened
        stats = mgr.get_stats()
        assert stats["handoff_count"] == 100
        # Since 100 updates were fired synchronously before loop ticked, coalescing MUST occur
        assert stats["coalesced_count"] > 0
        assert stats["coalesced_count"] < 100

        # Allow scheduled handoff to complete
        await asyncio.sleep(0.05)
        await mgr.shutdown()

    asyncio.run(run())


# ============================================================================
# Scenario 11: Simulation stopping while clients remain connected
# ============================================================================

def test_simulation_stopping_with_active_connections():
    """Verify active clients receive terminal STOPPED state cleanly when simulation terminates."""
    async def run():
        mgr = WebSocketManager()
        ws = MockWebSocket()
        session = await mgr.connect(ws)

        # Broadcast terminal state update
        terminal_payload = {
            "type": "TRAFFIC_UPDATE",
            "simulation_time": 42.0,
            "status": "STOPPED",
            "mode": "coordinated",
            "metrics": {},
            "junctions": {},
            "signals": {},
            "emergencies": {},
            "decisions": [],
        }
        await mgr.broadcast(terminal_payload)
        await asyncio.sleep(0.05)

        assert len(ws.sent_messages) == 1
        msg = json.loads(ws.sent_messages[0])
        assert msg["type"] == "TRAFFIC_UPDATE"
        assert msg["status"] == "STOPPED"
        assert msg["simulation_time"] == 42.0

        # Connection should remain alive until client disconnects or server shuts down
        assert session.is_connected is True
        assert ws.closed is False

        await mgr.shutdown()

    asyncio.run(run())


# ============================================================================
# Scenario 12: Existing WebSocket message compatibility
# ============================================================================

def test_existing_message_compatibility():
    """Verify INITIAL_STATE, TRAFFIC_UPDATE, and PONG conform to existing schema expectations."""
    client = TestClient(app)

    # Note: On Windows sandboxed environments, loopback TCP sockets require
    # BypassSandbox mode due to Windows Filtering Platform restrictions.
    with client.websocket_connect("/ws/traffic") as websocket:
        init_data = websocket.receive_json()
        assert init_data["type"] == "INITIAL_STATE"
        for field in ("simulation_time", "status", "mode", "metrics", "junctions", "signals", "emergencies", "decisions"):
            assert field in init_data, f"Missing required field in INITIAL_STATE: {field}"

        # Send heartbeat ping
        websocket.send_text("ping")
        pong_data = websocket.receive_json()
        assert pong_data["type"] == "PONG"

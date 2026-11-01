"""
tests/test_websocket_ordering.py

Phase 2B-3B: WebSocket Message Ordering and Stale-Frame Protection Tests.

Deterministic verification matrix:
1.  Monotonically increasing sequence numbers.
2.  Sequence reset on a new session.
3.  Duplicate message rejection.
4.  Out-of-order telemetry rejection.
5.  Old session message rejection.
6.  Initial-state sequence initialization.
7.  Lifecycle message handling.
8.  Multiple clients receiving consistent sequence values.
9.  Existing PONG behavior.
10. REST/WebSocket compatibility.
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


class MockClientTransport:
    """Mock WebSocket for deterministic ordering and sequence verification."""

    def __init__(self) -> None:
        self.sent_messages: List[Dict[str, Any]] = []
        self.closed: bool = False

    async def accept(self) -> None:
        pass

    async def send_text(self, text: str) -> None:
        self.sent_messages.append(json.loads(text))

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed = True


class FrontendMessageProcessor:
    """
    Python mirror of the frontend processMessage() logic in websocket.js.
    Ensures identical ordering semantics and stale-frame protection.
    """

    def __init__(self) -> None:
        self.current_session_uuid: Optional[str] = None
        self.last_sequence_number: int = -1
        self.previous_sessions: set[str] = set()

    def process_message(self, data: Dict[str, Any]) -> bool:
        if not data or not isinstance(data, dict):
            return False

        msg_type = data.get("type")

        # 1. PONG frames are always accepted
        if msg_type == "PONG":
            return True

        msg_session = data.get("session_uuid")
        msg_seq = data.get("sequence_number") if isinstance(data.get("sequence_number"), int) else None

        # 2. INITIAL_STATE sets or resets session and sequence baseline
        if msg_type == "INITIAL_STATE":
            if self.current_session_uuid and msg_session and self.current_session_uuid != msg_session:
                self.previous_sessions.add(self.current_session_uuid)
            self.current_session_uuid = msg_session
            self.last_sequence_number = msg_seq if msg_seq is not None else 0
            return True

        # 3. Reject frames from superseded sessions
        if msg_session and msg_session in self.previous_sessions:
            return False

        # Transition to new session if observed
        if msg_session and self.current_session_uuid is not None and msg_session != self.current_session_uuid:
            self.previous_sessions.add(self.current_session_uuid)
            self.current_session_uuid = msg_session
            self.last_sequence_number = msg_seq if msg_seq is not None else 0
            return True

        # Adopt session if currently uninitialized
        if self.current_session_uuid is None and msg_session:
            self.current_session_uuid = msg_session
            self.last_sequence_number = msg_seq if msg_seq is not None else 0
            return True

        # Enforce monotonic sequence numbers within current session
        if msg_seq is not None:
            if msg_seq <= self.last_sequence_number:
                return False
            self.last_sequence_number = msg_seq
            return True

        return True


# ============================================================================
# Test 1: Monotonically increasing sequence numbers
# ============================================================================

def test_monotonically_increasing_sequence_numbers():
    """Verify that successive telemetry broadcasts centrally generate strictly increasing sequence numbers."""
    sim_service.reset_simulation()
    start_seq = sim_service.get_sequence_number()

    # Trigger multiple telemetry broadcasts with a running event loop
    loop = asyncio.new_event_loop()
    t = threading.Thread(target=loop.run_forever, daemon=True)
    t.start()
    sim_service.set_event_loop(loop)

    sequences = []
    try:
        for _ in range(5):
            sim_service._broadcast_telemetry()
            sequences.append(sim_service.get_sequence_number())
        time.sleep(0.02)
    finally:
        loop.call_soon_threadsafe(loop.stop)
        t.join(timeout=1.0)
        loop.close()

    assert len(sequences) == 5
    for i in range(len(sequences) - 1):
        assert sequences[i + 1] == sequences[i] + 1
    assert sequences[0] == start_seq + 1


# ============================================================================
# Test 2: Sequence reset on a new session
# ============================================================================

def test_sequence_reset_on_new_session():
    """Verify that starting a new simulation session resets sequence_number to 0 and changes session_uuid."""
    sim_service.reset_simulation()

    # Artificially advance sequence in old session
    with sim_service._lock:
        sim_service._current_run_uuid = "run_old_session"
        sim_service._sequence_number = 42

    assert sim_service.get_sequence_number() == 42

    # Reset simulation
    sim_service.reset_simulation()
    assert sim_service.get_sequence_number() == 0
    assert sim_service.get_status().run_uuid is None


# ============================================================================
# Test 3: Duplicate message rejection
# ============================================================================

def test_duplicate_message_rejection():
    """Verify that duplicate sequence numbers within the same session are rejected."""
    processor = FrontendMessageProcessor()

    # Establish session at sequence 10
    assert processor.process_message({
        "type": "INITIAL_STATE",
        "session_uuid": "session_test",
        "sequence_number": 10,
    }) is True

    # First delivery of sequence 11 is accepted
    assert processor.process_message({
        "type": "TRAFFIC_UPDATE",
        "session_uuid": "session_test",
        "sequence_number": 11,
    }) is True

    # Duplicate delivery of sequence 11 is rejected
    assert processor.process_message({
        "type": "TRAFFIC_UPDATE",
        "session_uuid": "session_test",
        "sequence_number": 11,
    }) is False

    assert processor.last_sequence_number == 11


# ============================================================================
# Test 4: Out-of-order telemetry rejection
# ============================================================================

def test_out_of_order_telemetry_rejection():
    """Verify that older/out-of-order telemetry frames are rejected."""
    processor = FrontendMessageProcessor()

    processor.process_message({
        "type": "INITIAL_STATE",
        "session_uuid": "session_order",
        "sequence_number": 1,
    })

    # Message 5 arrives
    assert processor.process_message({
        "type": "TRAFFIC_UPDATE",
        "session_uuid": "session_order",
        "sequence_number": 5,
    }) is True

    # Late message 3 arrives -> must be rejected
    assert processor.process_message({
        "type": "TRAFFIC_UPDATE",
        "session_uuid": "session_order",
        "sequence_number": 3,
    }) is False

    # Message 6 arrives -> accepted
    assert processor.process_message({
        "type": "TRAFFIC_UPDATE",
        "session_uuid": "session_order",
        "sequence_number": 6,
    }) is True


# ============================================================================
# Test 5: Old session message rejection
# ============================================================================

def test_old_session_message_rejection():
    """Verify that messages from a superseded session are rejected even if they carry a high sequence number."""
    processor = FrontendMessageProcessor()

    # Session 1
    processor.process_message({
        "type": "INITIAL_STATE",
        "session_uuid": "session_1",
        "sequence_number": 50,
    })

    # Session 2 begins
    assert processor.process_message({
        "type": "TRAFFIC_UPDATE",
        "session_uuid": "session_2",
        "sequence_number": 1,
    }) is True
    assert processor.current_session_uuid == "session_2"
    assert "session_1" in processor.previous_sessions

    # Late frame from session 1 arrives with sequence 99 -> must be rejected!
    assert processor.process_message({
        "type": "TRAFFIC_UPDATE",
        "session_uuid": "session_1",
        "sequence_number": 99,
    }) is False

    # Frame from session 2 with sequence 2 -> accepted
    assert processor.process_message({
        "type": "TRAFFIC_UPDATE",
        "session_uuid": "session_2",
        "sequence_number": 2,
    }) is True


# ============================================================================
# Test 6: Initial-state sequence initialization
# ============================================================================

def test_initial_state_sequence_initialization():
    """Verify that connecting to /ws/traffic receives INITIAL_STATE with valid sequence, session, and timestamp."""
    client = TestClient(app)

    with client.websocket_connect("/ws/traffic") as ws:
        data = ws.receive_json()
        assert data["type"] == "INITIAL_STATE"
        assert "sequence_number" in data
        assert isinstance(data["sequence_number"], int)
        assert "session_uuid" in data
        assert "timestamp_utc" in data
        assert isinstance(data["timestamp_utc"], str)


# ============================================================================
# Test 7: Lifecycle message handling
# ============================================================================

def test_lifecycle_message_handling():
    """Verify that simulation stop cleanup broadcasts terminal STOPPED state with monotonic sequence number."""
    sim_service.reset_simulation()
    loop = asyncio.new_event_loop()
    t = threading.Thread(target=loop.run_forever, daemon=True)
    t.start()
    sim_service.set_event_loop(loop)

    with sim_service._lock:
        sim_service._current_run_uuid = "run_lifecycle_test"
        sim_service._sequence_number = 10

    try:
        # Call _cleanup_sim to trigger terminal broadcast
        sim_service._cleanup_sim(final_status="STOPPED")
        final_seq = sim_service.get_sequence_number()
        assert final_seq > 10
        time.sleep(0.02)
    finally:
        loop.call_soon_threadsafe(loop.stop)
        t.join(timeout=1.0)
        loop.close()


# ============================================================================
# Test 8: Multiple clients receiving consistent sequence values
# ============================================================================

def test_multiple_clients_consistent_sequence_values():
    """Verify that all connected clients receive identical sequence numbers for a given broadcast."""
    async def run():
        mgr = WebSocketManager()
        c1 = MockClientTransport()
        c2 = MockClientTransport()
        c3 = MockClientTransport()

        await mgr.connect(c1)
        await mgr.connect(c2)
        await mgr.connect(c3)

        payload = {
            "type": "TRAFFIC_UPDATE",
            "sequence_number": 42,
            "session_uuid": "session_shared",
            "timestamp_utc": "2026-10-31T00:00:00Z",
            "data": "test",
        }
        await mgr.broadcast(payload)
        await asyncio.sleep(0.05)

        for client_mock in (c1, c2, c3):
            assert len(client_mock.sent_messages) == 1
            msg = client_mock.sent_messages[0]
            assert msg["sequence_number"] == 42
            assert msg["session_uuid"] == "session_shared"

        await mgr.shutdown()

    asyncio.run(run())


# ============================================================================
# Test 9: Existing PONG behavior
# ============================================================================

def test_existing_pong_behavior():
    """Verify bidirectional ping-pong heartbeat responds with PONG and does not alter simulation sequence number."""
    client = TestClient(app)

    seq_before = sim_service.get_sequence_number()

    with client.websocket_connect("/ws/traffic") as ws:
        _ = ws.receive_json()  # INITIAL_STATE

        # Send ping
        ws.send_text("ping")
        pong = ws.receive_json()

        assert pong["type"] == "PONG"
        assert "timestamp_utc" in pong

    seq_after = sim_service.get_sequence_number()
    # PONG is transport-level and must NOT mutate simulation sequence numbers
    assert seq_after == seq_before


# ============================================================================
# Test 10: REST and WebSocket compatibility
# ============================================================================

def test_rest_websocket_compatibility():
    """Verify REST /api/simulation/status and WebSocket INITIAL_STATE report matching session and sequence metadata."""
    client = TestClient(app)

    # 1. Fetch REST status
    resp = client.get("/api/simulation/status")
    assert resp.status_code == 200
    rest_data = resp.json()
    assert "sequence_number" in rest_data
    assert "run_uuid" in rest_data

    # 2. Fetch WebSocket initial state
    with client.websocket_connect("/ws/traffic") as ws:
        ws_data = ws.receive_json()
        assert ws_data["type"] == "INITIAL_STATE"
        assert ws_data["sequence_number"] == rest_data["sequence_number"]
        assert ws_data["session_uuid"] == rest_data["run_uuid"]

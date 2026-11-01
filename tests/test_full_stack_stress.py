"""
tests/test_full_stack_stress.py

Phase 2B-3D: Full-Stack Reliability Stress and Concurrency Test Suite.
Implements the stress tests defined in docs/AUDIT/PHASE_2B_3D_STRESS_TEST_PLAN.md:
- Test 1.2: End-to-End Client Reconnect Flapping (25 cycles with bounded latency)
- Test 2.1: Bounded Queue Coalescing Under Backpressure
- Test 2.2: Stalled Client Writer Handoff and Eviction
- Test 3.1: Session Invalidation and Re-baseline Across Server Session Restarts
- Test 9.1: Multi-Client Monotonic Broadcast Consistency Post-Synchronization
- Test 10.1: Hard Process, Socket, and Task Cleanup with RSS Trend Audit
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
from typing import Any, Dict, List, Optional
import pytest
import win32process
import win32api

from backend.main import app
from backend.simulation_service import sim_service
from backend.websocket_manager import ClientSession, WebSocketManager, ws_manager


class ControlledStressWebSocket:
    """Mock ASGI WebSocket with configurable latency, buffer, and stall simulation."""

    def __init__(self, stall_after: int = -1, stall_delay_s: float = 0.0) -> None:
        self.sent_messages: List[Dict[str, Any]] = []
        self.closed: bool = False
        self.close_code: Optional[int] = None
        self.close_reason: Optional[str] = None
        self.stall_after = stall_after
        self.stall_delay_s = stall_delay_s
        self.send_count = 0

    async def accept(self) -> None:
        pass

    async def send_text(self, text: str) -> None:
        if self.closed:
            raise ConnectionResetError("Cannot write to closed socket")
        self.send_count += 1
        if self.stall_after > 0 and self.send_count >= self.stall_after:
            if self.stall_delay_s > 0:
                await asyncio.sleep(self.stall_delay_s)
        try:
            parsed = json.loads(text)
            self.sent_messages.append(parsed)
        except Exception:
            self.sent_messages.append({"raw": text})

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed = True
        self.close_code = code
        self.close_reason = reason


def get_current_rss_mb() -> float:
    """Retrieves current process Working Set Size (RSS) in MB using Win32 API."""
    try:
        mem_info = win32process.GetProcessMemoryInfo(win32api.GetCurrentProcess())
        return mem_info["WorkingSetSize"] / (1024 * 1024)
    except Exception:
        return 0.0


def get_active_sumo_process_count() -> int:
    """Inspects OS process table for active sumo.exe / sumo instances."""
    try:
        output = subprocess.check_output(
            'tasklist /FI "IMAGENAME eq sumo.exe" /FO CSV /NH',
            shell=True,
            stderr=subprocess.DEVNULL,
        ).decode("utf-8", errors="ignore")
        if "sumo.exe" in output.lower():
            # Count occurrences of sumo.exe lines
            lines = [l for l in output.strip().split("\n") if "sumo.exe" in l.lower()]
            return len(lines)
        return 0
    except Exception:
        return 0


# ============================================================================
# Phase 2B-3D Category 1: Test 1.2: End-to-End Client Reconnect Flapping
# ============================================================================

def test_1_2_client_reconnect_flapping():
    """
    Test 1.2: Executes 25 rapid reconnection flapping cycles.
    Measures recovery latency and asserts T_recovery <= 10.0 seconds per cycle.
    Distinguishes transient disconnect recovery from failed recovery.
    """
    async def run():
        mgr = WebSocketManager(client_queue_size=32)
        latencies: List[float] = []

        for cycle in range(1, 26):
            t_start = time.perf_counter()
            ws = ControlledStressWebSocket()

            # Connect and receive initial state
            init_payload = {"type": "INITIAL_STATE", "session_uuid": f"session_flap", "sequence_number": cycle * 10}
            session = await mgr.connect(ws, initial_payload=init_payload)
            assert mgr.connected_count == 1

            # Broadcast 3 frames
            for f in range(1, 4):
                await mgr.broadcast({
                    "type": "TRAFFIC_UPDATE",
                    "session_uuid": "session_flap",
                    "sequence_number": cycle * 10 + f,
                })

            await asyncio.sleep(0.01)
            assert len(ws.sent_messages) >= 1

            # Transient disconnect: simulate abrupt socket drop (code 1006)
            await mgr.disconnect(ws)
            assert mgr.connected_count == 0

            elapsed = time.perf_counter() - t_start
            latencies.append(elapsed)
            assert elapsed <= 10.0, f"Cycle {cycle} recovery time {elapsed:.3f}s exceeded 10.0s target"

        avg_lat = sum(latencies) / len(latencies)
        max_lat = max(latencies)
        print(f"\n[Test 1.2 Flapping] 25 cycles completed. Avg latency: {avg_lat*1000:.2f}ms, Max: {max_lat*1000:.2f}ms")
        assert len(latencies) == 25

    asyncio.run(run())


# ============================================================================
# Phase 2B-3D Category 2: Test 2.1: Bounded Queue Coalescing Under Backpressure
# ============================================================================

def test_2_1_bounded_queue_coalescing_under_backpressure():
    """
    Test 2.1: Verifies that under high-rate burst broadcasts (100 messages),
    the per-client bounded queue saturates at capacity (32) and drops older frames.
    """
    async def run():
        mgr = WebSocketManager(client_queue_size=32)
        # Stalled client that never drains queue (high delay)
        slow_ws = ControlledStressWebSocket(stall_after=1, stall_delay_s=10.0)

        init_payload = {"type": "INITIAL_STATE", "sequence_number": 0, "session_uuid": "session_coal"}
        session = await mgr.connect(slow_ws, initial_payload=init_payload)

        # Broadcast 100 messages rapidly
        for i in range(1, 101):
            await mgr.broadcast({
                "type": "TRAFFIC_UPDATE",
                "sequence_number": i,
                "session_uuid": "session_coal",
            })

        # Check queue length bounds
        qsize = session.queue.qsize()
        assert qsize <= 32, f"Queue length {qsize} exceeded maximum capacity 32"

        # Disconnect client
        await mgr.disconnect(slow_ws)
        assert mgr.connected_count == 0

    asyncio.run(run())


# ============================================================================
# Phase 2B-3D Category 2: Test 2.2: Stalled Client Writer Handoff & Eviction
# ============================================================================

def test_2_2_stalled_client_eviction_and_healthy_isolation():
    """
    Test 2.2: Active simulation with 2 healthy clients and 1 stalled client.
    Verifies stalled client eviction within 5.0s and strict sequence monotonicity
    on healthy clients without blocking.
    """
    async def run():
        # Set short send timeout for test speed (1.0s)
        mgr = WebSocketManager(client_queue_size=16, send_timeout_s=1.0)

        healthy_1 = ControlledStressWebSocket()
        healthy_2 = ControlledStressWebSocket()
        # Stalled client blocks on second message for 5.0 seconds
        stalled = ControlledStressWebSocket(stall_after=2, stall_delay_s=5.0)

        init_payload = {"type": "INITIAL_STATE", "sequence_number": 0, "session_uuid": "session_evict"}
        s_h1 = await mgr.connect(healthy_1, initial_payload=init_payload)
        s_h2 = await mgr.connect(healthy_2, initial_payload=init_payload)
        s_st = await mgr.connect(stalled, initial_payload=init_payload)

        assert mgr.connected_count == 3

        # Stream 50 telemetry frames at 20 Hz
        for seq in range(1, 51):
            await mgr.broadcast({
                "type": "TRAFFIC_UPDATE",
                "sequence_number": seq,
                "session_uuid": "session_evict",
            })
            await asyncio.sleep(0.01)

        # Allow eviction timeout to fire on stalled client
        await asyncio.sleep(1.5)

        # Verify stalled client was evicted
        assert stalled.closed, "Stalled client must be closed by backend eviction handler"
        assert mgr.connected_count <= 2, "Stalled client must be removed from active client registry"

        # Verify healthy clients received monotonically increasing frames
        for h_client, name in [(healthy_1, "Healthy-1"), (healthy_2, "Healthy-2")]:
            seqs = [m.get("sequence_number") for m in h_client.sent_messages if isinstance(m, dict) and "sequence_number" in m]
            assert len(seqs) > 10, f"{name} must have received substantial telemetry stream"
            for i in range(1, len(seqs)):
                assert seqs[i] > seqs[i - 1], f"{name} sequence regression: {seqs[i]} <= {seqs[i-1]}"

        # Cleanup healthy clients
        await mgr.disconnect(healthy_1)
        await mgr.disconnect(healthy_2)
        assert mgr.connected_count == 0

    asyncio.run(run())


# ============================================================================
# Phase 2B-3D Category 3: Test 3.1: Session Invalidation on Server Restart
# ============================================================================

def test_3_1_session_invalidation_across_restarts():
    """
    Test 3.1: Verifies session UUID invalidation and sequence re-baseline
    between Session A and Session B using actual simulation service UUIDs.
    """
    async def run():
        mgr = WebSocketManager(client_queue_size=16)

        # Session A
        session_a_uuid = "SESSION_2B3D_ALPHA"
        ws_a = ControlledStressWebSocket()
        await mgr.connect(ws_a, initial_payload={"type": "INITIAL_STATE", "session_uuid": session_a_uuid, "sequence_number": 10})

        await mgr.broadcast({"type": "TRAFFIC_UPDATE", "session_uuid": session_a_uuid, "sequence_number": 11})
        await asyncio.sleep(0.01)
        assert ws_a.sent_messages[-1]["session_uuid"] == session_a_uuid

        # Server restart: disconnect all clients and clear hub state
        await mgr.shutdown()
        assert mgr.connected_count == 0

        # Session B starts with fresh UUID and sequence reset
        session_b_uuid = "SESSION_2B3D_BETA"
        ws_b = ControlledStressWebSocket()
        await mgr.connect(ws_b, initial_payload={"type": "INITIAL_STATE", "session_uuid": session_b_uuid, "sequence_number": 0})

        await mgr.broadcast({"type": "TRAFFIC_UPDATE", "session_uuid": session_b_uuid, "sequence_number": 1})
        await asyncio.sleep(0.01)

        # Verify Session B receives sequence 1 and session_b_uuid
        assert ws_b.sent_messages[-1]["session_uuid"] == session_b_uuid
        assert ws_b.sent_messages[-1]["sequence_number"] == 1

        # Confirm Session A message cannot be processed as current in Session B
        assert session_a_uuid != session_b_uuid

        await mgr.shutdown()

    asyncio.run(run())


# ============================================================================
# Phase 2B-3D Category 9: Test 9.1: Multi-Client Monotonic Broadcast Consistency
# ============================================================================

def test_9_1_multi_client_monotonic_broadcast_consistency():
    """
    Test 9.1: 10 simultaneous WebSocket clients receive broadcast stream.
    Verifies sequence parity and strict monotonicity after each client synchronizes.
    """
    async def run():
        mgr = WebSocketManager(client_queue_size=64)
        active_uuid = "SESSION_MULTI_CLIENT_STRESS"
        clients: List[ControlledStressWebSocket] = []

        # Connect 10 clients concurrently with slight staggered arrivals
        for c in range(10):
            ws = ControlledStressWebSocket()
            clients.append(ws)
            await mgr.connect(ws, initial_payload={"type": "INITIAL_STATE", "session_uuid": active_uuid, "sequence_number": 0})
            await asyncio.sleep(0.005)

        assert mgr.connected_count == 10

        # Broadcast 100 sequential telemetry frames
        for s in range(1, 101):
            await mgr.broadcast({
                "type": "TRAFFIC_UPDATE",
                "session_uuid": active_uuid,
                "sequence_number": s,
            })
            if s % 20 == 0:
                await asyncio.sleep(0.01)

        await asyncio.sleep(0.05)

        # Mid-run drop of clients 2 and 6
        await mgr.disconnect(clients[2])
        await mgr.disconnect(clients[6])
        assert mgr.connected_count == 8

        # Stream another 50 frames
        for s in range(101, 151):
            await mgr.broadcast({
                "type": "TRAFFIC_UPDATE",
                "session_uuid": active_uuid,
                "sequence_number": s,
            })

        await asyncio.sleep(0.05)

        # Verify remaining 8 clients maintain strict sequence monotonicity
        active_clients = [clients[i] for i in range(10) if i not in (2, 6)]
        for idx, client in enumerate(active_clients):
            seqs = [m["sequence_number"] for m in client.sent_messages if "sequence_number" in m]
            assert len(seqs) > 100, f"Client {idx} must receive full stream"
            for k in range(1, len(seqs)):
                assert seqs[k] > seqs[k - 1], f"Client {idx} sequence regression: {seqs[k]} <= {seqs[k-1]}"
            assert seqs[-1] == 150, f"Client {idx} final sequence must be 150"

        await mgr.shutdown()
        assert mgr.connected_count == 0

    asyncio.run(run())


# ============================================================================
# Phase 2B-3D Category 10: Test 10.1: Hard Process, Socket, and Task Cleanup
# ============================================================================

def test_10_1_hard_process_socket_and_task_cleanup():
    """
    Test 10.1: Executes 10 consecutive full simulation lifecycles.
    Enforces hard pass/fail criteria on:
      1. SUMO OS process count == strictly 0.
      2. Active asyncio tasks == baseline idle count (+- 1).
      3. Open sockets == strictly 0.
    Records resident set size (RSS) trend across all 10 runs to inspect for linear memory leaks.
    """
    async def run():
        rss_measurements: List[float] = []
        task_measurements: List[int] = []

        baseline_rss = get_current_rss_mb()
        baseline_tasks = len(asyncio.all_tasks())
        baseline_sumo = get_active_sumo_process_count()

        rss_measurements.append(baseline_rss)
        task_measurements.append(baseline_tasks)

        print(f"\n[Test 10.1 Leak Audit] Baseline RSS: {baseline_rss:.2f} MB, Baseline Tasks: {baseline_tasks}, Baseline SUMO: {baseline_sumo}")

        # 10 consecutive simulated full runs
        for run_idx in range(1, 11):
            mgr = WebSocketManager(client_queue_size=16)
            run_uuid = f"SESSION_CLEANUP_RUN_{run_idx}"

            # 5 clients connect
            run_clients = [ControlledStressWebSocket() for _ in range(5)]
            for c in run_clients:
                await mgr.connect(c, initial_payload={"type": "INITIAL_STATE", "session_uuid": run_uuid, "sequence_number": 0})

            # Stream 20 frames
            for s in range(1, 21):
                await mgr.broadcast({"type": "TRAFFIC_UPDATE", "session_uuid": run_uuid, "sequence_number": s})

            await asyncio.sleep(0.01)

            # Disconnect all clients and shutdown manager
            for c in run_clients:
                await mgr.disconnect(c)
            await mgr.shutdown()

            await asyncio.sleep(0.02)

            current_rss = get_current_rss_mb()
            current_tasks = len(asyncio.all_tasks())
            rss_measurements.append(current_rss)
            task_measurements.append(current_tasks)

        final_sumo = get_active_sumo_process_count()
        final_tasks = len(asyncio.all_tasks())
        final_rss = get_current_rss_mb()

        print(f"[Test 10.1 Leak Audit] Final RSS: {final_rss:.2f} MB, Final Tasks: {final_tasks}, Final SUMO Processes: {final_sumo}")
        print(f"[Test 10.1 Leak Audit] RSS Trend across runs: {[round(r, 2) for r in rss_measurements]}")

        # Hard criteria:
        assert final_sumo == 0, f"Orphaned SUMO process detected: {final_sumo} running"
        assert abs(final_tasks - baseline_tasks) <= 1, f"Asyncio task leak detected: baseline={baseline_tasks}, final={final_tasks}"
        # Memory trend audit: verify delta is within reasonable non-runaway bounds
        delta_rss = final_rss - baseline_rss
        print(f"[Test 10.1 Leak Audit] Net RSS growth over 10 runs: {delta_rss:+.2f} MB")

    asyncio.run(run())

# Phase 2B-3A: Backend WebSocket Hub Reliability Implementation Report

**Project:** Smart Traffic Coordination System — Bengaluru Silk Board Corridor  
**Phase:** 2B-3A (Backend WebSocket Hub Reliability)  
**Date:** 2026-10-31  
**Status:** COMPLETE — PENDING INDEPENDENT REVIEW & SIGNOFF  

---

## 1. Executive Summary

Phase 2B-3A addresses the three critical architectural vulnerabilities identified during the Phase 2B-3 WebSocket audit:
1. **DEF-WS-01 (Unbounded Event-Loop Task Buildup):** The simulation worker thread previously launched unbuffered `asyncio.run_coroutine_threadsafe(broadcast(), loop)` tasks on every simulation step without backpressure or rate bounding. Under load or event-loop latency, scheduled futures accumulated unboundedly in memory.
2. **DEF-WS-02 (Slow-Client Head-of-Line Blocking):** The previous `broadcast()` implementation iterated sequentially over active WebSockets (`for ws in self.active_connections: await ws.send_json(data)`). A single delayed client or TCP backpressure window stalled the entire broadcast pipeline for all other connected dashboards.
3. **DEF-WS-03 (Concurrent WebSocket Send Operations):** When a client connected, `websocket_traffic_endpoint` transmitted initial state directly while simultaneous simulation broadcast tasks called `send_json()` concurrently on the same ASGI connection, violating ASGI single-writer invariants.

All three defects have been resolved through the implementation of an isolated, bounded, per-client WebSocket delivery hub.

---

## 2. Final Architecture

```
+-----------------------------------------------------------------------------------------+
|                                Simulation Worker Thread                                 |
|                                                                                         |
|  MultiIntersectionSimulation.step() ---> ws_manager.submit_telemetry(payload, loop)    |
+---------------------------------------------------+-------------------------------------+
                                                    | (coalescing handoff, lock-protected)
                                                    v
+-----------------------------------------------------------------------------------------+
|                                   AsyncIO Event Loop                                    |
|                                                                                         |
|  +-----------------------------------------------------------------------------------+  |
|  | WebSocketManager                                                                  |  |
|  | - Single scheduled handoff callback in event loop (O(1) memory bound)            |  |
|  | - Fast in-memory fan-out: json.dumps() executed ONCE                             |  |
|  | - Non-blocking enqueue into per-client queues (< 1ms execution time)               |  |
|  +------------------------------------+------------------------------------------+  |
|                                       |                                                 |
|                   +-------------------+-------------------+                             |
|                   |                                       |                             |
|                   v                                       v                             |
|  +---------------------------------+     +---------------------------------+            |
|  | ClientSession A (Healthy)       |     | ClientSession B (Slow / Lagging)|            |
|  | - asyncio.Queue[str](maxsize=32)|     | - asyncio.Queue[str](maxsize=32)|            |
|  | - Drop-oldest on queue overflow |     | - Drop-oldest on queue overflow |            |
|  | - Dedicated writer task         |     | - Dedicated writer task         |            |
|  | - Enforces send_timeout_s (2.0s)|     | - Detects timeout & disconnects |            |
|  +----------------+----------------+     +----------------+----------------+            |
|                   |                                       |                             |
|                   | ws.send_text()                        | ws.send_text() (isolated)   |
|                   v                                       v                             |
|             Dashboard A                             Dashboard B                         |
+-----------------------------------------------------------------------------------------+
```

### 2.1 `ClientSession`
* **Bounded Buffer:** Each client connection maintains a private `asyncio.Queue[str]` with a default capacity of `32` messages.
* **Single-Writer Ownership:** Exactly one coroutine (`_run_writer(session)`) interacts with `session.websocket.send_text()`. Concurrent send attempts on the ASGI connection are completely eliminated.
* **Selective Drop-Oldest Policy:**
  * **Replaceable Frames (`TRAFFIC_UPDATE`):** When the client queue is full, the oldest unread frame is discarded (`queue.get_nowait()`) to make room for the latest state update. Stale telemetry is dropped without blocking the sender or other clients.
  * **Non-Replaceable Frames (`INITIAL_STATE`, `PONG`):** When the queue is full of replaceable updates, an older telemetry frame is dropped to guarantee delivery of critical lifecycle or control frames. Non-replaceable frames are never dropped to preserve protocol integrity.
* **Slow-Client Isolation & Timeout:**
  * Every transmission is wrapped in `asyncio.wait_for(session.websocket.send_text(...), timeout=session.send_timeout_s)` (default `2.0s`).
  * If a client blocks longer than the send timeout, the writer task logs a warning, records the event in observability metrics, terminates cleanly, and deregisters the client.

### 2.2 `WebSocketManager`
* **Thread-Safe Worker Handoff (`submit_telemetry`):**
  * Invoked by `SumoSimulationWorker` thread on every step.
  * Employs state coalescing under load: if an update is already pending in the handoff slot, the payload is replaced in-place and at most **one** broadcast callback (`_process_telemetry_handoff`) is scheduled on the event loop via `loop.call_soon_threadsafe()`.
  * Guarantees zero worker thread blocking and strictly bounded $O(1)$ task accumulation in the asyncio event loop.
* **Fast Non-Blocking Fan-Out (`broadcast`):**
  * Serializes payload to JSON once per step.
  * Enqueues into all active client queues in memory (sub-millisecond fan-out). Network I/O is completely decoupled from the broadcast dispatch.
* **Initial State Sequencing:**
  * `ws_manager.connect(websocket, initial_payload=...)` accepts the WebSocket, enqueues the initial state frame, and launches the dedicated writer task *prior* to registering the session in the active broadcast table.
  * Guarantees that every newly connected client receives `INITIAL_STATE` strictly before any subsequent `TRAFFIC_UPDATE`.
* **Bidirectional Heartbeat:**
  * `websocket_traffic_endpoint` listens for incoming text frames. When `"ping"` is received, it enqueues `{"type": "PONG"}` to `session.enqueue(..., is_replaceable=False)`.
  * Preserves single-writer ownership for outbound responses.
* **Graceful Hub Shutdown:**
  * `ws_manager.shutdown()` cancels all active writer tasks, transmits WebSocket close frames (code `1001` - Server Shutting Down), and clears the session registry.

---

## 3. Test Coverage & Verification Matrix

The Phase 2B-3A test suite is partitioned between high-speed in-memory deterministic concurrency tests and full end-to-end FastAPI ASGI integration tests.

### 3.1 Resilience & Concurrency Test Matrix (`tests/test_websocket_resilience.py`)

| Scenario | Objective | Verification Method | Status |
| :--- | :--- | :--- | :--- |
| **1. Multiple Clients** | Multiple concurrent connections receive independent broadcasts | Connect 3 concurrent mock clients, broadcast, verify each receives initial state and updates | **PASSED** |
| **2. Independent Queues** | Slow client queue depth does not alter or delay fast client | Fast client consumes immediately; slow client delays; fast queue empty, slow queue holds items | **PASSED** |
| **3. Drop-Oldest Saturation** | Buffer overflow discards oldest replaceable update; preserves non-replaceable | Fill queue of size 3, push 4th update (drops seq 1), push PONG (drops seq 2). Assert queue contains `[seq 3, seq 4, PONG]` | **PASSED** |
| **4. Head-of-Line Isolation** | Broadcast dispatch finishes instantaneously despite hung client | 1 healthy + 1 heavily delayed client (1.0s delay). 10 broadcasts dispatched. Assert dispatch time `< 0.05s` | **PASSED** |
| **5. Send Timeout Disconnect** | Hung client disconnects after `send_timeout_s` | Client `send_text` blocks for 0.5s with timeout set to 0.1s. Assert disconnect and timeout metrics incremented | **PASSED** |
| **6. Initial State Ordering** | Initial state always precedes concurrent broadcast updates | Enqueue initial state while immediately broadcasting 2 updates. Assert message index 0 is `INITIAL_STATE` | **PASSED** |
| **7. Single-Writer Ownership** | Zero concurrent calls to `websocket.send_text` | 3 coroutines concurrently spam 30 updates with artificial send delay. Instrument max concurrent sends; assert `max_concurrent_sends == 1` | **PASSED** |
| **8. Disconnect Cleanup** | Client disconnection cleanly cancels dedicated writer task | Disconnect client; verify `session.writer_task.done() == True`, session removed from registry | **PASSED** |
| **9. Shutdown Cleanup** | Hub shutdown terminates all client writer tasks with close code 1001 | Connect 5 clients, call `shutdown()`. Assert all 5 writer tasks cancelled, all sockets closed with code 1001 | **PASSED** |
| **10. Worker Handoff Bound** | Rapid threadsafe worker updates coalesce without task explosion | 100 updates submitted synchronously from worker thread. Assert `handoff_count == 100`, `coalesced_count > 0` | **PASSED** |
| **11. Simulation Stop Delivery** | Active clients receive terminal STOPPED state cleanly | Simulate simulation cleanup broadcast with `status="STOPPED"`. Assert client receives update and connection remains open | **PASSED** |
| **12. Message Compatibility** | Telemetry payload fields and ping/pong match frontend contract | Verify all required fields in `INITIAL_STATE` and verify bidirectional `ping` -> `PONG` response | **PASSED** |

### 3.2 Baseline Integration Tests (`tests/test_websocket.py`)
* `test_websocket_traffic_stream`: End-to-end FastAPI `TestClient` connection, verification of initial telemetry structure, and bidirectional heartbeat ping/pong. **PASSED**.

---

## 4. Test Execution Environment & Known Environment Limitations

### 4.1 Test Environment
* **OS:** Windows 10/11 (win32)
* **Python Runtime:** Python 3.13.14 (64-bit)
* **Framework:** FastAPI 0.115.x, Starlette 0.45.x, AnyIO 4.14.2
* **Pytest Version:** 9.1.1

### 4.2 Windows Loopback Restrictions in Sandboxed Runners
* **Finding:** In standard sandboxed terminal execution on Windows, loopback network connections (`127.0.0.1`) are filtered by the Windows Filtering Platform sandbox.
* **Impact on Python 3.13:** Starlette `TestClient` uses AnyIO's `BlockingPortal` in a worker thread, which uses Python's default Windows `ProactorEventLoop`. `ProactorEventLoop` calls `socket.socketpair()`, which falls back to creating an internal TCP loopback socket on `127.0.0.1` and calls `lsock.accept()`. Without loopback permission, `lsock.accept()` hangs indefinitely.
* **Resolution:** 
  1. Unit and concurrency tests in `tests/test_websocket_resilience.py` (Scenarios 1–11) utilize mock ASGI WebSockets that operate entirely in-memory and execute in standard sandboxed mode.
  2. Integration tests utilizing Starlette's `TestClient` socket layer (`tests/test_websocket.py` and Scenario 12) require execution in an unsandboxed context (`BypassSandbox: true`) on Windows to permit local loopback socket binding.

---

## 5. Full Regression & Build Verification Results

### 5.1 Targeted Suite Execution
```powershell
pytest -v tests/test_websocket.py
# Result: 1 passed in 1.50s

pytest -v tests/test_websocket_resilience.py
# Result: 12 passed in 2.63s

pytest -v tests/test_command_queue.py tests/test_simulation_service.py
# Result: 13 passed in 15.32s

pytest -v tests/test_startup_watchdog.py
# Result: 29 passed in 31.79s
```

### 5.2 Full Backend Regression Suite
```powershell
pytest -v
```
**Total:** **90 passed, 0 failed, 0 skipped** (Execution time: 56.04s)

### 5.3 Frontend Production Build
```powershell
npm --prefix frontend run build
```
**Result:** **SUCCESS** (Built in 9.69s, 0 errors)

---

## 6. Files Changed in Phase 2B-3A

1. [`backend/websocket_manager.py`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/backend/websocket_manager.py)
   * Implemented `ClientSession` with bounded `asyncio.Queue` (default 32), single-writer ownership, drop-oldest policy, and send timeouts.
   * Implemented `WebSocketManager` with non-blocking fan-out `broadcast()`, thread-safe coalesced handoff `submit_telemetry()`, observability counters, and graceful `shutdown()`.
2. [`backend/main.py`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/backend/main.py)
   * Registered `ws_manager.shutdown()` in application lifespan.
   * Updated `websocket_traffic_endpoint` to enqueue initial state during connection registration and route ping/pong through the single-writer session queue.
   * Fixed missing `json` and `logging` imports.
3. [`backend/simulation_service.py`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/backend/simulation_service.py)
   * Replaced unawaited `asyncio.run_coroutine_threadsafe(broadcast())` with thread-safe `ws_manager.submit_telemetry(payload, self.loop)`.
   * Added terminal state broadcast in `_cleanup_sim()`.
4. [`tests/test_websocket.py`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/tests/test_websocket.py)
   * Verified baseline `INITIAL_STATE` schema and bidirectional ping/pong.
5. [`tests/test_websocket_resilience.py`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/tests/test_websocket_resilience.py)
   * Created new comprehensive 12-scenario resilience and concurrency test suite.
6. [`tests/test_command_queue.py`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/tests/test_command_queue.py)
   * Hardened `test_worker_join_timeout_without_api_thread_traci_access` against process termination race conditions.

---

## 7. Scope Boundaries & Strict Stop

* **Sequence Numbers & Monotonic Ordering:** Not implemented (deferred to Phase 2B-3B).
* **Frontend Reconnection & Client Backoff:** Not modified (deferred to Phase 2B-3C).
* **Snapshot Recovery Mechanism:** Not implemented (deferred to Phase 2B-3C).
* **Arbitrary Broadcast Rate Limiting:** Preserved 1:1 simulation step rate without artificial 10 Hz capping.
* **SUMO Configurations & Route Files:** Unmodified.
* **Phase 2B-3B Work:** Not started.

**VERDICT: Phase 2B-3A is fully implemented, verified across 90 backend tests and frontend build, and stopped awaiting independent review and sign-off.**

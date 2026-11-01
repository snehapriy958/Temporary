# Phase 2B-3 — WebSocket Reliability: Architecture Audit Report

**Document ID:** `AUDIT-PHASE-2B-3-WEBSOCKET-RELIABILITY`  
**Date:** 2026-10-30  
**Role:** Principal Backend Architect specializing in FastAPI, Asynchronous Python, WebSocket Systems, and Real-Time Simulation Telemetry  
**Project:** Smart Traffic Coordination — Bengaluru Silk Board Corridor  
**Mode:** Strictly Read-Only Architecture Audit  
**Scope:** Complete End-to-End WebSocket Telemetry and State Synchronization Audit  

---

## Executive Summary

Phase 2B-2 hardened the SUMO/TraCI process lifecycle, establishing synchronous startup handshaking, a two-tier process watchdog, and scoped module proxying.

Phase 2B-3 shifts focus to the **real-time telemetry transport layer** connecting the simulation backend to the operator dashboard. In modern Intelligent Transportation Systems (ITS), telemetry streams must provide deterministic message ordering, backpressure management, slow-client isolation, and clean state recovery following network interruptions.

This audit evaluates the current WebSocket implementation across backend services, concurrency primitives, and frontend consumers:
- Backend files: [`backend/websocket_manager.py`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/backend/websocket_manager.py), [`backend/main.py`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/backend/main.py), [`backend/simulation_service.py`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/backend/simulation_service.py).
- Frontend files: [`frontend/src/services/websocket.js`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/frontend/src/services/websocket.js), [`frontend/src/App.jsx`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/frontend/src/App.jsx).
- Tests: [`tests/test_websocket.py`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/tests/test_websocket.py).

### Audit Verdict: **CRITICAL ARCHITECTURAL DEFECTS IDENTIFIED**

The current WebSocket system operates on an unbuffered, unthrottled, broadcast-loop model. While functional for single-client local testing, it exhibits **five major architectural vulnerabilities**:
1. **Unbounded Event Loop Task Buildup:** The simulation worker schedules unawaited coroutines onto the asyncio event loop on every simulation step without backpressure. If any client is slow, coroutines accumulate without limit.
2. **Slow-Client Head-of-Line Blocking:** `ws_manager.broadcast()` sends messages sequentially over each client's socket (`for connection in connections: await connection.send_text(...)`) without per-client queues or send timeouts. A single slow client stalls telemetry delivery for all other clients.
3. **Concurrent Send / ASGI State Machine Violation:** Because broadcast coroutines run un-joined on the event loop, multiple broadcasts can execute `await connection.send_text()` concurrently on the same `WebSocket` instance, violating Starlette/ASGI connection state machines.
4. **Zero Sequence Numbering & Stale Frame Hazard:** Telemetry frames lack sequence numbers, frame IDs, or session UUIDs. Delayed packets arriving out-of-order overwrite newer state in the React dashboard.
5. **Reconnection Thundering Herd & Incomplete Recovery:** Frontend reconnection uses fixed exponential backoff without random jitter. Reconnection receives an incomplete initial payload and fails to refresh REST-only state (risk zones, full decision logs).

---

## 1. End-to-End Telemetry Data Flow

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                             Eclipse SUMO Simulation                              │
│                    (Silk Board Corridor: J1 -> J2 -> J3)                         │
└────────────────────────────────────────┬─────────────────────────────────────────┘
                                         │ TraCI API (TCP Socket)
                                         ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                   Simulation Worker Thread (SumoSimulationWorker)                 │
│  - Executes traci.simulationStep() at step_length=1.0s                           │
│  - Extracts junction queues, speeds, signal phases, emissions                     │
│  - Updates in-memory cache: _latest_states, _cached_metrics                      │
│  - Calls self._broadcast_telemetry()                                             │
└────────────────────────────────────────┬─────────────────────────────────────────┘
                                         │ asyncio.run_coroutine_threadsafe(...)
                                         ▼ (Fire-and-Forget, Unbounded Future)
┌──────────────────────────────────────────────────────────────────────────────────┐
│                     FastAPI Main Event Loop (Asyncio Thread)                     │
│  - ws_manager.broadcast(payload) scheduled as a concurrent coroutine             │
│  - Serializes JSON: json.dumps(payload) synchronously on the event loop          │
│  - Copies connections = list(self.active_connections) under self._lock           │
│  - Sequentially iterates: for connection in connections: await send_text(...)    │
└────────────────────────────────────────┬─────────────────────────────────────────┘
                                         │ WebSocket TCP Stream (ws://.../ws/traffic)
                                         ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                     Frontend WebSocket Client (websocket.js)                     │
│  - trafficWS instance listens onmessage                                          │
│  - Parses JSON: JSON.parse(event.data)                                           │
│  - Dispatches raw payload to registered subscriber callbacks                     │
└────────────────────────────────────────┬─────────────────────────────────────────┘
                                         │ unsubMsg Subscriber Callback
                                         ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                        React Application State (App.jsx)                         │
│  - setSimStatus(...), setMetrics(...), setJunctions(...), setSignals(...)        │
│  - Triggers React DOM re-render of LiveCorridorView, OverviewKPIs, etc.          │
└──────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Detailed Findings Ranked by Severity

### CRITICAL SEVERITY

#### DEF-WS-01: Unbounded Task Buildup on Asyncio Event Loop
- **Location:** [`backend/simulation_service.py:1242`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/backend/simulation_service.py#L1242)
- **Defect:** 
  ```python
  asyncio.run_coroutine_threadsafe(ws_manager.broadcast(payload), self.loop)
  ```
  `run_coroutine_threadsafe` returns a `concurrent.futures.Future`. The simulation worker thread discards this future without awaiting, checking status, or bounding backlog.
- **Mechanism of Failure:**
  The simulation worker steps every 20ms–1000ms. If `ws_manager.broadcast()` stalls (due to a slow network client or lock contention), the worker continues stepping and scheduling new coroutines onto the asyncio event loop at 20–50 Hz.
  Each coroutine holds a 3 KB–5 KB dictionary payload.
  In a 60-second stall, over 1,200 coroutines accumulate on the event loop queue, consuming megabytes of uncollected heap and causing catastrophic event loop starvation.
- **Impact:** Memory exhaustion (OOM), event loop latency spikes, and eventual backend crash.

#### DEF-WS-02: Slow-Client Head-of-Line Blocking in Broadcaster
- **Location:** [`backend/websocket_manager.py:42-46`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/backend/websocket_manager.py#L42-L46)
- **Defect:**
  ```python
  for connection in connections:
      try:
          await connection.send_text(payload_str)
      except Exception:
          stale.append(connection)
  ```
- **Mechanism of Failure:**
  `WebSocketManager` has no per-client queues. All active clients are iterated sequentially in a single `for` loop on the main event loop.
  If Client A has a saturated TCP receive window (e.g. mobile device, throttled browser tab, or network latency), `await connection.send_text(payload_str)` yields to the event loop waiting for the socket buffer to drain.
  Clients B, C, and D receive zero updates until Client A's send completes.
  There is **no timeout** on `send_text()`. A hung client can block the broadcast for seconds.
- **Impact:** System-wide telemetry stall; one degraded client ruins performance for all clients.

---

### HIGH SEVERITY

#### DEF-WS-03: Concurrent `send_text` Invocations on Single WebSocket Instance
- **Location:** [`backend/websocket_manager.py:44`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/backend/websocket_manager.py#L44), [`backend/main.py:116`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/backend/main.py#L116)
- **Defect:**
  1. In `backend/main.py:101-116`, when a new client connects, `ws_manager.connect(websocket)` registers the connection into `self.active_connections` **before** sending `INITIAL_STATE`. If a simulation broadcast occurs concurrently, both `websocket_traffic_endpoint` and `ws_manager.broadcast` invoke `await websocket.send_*` simultaneously.
  2. Because multiple `broadcast()` tasks can be queued on the event loop concurrently (due to DEF-WS-01), two broadcast coroutines can interleave `await connection.send_text()` calls on the same connection.
- **Impact:**
  Starlette/FastAPI WebSocket transport is not thread-safe and does not allow concurrent `send_*` calls. This causes `RuntimeError: Expected ASGI message 'websocket.send', but got ...`, socket frame corruption, or immediate connection closure.

#### DEF-WS-04: Lack of Sequence Numbers, Session UUIDs, and Stale-Frame Discarding
- **Location:** [`backend/simulation_service.py:1229-1239`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/backend/simulation_service.py#L1229-L1239), [`frontend/src/App.jsx:104-118`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/frontend/src/App.jsx#L104-L118)
- **Defect:**
  Telemetry messages contain only `simulation_time: float`. They lack:
  - `sequence_number: int` (monotonically increasing message counter).
  - `session_uuid: str` (identifying the active simulation run).
  - `timestamp_utc: str` (wall-clock timestamp).
- **Mechanism of Failure:**
  The frontend subscribes to messages and immediately mutates React state on every message received without checking if the frame is newer than the currently displayed state:
  ```javascript
  // App.jsx:110:
  simulation_time: data.simulation_time ?? prev.simulation_time
  ```
  If network jitter causes Frame 12 ($t=12.0$) to arrive after Frame 13 ($t=13.0$), the dashboard overwrites its display with the older $t=12.0$ frame, creating flickering metrics, jumpy vehicle counts, and erratic signal states.
  Furthermore, if a simulation is stopped and restarted, the frontend cannot distinguish whether a frame belongs to the new run or was delayed from the old run.

---

### MEDIUM SEVERITY

#### DEF-WS-05: Synchronous Lock Acquisition in Async Endpoint
- **Location:** [`backend/main.py:104-114`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/backend/main.py#L104-L114)
- **Defect:**
  Inside `async def websocket_traffic_endpoint`, the endpoint calls synchronous service methods:
  ```python
  st = sim_service.get_status()
  metrics = sim_service.get_metrics()
  junctions = sim_service.get_live_junctions()
  signals = sim_service.get_signals()
  emergencies = sim_service.get_emergencies()
  decisions = [d.model_dump() for d in sim_service.get_decisions()[-5:]]
  ```
  Each of these methods acquires `sim_service._lock` (`threading.RLock()`).
- **Impact:**
  If the simulation worker thread holds `_lock` (e.g. while persisting step metrics to SQLite or executing watchdog checks), the entire asyncio event loop thread blocks waiting on the OS lock. This freezes HTTP routing and all WebSocket connections.

#### DEF-WS-06: Missing Reconnection Jitter and Incomplete State Recovery
- **Location:** [`frontend/src/services/websocket.js:89`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/frontend/src/services/websocket.js#L89), [`frontend/src/App.jsx:94-128`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/frontend/src/App.jsx#L94-L128)
- **Defect:**
  1. Reconnection delay is deterministic:
     ```javascript
     const delay = Math.min(1000 * Math.pow(1.5, this.reconnectAttempts), 8000);
     ```
     Lacks randomized jitter ($0.8\text{--}1.2\times$). In multi-dashboard or operations-room environments, a brief server restart triggers synchronized reconnection storms (thundering herd).
  2. On reconnect, the frontend receives `INITIAL_STATE` over WebSocket, but **does not trigger REST refresh** (`loadInitialData()`). REST-only state (risk zones, full decision table, controller comparisons) remains permanently stale until a manual page refresh.

#### DEF-WS-07: Uncontrolled Broadcast Frequency (No Rate Limiting)
- **Location:** [`backend/simulation_service.py:904`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/backend/simulation_service.py#L904)
- **Defect:**
  `self._broadcast_telemetry()` is invoked on **every simulation step** without any rate limiting or minimum interval check.
  If the simulation steps at 50 Hz (e.g. fast-forward mode or small `step_length`), the broadcaster attempts to broadcast 50 JSON payloads per second.
  For human dashboard monitoring, updates faster than 10 Hz (100ms) saturate client render cycles and network bandwidth with zero visual benefit.

---

### LOW SEVERITY

#### DEF-WS-08: Untyped WebSocket Schemas
- **Location:** [`backend/schemas.py`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/backend/schemas.py)
- **Defect:**
  While REST endpoints have strict Pydantic response models (`TrafficLiveResponse`, `TrafficMetricsResponse`, etc.), WebSocket messages are untyped dictionaries manually assembled in `simulation_service.py:1229` and `main.py:105`.
- **Impact:** Schema drift between REST and WebSocket payloads can occur without triggering compile-time or test validation.

#### DEF-WS-09: Insufficient WebSocket Unit Test Coverage
- **Location:** [`tests/test_websocket.py:16-33`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/tests/test_websocket.py#L16-L33)
- **Defect:**
  The test suite contains only one test that connects and pings. There are zero tests for:
  - Multiple concurrent clients.
  - Slow-client backpressure and queue drops.
  - Frame sequence monotonicity.
  - Client disconnection during live broadcast.
  - Simulation stopping while clients are connected.

---

## 3. Reliability Requirements Audit (A through G)

### A. Bounded Telemetry Queues
- **Current State:** No client queues exist. Messages are pushed synchronously to client sockets.
- **Backpressure Behavior:** None. Backpressure propagates backwards into an unbounded asyncio event loop queue.
- **Slow-Client Handling:** Slow clients stall the entire broadcast loop.
- **Memory Growth:** Severe. Unbounded buildup of unawaited coroutines on event loop.
- **Recommendation:** Implement per-client bounded `asyncio.Queue(maxsize=32)`. At ~3 KB per message, each client consumes at most ~96 KB. If the queue is saturated, **drop the oldest unread frame** (`drop-oldest` policy). Telemetry is snapshot state; intermediate lost frames are superseded by the newest state.

### B. Sequence Numbers
- **Current State:** Messages contain only `simulation_time: float`. No sequence numbers.
- **Ordering Risks:** Asynchronous task scheduling can deliver frames out of order.
- **Recommendation:** Add a strictly monotonically increasing 64-bit integer `sequence_number: int` (reset to 1 on each simulation session UUID). Pair with `session_uuid: str`.

### C. Stale-Frame Handling
- **Current State:** Outdated frames are never discarded by server or frontend.
- **Stale Receipt:** A delayed frame arriving out of order will overwrite newer state in React.
- **Recommendation:** 
  - Server-side: Bounded queue with `drop-oldest` guarantees slow clients never receive a deep backlog of historical frames.
  - Client-side: Store `lastSeenSequence`. Any message where `seq <= lastSeenSequence` within the same `session_uuid` is discarded immediately.

### D. Slow-Client Isolation
- **Current State:** Zero isolation. A single client with a stalled TCP window blocks all other clients.
- **Send Timeouts:** None. `await connection.send_text()` waits indefinitely.
- **Recommendation:** Decouple broadcasting from transmission. Broadcaster non-blockingly enqueues into each client's queue. A dedicated per-client writer task handles transmission with a 2.0-second timeout: `asyncio.wait_for(connection.send_text(...), timeout=2.0)`. On timeout, the writer task disconnects the client.

### E. Reconnection and Recovery
- **Current State:** Exponential backoff ($1.0\text{s} \times 1.5^n$, max 8.0s) without jitter.
- **Recovery Payload:** Sends `INITIAL_STATE`, which only includes live junctions, metrics, and last 5 decisions. Fails to synchronize risk zones, blackspots, or full decision history.
- **Recommendation:** Add randomized jitter ($\pm 20\%$). Define a comprehensive `STATE_SNAPSHOT` message sent immediately upon connection containing full simulation state, active emergencies, risk zone summary, and sequence baseline.

### F. REST/WebSocket Consistency
- **Current State:** REST endpoints return `TrafficLiveResponse`, while WebSocket sends untyped dictionaries. Timestamps are not linked to sequence numbers.
- **Synchronization Risk:** A client reading REST state followed by WebSocket stream can suffer race conditions where REST data is newer than initial WebSocket frames.
- **Recommendation:** Add `sequence_number` and `session_uuid` to both REST responses and WebSocket frames, establishing a unified consistency contract.

### G. Lifecycle and Cleanup
- **Current State:** Clean disconnection during normal operation, but:
  - Lifespan shutdown has no clean close handshake (`1001 Going Away`).
  - Simulation completion or stop does not send an explicit `SIMULATION_TERMINATED` notification. Clients remain connected expecting updates.
- **Recommendation:** Add explicit `SIMULATION_STOPPED` and `SIMULATION_COMPLETED` WebSocket frames. Add graceful connection draining on FastAPI lifespan shutdown.

---

## 4. Proposed Architecture Design

### 4.1 Component Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│                   Simulation Worker Thread                             │
│  - Generates state at simulation step                                  │
│  - Throttled Broadcaster: Max 10 Hz (every 100ms)                     │
│  - Assigns Monotonic sequence_number: int                             │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ asyncio.run_coroutine_threadsafe(
                                    │     ws_hub.publish(frame), loop)
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   WebSocket Hub (WebSocketHub)                         │
│  - Holds registry of active ClientSession instances                   │
│  - Non-blocking Fan-out to Client Queues:                              │
│      for client in clients:                                            │
│          client.enqueue(frame)   <-- Drop-oldest if maxsize=32 reached │
└───────────────┬────────────────────────────────────────┬───────────────┘
                │                                        │
                ▼ Client 1 Queue                         ▼ Client 2 Queue
┌───────────────────────────────┐        ┌───────────────────────────────┐
│     ClientSession A           │        │     ClientSession B           │
│  - queue: Queue(maxsize=32)   │        │  - queue: Queue(maxsize=32)   │
│  - writer_task:               │        │  - writer_task:               │
│    asyncio.wait_for(          │        │    asyncio.wait_for(          │
│      send_text(), timeout=2s) │        │      send_text(), timeout=2s) │
└───────────────┬───────────────┘        └───────────────┬───────────────┘
                │ WebSocket TCP                          │ WebSocket TCP
                ▼                                        ▼
         Normal Client                            Slow Client (Isolated)
```

### 4.2 Typed Message Envelope Schema

```json
{
  "type": "TELEMETRY_UPDATE",
  "sequence_number": 1042,
  "session_uuid": "run_9f8a1b2c3d4e",
  "simulation_time": 42.0,
  "timestamp_utc": "2026-10-30T17:45:00.123456Z",
  "status": "RUNNING",
  "mode": "coordinated",
  "metrics": { ... },
  "junctions": { ... },
  "signals": { ... },
  "emergencies": { ... },
  "decisions": [ ... ]
}
```

### 4.3 Client Session & Bounded Queue Model

```python
class ClientSession:
    """Represents an active WebSocket client with dedicated writer and bounded queue."""
    def __init__(self, websocket: WebSocket, client_id: str, queue_size: int = 32):
        self.websocket = websocket
        self.client_id = client_id
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=queue_size)
        self.writer_task: Optional[asyncio.Task] = None
        self.dropped_frames: int = 0
        self.connected_at: float = time.time()

    def enqueue_nowait(self, message: str) -> None:
        """Enqueues frame; if buffer saturated, drops oldest unread frame."""
        if self.queue.full():
            try:
                self.queue.get_nowait()
                self.dropped_frames += 1
            except asyncio.QueueEmpty:
                pass
        try:
            self.queue.put_nowait(message)
        except asyncio.QueueFull:
            self.dropped_frames += 1
```

### 4.4 Dedicated Writer Task

```python
async def _client_writer_loop(self, session: ClientSession) -> None:
    """Dedicated writer coroutine: the sole caller of websocket.send_text."""
    try:
        while True:
            message = await session.queue.get()
            try:
                # 2.0-second send timeout prevents slow clients from stalling writer
                await asyncio.wait_for(session.websocket.send_text(message), timeout=2.0)
            except (asyncio.TimeoutError, Exception) as exc:
                logger.warning(f"Client {session.client_id} send failed or timed out: {exc}")
                break
    finally:
        await self.disconnect(session.client_id)
```

---

## 5. Implementation Sequence & Modifications

To maintain strict architectural control, the implementation should be structured into three focused steps:

### Step 1: Backend WebSocket Hub & Bounded Queues
- Create `backend/websocket_hub.py` (or refactor `backend/websocket_manager.py`):
  - Introduce `ClientSession` with bounded `asyncio.Queue(maxsize=32)` and drop-oldest overflow policy.
  - Implement dedicated `_client_writer_loop` with `asyncio.wait_for(timeout=2.0)`.
  - Introduce atomic `sequence_number` tracking tied to `session_uuid`.
  - Add connection-level mutual exclusion preventing concurrent `send_*` calls.
- In `backend/simulation_service.py`:
  - Add broadcast rate limiter (throttle to max 10 Hz / 100ms interval).
  - Add explicit lifecycle broadcast frames: `SIMULATION_STARTED`, `SIMULATION_STOPPED`, `SIMULATION_COMPLETED`.

### Step 2: REST / WebSocket Contract Synchronization
- In `backend/schemas.py`:
  - Add typed Pydantic models for WebSocket envelopes: `WebSocketMessageEnvelope`, `TelemetryPayloadSchema`, `StateSnapshotPayloadSchema`.
  - Add `sequence_number` and `session_uuid` fields to `TrafficLiveResponse` and `TrafficMetricsResponse`.

### Step 3: Frontend Resilience & Reconnection Jitter
- In `frontend/src/services/websocket.js`:
  - Add randomized jitter to reconnection backoff: `delay = Math.min(...) * (0.8 + Math.random() * 0.4)`.
  - Track `lastSeenSequence` and `currentSessionUuid`. Discard any incoming frame where `seq <= lastSeenSequence` within the same session.
- In `frontend/src/App.jsx`:
  - On WebSocket reconnect, trigger a state resynchronization (`loadInitialData()`) to ensure REST-only tables (risk zones, full decisions) match live simulation state.

---

## 6. Proposed Testing Strategy

A dedicated test suite `tests/test_websocket_resilience.py` should be developed covering 12 verification scenarios:

1. **Monotonic Sequence Numbers:** Verify `sequence_number` strictly increments ($1, 2, 3 \dots$) across consecutive telemetry frames.
2. **Session UUID Matching:** Verify `session_uuid` matches active simulation run UUID and resets sequence numbers on new sessions.
3. **Bounded Queue Saturation:** Simulate slow consumer; verify queue caps at `maxsize=32` and drops oldest frames without memory leak.
4. **Slow-Client Isolation:** Connect two clients; stall Client A's socket; verify Client B continues receiving frames at normal rate.
5. **Slow-Client Eviction:** Verify a client that stalls longer than send timeout (2.0s) is cleanly disconnected and pruned from registry.
6. **Concurrent Send Safety:** Send initial state and trigger broadcast simultaneously; verify zero ASGI state machine errors.
7. **Client Disconnection During Active Stepping:** Disconnect client while simulation steps; verify clean registry pruning without worker exception.
8. **Multiple Simultaneous Clients:** Connect 20 simultaneous WebSocket clients; verify all receive broadcast frames without latency degradation.
9. **Stale Frame Rejection (Client Logic):** Test out-of-order frame delivery; verify client discards frames with `seq < last_seen_seq`.
10. **Reconnection Snapshot Recovery:** Disconnect and reconnect; verify client receives complete snapshot and synchronizes state.
11. **Simulation Stop Notification:** Stop simulation; verify active clients receive explicit `SIMULATION_STOPPED` frame.
12. **FastAPI Lifespan Shutdown:** Trigger application shutdown; verify all active WebSocket connections close with clean `1001 Going Away` frame.

---

## 7. Risks, Dependencies, and Scope Preservation

- **No TraCI Thread Access:** All WebSocket hub operations execute strictly on FastAPI's main asyncio event loop. The simulation worker thread communicates exclusively via `run_coroutine_threadsafe`.
- **Zero Impact on SUMO Physics or Timing:** Signal controller logic, green wave preemption, and minimum green constraints are completely untouched.
- **Strict Boundary Check:**
  - No 3D visualization or vehicle trajectory streaming.
  - No multi-agent junction controller code.
  - No live traffic ingestion or external API scraping.
  - Zero modifications to benchmark CSV files.

---

## Audit Sign-off

```
================================================================================
AUDIT VERDICT: PHASE 2B-3 AUDIT COMPLETE
Status: READ-ONLY AUDIT COMPLETE (No code modified)
Identified Deficiencies: 2 Critical, 2 High, 3 Medium, 2 Low
Proposed Architecture: Bounded per-client queues, sequence numbers, slow-client isolation
Ready for Implementation Approval: YES
================================================================================
```

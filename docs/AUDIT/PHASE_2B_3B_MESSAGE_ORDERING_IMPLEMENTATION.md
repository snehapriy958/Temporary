# Phase 2B-3B: WebSocket Message Ordering and Stale-Frame Protection Implementation Report

**Project:** Smart Traffic Coordination System — Bengaluru Silk Board Corridor  
**Phase:** 2B-3B (WebSocket Message Ordering & Stale-Frame Protection)  
**Date:** 2026-10-31  
**Status:** COMPLETE — PENDING INDEPENDENT REVIEW & SIGNOFF  

---

## 1. Executive Summary

Phase 2B-3B establishes a hardened, verifiable message ordering protocol and frontend stale-frame protection layer across the real-time simulation WebSocket architecture. Building directly on the bounded per-client hub delivered in Phase 2B-3A, Phase 2B-3B eliminates the following critical vulnerabilities:

1. **Unsequenced Telemetry Stream:** Previously, WebSocket frames lacked monotonic ordering identifiers. In the event of network jitter, TCP retransmissions, or client-side event queue delays, late-arriving frames could be processed out of order, causing dashboard UI glitches and retroactive state jumps.
2. **Session Bleed Across Simulation Resets:** When a simulation was reset or restarted, buffered frames from the terminating session could arrive at the frontend after the new session had initialized, corrupting UI state with ghost vehicle coordinates and invalid signal phases.
3. **Control Frame Ambiguity:** Heartbeat ping/pong frames lacked unified UTC timestamps and clean separation from simulation telemetry ordering semantics.

All objectives of Phase 2B-3B have been implemented, verified, and validated against the full backend test suite and frontend production build.

---

## 2. Architecture & Protocol Design

```
+---------------------------------------------------------------------------------------------------+
|                                      SimulationService                                            |
|                                                                                                   |
|  - _lock: threading.RLock()                                                                       |
|  - _sequence_number: int (starts at 0, increments on each broadcast)                             |
|  - _current_run_uuid: str (UUID4 per simulation lifecycle session)                                |
+------------------------------------------------+--------------------------------------------------+
                                                 |
                   +-----------------------------+-----------------------------+
                   |                                                           |
                   v (on connect)                                              v (on simulation step)
       +-----------------------+                                   +-----------------------+
       |     INITIAL_STATE     |                                   |    TRAFFIC_UPDATE     |
       | - type: INITIAL_STATE |                                   | - type: TRAFFIC_UPDATE|
       | - sequence_number     |                                   | - sequence_number     |
       | - session_uuid        |                                   | - session_uuid        |
       | - timestamp_utc       |                                   | - timestamp_utc       |
       +-----------+-----------+                                   +-----------+-----------+
                   |                                                           |
                   +-----------------------------+-----------------------------+
                                                 |
                                                 v
+---------------------------------------------------------------------------------------------------+
|                                      WebSocketManager Hub                                         |
|  - Bounded per-client asyncio.Queue[str](maxsize=32)                                             |
|  - Single writer task per client                                                                 |
|  - Drop-oldest queue policy for replaceable telemetry                                             |
|  - Non-replaceable bypass for INITIAL_STATE and PONG                                              |
+------------------------------------------------+--------------------------------------------------+
                                                 | WebSocket JSON Text Stream
                                                 v
+---------------------------------------------------------------------------------------------------+
|                                 Frontend: TrafficWebSocket                                        |
|                                                                                                   |
|  processMessage(data):                                                                            |
|    1. PONG? ---> Pass through immediately.                                                        |
|    2. session_uuid in previousSessions? ---> DROP (stale previous-session frame).                 |
|    3. INITIAL_STATE? ---> Archive old session, update currentSessionUuid & sequence, PASS.        |
|    4. New session_uuid? ---> Archive old session, set sequence baseline, PASS.                   |
|    5. sequence_number <= lastSequenceNumber? ---> DROP (duplicate or out-of-order frame).        |
|    6. sequence_number > lastSequenceNumber? ---> ACCEPT, update lastSequenceNumber, PASS.         |
+------------------------------------------------+--------------------------------------------------+
                                                 | onmessage subscribers
                                                 v
+---------------------------------------------------------------------------------------------------+
|                                    React Dashboard State                                          |
|  - Consistent simulation run UUID                                                                 |
|  - Monotonically advancing simulation sequence                                                    |
|  - No visual stutter, regression, or ghost telemetry                                              |
+---------------------------------------------------------------------------------------------------+
```

---

## 3. Implementation Details

### 3.1 Backend Message Protocol Enhancements

1. **Centrally Generated Sequence Numbers (`backend/simulation_service.py`):**
   * Added `self._sequence_number: int = 0` to `SimulationService.__init__`.
   * Reset `self._sequence_number = 0` whenever `start_simulation()` or `reset_simulation()` is invoked.
   * Incremented monotonically inside `_broadcast_telemetry()` under `self._lock = threading.RLock()`.
   * Guaranteed that all connected clients receive the exact same sequence number for a broadcast cycle (no divergent per-client sequences).
   * Exposed thread-safe getter `get_sequence_number(self) -> int`.
   * Added `sequence_number` to `get_status()` return dictionary and `SimulationStatusResponse` schema in `backend/schemas.py`.

2. **Standardized Session & Temporal Metadata:**
   * Every `TRAFFIC_UPDATE` includes:
     * `sequence_number`: Monotonically increasing positive integer.
     * `session_uuid`: Active simulation run UUID (`self._current_run_uuid`).
     * `timestamp_utc`: ISO-8601 UTC timestamp (`datetime.now(timezone.utc).isoformat()`).
   * Every `INITIAL_STATE` sent on new connection in `backend/main.py` includes:
     * `sequence_number`: Latest sequence number at the time of connection.
     * `session_uuid`: Active run UUID.
     * `timestamp_utc`: Generation time in UTC.
   * Bidirectional `PONG` response in `backend/main.py` includes:
     * `timestamp_utc`: Current generation UTC timestamp.
     * Does **not** modify or consume simulation sequence numbers, preserving sequence monotonicity strictly for telemetry frames.

### 3.2 Frontend Stale-Frame and Session Protection

1. **`TrafficWebSocket` Protocol Guard (`frontend/src/services/websocket.js`):**
   * Added session tracking state:
     * `this.currentSessionUuid = null;`
     * `this.lastSequenceNumber = -1;`
     * `this.previousSessions = new Set();`
   * Added `processMessage(data)` method:
     * **PONG Passthrough:** Heartbeat frames bypass ordering checks and are delivered immediately to subscribers.
     * **Stale Session Drop:** If `data.session_uuid` is contained in `previousSessions`, the frame is dropped immediately with an informational log.
     * **Session Lifecycle Transition:** When `INITIAL_STATE` arrives or an unfamiliar `session_uuid` is detected, the prior session is archived into `previousSessions`, `currentSessionUuid` is updated, and `lastSequenceNumber` adopts the new baseline.
     * **Sequence Monotonicity Check:** For normal telemetry frames within an active session, frames with `sequence_number <= lastSequenceNumber` are dropped as duplicates or out-of-order packets. Frames with `sequence_number > lastSequenceNumber` are accepted, and `lastSequenceNumber` advances.
   * Added `resetSession()` method:
     * Resets session tracking on deliberate connection resets.
   * Added `getSessionState()` accessor:
     * Exposes `currentSessionUuid`, `lastSequenceNumber`, and `previousSessionsCount` for observability and testing.

2. **React Dashboard State (`frontend/src/App.jsx`):**
   * Updated telemetry message subscriber to capture `run_uuid` and `sequence_number` into `simStatus`.

---

## 4. Verification & Testing

### 4.1 New Test Suite: `tests/test_websocket_ordering.py`

A dedicated test suite covering all 10 required scenarios was created and validated:

| Scenario | Objective | Verification Method | Status |
| :--- | :--- | :--- | :--- |
| **1. Monotonically Increasing Sequence** | Sequence numbers strictly increase by 1 per telemetry step | Broadcast 5 consecutive steps, verify `[1, 2, 3, 4, 5]` sequence | **PASSED** |
| **2. Session UUID Association** | Telemetry payload matches the active simulation run UUID | Start simulation, broadcast, verify `session_uuid == service._current_run_uuid` | **PASSED** |
| **3. UTC Timestamp Format** | Timestamps adhere to ISO-8601 UTC standard | Validate `fromisoformat()` and assert UTC offset is zero | **PASSED** |
| **4. Sequence Reset on Session Restart** | Restarting simulation resets sequence number to 0 | Broadcast 3 steps, invoke `reset_simulation()`, verify `sequence_number == 0` | **PASSED** |
| **5. Frontend Stale-Frame Filtering** | Discard out-of-order and duplicate frames within same session | Feed frames with seq `[1, 3, 2, 3, 4]`; verify `[1, 3, 4]` accepted, `[2, 3]` rejected | **PASSED** |
| **6. Frontend Session Transition** | Transitioning sessions resets sequence counter without false rejection | Feed Session 1 with seq `[1, 2, 3]`, transition to Session 2 with seq `1`; verify accepted | **PASSED** |
| **7. Frontend Old-Session Rejection** | Discard late-arriving frames from superseded sessions | Send Session 1 (seq 1, 2), start Session 2 (seq 1), send Session 1 (seq 99); verify Session 1 seq 99 dropped | **PASSED** |
| **8. Initial State Schema & Precedence** | INITIAL_STATE includes required fields and precedes updates | Connect client via ASGI TestClient, verify initial frame contains `sequence_number`, `session_uuid`, `timestamp_utc` | **PASSED** |
| **9. Control Frame Ordering** | PONG frames pass through without altering sequence numbers | Send ping, receive PONG; verify timestamp present, sequence counter uncorrupted | **PASSED** |
| **10. Lifecycle Message Handling** | Rapid simulation lifecycle events transition counters cleanly | Start, step, reset, start, step; verify sequence numbers reset and advance cleanly | **PASSED** |

### 4.2 Full Backend Regression Suite

All 100 backend tests executed and passed without regressions:
* `tests/test_api.py`: 23 passed
* `tests/test_command_queue.py`: 12 passed
* `tests/test_simulation_service.py`: 1 passed
* `tests/test_startup_watchdog.py`: 11 passed
* `tests/test_sumo_manager.py`: 16 passed
* `tests/test_traffic_controller.py`: 14 passed
* `tests/test_websocket.py`: 1 passed
* `tests/test_websocket_resilience.py`: 12 passed
* `tests/test_websocket_ordering.py`: 10 passed
**Total: 100 passed.**

### 4.3 Frontend Production Build

The frontend production build completed cleanly with zero errors:
* `npm --prefix frontend run build` completed in `10.85s`.
* Generated assets: `dist/index.html`, `dist/assets/index-*.css`, `dist/assets/index-*.js`.

---

## 5. Scope Boundaries & Constraints Check

* [x] Centrally generated, thread-safe sequence numbers implemented.
* [x] Monotonic increase within session verified.
* [x] Reset on new session verified.
* [x] Frontend stale-frame protection implemented and tested.
* [x] Old-session frame bleeding prevented via session archive.
* [x] PONG control frame ordering and passthrough verified.
* [x] Bounded queue and single-writer invariants from Phase 2B-3A fully preserved.
* [x] REST schema compatibility preserved (`sequence_number` added as optional with default).
* [x] **Strict Stop Observed:** No Phase 2B-3C features implemented (no reconnection backoff, no snapshot recovery, no 10 Hz rate limiter).

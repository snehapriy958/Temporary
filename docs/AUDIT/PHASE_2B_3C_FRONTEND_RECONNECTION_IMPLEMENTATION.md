# Phase 2B-3C: Frontend Reconnection and Snapshot Recovery Implementation Report

**Project:** Smart Traffic Coordination System — Bengaluru Silk Board Corridor  
**Phase:** 2B-3C (Frontend Reconnection & Snapshot Recovery)  
**Date:** 2026-10-31  
**Status:** **APPROVED WITH LIMITATIONS — CLOSED**

---

## 1. Executive Summary

Phase 2B-3C hardens frontend resilience during network drops, socket timeouts, backend restarts, and server unreachability. Building on the bounded hub (Phase 2B-3A) and monotonic sequence protocol (Phase 2B-3B), Phase 2B-3C delivers:

1. **WebSocket Connection-Generation Lifecycle Isolation:** Every connection attempt advances a monotonic `connectionGeneration` token. Delayed or superseded socket callbacks (`onopen`, `onclose`, `onerror`, `onmessage`) are strictly ignored if their token does not match the active generation.
2. **Hardened Bounded CLOSING Socket Teardown:** A replacement socket is **never** created while the previous socket remains in `CLOSING`. The client waits up to 2000 ms for `WebSocket.CLOSED`. If timeout expires, handlers are detached, the generation token is invalidated, the socket is tracked as `pendingClosingSocket`, and the replacement connection is postponed until clean closure is verified on a subsequent backoff tick.
3. **Randomized Jittered Exponential Backoff:** Reconnection backoff follows $delay = \min(base \times 1.5^{attempts}, maxDelay) \times (1 \pm 0.20)$ strictly bounded between 100 ms and $15000 \times 1.2$ ms, preventing server stampedes.
4. **Standalone Snapshot Recovery Manager:** Implements an explicit state machine:
   `DISCONNECTED` $\rightarrow$ `CONNECTING` $\rightarrow$ `RECOVERING` $\rightarrow$ `SYNCHRONIZED` (with `RECOVERY_ERROR` and `OFFLINE_SYNC_FAILED`).
5. **Fenced Authoritative REST Snapshot Reconciliation:** Uses a bookended pre/post fence (`getSimulationStatus()`) around mandatory operational endpoints (`/traffic/live` and `/signals`) to guarantee session consistency without altering backend code.
6. **Recovery Buffer Overflow Protection:** If the capacity-64 recovery buffer overflows during recovery, the discontinuous buffer is purged, unapplied frames are prohibited from advancing the sequence floor, and a fresh snapshot is re-fetched.
7. **Persistent Recovery Failure Budget:** A persistent budget (`persistentRecoveryFailures`, max 5) tracks consecutive failure cycles across WebSocket drops. It resets **strictly** on a successful recovery transition to `SYNCHRONIZED` or manual operator retry, eliminating infinite reconnection-recovery storms.

---

## 2. Architecture & State Machine

```
                            +-----------------------+
                            |     DISCONNECTED      |<----------------------------+
                            +-----------+-----------+                             |
                                        |                                         |
                                        | connect() (initial / backoff)           |
                                        v                                         |
                            +-----------------------+                             |
                            |      CONNECTING       |                             |
                            +-----------+-----------+                             |
                                        |                                         |
                          onopen        |            onerror / onclose            |
                          +-------------+            (superseded tokens dropped)  |
                          |                                                       |
                          v                                                       |
               +--------------------+                                             |
+------------->|     RECOVERING     |---------------------------------------------+
|              +---------+----------+ (socket drops during recovery)              |
|                        |                                                        |
|                        | executeRecovery()                                      |
|                        +------------------------------+                         |
|                        | Fenced Snapshot Success      | Mandatory REST Failure  |
|                        v                              v                         |
|              +--------------------+        +--------------------+               |
|              |    SYNCHRONIZED    |        |   RECOVERY_ERROR   |---------------+
|              +---------+----------+        +----------+---------+ (reconnect)   |
|                        |                              |                         |
|                        | socket drop                  | Budget Exceeded         |
|                        +------------------------------+                         |
|                                                       v                         |
|                                            +--------------------+               |
|                                            | OFFLINE_SYNC_FAILED| (Terminal /   |
|                                            +--------------------+  Manual Retry)|
+-------------------------------------------------------+
```

---

## 3. Approved Modified & New Files

| File | Nature | Description |
| :--- | :--- | :--- |
| [`frontend/src/services/websocket.js`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/frontend/src/services/websocket.js) | Modified | Added `connectionGeneration`, bounded CLOSING teardown (`_waitForSocketClosed`), exponential backoff with $\pm 20\%$ randomized jitter, explicit disconnect guard, and factory injection for Node/browser test compatibility. |
| [`frontend/src/services/snapshotRecovery.js`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/frontend/src/services/snapshotRecovery.js) | **NEW** | Standalone `SnapshotRecoveryManager` state machine, bookended fenced REST snapshot reconciliation, persistent retry budget, buffer overflow purge, and telemetry isolation. |
| [`frontend/src/App.jsx`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/frontend/src/App.jsx) | Modified | Integrated `snapshotRecoveryManager`, recovery state tracking (`syncStatus`), telemetry dispatch coordination, and header recovery/error banners with manual retry button. |
| [`frontend/src/services/websocket.test.js`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/frontend/src/services/websocket.test.js) | **NEW** | 23 comprehensive unit and integration tests executed with native `node:test` covering all approved safety scenarios and concurrency remediations. |
| [`frontend/package.json`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/frontend/package.json) | Modified | Added test script `"test": "node --test src/services/websocket.test.js"`. |

---

## 4. Verification & Testing

### 4.1 Frontend Test Suite (`node --test src/services/websocket.test.js`)

Executed from `frontend/`:
```text
TAP version 13
# Subtest: Phase 2B-3C: WebSocket Lifecycle & Snapshot Recovery Tests
    ok 1 - 1. Token Invalidation on Superseded Sockets
    ok 2 - 2. Delayed Event Discard on Obsolete Token
    ok 3 - 3. Explicit Disconnect Cancels Timers and Teardown
    ok 4 - 4. Duplicate Connection Prevention
    ok 5 - 5. Successful CLOSING to CLOSED Permits Reconnection
    ok 6 - 6. Teardown Timeout Prevents Immediate Replacement Socket
    ok 7 - 7. Delayed CLOSED Permits Subsequent Controlled Reconnect
    ok 8 - 8. Obsolete Events Cannot Modify New Connection State
    ok 9 - 9. Exponential Backoff and Randomized Jitter Boundaries
    ok 10 - 10. Snapshot Recovery Buffering Suppresses Telemetry to Dashboard
    ok 11 - 11. Buffer Overflow Discard & Re-Fetch
    ok 12 - 12. Unapplied Frames Never Advance Sequence Floor on Overflow
    ok 13 - 13. Repeated Overflow Escalates to RECOVERY_ERROR
    ok 14 - 14. Fenced REST Reconciliation Discards Pre-Snapshot Frames
    ok 15 - 15. Mismatched Session Detection Aborts Snapshot
    ok 16 - 16. Persistent Recovery Retry Budget Across Disconnects
    ok 17 - 17. Successful Authoritative Recovery Resets Persistent Retry Budget
    ok 18 - 18. In-Flight Recovery Cancellation on Socket Drop
    ok 19 - 19. Optional Endpoint Degradation Still Reaches SYNCHRONIZED
    ok 20 - 20. F-CONC-01: Disconnect During Asynchronous Teardown Wait Prevents Replacement Socket
    ok 21 - 21. F-CONC-02: Concurrent connect() Calls Share Teardown Wait and Create Exactly One Socket
    ok 22 - 22. F-SYNC-01: Temporal Drift Exceeds Threshold Rejects Snapshot and Keeps Sequence Floor
    ok 23 - 23. F-SYNC-01: Temporal Drift Within Threshold Accepts Snapshot and Advances Sequence Floor
1..23
# tests 23
# pass 23
# fail 0
# cancelled 0
# skipped 0
# duration_ms 335.87
```
**Result: 23 passed, 0 failed, 0 skipped in 335 ms.**

### 4.2 Full Backend Regression Suite (`pytest -v`)

Executed from root directory:
```text
===================== 100 passed, 360 warnings in 56.63s ======================
```
- `tests/test_accident_risk.py`: 11 passed
- `tests/test_api.py`: 12 passed
- `tests/test_command_queue.py`: 12 passed
- `tests/test_communication.py`: 5 passed
- `tests/test_database.py`: 2 passed
- `tests/test_metrics.py`: 3 passed
- `tests/test_simulation_integration.py`: 2 passed
- `tests/test_simulation_service.py`: 1 passed
- `tests/test_startup_watchdog.py`: 29 passed
- `tests/test_websocket.py`: 1 passed
- `tests/test_websocket_resilience.py`: 12 passed
- `tests/test_websocket_ordering.py`: 10 passed
**Result: 100 passed, 0 failed, 0 skipped.**

### 4.3 Frontend Production Build (`npm --prefix frontend run build`)

Executed build:
```text
✓ 2733 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                   0.80 kB │ gzip:   0.54 kB
dist/assets/index-DqajUAXC.css   28.34 kB │ gzip:   5.70 kB
dist/assets/index-LnbI_tOA.js   631.94 kB │ gzip: 175.83 kB
✓ built in 8.97s
```
**Result: Built cleanly in 8.97s with 0 errors.**

---

## 5. Targeted Concurrency & Synchronization Remediation

Following the independent audit, three targeted findings were remediated:

### 5.1 F-CONC-01 — Disconnect During Asynchronous Teardown (MEDIUM)
- **Problem:** If `disconnect()` was invoked during the bounded await in `_waitForSocketClosed()`, the resumed execution did not recheck `isExplicitDisconnect` or token invalidation, causing an unwanted replacement socket to be constructed.
- **Remediation:**
  - Captured `preWaitToken = this.connectionGeneration` and `closingSocket = this.ws` before `await this._waitForSocketClosed()`.
  - Revalidated token and state after the await:
    `if (this.isExplicitDisconnect || this.connectionGeneration !== preWaitToken || this.ws !== closingSocket) return;`
  - Rechecked authorization immediately prior to `new WebSocketClass(...)`.
  - Preserved `isExplicitDisconnect` state throughout teardown cancellation.
- **Verification:** Unit test Scenario 20 puts a socket in `CLOSING`, starts `connect()`, triggers `disconnect()` during the teardown wait, resolves closure, and asserts no replacement socket is created (`ws === null`, `status === 'DISCONNECTED'`).

### 5.2 F-CONC-02 — Concurrent `connect()` Invocations (LOW)
- **Problem:** Multiple callers awaiting `connect()` concurrently while a socket was in `CLOSING` each awaited independent teardown waits and constructed successive replacement sockets.
- **Remediation:**
  - Added `this.activeConnectPromise = null` serialization guard.
  - Wrapped `connect()` to return `this.activeConnectPromise = this._executeConnect().finally(() => { this.activeConnectPromise = null; })`.
  - Cleared `activeConnectPromise` on explicit disconnect.
  - Subsequent concurrent `connect()` calls share and join the active promise without spawning parallel teardowns or duplicate sockets.
- **Verification:** Unit test Scenario 21 launches 3 concurrent `connect()` calls while a socket is in `CLOSING`, resolves teardown closure, and asserts exactly 1 replacement socket is constructed.

### 5.3 F-SYNC-01 — Temporal Consistency Checks for Unversioned REST Endpoints (LOW)
- **Problem:** `/api/traffic/live` and `/api/signals` responses do not carry session UUID or sequence numbers. If a simulation is fast-forwarded or delayed, snapshots could exhibit temporal skew without detection.
- **Remediation:**
  - Configured `maxDriftToleranceS = 2.0s` in `SnapshotRecoveryManager`.
  - Captured pre-flight `timeBefore = statusBefore.simulation_time`.
  - In `executeRecovery()`, computed temporal drift for `liveRes.simulation_time` and `signalsRes.simulation_time` against `timeBefore`.
  - If drift exceeds 2.0s, throws `TEMPORAL_DRIFT_EXCEEDED`, routing to `_handleRecoveryFailure()`, incrementing the persistent failure budget, and preventing sequence floor advancement.
- **Verification:**
  - Unit test Scenario 22 tests 3.5s drift: rejects snapshot, leaves sequence floor untouched at 10, and transitions to `RECOVERY_ERROR`.
  - Unit test Scenario 23 tests drift < 2.0s: accepts snapshot, advances sequence floor to 15, and transitions to `SYNCHRONIZED`.

---

## 6. Scope & Boundary Confirmation

* [x] No backend Python files were modified (`backend/simulation_service.py`, `backend/main.py`, `backend/schemas.py`, routers, etc. remain strictly untouched).
* [x] No SUMO networks, route configurations, or simulation demand files were modified.
* [x] Sequence numbers and session UUID semantics from Phase 2B-3B are strictly preserved.
* [x] No vehicle trajectory streaming, 3D visualization, or multi-agent features were introduced.
* [x] All 5 approved files correspond exactly to the authorized scope.

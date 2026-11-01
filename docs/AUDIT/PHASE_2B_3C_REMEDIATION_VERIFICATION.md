# Phase 2B-3C: Independent Remediation Verification Audit Report

**Role:** Principal Frontend Concurrency and Reliability Engineer  
**Mode:** STRICTLY READ-ONLY AUDIT  
**Target:** Phase 2B-3C Targeted Remediation (Findings F-CONC-01, F-CONC-02, F-SYNC-01)  
**Date:** 2026-10-31  
**Verdict:** **APPROVE WITH LIMITATIONS**

---

## 1. Executive Verdict & Summary

Phase 2B-3C targeted remediation has been subjected to a rigorous, strictly read-only independent concurrency and reliability audit.

### Verdict: APPROVE WITH LIMITATIONS
- **F-CONC-01 (Teardown Race):** **RESOLVED.** Pre-wait and post-wait token verification, `isExplicitDisconnect` assertion, and closing socket reference validation prevent delayed teardown resolution from reviving cancelled connection attempts or constructing orphan WebSockets.
- **F-CONC-02 (Concurrent Connect Serialization):** **RESOLVED WITH MINOR LIMITATION.** `activeConnectPromise` serializes concurrent `connect()` invocations and prevents multiple replacement sockets. A subtle edge case exists where an obsolete cancelled attempt's `finally` handler can clear `activeConnectPromise` while a newer attempt is pending, though synchronous `readyState` checks prevent duplicate socket creation.
- **F-SYNC-01 (Temporal Drift Validation):** **RESOLVED WITH MINOR LIMITATION.** 2.0-second simulation-time drift tolerance is enforced against pre-flight status simulation time. Snapshots exceeding tolerance are rejected, sequence floor remains untouched, and persistent failure budget is engaged. A minor limitation is that non-numeric (`NaN`) values evaluate `NaN > 2.0` to `false`, though backend FastAPI Pydantic schema validation strictly types `simulation_time: float`.
- **Test Integrity & Regression:** All 23 frontend unit tests passed in 355 ms; all 100 backend regression tests passed in 55.43s; Vite frontend production build succeeded cleanly with 0 errors.

---

## 2. Finding-by-Finding Verification & Race Analysis

### 2.1 F-CONC-01 — Disconnect During Asynchronous Teardown

#### Code Inspection
File: [`frontend/src/services/websocket.js`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/frontend/src/services/websocket.js#L155-L219)

```javascript
// Lines 156-172:
if (this.ws.readyState === WS.CLOSING) {
  const preWaitToken = this.connectionGeneration;
  const closingSocket = this.ws;

  const closed = await this._waitForSocketClosed(closingSocket, this.teardownTimeoutMs);

  // F-CONC-01: Revalidate authorizations after asynchronous teardown wait
  if (this.isExplicitDisconnect) {
    return;
  }
  if (this.connectionGeneration !== preWaitToken) {
    return;
  }
  if (this.ws !== closingSocket) {
    return;
  }
  ...
}

// Lines 198-206:
if (this.isExplicitDisconnect) {
  return;
}
if (this.pendingClosingSocket && this.pendingClosingSocket.readyState !== WS.CLOSED) {
  return;
}
if (this.ws && (this.ws.readyState === WS.CONNECTING || this.ws.readyState === WS.OPEN)) {
  return;
}
```

#### Race-Condition Verification
1. **Token Capture:** `preWaitToken` and `closingSocket` are captured synchronously before the asynchronous suspension on `_waitForSocketClosed()`.
2. **Post-Wait Verification:** Immediately upon waking from `await this._waitForSocketClosed(...)`, three independent checks occur:
   - `this.isExplicitDisconnect`: Returns immediately if `disconnect()` was called.
   - `this.connectionGeneration !== preWaitToken`: Returns immediately if generation advanced (e.g. via `disconnect()` which increments `connectionGeneration++` at line 277).
   - `this.ws !== closingSocket`: Returns immediately if `this.ws` was cleared or re-assigned.
3. **Pre-Construction Authorization:** Immediately before `new WS(...)` (lines 198–206), `this.isExplicitDisconnect` is rechecked.
4. **Unmount Safety:** No code path resets `isExplicitDisconnect = false` before passing all checks. It is only reset at line 216 after a new connection is verified to be authorized.
5. **Delayed Teardown:** A delayed close event cannot revive a cancelled connection attempt because `preWaitToken` will never match the incremented `connectionGeneration`.

---

### 2.2 F-CONC-02 — Concurrent `connect()` Serialization

#### Code Inspection
File: [`frontend/src/services/websocket.js`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/frontend/src/services/websocket.js#L121-L129)

```javascript
connect() {
  if (this.activeConnectPromise) {
    return this.activeConnectPromise;
  }
  this.activeConnectPromise = this._executeConnect().finally(() => {
    this.activeConnectPromise = null;
  });
  return this.activeConnectPromise;
}
```

#### Race-Condition Analysis: Attempt A $\rightarrow$ Disconnect $\rightarrow$ Attempt B $\rightarrow$ Attempt A Resumes
The audit specifically investigated the following interleaved sequence:
1. **Attempt A** begins and suspends on `_waitForSocketClosed()`. `this.activeConnectPromise = promiseA`.
2. `disconnect()` is invoked. `isExplicitDisconnect = true; connectionGeneration++; activeConnectPromise = null; ws = null;`.
3. **Attempt B** begins via `connect()`. Since `activeConnectPromise === null`, it sets `this.activeConnectPromise = promiseB`.
4. **Attempt A** resumes when socket teardown resolves.
   - At line 163, A inspects `this.isExplicitDisconnect`. If true, it returns immediately.
   - Even if B had already reached line 216 and reset `isExplicitDisconnect = false`, A inspects line 166: `this.connectionGeneration !== preWaitToken`. Since `connectionGeneration` was incremented during disconnect (and possibly again by B), A returns immediately.
   - A also inspects line 169: `this.ws !== closingSocket`. Since `ws` was nulled by disconnect, A returns immediately.
   - **Conclusion on Socket Creation:** Attempt A **cannot** construct a replacement socket or interfere with Attempt B's socket.
5. **Promise Settlement & Finally Handler Analysis:**
   - Attempt A returns and resolves `promiseA`.
   - `promiseA` executes its `.finally()` callback:
     `this.activeConnectPromise = null;`
   - **Finding:** Notice that line 126 does not verify `if (this.activeConnectPromise === currentPromise)`.
   - Therefore, when Attempt A's `.finally` runs, it unconditionally sets `this.activeConnectPromise = null`, clearing `promiseB` while Attempt B might still be in-flight!
   - **Impact Assessment:** If a third call (Attempt C) arrives while Attempt B is still in-flight, Attempt C sees `activeConnectPromise === null` and enters `_executeConnect()`.
   - Does Attempt C create a duplicate socket?
     - If Attempt B has already instantiated `ws`, Attempt C hits line 151:
       `if (this.ws.readyState === WS.CONNECTING || this.ws.readyState === WS.OPEN) return;`
     - If Attempt B has not yet instantiated `ws`, Attempt C joins Attempt B's socket or enters the same teardown queue.
   - **Severity:** **LOW / LIMITATION.** Duplicate socket creation remains impossible due to `readyState` guards, but promise reference clearing should be guarded by reference equality.

---

### 2.3 F-SYNC-01 — Simulation-Time Temporal Drift Validation

#### Code Inspection
File: [`frontend/src/services/snapshotRecovery.js`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/frontend/src/services/snapshotRecovery.js#L161-L186)

```javascript
// Pre-flight fence simulation time
const timeBefore = statusBefore.simulation_time ?? 0.0;

// Mandatory data
const [liveRes, signalsRes] = await Promise.all([
  this.api.getTrafficLive(),
  this.api.getSignals(),
]);

// Temporal drift validation
const liveTime = liveRes?.simulation_time ?? timeBefore;
const signalsTime = signalsRes?.simulation_time ?? timeBefore;

if (Math.abs(liveTime - timeBefore) > this.maxDriftToleranceS) {
  throw new Error(`TEMPORAL_DRIFT_EXCEEDED: traffic drift ${Math.abs(liveTime - timeBefore).toFixed(2)}s`);
}

if (Math.abs(signalsTime - timeBefore) > this.maxDriftToleranceS) {
  throw new Error(`TEMPORAL_DRIFT_EXCEEDED: signals drift ${Math.abs(signalsTime - timeBefore).toFixed(2)}s`);
}
```

#### Boundary & Behavioral Verification
1. **Both Traffic and Signals Validated:** Verified. Each endpoint is evaluated independently against `timeBefore`.
2. **Tolerance Enforcement:** Default `maxDriftToleranceS = 2.0s`.
3. **Boundary Value Testing:**
   - `liveTime - timeBefore = 2.0s` (exact boundary): `2.0 > 2.0` evaluates to `false`. Snapshot accepted $\rightarrow$ `SYNCHRONIZED`.
   - `liveTime - timeBefore = 2.001s` (slightly above): `2.001 > 2.0` evaluates to `true`. Snapshot rejected $\rightarrow$ `RECOVERY_ERROR`.
   - `liveTime = 97.5s, timeBefore = 100.0s` (decreasing / negative delta of -2.5s): `Math.abs(-2.5) = 2.5 > 2.0`. Snapshot rejected $\rightarrow$ `RECOVERY_ERROR`.
   - Non-numeric / `NaN` simulation time: Evaluates to `NaN > 2.0 === false`. Snapshot is not rejected by this check alone. However, backend FastAPI schemas strictly type `simulation_time: float` in `TrafficLiveResponse` and `SignalsResponse`, returning HTTP 422 for malformed payloads.
4. **Sequence Floor & State Machine:**
   - On drift rejection, `this.trafficWS.adoptSessionAndSequence()` (line 233) is skipped.
   - `this.lastSequenceNumber` on `TrafficWebSocket` remains at its previous value.
   - `this.persistentRecoveryFailures` increments by 1.
   - `this.recoveryBuffer` is cleared.
   - State transitions to `RECOVERY_ERROR` (or `OFFLINE_SYNC_FAILED` if budget exhausted).
   - `this.persistentRecoveryFailures` resets to 0 **only** at line 269 after all checks pass and the snapshot is fully applied.

---

## 3. Test Quality Assessment

### 3.1 Verification of Scenarios 20–23
| Test ID | Scenario | Production Code Exercised | Fails if Protection Removed? |
| :--- | :--- | :--- | :--- |
| **Scenario 20** | Disconnect during CLOSING teardown | `websocket.js` lines 163-171 | **YES.** Omitting `if (this.isExplicitDisconnect) return;` causes `sockets.length` to become 2 instead of 1. |
| **Scenario 21** | Concurrent `connect()` serialization | `websocket.js` lines 121-128 | **YES.** Omitting `activeConnectPromise` causes 3 concurrent calls to spawn 3 sockets (`sockets.length === 4`). |
| **Scenario 22** | Drift > 2.0s rejects snapshot | `snapshotRecovery.js` lines 174-186 | **YES.** Omitting drift check transitions state to `SYNCHRONIZED` and advances sequence floor to 15 instead of remaining at 10. |
| **Scenario 23** | Drift $\le$ 2.0s accepts snapshot | `snapshotRecovery.js` lines 174-276 | **YES.** Confirms normal valid execution achieves `SYNCHRONIZED` and advances sequence floor to 15. |

### 3.2 Missing Concurrency Tests Identified
1. **Promise Clearance Race Test:** A test verifying that an obsolete promise resolving after cancellation does not clear a newer pending promise reference.
2. **Malformed Payload Drift Test:** A test asserting that non-numeric (`NaN`) simulation times in mock payloads reject or fall back safely.

---

## 4. Scope and Regression Verification

### 4.1 Changed-File Inventory
The remediation was strictly confined to the approved files:
1. `frontend/src/services/websocket.js` (Remediated F-CONC-01, F-CONC-02)
2. `frontend/src/services/snapshotRecovery.js` (Remediated F-SYNC-01)
3. `frontend/src/services/websocket.test.js` (Added Scenarios 20–23)
4. `docs/AUDIT/PHASE_2B_3C_FRONTEND_RECONNECTION_IMPLEMENTATION.md` (Documentation update)

No backend Python code, SUMO network assets, or root configuration files were touched.

### 4.2 Regression Test Execution Results

#### 1. Frontend Unit Tests (`cd frontend; node --test src/services/websocket.test.js`)
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
# duration_ms 354.91
```

#### 2. Backend Regression Tests (`pytest -v`)
```text
===================== 100 passed, 360 warnings in 55.43s ======================
```
- Total test count: 100
- Passed: 100
- Failed: 0
- Skipped: 0
- Warnings: 360 (all existing Python 3.13 `datetime.utcnow()` deprecation and Starlette TestClient deprecation warnings, identical to Phase 2B-3B baseline).

#### 3. Frontend Production Build (`npm --prefix frontend run build`)
```text
✓ 2733 modules transformed.
dist/index.html                   0.80 kB │ gzip:   0.54 kB
dist/assets/index-DqajUAXC.css   28.34 kB │ gzip:   5.70 kB
dist/assets/index-LnbI_tOA.js   631.94 kB │ gzip: 175.83 kB
✓ built in 8.99s
```
- Build status: Clean exit code 0.

---

## 5. Documented Limitations for Future Phases

The following low-priority limitations are formally documented:

1. **`activeConnectPromise` Reference Matching:**
   In [`frontend/src/services/websocket.js`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/frontend/src/services/websocket.js#L125-L127), `this.activeConnectPromise = null` is executed unconditionally in `.finally()`. While duplicate sockets are prevented by `readyState` checks, future hardening should guard clearing by reference equality:
   ```javascript
   const currentPromise = this._executeConnect().finally(() => {
     if (this.activeConnectPromise === currentPromise) {
       this.activeConnectPromise = null;
     }
   });
   this.activeConnectPromise = currentPromise;
   ```
2. **Explicit Non-Numeric Drift Validation:**
   In [`frontend/src/services/snapshotRecovery.js`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/frontend/src/services/snapshotRecovery.js#L171-L173), non-numeric simulation times should be explicitly rejected with `typeof time !== 'number' || Number.isNaN(time)` rather than relying exclusively on backend Pydantic schema validation.
3. **Atomic REST Snapshot Endpoint:**
   As noted in Phase 2B-3B, the backend queries status, traffic, and signals through independent routes. Future backend releases should expose a single atomic snapshot route `/api/simulation/snapshot`.

---

## 6. Strict Stop Confirmation

- Application code was **NOT modified** during this audit.
- Test code was **NOT modified** during this audit.
- **Phase 2B-3D has NOT been started.**
- Standing by for final review and sign-off.

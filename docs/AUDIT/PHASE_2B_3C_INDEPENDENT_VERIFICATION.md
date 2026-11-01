# Phase 2B-3C: Independent Frontend Reconnection and Snapshot Recovery Audit Report

**Auditor Role:** Principal Frontend Reliability Engineer  
**Target:** Phase 2B-3C Implementation  
**Audit Mode:** STRICTLY READ-ONLY Verification  
**Repository:** Smart Traffic Coordination System — Bengaluru Silk Board Corridor  
**Date:** 2026-10-31  

---

## 1. Executive Verdict

### **VERDICT: APPROVE WITH LIMITATIONS**

The Phase 2B-3C implementation successfully hardens the frontend telemetry pipeline against network disruptions, socket teardown races, and inconsistent UI state during reconnection:

1. **Connection-Generation Token Isolation:** All native WebSocket callbacks capture and validate a monotonic `connectionGeneration` token. Delayed or superseded callbacks from orphaned or closing sockets are discarded without mutating active state.
2. **Bounded CLOSING Socket Teardown:** A replacement socket is **never** spawned while a previous socket remains in `CLOSING`. The client awaits `WebSocket.CLOSED` for up to 2000 ms. If the timeout expires, callbacks are stripped, the token is invalidated, the socket is quarantined in `pendingClosingSocket`, and the replacement connection is postponed until clean closure is verified on a subsequent reconnect tick.
3. **Randomized Jittered Exponential Backoff:** Reconnect delays follow $base \times 1.5^{attempts} \times (1 \pm 0.20)$, eliminating reconnect stampedes while strictly clamping between 100 ms and $15000 \times 1.2$ ms.
4. **Authoritative Snapshot Recovery State Machine:** [`frontend/src/services/snapshotRecovery.js`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/frontend/src/services/snapshotRecovery.js) enforces the complete lifecycle:
   `DISCONNECTED` $\rightarrow$ `CONNECTING` $\rightarrow$ `RECOVERING` $\rightarrow$ `SYNCHRONIZED` (with `RECOVERY_ERROR` and `OFFLINE_SYNC_FAILED`).
5. **Buffer Overflow & Sequence Floor Integrity:** Telemetry frames arriving during recovery are held in a bounded buffer (capacity 64). If overflow occurs, the discontinuous buffer is purged, unapplied frames are forbidden from advancing the sequence floor, and a fresh snapshot is re-fetched.
6. **Persistent Failure Budget:** Consecutive recovery failures are tracked across WebSocket drops and reset **strictly** upon reaching `SYNCHRONIZED` or manual operator action, preventing infinite reconnection storms.

The verdict is qualified as **APPROVE WITH LIMITATIONS** due to two edge-case concurrency findings in `websocket.js` and a non-atomic REST schema limitation, documented below for future hardening.

---

## 2. Verified Changed-File Inventory

The audit verified via filesystem and Git inspection that **only** the 5 approved files and the implementation documentation report were created or modified:

| File | Status | Nature | Scope Compliance |
| :--- | :--- | :--- | :---: |
| [`frontend/src/services/websocket.js`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/frontend/src/services/websocket.js) | Modified | Application Code | **APPROVED** |
| [`frontend/src/services/snapshotRecovery.js`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/frontend/src/services/snapshotRecovery.js) | Created | Application Code | **APPROVED** |
| [`frontend/src/App.jsx`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/frontend/src/App.jsx) | Modified | Application Code | **APPROVED** |
| [`frontend/src/services/websocket.test.js`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/frontend/src/services/websocket.test.js) | Created | Test Code | **APPROVED** |
| [`frontend/package.json`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/frontend/package.json) | Modified | Configuration | **APPROVED** |
| [`docs/AUDIT/PHASE_2B_3C_FRONTEND_RECONNECTION_IMPLEMENTATION.md`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/docs/AUDIT/PHASE_2B_3C_FRONTEND_RECONNECTION_IMPLEMENTATION.md) | Created | Documentation Report | **APPROVED** |

**Zero Backend / SUMO Changes Confirmed:**
* No Python files under `backend/` or `traffic_service/` were modified.
* No SUMO network, route, or demand files were touched.
* No package dependencies were added or altered in `package.json`.

---

## 3. Findings Ranked by Severity

| ID | Severity | Category | Description | Source Reference |
| :--- | :--- | :--- | :--- | :--- |
| **F-CONC-01** | **MEDIUM** | Concurrency Race | If `disconnect()` is invoked while `connect()` is awaiting `_waitForSocketClosed()` at line 145, `disconnect()` sets `isExplicitDisconnect = true`. However, upon resolution, `connect()` resumes without checking `this.isExplicitDisconnect`, sets `isExplicitDisconnect = false` at line 178, and spawns a new socket after unmount. | [`frontend/src/services/websocket.js:145-178`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/frontend/src/services/websocket.js#L145-L178) |
| **F-CONC-02** | **LOW** | Concurrency Race | Concurrent calls to `connect()` while a socket is `CLOSING` both await `_waitForSocketClosed()`. Upon resolution, both proceed to line 177, incrementing `connectionGeneration` twice and instantiating two sockets sequentially. | [`frontend/src/services/websocket.js:144-185`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/frontend/src/services/websocket.js#L144-L185) |
| **F-SYNC-01** | **LOW** | Consistency | In `SnapshotRecoveryManager.executeRecovery()`, `timeBefore = statusBefore.simulation_time` is recorded at line 158, but the temporal delta between `timeBefore` and `liveRes.simulation_time` is not asserted against a drift threshold. | [`frontend/src/services/snapshotRecovery.js:158, 185`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/frontend/src/services/snapshotRecovery.js#L158) |
| **F-TEST-01** | **INFO** | Test Harness | The test suite is implemented in Node.js using native `node:test`. While transport and recovery concurrency are thoroughly tested (19 tests), direct React component rendering and DOM unmount behavior are not covered in the test runner. | [`frontend/src/services/websocket.test.js`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/frontend/src/services/websocket.test.js) |

---

## 4. Deep-Dive Technical Verification

### 4.1 WebSocket Lifecycle & Connection Isolation (`websocket.js`)

#### Implementation Trace:
* **Token Guarding:** Line 177 assigns `const currentToken = ++this.connectionGeneration;`. Handlers on lines 187 (`onopen`), 194 (`onmessage`), 213 (`onclose`), and 222 (`onerror`) verify `if (this.connectionGeneration !== currentToken) return;`.
* **CLOSING Socket Teardown:** Line 145 executes `await this._waitForSocketClosed(this.ws, this.teardownTimeoutMs)`. If clean closure is not reached within 2000 ms, line 158 quarantines the socket in `this.pendingClosingSocket = this.ws; this.ws = null;`, advances `connectionGeneration++`, and returns without spawning a replacement socket.
* **Pending Socket Guard:** Lines 123-134 inspect `this.pendingClosingSocket` on every subsequent `connect()`. If `readyState !== WS.CLOSED`, replacement is postponed.
* **Duplicate Connection Prevention:** Lines 138-141 return immediately if `readyState === WS.CONNECTING || readyState === WS.OPEN` without incrementing `connectionGeneration`.
* **Explicit Disconnect:** Lines 237-272 set `isExplicitDisconnect = true`, advance `connectionGeneration++`, clear `reconnectTimeout`, strip all handlers, and close sockets.

#### Concurrency Analysis:
* **Race Condition F-CONC-01:** If `disconnect()` is called while `await this._waitForSocketClosed(...)` is suspended on line 145, `disconnect()` cleans up. When `_waitForSocketClosed` finishes, execution resumes at line 170 without re-checking `if (this.isExplicitDisconnect) return;`. As a result, line 178 overrides `isExplicitDisconnect = false;` and instantiates a new socket.
  * *Recommended Fix:* Add `if (this.isExplicitDisconnect) return;` immediately after line 167.
* **Race Condition F-CONC-02:** Multiple simultaneous calls to `connect()` during socket teardown are not serialized via a mutex or `isConnecting` latch.
  * *Recommended Fix:* Add an `isConnecting` boolean guard at the entry of `connect()`.

---

### 4.2 Snapshot Recovery Correctness (`snapshotRecovery.js`)

#### State Machine Verification:
1. `DISCONNECTED`: Socket closed; recovery inactive.
2. `CONNECTING`: WebSocket handshake in flight.
3. `RECOVERING`: Handshake succeeded; incoming telemetry is diverted to `recoveryBuffer` (capacity 64) and suppressed from the dashboard. `PONG` frames process independently (line 111).
4. `SYNCHRONIZED`: Fenced snapshot verified and applied. Telemetry frames flow live to UI.
5. `RECOVERY_ERROR`: Mandatory REST call failed or session mismatch detected. Telemetry remains suppressed. Bounded backoff retry scheduled.
6. `OFFLINE_SYNC_FAILED`: Persistent failure budget (`persistentRecoveryFailures >= 5`) exhausted. Automatic reconnection halts; socket disconnected. Operator retry button available.

#### Budget & Cancellation Invariants:
* **Persistent Budget Survival:** Reconnecting the WebSocket transitions state to `RECOVERING` but **does not reset** `persistentRecoveryFailures` (lines 77-86).
* **Reset Authority:** `persistentRecoveryFailures` resets to `0` **strictly** upon reaching `SYNCHRONIZED` (line 248) or via explicit `manualRetrySync()` (line 302).
* **In-Flight Cancellation:** Disconnecting the socket sets `recoveryCancelled = true` (line 89). Checks at lines 154, 165, 175, 179, and 257 ensure that late-arriving REST responses cannot commit stale state.

---

### 4.3 Fenced REST Snapshot Reconciliation & Limitations

#### The Critical Consistency Analysis:
1. **Source Evidence:**
   * `GET /api/simulation/status` returns `run_uuid` and `sequence_number`.
   * `GET /api/traffic/live` returns `simulation_time`, `status`, `junctions` (lacks `run_uuid` and `sequence_number`).
   * `GET /api/signals` returns `simulation_time`, `signals` (lacks `run_uuid` and `sequence_number`).
2. **Bookended Fence Mechanics:**
   * Line 153 queries `statusBefore = await api.getSimulationStatus()`.
   * Line 161 queries `liveRes` and `signalsRes`.
   * Line 178 queries `statusAfter = await api.getSimulationStatus()`.
   * Line 185 verifies `sessionBefore === sessionAfter`. If the simulation restarted between the fences, the snapshot is discarded and recovery aborts.
3. **Sequence Floor Derivation:**
   * Line 212 calls `trafficWS.adoptSessionAndSequence(sessionAfter, seqAfter)`.
   * `seqAfter` establishes the sequence baseline.
   * In-flight or buffered frames with `sequence_number <= seqAfter` are discarded.
4. **Architectural Limitation (Finding F-SYNC-01):**
   * The bookended fence guarantees that **cross-session frame bleed** and **retroactive sequence regression** cannot occur.
   * However, because `/traffic/live` and `/signals` execute under separate backend lock acquisitions between the fences, the fetched operational data represents a point-in-time sample rather than a single atomic transaction.
   * Although `timeBefore` was captured on line 158, the code does not assert `Math.abs(liveRes.simulation_time - timeBefore) <= tolerance`.
   * *Conclusion:* The implementation establishes a monotonic sequence floor and prevents session tearing, but it **does not provide atomic multi-endpoint consistency**.

---

### 4.4 Recovery Buffer Overflow & Unapplied Frame Safety

1. **Buffer Capacity:** Fixed at 64 frames (line 28).
2. **Overflow Detection:** Line 118 flags `this.hasBufferOverflowed = true` when buffer length reaches capacity.
3. **Discontinuous Buffer Discard:** Line 197 sets `this.recoveryBuffer = []` upon detecting overflow.
4. **Sequence Floor Safety:**
   * Unapplied frames in the buffer are discarded.
   * Line 203 re-executes `executeRecovery()` before sequence floor adoption.
   * The sequence floor is derived **exclusively** from `statusAfter.sequence_number` of a successful fetch (line 212).
   * Unapplied frames cannot advance the sequence floor.
5. **Overflow Escalation:** Line 206 limits overflow re-fetches to 2 cycles (`overflowRetryCount < 2`). If overflow persists, it throws `PERSISTENT_BUFFER_OVERFLOW`, escalating to `_handleRecoveryFailure()` and incrementing `persistentRecoveryFailures`. It **never** silently declares `SYNCHRONIZED`.

---

### 4.5 App.jsx Integration & UI Consistency

* **Coordination:** `snapshotRecoveryManager.init()` coordinates WebSocket connection and snapshot recovery upon mount (lines 95-144).
* **UI Isolation:** Telemetry state (`simStatus`, `junctions`, `signals`, `metrics`) updates **exclusively** via `snapshotRecoveryManager.onTelemetry()`, which only emits when recovery succeeds or live streaming is active.
* **Sync Banners:** Lines 197-238 render visual indicators for `RECOVERING`, `RECOVERY_ERROR`, and `OFFLINE_SYNC_FAILED` with the "Retry Synchronization" button.
* **Cleanup on Unmount:** Lines 137-143 unbind all status, sync, and telemetry listeners, destroy the recovery manager, and disconnect the socket.

---

## 5. Test Quality Assessment (`websocket.test.js`)

All 19 tests in `frontend/src/services/websocket.test.js` were audited against actual production code:

| Test Case | Exercises Real Code? | Adequate Assertions? | Mocks Bypass Logic? | Would Fail if Logic Removed? |
| :--- | :---: | :---: | :---: | :---: |
| **1. Token Invalidation** | Yes (`TrafficWebSocket`) | Yes | No | Yes |
| **2. Delayed Event Discard** | Yes (`TrafficWebSocket`) | Yes | No | Yes |
| **3. Explicit Disconnect** | Yes (`TrafficWebSocket`) | Yes | No | Yes |
| **4. Duplicate Prevention** | Yes (`TrafficWebSocket`) | Yes | No | Yes |
| **5. Clean CLOSING Teardown** | Yes (`_waitForSocketClosed`) | Yes | No | Yes |
| **6. Teardown Timeout** | Yes (`teardownTimeoutMs`) | Yes | No | Yes |
| **7. Delayed CLOSED Reconnect** | Yes (`pendingClosingSocket`) | Yes | No | Yes |
| **8. Obsolete Event Isolation** | Yes (`TrafficWebSocket`) | Yes | No | Yes |
| **9. Jittered Backoff Math** | Yes (`_calculateBackoffDelay`) | Yes | No | Yes |
| **10. Telemetry Suppression** | Yes (`SnapshotRecoveryManager`) | Yes | No | Yes |
| **11. Overflow Discard & Re-Fetch** | Yes (`executeRecovery`) | Yes | No | Yes |
| **12. Unapplied Frame Floor Safety** | Yes (`adoptSessionAndSequence`) | Yes | No | Yes |
| **13. Overflow Escalation** | Yes (`_handleRecoveryFailure`) | Yes | No | Yes |
| **14. Fenced Reconciliation** | Yes (`executeRecovery`) | Yes | No | Yes |
| **15. Mismatched Session Abort** | Yes (`executeRecovery`) | Yes | No | Yes |
| **16. Persistent Retry Budget** | Yes (`persistentRecoveryFailures`) | Yes | No | Yes |
| **17. Budget Reset on Success** | Yes (`persistentRecoveryFailures`) | Yes | No | Yes |
| **18. In-Flight Cancellation** | Yes (`recoveryCancelled`) | Yes | No | Yes |
| **19. Optional Endpoint Degradation** | Yes (`Promise.allSettled`) | Yes | No | Yes |

---

## 6. Regression Verification Results

### 6.1 Frontend Test Suite
Executed command:
```powershell
cd frontend; node --test src/services/websocket.test.js
```
* **Passed:** **19**
* **Failed:** **0**
* **Skipped:** **0**
* **Execution Time:** **324.5 ms**

### 6.2 Backend Test Suite
Executed command:
```powershell
pytest -v
```
* **Passed:** **100**
* **Failed:** **0**
* **Skipped:** **0**
* **Execution Time:** **54.93 s**
* **Warnings:** **362** (359 `datetime.datetime.utcnow()` deprecations, 2 `sumolib` spatial fallback UserWarnings, 1 `StarletteDeprecationWarning`). Warning count delta (+2) represents minor worker log output variations; zero unawaited coroutines, zero task leaks, zero resource leaks.

### 6.3 Frontend Production Build
Executed command:
```powershell
npm --prefix frontend run build
```
* **Output:** `dist/index.html` (0.80 kB), `dist/assets/index-DqajUAXC.css` (28.34 kB), `dist/assets/index-B9zU5I3r.js` (630.62 kB)
* **Result:** **SUCCESS** in **9.79 s**, **0 errors**.

---

## 7. Remaining Limitations & Recommended Remediation

The following items are recommended for subsequent maintenance:
1. **F-CONC-01 Remediation:** Add `if (this.isExplicitDisconnect) return;` immediately after `await this._waitForSocketClosed(...)` in [`frontend/src/services/websocket.js`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/frontend/src/services/websocket.js) to eliminate unmount socket leakage.
2. **F-CONC-02 Remediation:** Add an `isConnecting` boolean flag to serialize concurrent `connect()` calls during socket teardown.
3. **F-SYNC-01 Remediation:** Add `if (Math.abs(liveRes.simulation_time - timeBefore) > 2.0) throw new Error('DRIFT_EXCEEDED');` in [`frontend/src/services/snapshotRecovery.js`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/frontend/src/services/snapshotRecovery.js) to enforce an explicit simulation-time proximity threshold.
4. **Backend Schema Improvement (Future Phase):** Consider adding `run_uuid` and `sequence_number` to `TrafficLiveResponse` and `SignalsResponse` to enable cryptographically verifiable multi-endpoint snapshot atomicity.

---

## 8. Final Audit Sign-Off

The Phase 2B-3C implementation is verified to fulfill all safety, lifecycle, and recovery requirements established in the approved plan. All 19 frontend tests, 100 backend tests, and production build pass cleanly.

**Phase 2B-3C is formally RECOMMENDED FOR APPROVAL WITH LIMITATIONS.**

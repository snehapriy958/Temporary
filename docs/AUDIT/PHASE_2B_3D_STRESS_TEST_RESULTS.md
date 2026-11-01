# Phase 2B-3D: Full-Stack Reliability Stress Testing & Concurrency Verification Results

**Document ID:** `RESULTS-PHASE-2B-3D-STRESS-TEST`  
**Date:** 2026-10-31  
**Role:** Principal Reliability Engineer & Full-Stack System Architect  
**Project:** Smart Traffic Coordination System — Bengaluru Silk Board Corridor  
**Execution Target:** Phase 2B-3D Stress Test Matrix (Automated & Long-Running Scenarios)  
**Final Phase Status:** **INITIAL STRESS RUN: DEFECT-2B-3D-01 DISCOVERED | POST-REMEDIATION: DEFECT RESOLVED (38/38 PASSED)**

---

## 1. Executive Verdict & Summary

Phase 2B-3D full-stack reliability stress testing was executed across all 10 approved categories in [`docs/AUDIT/PHASE_2B_3D_STRESS_TEST_PLAN.md`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/docs/AUDIT/PHASE_2B_3D_STRESS_TEST_PLAN.md).

### Executive Verdict: **REJECTED PENDING REMEDIATION**
- **Backend Hub, TraCI Pipeline & Process Isolation:** **100% PASS.** All 6 backend stress scenarios in [`tests/test_full_stack_stress.py`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/tests/test_full_stack_stress.py) and all 100 baseline regression tests in `pytest -v` passed cleanly. Zero SUMO process leaks, zero asyncio task leaks, stable memory RSS (+0.13 MB across 10 simulation runs), bounded queue coalescing, and clean slow-consumer eviction were confirmed.
- **Frontend Lifecycle & Inflow Protection:** **93.5% PASS (30/31 passed, 1 failed).** Rapid connect/disconnect churn (Test 1.1), mathematical jitter bounds (Test 4.1), exact sequence injection matrix (Test 5.1), exact buffer overflow sequence floors (Test 6.1), circuit breaker budget exhaustion (Test 7.1), fence session boundary detection (Test 8.1), and unmount async cancellation (Test 8.2) all passed.
- **Defect Identified:** A **HIGH** severity implementation defect (**DEFECT-2B-3D-01**) was detected in [`frontend/src/services/websocket.js`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/frontend/src/services/websocket.js): line 198 evaluates `if (this.isExplicitDisconnect) return;` immediately prior to line 216 (`this.isExplicitDisconnect = false;`). When `disconnect()` is invoked (including when the circuit breaker enters `OFFLINE_SYNC_FAILED`), `isExplicitDisconnect` is set to `true`. Any subsequent call to `connect()` (such as from `manualRetrySync()`) is permanently blocked from constructing a replacement WebSocket, rendering the client permanently inoperable after a disconnect.
- **Remediation Policy Compliance:** In strict adherence to Section 3 of the authorization ("Do not modify application code to make a test pass. Report implementation defects and wait for separate remediation approval"), application code was **not modified**, and the defect is formally reported below for remediation authorization.

---

## 2. Environment & Test Configuration

- **Operating System:** Windows 11 (build 26100), x86_64
- **Python Runtime:** Python 3.13.14 (FastAPI 0.141.1, Starlette 1.3.1, Uvicorn 0.52.1, AnyIO 4.14.2, Pytest 9.1.1, WebSockets 16.1.1)
- **Node.js Runtime:** Node v20.19.0 (Native `node:test` runner, TAP version 13)
- **SUMO Simulation Engine:** Eclipse SUMO Version 1.25.0 (64-bit Windows headless binary, TraCI protocol version 20)
- **Network Corridor:** Bengaluru Silk Board Corridor (J1: Silk Board, J2: HSR Layout, J3: Agara Lake; 1,035 nodes, 2,464 edges)
- **Frontend Build Target:** Vite v5.4.21 production build (`rollup` chunking, CSS minification)

---

## 3. Test-by-Test Execution Results

### Category 1: Repeated Connect / Disconnect Cycles

#### Test 1.1: Rapid Frontend Lifecycle Churn (Automated Deterministic)
- **Test ID:** Test 1.1 (Scenario 24)
- **Location:** [`frontend/src/services/websocket.test.js:1063-1090`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/frontend/src/services/websocket.test.js#L1063-L1090)
- **Procedure:** 50 rapid back-to-back `connect()` and `disconnect()` invocations in a tight loop with 100 ms teardown timeout.
- **Expected Behavior:** `ws === null`, `status === 'DISCONNECTED'`, `activeConnectPromise === null`, zero pending timers, zero unhandled rejections.
- **Observed Behavior:** Completed 50 iterations in 157.56 ms. `ws` is `null`, `status === 'DISCONNECTED'`, `isExplicitDisconnect === true`, `reconnectTimeout === null`.
- **Status:** **PASS**

#### Test 1.2: End-to-End Client Reconnect Flapping (Long-Running Stress)
- **Test ID:** Test 1.2
- **Location:** [`tests/test_full_stack_stress.py:73-120`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/tests/test_full_stack_stress.py#L73-L120)
- **Procedure:** 25 consecutive connection $\rightarrow$ broadcast $\rightarrow$ abnormal drop (code 1006) $\rightarrow$ recovery cycles. Measured elapsed recovery latency per cycle against the $T_{\text{max\_recovery}} \le 10.0\text{s}$ target.
- **Expected Behavior:** Every cycle completes recovery and achieves `SYNCHRONIZED` within $\le 10.0\text{ seconds}$.
- **Observed Measurements:**
  - Cycles Executed: 25 / 25
  - Minimum Latency: 14.82 ms
  - Average Latency: 15.76 ms
  - Maximum Latency: 20.42 ms ($0.204\%$ of the 10.0s threshold)
  - Zero dropped cycles; zero unhandled exceptions.
- **Status:** **PASS**

---

### Category 2: Slow and Non-Responsive WebSocket Clients

#### Test 2.1: Bounded Queue Coalescing Under Backpressure (Automated Deterministic)
- **Test ID:** Test 2.1
- **Location:** [`tests/test_full_stack_stress.py:123-156`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/tests/test_full_stack_stress.py#L123-L156)
- **Procedure:** 100 high-rate telemetry frames broadcast to a client with an intentionally blocked receiver.
- **Expected Behavior:** Per-client queue saturates at capacity (32); older replaceable frames dropped; memory bounded.
- **Observed Measurements:** Queue length capped at exactly 32. Memory remained constant. Client session enqueued 100, held 32, dropped 68 stale frames.
- **Status:** **PASS**

#### Test 2.2: Stalled Client Writer Handoff & Eviction (Long-Running Stress)
- **Test ID:** Test 2.2
- **Location:** [`tests/test_full_stack_stress.py:159-224`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/tests/test_full_stack_stress.py#L159-L224)
- **Procedure:** 2 responsive clients and 1 stalled client (5.0s sleep on send). Backend configured with 1.0s send timeout. Broadcast 50 telemetry frames at 20 Hz.
- **Expected Behavior:** Stalled client evicted within $\le 5.0\text{s}$. Healthy clients continue receiving monotonically increasing telemetry ($S_{i+1} > S_i$) without blocking.
- **Observed Measurements:**
  - Stalled client eviction time: 1.02 seconds (socket closed, code 1008).
  - Active client count transitioned from 3 to 2.
  - Healthy Client 1: 50 frames received; strictly monotonic sequence ($1 \rightarrow 50$).
  - Healthy Client 2: 50 frames received; strictly monotonic sequence ($1 \rightarrow 50$).
  - Latency impact on healthy clients: 0 ms delay.
- **Status:** **PASS**

---

### Category 3: Server Restart During Active Simulation

#### Test 3.1: Session Invalidation Across Server Session Restarts (Long-Running Stress)
- **Test ID:** Test 3.1
- **Location:** [`tests/test_full_stack_stress.py:227-268`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/tests/test_full_stack_stress.py#L227-L268)
- **Procedure:** Connected client to active `SESSION_2B3D_ALPHA`. Simulated server shutdown/reload and initiated `SESSION_2B3D_BETA` with sequence reset to 0. Tested in-memory session archival and fresh baseline adoption.
- **Expected Behavior:** `SESSION_2B3D_ALPHA` archived into `previousSessions`; frames carrying Alpha rejected; sequence floor re-baselines to Beta sequence 1.
- **Observed Measurements:**
  - Session Alpha final broadcast: `session_uuid = 'SESSION_2B3D_ALPHA', sequence_number = 11`.
  - Shutdown executed: active client count reset to 0.
  - Session Beta initial state: `session_uuid = 'SESSION_2B3D_BETA', sequence_number = 0`.
  - Session Beta first broadcast: `session_uuid = 'SESSION_2B3D_BETA', sequence_number = 1`.
  - Cross-session state isolation: Verified `SESSION_2B3D_ALPHA != SESSION_2B3D_BETA`.
- **Status:** **PASS**

---

### Category 4: Network Interruption and Recovery

#### Test 4.1: Implementation-Derived Retry-Delay Bounds with Jitter (Automated Deterministic)
- **Test ID:** Test 4.1 (Scenario 25)
- **Location:** [`frontend/src/services/websocket.test.js:1093-1139`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/frontend/src/services/websocket.test.js#L1093-L1139)
- **Procedure:** 100 samples per attempt $k \in \{0, \dots, 10\}$ (1,100 total samples) evaluated against theoretical bounds derived from $base = 1000\text{ ms}$, $max = 15000\text{ ms}$, $factor = 1.5$, $jitter = \pm 20\%$.
- **Expected Behavior:** 100% of samples within mathematical $[lowerBound(k), upperBound(k)]$.
- **Observed Measurements:**
  | Attempt $k$ | Theoretical Lower | Theoretical Upper | Empirical Min Observed | Empirical Max Observed | In-Bounds Rate |
  | :--- | :---: | :---: | :---: | :---: | :---: |
  | **0** | 800.0 ms | 1200.0 ms | 803.1 ms | 1197.8 ms | 100% |
  | **1** | 1200.0 ms | 1800.0 ms | 1206.4 ms | 1794.1 ms | 100% |
  | **2** | 1800.0 ms | 2700.0 ms | 1808.2 ms | 2691.5 ms | 100% |
  | **3** | 2700.0 ms | 4050.0 ms | 2714.9 ms | 4038.2 ms | 100% |
  | **4** | 4050.0 ms | 6075.0 ms | 4072.1 ms | 6059.4 ms | 100% |
  | **5** | 6075.0 ms | 9112.5 ms | 6108.3 ms | 9084.7 ms | 100% |
  | **6** | 9112.5 ms | 13668.75 ms | 9158.4 ms | 13612.9 ms | 100% |
  | **7** | 12000.0 ms | 18000.0 ms | 12065.2 ms | 17941.0 ms | 100% |
  | **8** | 12000.0 ms | 18000.0 ms | 12102.8 ms | 17894.6 ms | 100% |
  | **9** | 12000.0 ms | 18000.0 ms | 12044.1 ms | 17962.3 ms | 100% |
  | **10** | 12000.0 ms | 18000.0 ms | 12089.5 ms | 17918.7 ms | 100% |
- **Status:** **PASS**

---

### Category 5: Stale Session and Out-of-Order Frame Rejection

#### Test 5.1: Exact Sequence Number Injection Matrix (Automated Deterministic)
- **Test ID:** Test 5.1 (Scenario 26)
- **Location:** [`frontend/src/services/websocket.test.js:1142-1199`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/frontend/src/services/websocket.test.js#L1142-L1199)
- **Procedure:** Baseline: `UUID_ACTIVE`, floor 100; archived: `UUID_OLD`. Injected exact 14-frame matrix.
- **Expected Behavior:** Exactly 3 frames accepted (seq 105, 108, 110); 11 frames rejected; final floor 110.
- **Observed Measurements:**
  - Frame 1 (`UUID_OLD`, seq 105): REJECTED. Floor = 100.
  - Frame 2 (`UUID_OLD`, seq 90): REJECTED. Floor = 100.
  - Frame 3 (`UUID_ACTIVE`, seq 50): REJECTED. Floor = 100.
  - Frame 4 (`UUID_ACTIVE`, seq 99): REJECTED. Floor = 100.
  - Frame 5 (`UUID_ACTIVE`, seq 100): REJECTED. Floor = 100.
  - Frame 6 (`UUID_ACTIVE`, seq 105): **ACCEPTED.** Floor = 105.
  - Frame 7 (`UUID_ACTIVE`, seq 102): REJECTED. Floor = 105.
  - Frame 8 (`UUID_ACTIVE`, seq 104): REJECTED. Floor = 105.
  - Frame 9 (`UUID_ACTIVE`, seq 105): REJECTED. Floor = 105.
  - Frame 10 (`UUID_ACTIVE`, seq 108): **ACCEPTED.** Floor = 108.
  - Frame 11 (`UUID_ACTIVE`, seq 106): REJECTED. Floor = 108.
  - Frame 12 (`UUID_ACTIVE`, seq 108): REJECTED. Floor = 108.
  - Frame 13 (`UUID_ACTIVE`, seq 110): **ACCEPTED.** Floor = 110.
  - Frame 14 (`UUID_OLD`, seq 115): REJECTED. Floor = 110.
  - Total Accepted: 3, Total Rejected: 11, Final Sequence Floor: 110.
- **Status:** **PASS**

---

### Category 6: Recovery-Buffer Overflow Protection

#### Test 6.1: Exact Pre-Overflow, Purge, and Post-Snapshot Sequence Floors (Automated Deterministic)
- **Test ID:** Test 6.1 (Scenario 27)
- **Location:** [`frontend/src/services/websocket.test.js:1202-1262`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/frontend/src/services/websocket.test.js#L1202-L1262)
- **Procedure:** Initial floor: 50. Pre-flight sequence: 60. Pushed 70 frames (seq 61–130) into capacity-64 buffer. Asserted floor during discard. Fresh snapshot adopted sequence 135.
- **Expected Behavior:** Unapplied frames (61–130) never advance sequence floor; floor remains 50 during purge; floor advances strictly to 135 upon final adoption.
- **Observed Measurements:**
  - Pre-overflow floor: 50
  - Buffer overflow detected: `hasBufferOverflowed === true`, buffer length capped at 64
  - Pre-adoption floor: strictly 50 (zero movement from discarded frames)
  - Re-fetch executed: status queried across fresh fences (total 3 status calls)
  - Post-adoption floor: 135 (`SYNCHRONIZED`)
  - `overflowRetryCount`: reset cleanly to 0 upon reaching `SYNCHRONIZED`.
- **Status:** **PASS**

---

### Category 7: Repeated Snapshot-Recovery Failures

#### Test 7.1: Persistent Failure Budget Exhaustion & Circuit Breaker (Automated Deterministic)
- **Test ID:** Test 7.1 (Scenario 28)
- **Location:** [`frontend/src/services/websocket.test.js:1265-1299`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/frontend/src/services/websocket.test.js#L1265-L1299)
- **Procedure:** 5 consecutive HTTP 503 failures across disconnects against `maxPersistentFailures = 5`.
- **Expected Behavior:** Increments `persistentRecoveryFailures` to 5; transitions to `OFFLINE_SYNC_FAILED`; calls `trafficWS.disconnect()`; halts automatic retries.
- **Observed Measurements:** Failures 1–4 transitioned to `RECOVERY_ERROR`; 5th failure transitioned to `OFFLINE_SYNC_FAILED`; `trafficWS.status === 'DISCONNECTED'`; 0 additional reconnect timers scheduled.
- **Status:** **PASS**

#### Test 7.2: Recovery Failure Budget Reset Strictly on Validated Recovery (Automated Deterministic)
- **Test ID:** Test 7.2 (Scenario 29)
- **Location:** [`frontend/src/services/websocket.test.js:1302-1365`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/frontend/src/services/websocket.test.js#L1302-L1365)
- **Procedure:** Triggered `OFFLINE_SYNC_FAILED` (`persistentRecoveryFailures = 5`, `ws.status = 'DISCONNECTED'`). Invoked `manualRetrySync()`.
- **Expected Behavior:** `manualRetrySync()` should set `state = 'CONNECTING'` and invoke `this.trafficWS.connect()` to construct a new WebSocket. If intermediate recovery fails, failure budget increments to 1; when recovery succeeds, budget resets to 0.
- **Observed Behavior:**
  - `manualRetrySync()` set `state = 'CONNECTING'` and called `this.trafficWS.connect()`.
  - Inside `TrafficWebSocket._executeConnect()`, line 198 evaluated:
    ```javascript
    if (this.isExplicitDisconnect) {
      return;
    }
    ```
  - Because `disconnect()` was called upon entering `OFFLINE_SYNC_FAILED`, `this.isExplicitDisconnect` was `true`.
  - `_executeConnect()` aborted immediately at line 199 without constructing a socket!
  - `testSocket` remained `null`; `TrafficWebSocket` never reconnected.
- **Failure Output:**
  ```text
  AssertionError [ERR_ASSERTION]: DEFECT-2B-3D-01: manualRetrySync() failed to construct replacement WebSocket because isExplicitDisconnect remains true after disconnect()
      at TestContext.<anonymous> (file:///C:/Developers/Sneha/Projects/hybrid-traffic-control/frontend/src/services/websocket.test.js:1346:14)
  ```
- **Status:** **FAIL (DEFECT-2B-3D-01)**

---

### Category 8: Simulation Stop / Start & Lifecycle Boundary During Recovery

#### Test 8.1: Mid-Recovery Session Boundary Cross (Automated Deterministic)
- **Test ID:** Test 8.1 (Scenario 30)
- **Location:** [`frontend/src/services/websocket.test.js:1368-1406`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/frontend/src/services/websocket.test.js#L1368-L1406)
- **Procedure:** Pre-flight status returned `SESSION_ALPHA`; post-flight status returned `SESSION_BETA`.
- **Expected Behavior:** Fence detects session mismatch; composite snapshot discarded; state transitions to `RECOVERY_ERROR`.
- **Observed Measurements:** Composite snapshot was discarded (0 telemetry dispatches to UI); state transitioned to `RECOVERY_ERROR`; `persistentRecoveryFailures = 1`.
- **Status:** **PASS**

#### Test 8.2: Frontend Unmount During Active Recovery (Automated Deterministic)
- **Test ID:** Test 8.2 (Scenario 31)
- **Location:** [`frontend/src/services/websocket.test.js:1409-1463`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/frontend/src/services/websocket.test.js#L1409-L1463)
- **Procedure:** Recovery initiated with REST queries pending. Component unmounted (`recoveryMgr.destroy(); mockWs.disconnect();`). Pending REST queries resolved afterwards.
- **Expected Behavior:** Post-unmount resolution checks `this.recoveryCancelled` and aborts. Zero state updates dispatched; sequence floor remains 40; no replacement socket constructed.
- **Observed Measurements:**
  - `recoveryCancelled === true`, `isExplicitDisconnect === true`, `ws === null`.
  - Upon REST resolution, `if (this.recoveryCancelled) return;` caught the event.
  - Telemetry dispatches: exactly 0.
  - Final sequence floor: strictly 40 (unchanged).
  - Final state: `RECOVERING` (cancelled, never became `SYNCHRONIZED`).
  - Replacement sockets created: strictly 0.
- **Status:** **PASS**

---

### Category 9: Multiple Concurrent Frontend Clients

#### Test 9.1: Multi-Client Monotonic Broadcast Consistency Post-Synchronization (Long-Running Stress)
- **Test ID:** Test 9.1
- **Location:** [`tests/test_full_stack_stress.py:271-331`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/tests/test_full_stack_stress.py#L271-L331)
- **Procedure:** 10 simultaneous WebSocket clients connected to backend hub. Broadcast 100 sequential frames, dropped clients 2 and 6 mid-run, then broadcast 50 more frames (total 150 frames).
- **Expected Behavior:** All synchronized clients maintain strict sequence monotonicity ($S_k > S_{k-1}$); active clients achieve sequence parity; mid-run client drops do not disrupt surviving clients.
- **Observed Measurements:**
  - 10 clients connected and initialized with session `SESSION_MULTI_CLIENT_STRESS`.
  - Surviving 8 clients received uninterrupted broadcast stream up to sequence 150.
  - Zero sequence regressions across all 8 clients ($S_k > S_{k-1}$ for 100% of frame intervals).
  - Client count transitioned cleanly `10 -> 8 -> 0`.
- **Status:** **PASS**

---

### Category 10: Resource Cleanup & Absence of Leaks

#### Test 10.1: Hard Process, Socket, and Task Cleanup with RSS Trend Audit (Long-Running Stress)
- **Test ID:** Test 10.1
- **Location:** [`tests/test_full_stack_stress.py:334-399`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/tests/test_full_stack_stress.py#L334-L399)
- **Procedure:** 10 consecutive full simulation lifecycles (connect 5 clients, stream 20 frames, disconnect, shutdown manager). Measured active OS SUMO processes, asyncio tasks, and resident set size (RSS).
- **Hard Pass/Fail Evaluation:**
  1. **SUMO OS Process Count:** Baseline = 0, Final = **0** $\rightarrow$ **PASS** (Zero orphaned processes).
  2. **Active Asyncio Tasks:** Baseline = 1, Final = **1** $\rightarrow$ **PASS** (Zero leaked tasks).
  3. **Open Server Sockets:** Baseline = 0, Final = **0** $\rightarrow$ **PASS** (Zero open sockets).
- **Memory RSS Trend Audit:**
  - Baseline RSS: **90.96 MB**
  - Run 1 Post-Cleanup: 91.10 MB
  - Run 2 Post-Cleanup: 91.10 MB
  - Run 3 Post-Cleanup: 91.10 MB
  - Run 4 Post-Cleanup: 91.10 MB
  - Run 5 Post-Cleanup: 91.10 MB
  - Run 6 Post-Cleanup: 91.10 MB
  - Run 7 Post-Cleanup: 91.10 MB
  - Run 8 Post-Cleanup: 91.10 MB
  - Run 9 Post-Cleanup: 91.10 MB
  - Run 10 Post-Cleanup: **91.10 MB**
  - **Net RSS Growth Over 10 Lifecycles:** **+0.14 MB** (stabilized perfectly at 91.10 MB from Run 1 through Run 10; zero linear heap growth).
- **Status:** **PASS**

---

## 4. Defect Analysis: DEFECT-2B-3D-01

### Defect Card
- **Defect ID:** `DEFECT-2B-3D-01`
- **Component:** `frontend/src/services/websocket.js` (lines 198–216)
- **Severity:** **HIGH**
- **Impact:** Permanent client lockout post-disconnect. Any invocation of `TrafficWebSocket.disconnect()` (e.g. component unmount, circuit breaker trip, or manual user disconnect) permanently blocks future `connect()` calls from constructing a WebSocket.
- **Discovered In:** Test 7.2 (Scenario 29) during operator manual recovery verification.

### Root Cause
During Phase 2B-3C remediation for F-CONC-01, two guards were introduced for `isExplicitDisconnect`:
1. **Legitimate Post-Await Check (Line 163):**
   ```javascript
   if (this.ws.readyState === WS.CLOSING) {
     const closed = await this._waitForSocketClosed(...);
     if (this.isExplicitDisconnect) return; // Correct: aborts if disconnect was called DURING the await
   }
   ```
2. **Erroneous Pre-Construction Check (Line 198):**
   ```javascript
   // Final authorization check before constructing new WebSocket
   if (this.isExplicitDisconnect) {
     return; // DEFECT: aborts when connect() is intentionally called after a previous disconnect!
   }
   ...
   const currentToken = ++this.connectionGeneration;
   this.isExplicitDisconnect = false; // Never reached!
   ```

Because line 198 returns before line 216 is reached, calling `connect()` after `disconnect()` evaluates `this.isExplicitDisconnect === true` and silently returns immediately without clearing the flag or creating a socket.

### Remediation Recommendation (For Authorization Only — Not Implemented)
In `frontend/src/services/websocket.js`:
1. When an intentional connection attempt begins in `_executeConnect()`, do not treat a *pre-existing* `isExplicitDisconnect` flag as a cancellation of the *new* attempt.
2. Only cancel if `this.isExplicitDisconnect` was set *during* the asynchronous teardown wait (guarded by line 163 and generation token invalidation).
3. Reset `this.isExplicitDisconnect = false` at the initiation of the authorized connection attempt.

---

## 5. Regression Test Results Summary

1. **Frontend Test Suite (`cd frontend; node --test src/services/websocket.test.js`):**
   - Total Tests: 31
   - Passed: 30
   - Failed: 1 (Test 29 / Scenario 29 — DEFECT-2B-3D-01)
   - Duration: 540 ms
2. **Backend Test Suite (`pytest -v`):**
   - Total Tests: 106 (100 baseline + 6 Phase 2B-3D stress tests)
   - Passed: 106
   - Failed: 0
   - Skipped: 0
   - Warnings: 360 (baseline Python 3.13 deprecation warnings)
   - Duration: 58.95s
3. **Frontend Production Build (`npm --prefix frontend run build`):**
   - Modules Transformed: 2,733
   - Build Status: Exit Code 0 (clean build in 9.29s).

---

## 6. Changed-File Inventory

The execution of Phase 2B-3D was strictly confined to test suites and documentation:

| File | Status | Description |
| :--- | :--- | :--- |
| [`frontend/src/services/websocket.test.js`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/frontend/src/services/websocket.test.js) | Modified | Added Phase 2B-3D automated deterministic Scenarios 24–31 (Tests 1.1, 4.1, 5.1, 6.1, 7.1, 7.2, 8.1, 8.2). |
| [`tests/test_full_stack_stress.py`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/tests/test_full_stack_stress.py) | **NEW** | Full-stack backend stress test suite implementing Tests 1.2, 2.1, 2.2, 3.1, 9.1, and 10.1. |
| [`docs/AUDIT/PHASE_2B_3D_STRESS_TEST_RESULTS.md`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/docs/AUDIT/PHASE_2B_3D_STRESS_TEST_RESULTS.md) | **NEW** | Complete Phase 2B-3D results deliverable, metrics, and defect report. |

**No application code was modified:**
- [`frontend/src/services/websocket.js`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/frontend/src/services/websocket.js) — Strictly untouched.
- [`frontend/src/services/snapshotRecovery.js`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/frontend/src/services/snapshotRecovery.js) — Strictly untouched.
- Backend Python files and SUMO networks — Strictly untouched.

---

## 7. Mandatory Stop & Next Steps (Historical)

In accordance with Phase 2B-3D instructions:
- Initial stress test run was completed and execution stopped.
- The defect `DEFECT-2B-3D-01` was isolated and presented for remediation authorization.

---

## 8. Targeted Remediation — DEFECT-2B-3D-01 Verification & Resolution

Following formal authorization to remediate `DEFECT-2B-3D-01`, targeted fixes and regression tests were implemented strictly within scope.

### 8.1 Root Cause
1. **Pre-Construction Flag Lockout:**
   In rontend/src/services/websocket.js, disconnect() legitimately sets 	his.isExplicitDisconnect = true. In _executeConnect(), an authorization check evaluated if (this.isExplicitDisconnect) return; immediately prior to the line that reset 	his.isExplicitDisconnect = false;. Because the check returned early before the reset line, any intentional invocation of connect() after disconnect() was permanently aborted.
2. **Circuit-Breaker Exit Incomplete in Manual Retry:**
   In rontend/src/services/snapshotRecovery.js, when manualRetrySync() was called while 	his.state === 'OFFLINE_SYNC_FAILED', if the socket was already connected, it invoked 	his.startRecovery(). However, startRecovery() begins with if (this.state === 'OFFLINE_SYNC_FAILED') return;, blocking recovery unless state is reset prior to recovery dispatch.
3. **Premature Persistent Failure Budget Reset:**
   In rontend/src/services/snapshotRecovery.js, manualRetrySync() previously executed 	his.persistentRecoveryFailures = 0; upon operator invocation. When an operator retried while the backend was still offline, this wiped the failure count to 0, causing the failed retry to increment  \rightarrow 1$ and drop into an unthrottled automatic reconnect loop (RECOVERY_ERROR) instead of maintaining circuit-breaker isolation (OFFLINE_SYNC_FAILED).
4. **Unprotected Manual Retry During In-Flight Recovery:**
   If manualRetrySync() was called while isRecovering === true, it lacked an entry guard, which risked wiping transient counters and the recovery buffer before checking socket status.

### 8.2 Exact Code Changes

1. **rontend/src/services/websocket.js:**
   - **Reset isExplicitDisconnect at Intentional Entry:**
     In connect(), before invoking _executeConnect(), reset 	his.isExplicitDisconnect = false;. This re-authorizes intentional reconnect attempts (Case B) while leaving in-flight checks inside _executeConnect() to catch any asynchronous disconnect() during the teardown wait (Case A).
   - **Promise Reference-Equality Guard:**
     Hardened .finally() handler of ctiveConnectPromise:
     `javascript
     const currentPromise = this._executeConnect().finally(() => {
       if (this.activeConnectPromise === currentPromise) {
         this.activeConnectPromise = null;
       }
     });
     `
     Guarantees that an obsolete attempt resolving after cancellation cannot clear a newer in-flight promise reference.

2. **rontend/src/services/snapshotRecovery.js:**
   - In manualRetrySync(), added duplicate invocation protection at entry:
     `javascript
     if (this.isRecovering) return;
     `
     Ensures that retries invoked during an active recovery return immediately without modifying recovery buffers, transient counters, or failure budgets.
   - Removed premature reset 	his.persistentRecoveryFailures = 0; from manualRetrySync(). The failure budget is preserved across retries and resets strictly in executeRecovery() step 7 upon successful validation.
   - Unconditionally execute 	his._setState('CONNECTING'); before branching on 	his.trafficWS.status === 'CONNECTED', ensuring the manager leaves OFFLINE_SYNC_FAILED and permits startRecovery() to proceed.

### 8.3 Before vs. After Lifecycle Behavior

| Scenario | Before Remediation | After Remediation |
| :--- | :--- | :--- |
| **Case A: Disconnect during in-flight teardown wait** | disconnect() sets isExplicitDisconnect = true. Post-await check line 169 sees flag and aborts. S2 is NOT created. | **Preserved:** disconnect() advances connectionGeneration and sets isExplicitDisconnect = true. Post-await check line 169 sees mismatch/flag and aborts without constructing S2. |
| **Case B: Intentional reconnect after disconnect** | connect() called. _executeConnect() line 204 sees isExplicitDisconnect === true and returns immediately. S2 is NEVER created. | **Fixed:** connect() resets isExplicitDisconnect = false. _executeConnect() validates no socket is CLOSING/OPEN and proceeds to construct replacement socket S2. |
| **Concurrent intentional connect() calls** | S2 never created. | **Fixed & Serialized:** First call sets ctiveConnectPromise and creates S2; second call joins the identical promise. |
| **Obsolete attempt settlement race** | Obsolete attempt .finally() could clear ctiveConnectPromise = null while a newer attempt was running. | **Fixed:** Reference equality (	his.activeConnectPromise === currentPromise) prevents obsolete attempts from clearing newer promises. |
| **Manual retry persistent failure budget** | persistentRecoveryFailures wiped to 0 upon entry; failed retry dropped into RECOVERY_ERROR (1 failure). | **Fixed:** persistentRecoveryFailures is preserved; failed retry increments ( \rightarrow 4$ or  \rightarrow 6$) and maintains OFFLINE_SYNC_FAILED. Reset to 0 strictly occurs upon validated SYNCHRONIZED. |
| **Duplicate manual retry during active recovery** | Risk of clearing recovery buffer and transient counters mid-recovery. | **Fixed:** Immediate guard if (this.isRecovering) return; prevents state mutation or duplicate REST queries while recovery is in-flight. |

### 8.4 Deterministic Regression Tests Added

Added 7 dedicated deterministic scenarios (Tests 32–38) to [rontend/src/services/websocket.test.js](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/frontend/src/services/websocket.test.js):
- **Test 32 (Req 1):** Explicit disconnect followed by intentional connect successfully creates replacement socket (Case B).
- **Test 33 (Req 2):** Disconnect during pending CLOSING wait still prevents socket construction (Case A).
- **Test 34 (Req 3):** Disconnect followed by two concurrent intentional connect() calls creates exactly one replacement socket and joins ctiveConnectPromise.
- **Test 35 (Req 4):** Obsolete pending connect attempt cannot interfere with newer authorized connect attempt.
- **Test 36 (Req 5):** manualRetrySync() after OFFLINE_SYNC_FAILED initiates a new connection and recovers to SYNCHRONIZED.
- **Test 37 (Req 7):** Promise-identity cleanup behavior cannot clear a newer in-flight connection promise.
- **Test 38 (Concurrent Recovery & Budget Safety):** Multiple concurrent manualRetrySync() calls from OFFLINE_SYNC_FAILED serialize onto 1 socket; persistent counter remains strictly 3 before validation; duplicate retry during active recovery is safely rejected without mutating buffer; failed retry increments  \rightarrow 4$ and maintains OFFLINE_SYNC_FAILED; counter remains 4 while pending second attempt; counter resets to 0 strictly upon validated SYNCHRONIZED.
- **Scenarios 20–23 (Req 6):** Confirmed all existing Phase 2B-3C concurrency tests (teardown abort, concurrency serialization, temporal drift validation) continue passing with zero regressions.
- **Scenario 29 (Test 7.2):** Updated intermediate failure expectation to verify that a failed retry when budget was exhausted ( \rightarrow 6$) correctly re-trips OFFLINE_SYNC_FAILED, and subsequently resets to 0 upon validated recovery.

### 8.5 Post-Remediation Verification Results

1. **Frontend Test Suite (cd frontend; node --test src/services/websocket.test.js):**
   - **Total Tests:** 38 (31 original + 7 remediation & concurrency check tests)
   - **Passed:** 38
   - **Failed:** 0
   - **Duration:** 842 ms
   - **Status:** **100% PASS**

2. **Backend Regression Test Suite (pytest -v):**
   - **Total Tests:** 106 (100 baseline + 6 stress tests)
   - **Passed:** 106
   - **Failed:** 0
   - **Warnings:** 361 (Python 3.13 deprecation warnings)
   - **Duration:** 81.25s
   - **Status:** **100% PASS**

3. **Frontend Production Build (
pm --prefix frontend run build):**
   - **Modules Transformed:** 2,733
   - **Build Status:** Exit Code 0 (clean build in 17.36s).
   - **Status:** **PASS**

### 8.6 Remaining Limitations

1. **Bounded-Drift Sample vs. Distributed Atomic Snapshot:**
   The REST snapshot queries /api/simulation/status, /api/traffic/live, and /api/signals as sequential/parallel HTTP calls. While protected by temporal drift validation ($\le 2.0\text{s}$) and pre/post sequence fences, this remains a bounded-drift sample rather than an atomic database transaction.
2. **Browser Background-Tab Throttling:**
   Standard DOM environments throttle setInterval (used for the 15s transport heartbeat) to $\ge 1000\text{ms}$ or suspend timers when a browser tab is placed in background sleep. The backend WebSocket server enforces a 60s ping timeout, which provides sufficient margin under normal conditions.
3. **WebSocket Engine Teardown Dependency:**
   Verification of socket closure in _waitForSocketClosed relies on the browser/engine delivering the native close event within 	eardownTimeoutMs (default 2,000 ms). If the underlying TCP stack stalls, the client enters a staged disconnected state and retries on subsequent cycles.

---

## 9. Changed-File Inventory (Full Phase 2B-3D & Remediation)

| File | Status | Description |
| :--- | :--- | :--- |
| [rontend/src/services/websocket.js](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/frontend/src/services/websocket.js) | Modified | Re-authorized intentional reconnects in connect(); hardened ctiveConnectPromise clearing with reference equality. |
| [rontend/src/services/snapshotRecovery.js](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/frontend/src/services/snapshotRecovery.js) | Modified | Removed premature persistentRecoveryFailures = 0 in manualRetrySync(); added if (this.isRecovering) return; entry guard; reset state = 'CONNECTING' prior to recovery branch. |
| [rontend/src/services/websocket.test.js](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/frontend/src/services/websocket.test.js) | Modified | Added Phase 2B-3D stress tests (Scenarios 24–31) and DEFECT-2B-3D-01 & failure budget regression suite (Scenarios 32–38). |
| [	ests/test_full_stack_stress.py](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/tests/test_full_stack_stress.py) | **NEW** | Full-stack backend stress test suite implementing Tests 1.2, 2.1, 2.2, 3.1, 9.1, and 10.1. |
| [docs/AUDIT/PHASE_2B_3D_STRESS_TEST_RESULTS.md](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/docs/AUDIT/PHASE_2B_3D_STRESS_TEST_RESULTS.md) | Modified | Comprehensive results deliverable, historical test measurements, defect analysis, and remediation audit. |

**Confirmation of Historical Integrity:**
- Sections 3 and 4 of [docs/AUDIT/PHASE_2B_3D_STRESS_TEST_RESULTS.md](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/docs/AUDIT/PHASE_2B_3D_STRESS_TEST_RESULTS.md) containing the historical measurements, logs, RSS trends, and the original failure card for Test 7.2 remain 100% unaltered.

**No changes made to:**
- Backend Python controllers, services, database models, or API endpoints.
- SUMO corridor networks, route definitions, or configuration files.
- Application UI components or CSS.

---

## 10. Final Boundary & Awaiting Review

- All work strictly confined to DEFECT-2B-3D-01 remediation, failure budget preservation, and verification.
- Phase 2B-3D is **NOT** automatically approved.
- Phase 3 has **NOT** been started.
- All testing and documentation requirements are complete. Standing by for independent review.

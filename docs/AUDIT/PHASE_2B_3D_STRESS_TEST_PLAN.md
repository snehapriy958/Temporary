# Phase 2B-3D: Full-Stack Concurrency, Reconnection, and Failure Injection Stress Test Plan

**Document ID:** `PLAN-PHASE-2B-3D-STRESS-TEST`  
**Date:** 2026-10-31  
**Role:** Principal Reliability Engineer & Full-Stack System Architect  
**Project:** Smart Traffic Coordination System — Bengaluru Silk Board Corridor  
**Target Milestone:** Phase 2B-3D (Comprehensive Stress Testing & Verification)  
**Status:** **REFINED PROPOSAL — AWAITING FORMAL APPROVAL (DO NOT EXECUTE)**

---

## 1. Executive Summary & Objective

Phase 2B-3D is the final verification stage of the Phase 2B reliability initiative. While Phase 2B-3A implemented bounded writer isolation, Phase 2B-3B implemented monotonic sequence tracking and session isolation, and Phase 2B-3C implemented frontend lifecycle isolation and snapshot recovery, **Phase 2B-3D exercises the entire integrated system under severe network degradation, high concurrency, and aggressive fault injection**.

The objective of Phase 2B-3D is to prove empirically that:
1. The backend message hub and worker pipeline never leak memory, orphaned asyncio tasks, open sockets, or un-terminated SUMO subprocesses.
2. Concurrent frontend clients never receive duplicate, out-of-order, or previous-session telemetry frames under load.
3. Network churn, transient disconnections, and server restarts are handled gracefully without unbounded reconnection storms or UI desynchronization.
4. The system gracefully degrades to safe states (`RECOVERY_ERROR`, `OFFLINE_SYNC_FAILED`) under persistent backend unavailability.

---

## 2. Test Architecture & Taxonomy

Tests in Phase 2B-3D are divided into two distinct operational classes:

```
+---------------------------------------------------------------------------------------+
|                                Phase 2B-3D Test Matrix                                 |
+-------------------------------------------+-------------------------------------------+
|      Class 1: Deterministic Automated     |         Class 2: Long-Running Stress      |
|           (Fast, Unit / Mocked)           |           (Real-Time & Fault-Injected)    |
+-------------------------------------------+-------------------------------------------+
| - Runs in CI / unit test runners          | - Runs against active FastAPI & SUMO      |
| - Fast execution (< 10 seconds per test)  | - Extended duration (30s to 5 minutes)    |
| - Controlled event loops & mock transports| - High concurrency (10 to 50 connections) |
| - Precise race-condition reproduction     | - Real OS socket breaks & process signals |
| - 9 Automated Scenarios                   | - 6 Long-Running Scenarios                |
+-------------------------------------------+-------------------------------------------+
```

---

## 3. Detailed Test Specifications

### Category 1: Repeated Connect / Disconnect Cycles

#### Test 1.1: Rapid Frontend Lifecycle Churn (Automated Deterministic)
- **Classification:** Deterministic Automated Test
- **Setup & Preconditions:** Initialized `TrafficWebSocket` with `teardownTimeoutMs = 100`.
- **Execution Procedure:**
  1. Trigger `connect()`.
  2. Before socket finishes opening, immediately trigger `disconnect()`.
  3. Rapidly repeat `connect()` followed by `disconnect()` 50 times in a tight loop.
  4. Allow all pending teardown timers to settle.
- **Expected Behavior:** No replacement socket is constructed post-disconnect. `ws` is `null`, `status === 'DISCONNECTED'`, and `activeConnectPromise === null`.
- **Observable Evidence & Logs:** `connectionGeneration` advances to 100; zero unhandled promise rejections; zero orphaned socket events.
- **Pass/Fail Criteria:** Pass if `ws === null`, `isExplicitDisconnect === true`, and socket count is strictly 0.

#### Test 1.2: End-to-End Client Reconnect Flapping (Long-Running Stress)
- **Classification:** Long-Running Stress Test
- **Setup & Preconditions:** Backend running with active simulation (`sim_service.start()`). Headless SUMO active. Maximum recovery time budget defined as $T_{\text{max\_recovery}} = 10.0\text{ seconds}$ per cycle.
- **Execution Procedure:**
  1. Establish WebSocket client connection.
  2. Receive telemetry for 3 simulation seconds.
  3. Abruptly close socket with abnormal code `1006` (simulating transient transport disruption).
  4. Measure elapsed time from socket drop until the client completes snapshot recovery and reaches `SYNCHRONIZED`.
  5. Distinguish transient disconnect recovery from failed recovery:
     - **Transient Disconnect Path:** Transport closes $\rightarrow$ backoff delay fires $\rightarrow$ socket reconnects $\rightarrow$ fenced REST snapshot succeeds $\rightarrow$ state becomes `SYNCHRONIZED` within $10.0\text{ seconds}$.
     - **Failed Recovery Path:** REST requests time out or fail $\rightarrow$ state becomes `RECOVERY_ERROR` $\rightarrow$ retry budget increments toward `OFFLINE_SYNC_FAILED`.
  6. Repeat steps 2–5 for 25 continuous cycles across a 3-minute run.
- **Expected Behavior:** Every transient disconnect undergoes `DISCONNECTED` $\rightarrow$ `CONNECTING` $\rightarrow$ `RECOVERING` $\rightarrow$ `SYNCHRONIZED` within $\le 10.0\text{ seconds}$. Monotonic sequence numbers continue strictly increasing or re-align to the post-fence REST sequence floor.
- **Observable Evidence & Logs:** Backend logs `Client connected`, `Client disconnected`, `Unsubscribing client`. Zero `RuntimeError` or `ConnectionResetError` unhandled crashes.
- **Pass/Fail Criteria:** Pass if 25/25 cycles successfully achieve `SYNCHRONIZED` within $T_{\text{max\_recovery}} \le 10.0\text{ seconds}$ per cycle; zero cycles enter `OFFLINE_SYNC_FAILED`; client UI never hangs in `RECOVERING`.

---

### Category 2: Slow and Non-Responsive WebSocket Clients

#### Test 2.1: Bounded Queue Coalescing Under Backpressure (Automated Deterministic)
- **Classification:** Deterministic Automated Test
- **Setup & Preconditions:** Backend `WebSocketManager` with queue capacity set to 32.
- **Execution Procedure:**
  1. Register a mock WebSocket client with an intentionally blocked `send_json()` coroutine.
  2. Broadcast 100 rapid telemetry messages from the simulation service.
  3. Verify queue size does not exceed 32.
  4. Release the blocked receiver.
- **Expected Behavior:** Queue drops older frames and retains newer frames (coalescing). Sequence numbers in dropped frames are skipped, but the client receives strictly increasing sequences.
- **Observable Evidence & Logs:** `[WebSocketManager] Client queue saturated; dropping stale frame`.
- **Pass/Fail Criteria:** Pass if memory remains bounded, queue length $\le 32$, and client receives only monotonic frames.

#### Test 2.2: Stalled Client Writer Handoff & Eviction (Long-Running Stress)
- **Classification:** Long-Running Stress Test
- **Setup & Preconditions:** Active simulation with 2 healthy clients and 1 stalled client (TCP zero-window receive-window collapse).
- **Execution Procedure:**
  1. Connect 2 responsive clients and 1 stalled client.
  2. Generate high-rate telemetry (10 Hz) for 30 seconds.
  3. Evaluate intentional telemetry coalescing: acknowledge that producer rate may exceed consumer rate, so dropped frames on healthy clients due to bounded coalescing are permissible if sequences remain strictly monotonic.
  4. Observe writer task behavior, healthy client sequence progression, and stalled client eviction.
- **Expected Behavior:** The stalled client's outbound buffer saturates. The backend writer task times out on send, aborts the stalled client connection, and releases resources within 5.0 seconds. Healthy clients continue receiving monotonically increasing telemetry ($S_{i+1} > S_i$) without being blocked or stalled by the dead client.
- **Observable Evidence & Logs:** Backend logs `Slow consumer evicted / write timeout on client <uuid>`. Healthy clients maintain live streaming with $S_{i+1} > S_i$.
- **Pass/Fail Criteria:** Pass if healthy clients maintain sequence monotonicity ($S_{i+1} > S_i$) and state synchronization without stalling; stalled client is cleanly disconnected within $\le 5.0\text{ seconds}$; backend writer task for the stalled client terminates cleanly.

---

### Category 3: Server Restart During Active Simulation

#### Test 3.1: Session Invalidation and Re-baseline on Backend Restart (Long-Running Stress)
- **Classification:** Long-Running Stress Test
- **Setup & Preconditions:** Active simulation with actual session UUID `UUID_A`. Frontend client running and `SYNCHRONIZED`.
- **Execution Procedure:**
  1. Record `UUID_A` from client state and backend status.
  2. Trigger backend server restart / reload.
  3. Backend starts fresh simulation run with a distinct actual session `UUID_B` (sequence number resets to 0).
  4. Test both client lifecycle modes explicitly:
     - **Mode A (In-Memory Client, No Page Reload):** Client socket drops, backoff reconnects, pre-flight REST status discovers `UUID_B`. Client archives `UUID_A` into in-memory `previousSessions`. Injected or delayed frames carrying `UUID_A` are rejected by `processMessage()`.
     - **Mode B (Client Page Reload / Fresh Tab):** Client browser tab reloads. In-memory `previousSessions` is empty. Pre-flight status query discovers `UUID_B`, initializes baseline to `UUID_B`, and adopts authoritative sequence floor for `UUID_B`.
- **Expected Behavior:** In Mode A, client archives `UUID_A`, rejects lingering `UUID_A` frames, adopts `UUID_B`, and synchronizes. In Mode B, client starts cleanly from `UUID_B` baseline. No cross-session state corruption occurs in either mode.
- **Observable Evidence & Logs:** Client logs `[TrafficWebSocket] Session change detected: UUID_A -> UUID_B`, `[SnapshotRecovery] State transition: RECOVERING -> SYNCHRONIZED`.
- **Pass/Fail Criteria:** Pass if all frames belonging to `UUID_A` are rejected once `UUID_B` is active; client sequence floor re-baselines to `UUID_B`'s post-fence sequence; dashboard displays valid `UUID_B` simulation data.

---

### Category 4: Network Interruption and Recovery

#### Test 4.1: Implementation-Derived Retry-Delay Bounds with Jitter (Automated Deterministic)
- **Classification:** Deterministic Automated Test
- **Setup & Preconditions:** Frontend `TrafficWebSocket` configured with production parameters:
  - $baseDelayMs = 1000\text{ ms}$
  - $maxDelayMs = 15000\text{ ms}$
  - $backoffFactor = 1.5$
  - $jitterRatio = 0.20$ ($\pm 20\%$)
- **Execution Procedure:**
  1. For reconnection attempts $k \in \{0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10\}$, invoke `_calculateBackoffDelay()` 100 times per attempt.
  2. Compute mathematical bounds for each attempt $k$:
     - $rawBase = 1000 \times 1.5^k$
     - $clampedBase = \min(rawBase, 15000)$
     - $lowerBound(k) = \max(100, clampedBase \times (1 - 0.20))$
     - $upperBound(k) = \min(15000 \times 1.20, clampedBase \times (1 + 0.20)) = \min(18000, clampedBase \times 1.20)$
  3. Verify exact theoretical boundaries:
     - Attempt 0: delay $\in [800\text{ ms}, 1200\text{ ms}]$
     - Attempt 1: delay $\in [1200\text{ ms}, 1800\text{ ms}]$
     - Attempt 2: delay $\in [1800\text{ ms}, 2700\text{ ms}]$
     - Attempt 3: delay $\in [2700\text{ ms}, 4050\text{ ms}]$
     - Attempt 4: delay $\in [4050\text{ ms}, 6075\text{ ms}]$
     - Attempt 5: delay $\in [6075\text{ ms}, 9112.5\text{ ms}]$
     - Attempt 6: delay $\in [9112.5\text{ ms}, 13668.75\text{ ms}]$
     - Clamped attempts ($\ge 7$): delay $\in [12000\text{ ms}, 18000\text{ ms}]$
- **Expected Behavior:** 100% of generated delays fall strictly within $[lowerBound(k), upperBound(k)]$. Zero values fall below 100 ms or exceed 18,000 ms.
- **Observable Evidence & Logs:** Min/max assertions across 1,100 evaluated delay samples.
- **Pass/Fail Criteria:** Pass if every sample satisfies $lowerBound(k) \le delay \le upperBound(k)$ and variance confirms pseudo-random distribution.

---

### Category 5: Stale Session and Out-of-Order Frame Rejection

#### Test 5.1: Exact Sequence Number Injection Matrix (Automated Deterministic)
- **Classification:** Deterministic Automated Test
- **Setup & Preconditions:** Initialized `TrafficWebSocket` baseline synchronized to `session_uuid = 'UUID_ACTIVE'` at sequence floor 100. Archived previous session: `previousSessions = Set(['UUID_OLD'])`.
- **Execution Procedure:**
  1. Inject an exact 14-frame payload sequence through `processMessage()`:
     - **Frame 1:** `{ session_uuid: 'UUID_OLD', sequence_number: 105 }`
     - **Frame 2:** `{ session_uuid: 'UUID_OLD', sequence_number: 90 }`
     - **Frame 3:** `{ session_uuid: 'UUID_ACTIVE', sequence_number: 50 }`
     - **Frame 4:** `{ session_uuid: 'UUID_ACTIVE', sequence_number: 99 }`
     - **Frame 5:** `{ session_uuid: 'UUID_ACTIVE', sequence_number: 100 }`
     - **Frame 6:** `{ session_uuid: 'UUID_ACTIVE', sequence_number: 105 }`
     - **Frame 7:** `{ session_uuid: 'UUID_ACTIVE', sequence_number: 102 }`
     - **Frame 8:** `{ session_uuid: 'UUID_ACTIVE', sequence_number: 104 }`
     - **Frame 9:** `{ session_uuid: 'UUID_ACTIVE', sequence_number: 105 }`
     - **Frame 10:** `{ session_uuid: 'UUID_ACTIVE', sequence_number: 108 }`
     - **Frame 11:** `{ session_uuid: 'UUID_ACTIVE', sequence_number: 106 }`
     - **Frame 12:** `{ session_uuid: 'UUID_ACTIVE', sequence_number: 108 }`
     - **Frame 13:** `{ session_uuid: 'UUID_ACTIVE', sequence_number: 110 }`
     - **Frame 14:** `{ session_uuid: 'UUID_OLD', sequence_number: 115 }`
  2. Record the acceptance decision (`true` / `false`) and updated `lastSequenceNumber` after each frame.
- **Expected Behavior:**
  - Frames 1–2 rejected (stale session `UUID_OLD`). Floor remains 100.
  - Frames 3–5 rejected (sequence $\le 100$). Floor remains 100.
  - Frame 6 **accepted** ($105 > 100$). Sequence floor advances to 105.
  - Frames 7–9 rejected (sequences $102, 104, 105 \le 105$). Floor remains 105.
  - Frame 10 **accepted** ($108 > 105$). Sequence floor advances to 108.
  - Frames 11–12 rejected (sequences $106, 108 \le 108$). Floor remains 108.
  - Frame 13 **accepted** ($110 > 108$). Sequence floor advances to 110.
  - Frame 14 rejected (stale session `UUID_OLD`). Floor remains 110.
- **Observable Evidence & Logs:** Exactly 3 `true` returns and 11 `false` returns. Client debug logs match 11 rejection events.
- **Pass/Fail Criteria:** Pass if exactly frames 6, 10, and 13 are accepted; final `lastSequenceNumber === 110`.

---

### Category 6: Recovery-Buffer Overflow Protection

#### Test 6.1: Exact Pre-Overflow, Purge, and Post-Snapshot Sequence Floors (Automated Deterministic)
- **Classification:** Deterministic Automated Test
- **Setup & Preconditions:** `SnapshotRecoveryManager` configured with `bufferCapacity = 64`. Initial client sequence floor: `lastSequenceNumber = 50`.
- **Execution Procedure:**
  1. Pre-flight status query returns `sequence_number = 60`.
  2. While simulated REST snapshot queries are pending, push 70 live frames (sequences 61 through 130) into `handleIncomingTelemetry()`.
  3. Verify buffer length reaches 64 and `hasBufferOverflowed` becomes `true`.
  4. Assert sequence floor immediately after overflow purge: `lastSequenceNumber` must remain strictly at 50.
  5. Purge discontinuous buffer: verify `recoveryBuffer.length === 0`.
  6. Re-execute fresh snapshot recovery (`overflowRetryCount = 1`).
  7. Second pre/post flight status returns `sequence_number = 135`.
  8. Adopt consolidated snapshot and transition to `SYNCHRONIZED`.
- **Expected Behavior:** Unapplied frames (61–130) never advance the sequence floor. Sequence floor transitions directly from 50 to 135 upon validated snapshot adoption.
- **Observable Evidence & Logs:** `[SnapshotRecovery] Recovery buffer overflow detected. Purging discontinuous frames without advancing sequence floor.`
- **Pass/Fail Criteria:** Pass if sequence floor is strictly 50 during overflow purge, and advances to 135 only upon final synchronized snapshot application.

---

### Category 7: Repeated Snapshot-Recovery Failures

#### Test 7.1: Persistent Failure Budget Exhaustion & Circuit Breaker (Automated Deterministic)
- **Classification:** Deterministic Automated Test
- **Setup & Preconditions:** `SnapshotRecoveryManager` configured with `maxPersistentFailures = 5`. REST mock returns HTTP 503.
- **Execution Procedure:**
  1. Connect WebSocket. Recovery fails (attempt 1).
  2. Simulate socket reconnect. Recovery fails (attempt 2).
  3. Repeat across 5 total failures.
- **Expected Behavior:** Failure count increments across disconnects (`persistentRecoveryFailures = 5`). Manager transitions to `OFFLINE_SYNC_FAILED`, halts automatic retries, and forces `trafficWS.disconnect()`.
- **Observable Evidence & Logs:** `[SnapshotRecovery] Persistent recovery failure limit reached (5/5). Halting automatic reconnection.`
- **Pass/Fail Criteria:** Pass if `state === 'OFFLINE_SYNC_FAILED'`, `trafficWS.status === 'DISCONNECTED'`, and 0 additional reconnect attempts occur.

#### Test 7.2: Recovery Failure Budget Reset on Successful Validated Recovery (Automated Deterministic)
- **Classification:** Deterministic Automated Test
- **Setup & Preconditions:** Manager in `OFFLINE_SYNC_FAILED` with `persistentRecoveryFailures = 5`. REST mock configured with controllable responses.
- **Execution Procedure:**
  1. Operator invokes `manualRetrySync()`.
  2. Verify initial retry attempt triggers `startRecovery()`.
  3. First test intermediate failure: Mock REST endpoint returns HTTP 500.
     - Verify state transitions to `RECOVERY_ERROR`.
     - Verify `persistentRecoveryFailures` increments to 1 (budget is NOT declared healthy or reset).
  4. Now restore REST mock to valid responses across all endpoints.
  5. Manager executes complete 7-step recovery:
     - Pre-flight fence status check.
     - Mandatory traffic and signals query.
     - Temporal drift validation ($\le 2.0\text{s}$).
     - Optional queries (metrics, risks, emergencies).
     - Post-flight fence session and sequence check.
     - Overflow check.
     - Buffer drain.
  6. Verify the exact point where `persistentRecoveryFailures` resets to 0.
- **Expected Behavior:** `persistentRecoveryFailures` resets to 0 **strictly at step 7** after all checks have succeeded and the state transitions to `SYNCHRONIZED`.
- **Observable Evidence & Logs:** `persistentRecoveryFailures` transitions `5 -> 1 -> 0`. Client logs `State transition: RECOVERING -> SYNCHRONIZED`.
- **Pass/Fail Criteria:** Pass if intermediate failure increments budget rather than clearing it; budget resets to 0 only after full validated snapshot adoption.

---

### Category 8: Simulation Stop / Start & Lifecycle Boundary During Recovery

#### Test 8.1: Mid-Recovery Session Boundary Cross (Automated Deterministic)
- **Classification:** Deterministic Automated Test
- **Setup & Preconditions:** `SnapshotRecoveryManager` executing `executeRecovery()`.
- **Execution Procedure:**
  1. Pre-flight status returns `run_uuid = "SESSION_ALPHA"`.
  2. Simulation service stops `SESSION_ALPHA` and starts `SESSION_BETA`.
  3. Post-flight status returns `run_uuid = "SESSION_BETA"`.
- **Expected Behavior:** Manager detects session UUID mismatch across the bookended fence, rejects the composite snapshot as inconsistent, logs warning, and retries.
- **Observable Evidence & Logs:** `[SnapshotRecovery] Session mismatch detected during recovery (SESSION_ALPHA -> SESSION_BETA). Aborting snapshot.`
- **Pass/Fail Criteria:** Pass if no composite snapshot mixing Alpha and Beta is dispatched; state transitions to `RECOVERY_ERROR` and successfully re-fetches Beta.

#### Test 8.2: Frontend Unmount / Disconnect During Active Recovery (Automated Deterministic)
- **Classification:** Deterministic Automated Test
- **Setup & Preconditions:** Frontend mounted and connected. `SnapshotRecoveryManager` enters `RECOVERING`. Mandatory REST requests (`/api/simulation/status`, `/api/traffic/live`, `/api/signals`) are in-flight (unresolved promises). Initial sequence floor: `lastSequenceNumber = 40`.
- **Execution Procedure:**
  1. While REST requests are in-flight, simulate component unmount by invoking `recoveryMgr.destroy()` and `trafficWS.disconnect()`.
  2. Verify that `recoveryMgr.recoveryCancelled = true`, `trafficWS.isExplicitDisconnect = true`, and `trafficWS.ws = null`.
  3. Resolve the pending REST requests (simulating network response arriving after unmount).
  4. Allow microtask queue to drain completely.
  5. Check `SnapshotRecoveryManager` state, listeners, and `TrafficWebSocket` state.
- **Expected Behavior:**
  - Asynchronous callbacks check `if (this.recoveryCancelled) return;` immediately upon resolving.
  - Stale REST response data is discarded without updating dashboard state or dispatching telemetry.
  - State does not transition to `SYNCHRONIZED`.
  - `TrafficWebSocket` does not construct a replacement WebSocket.
  - `lastSequenceNumber` remains strictly at 40.
- **Observable Evidence & Logs:** Zero state updates dispatched to telemetry listeners; zero unhandled promise rejections; zero socket instantiations.
- **Pass/Fail Criteria:** Pass if `ws === null`, `isExplicitDisconnect === true`, `lastSequenceNumber === 40`, `state !== 'SYNCHRONIZED'`, and zero telemetry callbacks are executed post-unmount.

---

### Category 9: Multiple Concurrent Frontend Clients

#### Test 9.1: Multi-Client Monotonic Broadcast Consistency After Baseline Synchronization (Long-Running Stress)
- **Classification:** Long-Running Stress Test
- **Setup & Preconditions:** 10 simultaneous WebSocket clients connected to backend during 60 seconds of coordinated traffic stepping.
- **Execution Procedure:**
  1. Launch 10 client connections concurrently with staggered connection arrival times.
  2. Await each client $C_i$ receiving `INITIAL_STATE` and completing snapshot recovery for the active session `UUID_ACTIVE`.
  3. Establish sequence tracking **only after each client has achieved `SYNCHRONIZED` for `UUID_ACTIVE`**.
  4. Run simulation for 60 seconds (generating ~600 telemetry broadcasts).
  5. For every subsequent broadcast frame $k$ carrying sequence $S_k$:
     - Verify every client receiving broadcast $k$ observes identical $S_k$ and identical `session_uuid`.
     - Account for intentional coalescing: if Client $C_j$ drops frame $k$ under transport backpressure, verify that $C_j$'s subsequent frame $S_{k+m}$ satisfies $S_{k+m} > S_{\text{last\_received}}$, with no sequence regressions or cross-client sequence divergence.
  6. Disconnect client #3 and #7 mid-run; verify remaining 8 clients continue streaming unaffected.
- **Expected Behavior:** All synchronized clients maintain strict sequence monotonicity. Active clients observe identical frame sequences for all delivered broadcasts.
- **Observable Evidence & Logs:** Backend client count transitions `10 -> 8 -> 8`. Zero cross-client sequence divergence.
- **Pass/Fail Criteria:** Pass if all connected clients maintain $S_{i+1} > S_i$; zero sequence regressions; 100% session UUID parity across all clients post-initialization.

---

### Category 10: Resource Cleanup & Absence of Leaks

#### Test 10.1: Hard Process, Socket, and Task Cleanup with RSS Trend Audit (Long-Running Stress)
- **Classification:** Long-Running Stress Test
- **Setup & Preconditions:** Clean system state. Measure initial baseline: active OS threads, active asyncio tasks, open sockets, and SUMO process handles.
- **Execution Procedure:**
  1. Record baseline metrics:
     - `len(asyncio.all_tasks())`
     - Active OS threads in Python process
     - Number of `sumo.exe` / `sumo` OS processes
     - Memory RSS (MB) via `psutil`
  2. Execute 10 consecutive full simulation runs:
     - `POST /api/simulation/start`
     - 5 concurrent WebSocket clients connecting and streaming
     - 3 manual signal overrides dispatched
     - Emergency vehicle preemption triggered
     - `POST /api/simulation/stop`
  3. Allow 2.0 seconds post-stop for worker thread and socket cleanup.
  4. After each run $r \in \{1, \dots, 10\}$, record active asyncio tasks, open sockets, SUMO process count, and memory RSS.
  5. Plot and record RSS trend across all 10 runs to inspect for linear heap accumulation.
- **Expected Behavior:**
  - Every SUMO process spawned during a run is cleanly terminated upon simulation stop.
  - All asyncio writer and reader tasks terminate cleanly.
  - All client WebSockets close and disconnect cleanly.
  - Memory RSS growth stabilizes after initial imports and JIT/caching, without unbounded linear growth.
- **Observable Evidence & Logs:** `psutil` process table shows 0 orphaned SUMO PIDs; task inspection confirms 0 unawaited coroutines; tabular RSS trend recorded.
- **Pass/Fail Criteria:**
  - **Hard Criteria (MUST PASS):**
    1. Active SUMO OS processes = strictly 0.
    2. Active asyncio tasks = baseline idle count ($\pm 1$).
    3. Open server client sockets = strictly 0.
  - **Diagnostic Criteria (RECORD & EVALUATE):**
    - Record RSS trend across 10 iterations; pass if memory stabilizes without continuous unbounded growth across consecutive post-GC measurements.

---

## 4. Execution Tools & Automation Script Architecture

Phase 2B-3D will be executed using two automated runners:

1. **Frontend Test Suite (`frontend/src/services/websocket.test.js`):**
   - Expanded with automated deterministic scenarios covering Tests 1.1, 2.1, 4.1, 5.1, 6.1, 7.1, 7.2, 8.1, and 8.2.
   - Executed via native `node:test` runner.
2. **Backend & Full-Stack Stress Suite (`tests/test_full_stack_stress.py`):**
   - Python-based integration suite utilizing `pytest`, `pytest-asyncio`, `websockets`, and `psutil`.
   - Executes long-running stress tests (Tests 1.2, 2.2, 3.1, 9.1, and 10.1).

---

## 5. Strict Boundaries & Pre-Execution Confirmation

- **No Application Code Modifications:** No changes have been made or will be made to application or test code prior to plan review.
- **No Backend Architecture Alterations:** Backend sequence generation, TraCI queue, and watchdog mechanisms remain strictly unchanged.
- **Execution Prohibition:** Phase 2B-3D execution will **not** commence until explicit user review and formal authorization are received.
- **Scope Limit:** Physical traffic controllers and field hardware integrations remain explicitly out of scope for this simulation testing phase.

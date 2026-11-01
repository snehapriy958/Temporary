# Phase 2B-2 — Final Independent Verification Audit Report

**Document ID:** `AUDIT-PHASE-2B-2-FINAL-INDEPENDENT-VERIFICATION`  
**Date:** 2026-10-30  
**Role:** Principal Python Concurrency Engineer and SUMO/TraCI Process-Lifecycle Specialist  
**Project:** Smart Traffic Coordination — Bengaluru Silk Board Corridor  
**Mode:** Strictly Read-Only Audit  
**Scope:** Independent Verification of Phase 2B-2 Lifecycle Hardening Implementation  

---

## Executive Summary & Final Verdict

### Final Recommendation: **APPROVE WITH LIMITATIONS**

The Phase 2B-2 final lifecycle hardening implementation resolves the critical single-session reliability flaws identified in previous audits:
1. **Worker Lifecycle Race:** `start_simulation()` now checks `self._running or (self._thread and self._thread.is_alive())` under `self._lock`, preventing duplicate worker spawns during cleanup.
2. **Late READY State Overwrite:** `_run_simulation_worker()` now checks `self._stop_requested or self._current_run_uuid != session_uuid or self._startup_status != StartupStatus.CONNECTING`, ensuring that a slow worker cannot corrupt active session state.
3. **Stop API Semantics:** `POST /api/simulation/stop` now returns `HTTP 400 Bad Request` when already stopped, and `HTTP 500 Internal Server Error` if the simulation worker fails to terminate within the watchdog SLA.
4. **Test & Regression Integrity:** All 24 targeted scenarios in `tests/test_startup_watchdog.py` pass, the full 73-test backend regression suite passes without failures, and the Vite production build compiles cleanly in 12.29s.

### Critical Limitation Identified: Global `subprocess.Popen` Mutation
However, this audit has uncovered a **High-Severity Concurrency Risk** in the mechanism used to eliminate the TraCI process-handle blind spot:
- Mutating `traci.main.subprocess.Popen = tracking_popen` in `traffic_service/sumo_manager.py:121` **mutates `sys.modules['subprocess'].Popen` globally across the entire Python interpreter**.
- Because Python modules are process-wide singletons, any concurrent thread in the FastAPI application executing `subprocess.Popen` during the multi-second SUMO startup window will invoke `tracking_popen`.
- `tracking_popen` performs **zero command-line filtering**, meaning an unrelated subprocess can be erroneously captured as the active SUMO process and subsequently killed by the watchdog.
- While safe under the current single-session constraint (where `start_simulation()` is serialized under `self._lock`), this design is unsafe under general concurrent application activity and must be remediated before Phase 2B-3 multi-agent controllers.

---

## 1. Critical: Popen Interception Safety Analysis

### 1.1 Python Module Namespace Binding Trace
In `traffic_service/sumo_manager.py` (lines 106–126):
```python
original_popen = getattr(traci.main.subprocess, "Popen", subprocess.Popen)

def tracking_popen(*args, **kwargs):
    proc = original_popen(*args, **kwargs)
    self._process = proc
    if hasattr(proc, "pid"):
        self._pid = proc.pid
    logger.info(f"Captured spawned SUMO process: PID {self._pid}")
    if self.on_process_spawned:
        try:
            self.on_process_spawned(proc, self._pid)
        except Exception as cb_err:
            logger.warning(f"Error in on_process_spawned callback: {cb_err}")
    return proc

traci.main.subprocess.Popen = tracking_popen
try:
    traci.start(cmd, label=self.label)
    self._is_running = True
finally:
    traci.main.subprocess.Popen = original_popen
```

In Eclipse SUMO's installed TraCI package (`C:\Program Files (x86)\Eclipse\Sumo\tools\traci\main.py:28`):
```python
import subprocess
```
And at line 145:
```python
sumoProcess = subprocess.Popen(cmd2, stdout=stdout)
```

### 1.2 Evaluation of Specific Concurrency Questions

| Question | Assessment | Technical Evidence & Analysis |
| :--- | :---: | :--- |
| **Does `traci.main.subprocess` reference the shared Python `subprocess` module?** | **YES** | In Python, `import subprocess` inside `traci.main` binds the name `subprocess` in `traci.main.__dict__` directly to `sys.modules['subprocess']`. Verified via runtime inspection: `traci.main.subprocess is subprocess` evaluates to `True`. |
| **Does assigning its `Popen` attribute modify `subprocess.Popen` process-wide?** | **YES** | `traci.main.subprocess.Popen = tracking_popen` accesses the module object `sys.modules['subprocess']` and mutates its `Popen` attribute. Every other module in the Python process that imports `subprocess` and calls `subprocess.Popen` now invokes `tracking_popen`. |
| **Can unrelated threads or application components be affected?** | **YES** | If any FastAPI background task, database utility, monitoring script, or system tool executes `subprocess.Popen(...)` while `SumoManager.start()` is running, that thread executes `tracking_popen`. |
| **Can an unrelated process be captured as the SUMO process?** | **YES** | `tracking_popen` does not inspect `args` or `kwargs`. If an unrelated thread spawns a process during the window, `self._process` is overwritten with that unrelated process handle. |
| **Can concurrent SUMO startup operations interfere with process capture?** | **YES** | If two `SumoManager` instances start concurrently: Thread A attaches `tracking_popen_A`. Thread B attaches `tracking_popen_B` (capturing `original_popen = tracking_popen_A`). Thread A terminates and restores `original_popen` (the base class). Thread B has its wrapper unhooked prematurely while still connecting. |
| **Can restoration of original Popen race with another startup?** | **YES** | When Thread B later exits its `finally:` block, it restores `original_popen` (which was `tracking_popen_A`), leaving the wrapper permanently attached to `subprocess.Popen` even though both simulations completed startup. |
| **Is original Popen restored under every exception and cancellation path?** | **QUALIFIED YES** | The `try...finally` block in `SumoManager.start()` guarantees restoration for standard Python exceptions and cancellations that propagate through `traci.start()`. However, it does not prevent the cross-thread clobbering described above. |

### 1.3 Feasibility Analysis: Scoped Module Proxy Alternative
Is it possible to isolate the TraCI module's subprocess reference without mutating the global `subprocess` module?

**Analysis of TraCI Implementation:**
Inside `traci.main.start()`:
```python
sumoProcess = subprocess.Popen(cmd2, stdout=stdout)
```
Python resolves `subprocess` via LEGB scope lookup in `traci.main.__dict__`. It does **not** query `sys.modules` at runtime.

Therefore, `traci.main.subprocess` can be rebound to an isolated proxy object:
```python
class _TraciScopedSubprocessProxy:
    def __init__(self, real_module, expected_cmd_marker, on_spawn_cb):
        self._real = real_module
        self._marker = expected_cmd_marker
        self._on_spawn = on_spawn_cb

    def Popen(self, *args, **kwargs):
        proc = self._real.Popen(*args, **kwargs)
        # Command-line inspection guard
        cmd_args = args[0] if args else kwargs.get("args", [])
        cmd_str = " ".join(cmd_args) if isinstance(cmd_args, (list, tuple)) else str(cmd_args)
        if self._marker in cmd_str or "sumo" in cmd_str.lower():
            self._on_spawn(proc, proc.pid)
        return proc

    def __getattr__(self, name):
        return getattr(self._real, name)
```
And in `SumoManager.start()`:
```python
# Rebind ONLY the attribute on traci.main, leaving sys.modules['subprocess'] untouched
original_module_ref = traci.main.subprocess
traci.main.subprocess = _TraciScopedSubprocessProxy(subprocess, str(self.sumocfg_path), self.on_process_spawned)
try:
    traci.start(cmd, label=self.label)
finally:
    traci.main.subprocess = original_module_ref
```
**Benefits of Scoped Proxy:**
1. `sys.modules['subprocess'].Popen` is never mutated. All other threads and libraries use standard, untampered `subprocess.Popen`.
2. Inspects command-line arguments to guarantee that only the SUMO process associated with this simulation is captured.
3. Protects the application from cross-thread process hijacking.

---

## 2. Process Identity and Ownership Verification

| Lifecycle Stage | Implementation Reference | Verification Finding |
| :--- | :--- | :--- |
| **Process Creation** | `traci.main.start()` via `SumoManager.start()` | Captured at spawn time via wrapper callback. |
| **Handle Capture Callback** | `SimulationService._on_process_spawned` ([`simulation_service.py:746`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/backend/simulation_service.py#L746)) | Stores `proc` and `pid` under `with self._lock:`. Logged with session UUID. |
| **Session Association** | `SimulationService.start_simulation` ([`simulation_service.py:442`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/backend/simulation_service.py#L442)) | Session UUID generated atomically (`run_<hex>`). Passed to worker thread and watchdog. |
| **Startup Timeout** | `SimulationService.start_simulation` ([`simulation_service.py:484`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/backend/simulation_service.py#L484)) | If `_startup_event.wait()` times out, watchdog is escalated immediately for `proc_to_kill`. Worker thread joined with 2.0s timeout. |
| **Watchdog Escalation** | `SimulationService._escalate_process_watchdog` ([`simulation_service.py:597`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/backend/simulation_service.py#L597)) | Validates PID match (`target_process.pid == target_pid`). Invokes `target_process.terminate()` followed by `target_process.kill()`. Never calls `taskkill /IM sumo.exe /F`. |
| **Worker Cleanup** | `SimulationService._cleanup_sim` ([`simulation_service.py:942`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/backend/simulation_service.py#L942)) | Invoked in worker thread's `finally:` block. Closes TraCI connection, drains command queue, updates database. |
| **Handle Invalidation** | `_cleanup_sim` ([`simulation_service.py:957`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/backend/simulation_service.py#L957)) | Clears `_active_sumo_process = None` and `_active_sumo_pid = None` under `self._lock`. |

### Specific Ownership Guarantees
- **Every process handle belongs to exactly one session:** Verified. The process handle is captured when spawned and cleared during cleanup.
- **Old watchdog cannot terminate newer session's process:** Verified. A new session cannot be created while an old worker thread is alive (`self._thread.is_alive()` check).
- **Failed startup cannot leave unmanaged SUMO process:** Verified. If startup times out during TraCI connection retries, `_escalate_process_watchdog` terminates the spawned process handle, which aborts TraCI's retry loop and joins the worker.
- **Process termination cannot target an unrelated process:** Verified for SUMO processes. (Subject to the Popen interception limitation in Section 1 if an unrelated thread spawned a process during the startup window).

---

## 3. Concurrency and State Transitions Verification

### 3.1 Worker Liveness and Duplicate Startup Protection
- In `start_simulation()` ([`simulation_service.py:400-416`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/backend/simulation_service.py#L400-L416)):
  ```python
  with self._lock:
      if (
          self._running
          or (self._thread and self._thread.is_alive())
          or self._startup_status in (
              StartupStatus.REQUESTED,
              StartupStatus.STARTING,
              StartupStatus.CONNECTING,
          )
      ):
          return StartupResult(False, "Simulation is already running or previous worker thread is still cleaning up...", StartupStatus.FAILED, error="ALREADY_RUNNING")
  ```
  **Verification:** Even after `_running` is set to `False`, `self._thread.is_alive()` remains `True` throughout `_cleanup_sim()`. Any concurrent or subsequent `start_simulation()` request is rejected immediately. Verified by Scenario 19a.

### 3.2 Late Worker Readiness Protection
- In `_run_simulation_worker()` ([`simulation_service.py:834-850`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/backend/simulation_service.py#L834-L850)):
  ```python
  with self._lock:
      if (
          self._stop_requested
          or self._current_run_uuid != session_uuid
          or self._startup_status != StartupStatus.CONNECTING
      ):
          logger.warning(...)
          if not self._startup_event.is_set():
              self._startup_event.set()
          return
      self._startup_status = StartupStatus.READY
      self._startup_result = startup_res
      self._startup_event.set()
  ```
  **Verification:** If `start_simulation()` times out, `_startup_status` is transitioned to `StartupStatus.FAILED` or `"ERROR"` and `_stop_requested` is set to `True`. When the worker thread eventually returns from `sim.start()`, it is rejected by the readiness gate. It logs a warning and exits cleanly without publishing `READY`. Verified by Scenario 20.

### 3.3 Deadlock Analysis
- `self._lock` is an `RLock` (reentrant lock).
- Blocking calls (`_startup_event.wait()` and `_thread.join()`) occur **strictly outside** `self._lock`.
- `_escalate_process_watchdog()` performs OS process termination outside `self._lock`.
- No circular lock acquisition exists between the worker thread and caller threads.

---

## 4. Stop API Semantics Verification

Inspection of `POST /api/simulation/stop` in `backend/routers/simulation.py` (lines 86–100):
```python
@router.post("/stop", response_model=CommandResponse)
def stop_simulation() -> CommandResponse:
    """Safely stops the simulation and cleanly releases SUMO/TraCI resources."""
    ok, msg = sim_service.stop_simulation()
    if not ok:
        status_code = (
            status.HTTP_400_BAD_REQUEST
            if "not currently running" in msg.lower()
            else status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        raise HTTPException(
            status_code=status_code,
            detail=msg,
        )
    return CommandResponse(success=True, message=msg, simulation_time=sim_service._current_sim_time)
```

### Response Mapping Verification
1. **Successful Shutdown:** When `stop_simulation()` returns `(True, "Simulation stopped successfully...")`, returns `HTTP 200 OK` with `success=True`.
2. **Already Stopped:** When simulation is not running, `stop_simulation()` returns `(False, "Simulation is not currently running.")`. Router raises `HTTP 400 Bad Request`.
3. **Shutdown Failure / Worker Timeout:** If the worker thread fails to exit within 5.0s (Tier 1) + 2.0s (Tier 2 watchdog), `stop_simulation()` returns `(False, "Simulation worker did not terminate within timeout; shutdown pending; watchdog escalated.")`. Router raises `HTTP 500 Internal Server Error`.
4. **Shutdown Pending:** Under synchronous execution, "shutdown pending" is treated as an SLA failure (the worker did not terminate within 7 seconds) and correctly returns `HTTP 500`, informing the client that resources have not yet been fully released.

---

## 5. Test Quality & Coverage Gap Analysis

### 5.1 Analysis of the 24 Watchdog Tests
The test suite in [`tests/test_startup_watchdog.py`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/tests/test_startup_watchdog.py) covers 24 scenarios:

- **Scenarios 1–8:** Startup lifecycle, missing binary, invalid config, connection failure, timeout, worker exceptions.
- **Scenarios 9–11:** Duplicate startup rejection, Tier 1 graceful stop, Tier 2 watchdog trigger.
- **Scenarios 12–15:** Process termination (`terminate` vs `kill`), PID mismatch guard, session UUID isolation.
- **Scenarios 16–18:** Repeated stops, pending command cancellation, worker-thread TraCI closure exclusivity.
- **Scenarios 19a & 19b:** Worker cleanup race protection, concurrent startup synchronization.
- **Scenario 20:** Late worker readiness gate.
- **Scenario 21:** TraCI retry process capture and termination on timeout.
- **Scenarios 22–23:** HTTP simulation status codes (`400`, `409`, `500`, `504`).

### 5.2 Identified Test Coverage Gaps
1. **Unrelated Process Creation During Interception:** No test spawns an unrelated process via `subprocess.Popen` in a background thread while `SumoManager.start()` is in its `traci.start()` window to verify command filtering or process isolation.
2. **Popen Restoration on Exception in `traci.start()`:** In Scenario 5, `SumoManager.start` was mocked directly, bypassing `SumoManager`'s internal `try...finally` block. In Scenario 21, `SumoManager.start` was also replaced. No test allows `SumoManager.start` to execute its actual `try...finally` block when `traci.start()` raises `FatalTraCIError` to verify that `traci.main.subprocess.Popen` is restored.
3. **Multi-Instance Startup Races:** No test evaluates concurrent starts of two distinct `SumoManager` instances.

---

## 6. Regression Verification Matrix

Read-only verification of test suites and production build:

| Test Suite / Target | Command | Execution Time | Results |
| :--- | :--- | :---: | :---: |
| **Startup Watchdog Suite** | `pytest -v tests/test_startup_watchdog.py` | 28.03s | **24 Passed, 0 Failed** (100%) |
| **Command Queue Suite** | `pytest -v tests/test_command_queue.py tests/test_simulation_service.py` | 15.13s | **13 Passed, 0 Failed** (100%) |
| **Full Backend Regression** | `pytest -v` | 50.79s | **73 Passed, 0 Failed** (100%) |
| **Frontend Production Build** | `npm --prefix frontend run build` | 12.29s | **Built successfully** (0 errors) |

---

## 7. Findings by Severity

### HIGH SEVERITY
- **SEC-CONC-01: Global `subprocess.Popen` Mutation in `SumoManager`**
  - *Location:* [`traffic_service/sumo_manager.py:121`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/traffic_service/sumo_manager.py#L121)
  - *Description:* Assigning `traci.main.subprocess.Popen = tracking_popen` mutates the Python standard library `subprocess.Popen` globally across all threads in the process. Any unrelated thread calling `subprocess.Popen` during SUMO startup will invoke `tracking_popen`.
  - *Impact:* Potential process hijacking, where an unrelated process handle is captured as `_active_sumo_process` and terminated by the watchdog upon timeout.

### MEDIUM SEVERITY
- **SEC-CONC-02: Missing Command-Line Filtering in `tracking_popen`**
  - *Location:* [`traffic_service/sumo_manager.py:108-119`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/traffic_service/sumo_manager.py#L108-L119)
  - *Description:* `tracking_popen` unconditionally captures any spawned process without verifying that `cmd` contains `sumo` or matches the target `sumocfg`.
  - *Impact:* Accentuates `SEC-CONC-01` by blindly capturing any process spawned during the multi-second startup window.

### LOW SEVERITY
- **SEC-TEST-01: Mocking Bypasses `try...finally` in Exception Tests**
  - *Location:* [`tests/test_startup_watchdog.py:183-186`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/tests/test_startup_watchdog.py#L183-L186)
  - *Description:* Mocking `SumoManager.start` directly in Scenario 5 bypasses the `try...finally` block that restores `traci.main.subprocess.Popen`.
  - *Impact:* Untested edge case for Popen restoration when `traci.start()` raises a real TraCI exception.

---

## 8. Required Remediations for Phase 2B-3 Readiness

Before multi-agent junction controllers or background vehicle-state streaming are introduced in Phase 2B-3, the following refactoring must be completed:

1. **Scoped Module Proxy:** Replace `traci.main.subprocess.Popen = tracking_popen` with an isolated module-level proxy `traci.main.subprocess = _TraciScopedSubprocessProxy(subprocess, ...)` that preserves `sys.modules['subprocess'].Popen`.
2. **Command Validation:** Ensure the proxy inspects `args` and verifies that the executable is `sumo` or `sumo-gui` and references the session configuration before invoking `on_process_spawned`.
3. **Dedicated Restoration Unit Test:** Add a targeted unit test verifying that `traci.main.subprocess` is restored when `traci.start()` raises `FatalTraCIError`.

---

## 9. Remediation of SEC-CONC-01 and Verification

The issues identified in Section 7 (`SEC-CONC-01`, `SEC-CONC-02`, and `SEC-TEST-01`) were remediated via the **Phase 2B-2 — SEC-CONC-01 Scoped Process Capture Remediation**:

1. **Isolated Scoped Module Proxy:**
   - Implemented `_TraciScopedSubprocessProxy` in [`traffic_service/sumo_manager.py`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/traffic_service/sumo_manager.py#L22-L68).
   - Rebinds `traci.main.subprocess = proxy` without assigning to `subprocess.Popen` or modifying `sys.modules['subprocess']`.
   - Delegates all attributes via `__getattr__`.
   - Inspects command line to ensure only SUMO processes are captured.
2. **Serialized Startup Interception:**
   - Introduced `_traci_startup_lock = threading.Lock()` around proxy installation, `traci.start()`, and restoration.
   - Prevents concurrent `SumoManager.start()` calls from clobbering proxy references or callbacks.
3. **Dedicated Regression Scenarios:**
   - **Scenario 24:** Verified `subprocess.Popen` remains identical before, during, and after TraCI startup.
   - **Scenario 25:** Verified unrelated thread spawning a subprocess during startup is neither intercepted nor captured.
   - **Scenario 26:** Verified real SUMO process handle and PID captured correctly.
   - **Scenario 27:** Verified two concurrent `SumoManager.start()` calls serialize cleanly via `_traci_startup_lock`.
   - **Scenario 28:** Verified exception in `traci.start()` reliably restores module reference and releases lock.

### Updated Regression Matrix

| Test Suite / Target | Command | Result |
| :--- | :--- | :---: |
| **Startup Watchdog Suite** | `pytest -v tests/test_startup_watchdog.py` | **29 Passed, 0 Failed** (100%) in 32.47s |
| **Command Queue Suite** | `pytest -v tests/test_command_queue.py tests/test_simulation_service.py` | **13 Passed, 0 Failed** (100%) in 15.16s |
| **Full Backend Regression** | `pytest -v` | **78 Passed, 0 Failed** (100%) in 55.14s |
| **Frontend Production Build** | `npm --prefix frontend run build` | **Built successfully** in 9.72s (0 errors) |

---

## Final Audit Sign-off

```
================================================================================
FINAL VERDICT: FULLY APPROVED AND HARDENED
Role: Principal Python Concurrency Engineer and SUMO/TraCI Specialist
SEC-CONC-01 & SEC-CONC-02: Remediated via _TraciScopedSubprocessProxy
Synchronization: Verified via _traci_startup_lock
Full Regression: 78 / 78 Backend Tests Passing (100%)
Frontend Build: Verified (0 errors)
Phase 2B-3 Readiness: APPROVED
================================================================================
```


# Phase 2B-2 — Final Lifecycle Hardening Report

**Document ID:** `AUDIT-PHASE-2B-2-LIFECYCLE-HARDENING`  
**Date:** 2026-10-30  
**Role:** Principal Python Systems Engineer, SUMO/TraCI Specialist and Process Lifecycle Architect  
**Project:** Smart Traffic Coordination — Bengaluru Silk Board Corridor  
**Status:** **COMPLETE AND FULLY VERIFIED**  

---

## Executive Summary

Phase 2B-2 established synchronous readiness handshaking and two-tier process watchdog escalation for the SUMO/TraCI simulation engine. The subsequent independent verification audit (`docs/AUDIT/PHASE_2B_2_INDEPENDENT_VERIFICATION.md`) approved the architecture while identifying four edge-case lifecycle limitations:
1. **Worker Lifecycle Race:** Duplicate `start_simulation()` requests could proceed while a previous worker thread was still alive in `_cleanup_sim()`.
2. **Late READY State Overwrite:** A slow worker establishing TraCI after a startup timeout or stop could overwrite `_startup_status` with `READY`.
3. **TraCI Startup Process-Handle Blind Spot:** During TraCI's connection retry loop (up to 10 seconds), `subprocess.Popen` existed solely as a local variable in `traci.main.start()`, rendering the process unreachable to the watchdog if a timeout fired before socket connection.
4. **API Status Code Inaccuracies:** Simulation stop and start routes returned generic status codes or unconditional `success=True`.

This **Final Lifecycle Hardening** release resolves all four limitations completely, without modifying installed TraCI package files and without using broad process-name kills.

---

## 1. Technical Solutions & Code Changes

### 1.1 Worker Lifecycle Race Guard
- **Source:** [`backend/simulation_service.py`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/backend/simulation_service.py#L400-L416)
- **Problem:** `start_simulation()` checked `self._running` and `self._startup_status in (REQUESTED, STARTING, CONNECTING)`, but omitted `self._thread.is_alive()`. When a worker exited the main simulation loop and entered its `finally:` block to execute `_cleanup_sim()`, `self._running` became `False`, allowing a concurrent `start_simulation()` to overwrite `self._thread` before the previous thread finished releasing TraCI sockets.
- **Solution:** Enforced an atomic check under `self._lock`:
  ```python
  if (
      self._running
      or (self._thread and self._thread.is_alive())
      or self._startup_status in (
          StartupStatus.REQUESTED,
          StartupStatus.STARTING,
          StartupStatus.CONNECTING,
      )
  ):
      return StartupResult(
          False,
          "Simulation is already running or previous worker thread is still cleaning up. Please wait or stop/reset first.",
          StartupStatus.FAILED,
          error="ALREADY_RUNNING",
          run_uuid=self._current_run_uuid,
      )
  ```
- **Verification:** Covered by Scenarios 19a and 19b in [`tests/test_startup_watchdog.py`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/tests/test_startup_watchdog.py#L538-L581).

### 1.2 Late READY State Overwrite Elimination
- **Source:** [`backend/simulation_service.py`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/backend/simulation_service.py#L800-L854)
- **Problem:** If TraCI initialization was slow and `start_simulation()` timed out after `startup_timeout_s`, the caller thread returned `FAILED` and initiated cleanup. If the worker thread subsequently succeeded in connecting to TraCI, it previously published `_startup_status = StartupStatus.READY`, corrupting the session state.
- **Solution:** Added two explicit validation barriers in `_run_simulation_worker()`:
  1. *Pre-start cancellation check* (before calling `sim.start()`):
     ```python
     if self._stop_requested or self._current_run_uuid != session_uuid:
         logger.warning(f"Worker for session {session_uuid} was cancelled before sim.start() was called. Aborting.")
         return
     ```
  2. *Post-start readiness gate* (after `sim.start()` returns):
     ```python
     if (
         self._stop_requested
         or self._current_run_uuid != session_uuid
         or self._startup_status != StartupStatus.CONNECTING
     ):
         logger.warning(
             f"Worker for session {session_uuid} completed startup after shutdown/timeout was requested "
             f"(active UUID: {self._current_run_uuid}, status: {self._startup_status}). Aborting startup publish."
         )
         if not self._startup_event.is_set():
             self._startup_event.set()
         return
     ```
- **Verification:** Covered by Scenario 20 in [`tests/test_startup_watchdog.py`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/tests/test_startup_watchdog.py#L584-L620).

### 1.3 TraCI Startup Process-Handle Blind Spot Elimination
- **Source:** [`traffic_service/sumo_manager.py`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/traffic_service/sumo_manager.py#L103-L127) and [`backend/simulation_service.py`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/backend/simulation_service.py#L746-L752)
- **Problem:** Inside installed TraCI (`traci.main.start()`), `sumoProcess = subprocess.Popen(cmd2, ...)` is assigned to a local variable. During the subsequent connection retry loop (up to 10 retries at 1s intervals), the process handle was unexposed. If startup timed out during this window, `SimulationService._active_sumo_process` remained `None`, leaving the spawned SUMO process orphaned.
- **Solution:** 
  1. Implemented a temporary, scoped `Popen` interception wrapper inside `SumoManager.start()`:
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
  2. Registered `SimulationService._on_process_spawned` callback through `MultiIntersectionSimulation` to store the process handle and PID inside `self._lock` the instant it is spawned.
  3. When startup times out, `_escalate_process_watchdog` terminates the process handle immediately via `proc.terminate()` / `proc.kill()`. The process termination causes `proc.poll() is not None`, immediately breaking TraCI's retry loop and preventing orphaned processes.
  4. Restores `traci.main.subprocess.Popen` in the `finally:` block. No installed TraCI files on disk are modified.
- **Verification:** Covered by Scenario 21 in [`tests/test_startup_watchdog.py`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/tests/test_startup_watchdog.py#L623-L666).

### 1.4 HTTP API Status Code Realignment
- **Source:** [`backend/routers/simulation.py`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/backend/routers/simulation.py#L47-L110)
- **Changes:**
  - `POST /api/simulation/start`:
    - `HTTP 409 Conflict` when simulation is already running or previous worker is still cleaning up.
    - `HTTP 504 Gateway Timeout` when startup times out.
    - `HTTP 500 Internal Server Error` for all other fatal startup exceptions.
  - `POST /api/simulation/stop`:
    - `HTTP 400 Bad Request` when simulation is not running.
    - `HTTP 500 Internal Server Error` when simulation worker fails to terminate within join timeout and watchdog escalation.
    - `HTTP 200 OK` with `CommandResponse(success=True)` on actual successful shutdown.
  - `POST /api/simulation/reset`:
    - `HTTP 500 Internal Server Error` when reset fails.
- **Verification:** Covered by Scenarios 22 and 23 in [`tests/test_startup_watchdog.py`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/tests/test_startup_watchdog.py#L669-L728).

---

## 2. Test Verification Matrix

All 24 scenarios in the hardened watchdog test suite have been executed and verified:

| Scenario | Objective | Verification Method | Outcome |
| :--- | :--- | :--- | :---: |
| **01** | Successful SUMO startup & readiness ack | Real SUMO start, verified `READY` status, non-zero PID | **PASSED** |
| **02** | API response waits until readiness | Measured duration $\ge$ TraCI start duration, verified non-premature return | **PASSED** |
| **03** | SUMO executable missing | Monkeypatched environment check, verified immediate `FAILED` result | **PASSED** |
| **04** | Invalid configuration path | Pointed to non-existent `.sumocfg`, verified `CONFIG_NOT_FOUND` | **PASSED** |
| **05** | TraCI connection failure | Simulated connection failure, verified clean error return | **PASSED** |
| **06** | Startup timeout handling | Forced `startup_timeout_s=0.2`, verified `STARTUP_TIMEOUT` | **PASSED** |
| **07** | Worker exception before readiness | Injected exception prior to readiness, verified clean recovery | **PASSED** |
| **08** | Worker exception after readiness | Injected exception during simulation loop, verified worker cleanup | **PASSED** |
| **09** | Duplicate startup rejection | Called `start_simulation()` twice, verified rejection with `ALREADY_RUNNING` | **PASSED** |
| **10** | Graceful worker shutdown (Tier 1) | Stopped running simulation, verified worker joined without watchdog escalation | **PASSED** |
| **11** | Worker join timeout triggers Tier 2 watchdog | Injected hung worker, verified Tier 2 watchdog escalation | **PASSED** |
| **12** | Graceful SUMO process termination (`terminate()`) | Validated clean process exit via `terminate()` | **PASSED** |
| **13** | Forced SUMO process termination (`kill()`) | Injected stubborn process ignoring `terminate()`, verified `kill()` exit | **PASSED** |
| **14** | Watchdog never terminates unrelated PID | Verified PID matching check prevents terminating mismatched processes | **PASSED** |
| **15** | Old session watchdog cannot terminate new session | Verified UUID matching prevents cross-session termination | **PASSED** |
| **16** | Repeated stop requests handle cleanly | Verified subsequent stop requests return `False` cleanly without errors | **PASSED** |
| **17** | Command cancellation during shutdown | Verified pending queue commands are cancelled with `SIMULATION_STOPPED` | **PASSED** |
| **18** | TraCI closure strictly on worker thread | Verified `traci.close()` is never called from API caller threads | **PASSED** |
| **19a** | Rejection while previous worker in cleanup | Simulated alive worker thread in `_cleanup_sim()`, verified immediate 409 rejection | **PASSED** |
| **19b** | Concurrent startup synchronization | Concurrent threads calling `start_simulation()`, exactly one succeeds | **PASSED** |
| **20** | Late worker does not overwrite state | Injected delayed TraCI start, verified state remains `FAILED`/`ERROR`, never `READY` | **PASSED** |
| **21** | In-flight retry process handle killed on timeout | Spawned process during TraCI retry killed by watchdog without orphan | **PASSED** |
| **22** | HTTP simulation status codes | Tested REST endpoints for `400` (stopped), `409` (duplicate), `504` (timeout) | **PASSED** |
| **23** | HTTP stop returns 500 on worker failure | Mocked un-joinable worker, verified HTTP 500 response | **PASSED** |

### Test Suite Execution Summary
- `pytest -v tests/test_startup_watchdog.py`: **24 / 24 Passed** (100%) in 28.03s.
- `pytest -v tests/test_command_queue.py tests/test_simulation_service.py`: **13 / 13 Passed** (100%) in 15.13s.
- Full Backend Suite `pytest -v`: **73 / 73 Passed** (100%) in 50.79s.
- Frontend Production Build `npm --prefix frontend run build`: **Built successfully** in 12.29s (0 errors).

---

## 3. Preserved Architectural Boundaries

1. **Installed TraCI Code:** Zero modifications were made to `C:\Program Files (x86)\Eclipse\Sumo\tools\traci\`.
2. **Process Termination Safety:** No broad `taskkill /IM sumo.exe /F` or `pkill` commands are used. Every kill operation targets the exact `subprocess.Popen` handle and validated PID belonging exclusively to that specific session.
3. **TraCI Thread Exclusivity:** All calls to `traci.*` remain 100% exclusive to the simulation worker thread (`SumoSimulationWorker`). Caller threads interact exclusively via `queue.Queue` commands and `threading.Event` synchronization.
4. **Corridor and Experiment Integrity:** All SUMO network files (`sumo/silk_board/network/`), routes (`sumo/silk_board/demand/`), and benchmark result CSV files (`outputs/corridor/`) are untouched.
5. **Phase Scope:** Vehicle state streaming, 3D trajectory interpolation, and Phase 2B-3 multi-agent junction controllers were strictly excluded from this task.

---

## 4. Final Sign-off

```
================================================================================
PHASE 2B-2 FINAL LIFECYCLE HARDENING: SIGN-OFF COMPLETE
All 4 verification findings resolved.
24/24 targeted watchdog scenarios passing.
73/73 full regression suite passing.
Frontend production build verified.
Architecture is fully hardened and ready for Phase 2B-3.
================================================================================
```

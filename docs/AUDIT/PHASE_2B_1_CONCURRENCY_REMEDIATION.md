# Phase 2B-1 — Concurrency Defect Remediation Report

**Role:** Senior Python Concurrency Engineer and SUMO/TraCI Specialist  
**Project:** Bengaluru Smart Traffic Coordination System (Silk Board Corridor)  
**Deliverable:** Concurrency Defect Remediation Sign-off  
**Date:** October 30, 2026  
**Status:** Completed and Verified  

---

## 1. Executive Summary

Following the findings of `docs/AUDIT/PHASE_2B_1_INDEPENDENT_VERIFICATION.md`, three specific concurrency vulnerabilities were remediated in the Phase 2B-1 codebase:

1. **`ISS-CONC-01` (Future Timeout and Cancellation Race):** Resolved by implementing an atomic, lock-protected command state machine (`PENDING -> RUNNING -> EXECUTED/REJECTED`, with `TIMED_OUT` and `EXECUTION_OUTCOME_UNKNOWN` branches) preventing `concurrent.futures.InvalidStateError` and distinguishing in-flight timeouts from unexecuted timeouts.
2. **`ISS-CONC-02` (Per-Command Exception Isolation):** Resolved by wrapping each command execution in an isolated `try...except` block in `_process_command_queue()`. Recoverable errors are completed with `COMMAND_EXECUTION_EXCEPTION` without stopping the simulation worker, while fatal TraCI socket errors (`FatalTraCIError`, `ConnectionError`, `BrokenPipeError`) trigger clean, explicit simulation session failures.
3. **`ISS-CONC-03` (TraCI Teardown Ownership Violation):** Resolved by restricting `traci.close()` strictly to the simulation worker thread's `finally:` block in `_run_simulation_worker()`. The caller thread in `stop_simulation()` requests shutdown via `_stop_requested = True`, waits on `join(timeout=5.0)`, and if the worker does not terminate within the timeout, reports shutdown failure/timeout without touching TraCI.

All 12 deterministic remediation tests in `tests/test_command_queue.py` passed, full backend regression testing achieved **49 of 49 passed (100%)**, and the frontend production build succeeded with zero errors.

---

## 2. Issue 1 Remediation — Command State Transition Model

### 2.1 State Transition Model
The `CommandStatus` enumeration was expanded to seven explicit states:
```python
class CommandStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    EXECUTED = "EXECUTED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"
    EXECUTION_OUTCOME_UNKNOWN = "EXECUTION_OUTCOME_UNKNOWN"
```

### 2.2 Thread-Safe State Machine (`SignalOverrideCommand`)
`SignalOverrideCommand` encapsulates an internal `threading.Lock()` (`_state_lock`) governing all state mutations:

```
                      ┌───────────────────────┐
                      │        PENDING        │
                      └──────────┬────────────┘
                                 │
           ┌─────────────────────┼─────────────────────┐
           │ (Caller Timeout)    │ (Worker Dequeue)    │ (Simulation Stop)
           ▼                     ▼                     ▼
┌─────────────────────┐ ┌─────────────────┐ ┌────────────────────┐
│      TIMED_OUT      │ │     RUNNING     │ │     CANCELLED      │
│ (Definitely not run)│ └────────┬────────┘ └────────────────────┘
└─────────────────────┘          │
                   ┌─────────────┴─────────────┐
                   │ (Caller Timeout)          │ (Worker Completion)
                   ▼                           ▼
      ┌─────────────────────────┐   ┌────────────────────────┐
      │EXECUTION_OUTCOME_UNKNOWN│   │  EXECUTED / REJECTED   │
      │   (In-flight timeout)   │   │(Future completed safely│
      └─────────────────────────┘   └────────────────────────┘
```

### 2.3 Atomic Transition Guarantees
1. **Definite Non-Execution (`PENDING -> TIMED_OUT`):**
   When the caller's `cmd.future.result(timeout=timeout_s)` raises `TimeoutError`, caller invokes `cmd.handle_caller_timeout()`. Under `_state_lock`, if state is `PENDING`, it transitions to `TIMED_OUT` and completes the future. When the worker later dequeues `cmd`, `cmd.try_transition_to_running()` returns `False`. The worker drops the command without touching TraCI.
2. **In-Flight Execution Uncertainty (`RUNNING -> EXECUTION_OUTCOME_UNKNOWN`):**
   If worker has already called `cmd.try_transition_to_running()`, the state is `RUNNING`. When caller times out, `handle_caller_timeout()` observes state `RUNNING` and returns `EXECUTION_OUTCOME_UNKNOWN`. **The caller does NOT cancel the underlying Future.**
3. **Immunity to `InvalidStateError`:**
   Because `cmd.future.cancel()` is never called on an in-flight command, when the worker completes TraCI execution, `cmd.complete_execution()` executes `self.future.set_result()` safely on a non-cancelled future.

---

## 3. Issue 2 Remediation — Per-Command Exception Isolation

In `backend/simulation_service.py:888` (`_process_command_queue()`), every dequeued command is wrapped in an explicit multi-tiered exception handler:

```python
try:
    # 1. Atomic transition & session validation
    # 2. Safety constraint validation (emergency, min_green, yellow)
    # 3. TraCI execution: ctrl.request_switch()
    # 4. Success completion: cmd.complete_execution(res)

except (traci.exceptions.FatalTraCIError, ConnectionError, BrokenPipeError) as fatal_exc:
    # TraCI socket connection is broken or closed
    logger.critical(f"Fatal TraCI connection failure: {fatal_exc}", exc_info=True)
    fail_res = CommandResult(False, f"Fatal TraCI error: {fatal_exc}", status=CommandStatus.REJECTED, ...)
    cmd.complete_execution(fail_res)
    raise  # Re-raise to abort worker loop and trigger clean session failure

except Exception as cmd_exc:
    # Non-fatal command error (e.g. controller logic error, invalid parameters)
    logger.exception(f"Command execution error: {cmd_exc}")
    fail_res = CommandResult(False, f"Command execution error: {cmd_exc}", status=CommandStatus.REJECTED, ...)
    cmd.complete_execution(fail_res)
    # Worker continues loop to process subsequent valid commands!
```

### Key Isolation Invariants:
- A single erroneous command completes with `COMMAND_EXECUTION_EXCEPTION` and does **not** terminate the simulation worker thread.
- Subsequent valid commands in the queue continue to be processed.
- Fatal socket breakdowns re-raise, cleanly transitioning the session to `status="ERROR"` rather than running with corrupted state.

---

## 4. Issue 3 Remediation — TraCI Teardown Ownership

### 4.1 Guaranteed Worker Teardown via `finally:`
In `_run_simulation_worker()`, simulation stepping and error handling are structured so that `_cleanup_sim()` is strictly executed in the worker's `finally:` block:

```python
final_st = "STOPPED"
try:
    # simulation init, stepping loop, command processing
    if self._current_sim_time >= self._duration:
        final_st = "COMPLETED"
except Exception as exc:
    logger.exception(f"Simulation run failed: {exc}")
    final_st = "ERROR"
finally:
    with self._lock:
        self._cleanup_sim(final_status=final_st)
```

### 4.2 Non-Blocking Teardown from API Threads
In `stop_simulation()`:
```python
if self._thread and self._thread.is_alive():
    self._thread.join(timeout=5.0)
    if self._thread.is_alive():
        logger.warning(
            "Simulation worker thread did not terminate within 5.0s join timeout. "
            "Shutdown remains pending on worker thread; TraCI will not be closed from caller thread."
        )
        return False, "Simulation worker did not terminate within timeout; shutdown pending."

return True, "Simulation stopped successfully and resources released."
```
If the worker thread fails to join within 5.0 seconds:
- The API thread **does NOT invoke `traci.close()` or `_cleanup_sim()`**.
- The API thread returns `False` with `"Simulation worker did not terminate within timeout; shutdown pending."`.
- TraCI single-thread ownership is preserved 100% across all operational and teardown paths.

---

## 5. Verification and Automated Test Matrix

A comprehensive deterministic test suite was executed in `tests/test_command_queue.py`:

| Test Name | Concurrency Invariant Verified | Outcome |
| :--- | :--- | :---: |
| `test_cancellation_before_dequeue` | Caller timeout in `PENDING` transitions to `TIMED_OUT`; worker skips without executing. | **PASSED** |
| `test_timeout_immediately_before_worker_execution` | Atomic lock race test; worker blocked from running command timed out in `PENDING`. | **PASSED** |
| `test_timeout_after_transition_to_running` | Command in `RUNNING` returns `EXECUTION_OUTCOME_UNKNOWN` to caller; future completes without error. | **PASSED** |
| `test_timeout_while_command_execution_in_progress` | Simulated slow TraCI call; caller returns in-flight timeout, worker finishes cleanly without crash. | **PASSED** |
| `test_successful_completion_after_caller_times_out` | Late completion by worker fulfills future with `EXECUTED` and persists to result. | **PASSED** |
| `test_command_raising_ordinary_exception_followed_by_valid_command` | Exception in command 1 rejects command 1 but does not kill worker; command 2 succeeds. | **PASSED** |
| `test_fatal_traci_connection_failure` | `FatalTraCIError` terminates simulation session cleanly with `ERROR` status. | **PASSED** |
| `test_stop_requested_while_commands_pending` | Simulation stop cancels pending commands in queue with `SIMULATION_STOPPED`. | **PASSED** |
| `test_worker_shutdown_and_connection_closure_on_same_thread` | Asserts `traci.close()` was executed on `SumoSimulationWorker` and not the caller thread. | **PASSED** |
| `test_worker_join_timeout_without_api_thread_traci_access` | Worker join timeout returns `False` and does not call `traci.close()` on caller thread. | **PASSED** |
| `test_session_restart_with_old_commands_pending` | Injected command from old session UUID rejected with `SESSION_EXPIRED`. | **PASSED** |
| `test_concurrent_manual_override_requests` | 6 concurrent client threads issuing overrides execute safely without race conditions. | **PASSED** |

### Test Execution Summary
- `pytest -v tests/test_command_queue.py` -> **12 passed in 15.57s**
- `pytest -v tests/test_simulation_service.py tests/test_simulation_integration.py` -> **3 passed in 7.06s**
- `pytest` (Full Regression Suite) -> **49 passed in 28.14s** (100% pass rate)
- `npm --prefix frontend run build` -> **Clean build in 9.62s** (0 errors)

---

## 6. Remaining Limitations & Boundaries

1. **Watchdog Escalation (Phase 2B-2):** If `SumoSimulationWorker` hangs completely due to an internal SUMO C++ deadlock, `stop_simulation()` currently returns `False` and leaves process cleanup to the OS. Implementing automated subprocess-level watchdogs and SIGKILL escalation is explicitly scheduled for Phase 2B-2.
2. **WebSocket Backpressure (Phase 2B-4):** Telemetry broadcasting currently uses `asyncio.run_coroutine_threadsafe()`. Rate-limiting and frame-skipping will be addressed in Phase 2B-4.

---

## 7. Sign-Off

All three concurrency defects identified in the independent verification report are resolved, verified, and signed off. Phase 2B-1 remediation is complete. Awaiting user authorization to begin Phase 2B-2.

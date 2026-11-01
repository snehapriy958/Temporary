"""
tests/test_command_queue.py

Comprehensive concurrency, safety, and lifecycle verification for the
Thread-Safe TraCI Command Queue (Phase 2B-1 Remediation).

Deterministic verification matrix:
1. Cancellation before dequeue (definitely did not execute).
2. Timeout immediately before worker execution.
3. Timeout after transition to RUNNING (returns EXECUTION_OUTCOME_UNKNOWN without InvalidStateError).
4. Timeout while command execution is in progress.
5. Successful completion after caller times out.
6. Command raising an ordinary exception followed by a valid command.
7. Fatal TraCI connection failure (explicit simulation failure).
8. Stop requested while commands are pending (clean cancellation).
9. Worker shutdown and connection closure occurring strictly on worker thread.
10. Worker join timeout without API-thread TraCI access.
11. Session restart with old commands pending.
12. Concurrent manual override requests.
"""

import concurrent.futures
import threading
import time
import pytest
import traci

from backend.simulation_service import (
    CommandResult,
    CommandStatus,
    SignalOverrideCommand,
    sim_service,
)


@pytest.fixture(autouse=True)
def clean_simulation_state():
    """Ensures simulation is cleanly stopped and reset before and after each test."""
    sim_service.stop_simulation()
    sim_service.reset_simulation()
    yield
    sim_service.stop_simulation()
    sim_service.reset_simulation()


def _start_and_wait_for_running(duration: int = 30) -> None:
    """Helper to start simulation and wait for worker thread to step."""
    ok, msg = sim_service.start_simulation(
        mode="coordinated",
        duration=duration,
        seed=42,
        step_length=1.0,
        decision_interval=5.0,
        enable_emergency=True,
        gui=False,
    )
    assert ok, f"Failed to start simulation: {msg}"
    for _ in range(25):
        if sim_service.get_status().simulation_time > 0.0:
            break
        time.sleep(0.2)
    assert sim_service.get_status().simulation_time > 0.0, "Simulation failed to advance."


# --------------------------------------------------------------------------
# Test 1: Cancellation before dequeue
# --------------------------------------------------------------------------
def test_cancellation_before_dequeue():
    """A command cancelled/timed out while PENDING must definitely not execute."""
    cmd = SignalOverrideCommand(
        command_id="cmd_cancel_before_dequeue",
        session_uuid="test_session_1",
        junction_id="J1",
        target_phase=0,
        confirmed=True,
        created_at=time.time(),
        timeout_s=1.0,
    )

    # Caller times out while still in queue
    timeout_res = cmd.handle_caller_timeout(sim_time=0.0, caller_thread="TestCaller")
    assert timeout_res.status == CommandStatus.TIMED_OUT
    assert timeout_res.rejection_reason == "TIMED_OUT_IN_QUEUE"
    assert "definitely not executed" in timeout_res.message

    # Worker attempts to transition to RUNNING
    can_run = cmd.try_transition_to_running()
    assert can_run is False, "Worker must not be able to execute a cancelled/timed-out command."
    assert cmd.status == CommandStatus.TIMED_OUT


# --------------------------------------------------------------------------
# Test 2: Timeout immediately before worker execution
# --------------------------------------------------------------------------
def test_timeout_immediately_before_worker_execution():
    """
    Caller times out while command is in PENDING state just as worker is about to run.
    The atomic transition must block worker execution and preserve the TIMED_OUT status.
    """
    cmd = SignalOverrideCommand(
        command_id="cmd_timeout_before_exec",
        session_uuid="test_session_2",
        junction_id="J2",
        target_phase=0,
        confirmed=True,
        created_at=time.time(),
        timeout_s=0.5,
    )

    # Caller handles timeout
    res = cmd.handle_caller_timeout(sim_time=5.0, caller_thread="TestCaller")
    assert res.status == CommandStatus.TIMED_OUT

    # Worker arrives and calls try_transition_to_running()
    assert cmd.try_transition_to_running() is False
    assert cmd.status == CommandStatus.TIMED_OUT


# --------------------------------------------------------------------------
# Test 3: Timeout after transition to RUNNING
# --------------------------------------------------------------------------
def test_timeout_after_transition_to_running():
    """
    Once the worker atomically transitions the command to RUNNING, caller timeout
    must report EXECUTION_OUTCOME_UNKNOWN without cancelling the future or raising InvalidStateError.
    """
    cmd = SignalOverrideCommand(
        command_id="cmd_timeout_after_running",
        session_uuid="test_session_3",
        junction_id="J1",
        target_phase=0,
        confirmed=True,
        created_at=time.time(),
        timeout_s=1.0,
    )

    # Worker transitions command to RUNNING
    assert cmd.try_transition_to_running() is True
    assert cmd.status == CommandStatus.RUNNING

    # Caller times out while in-flight
    caller_res = cmd.handle_caller_timeout(sim_time=10.0, caller_thread="TestCaller")
    assert caller_res.status == CommandStatus.EXECUTION_OUTCOME_UNKNOWN
    assert caller_res.rejection_reason == "IN_FLIGHT_TIMEOUT"
    assert "unknown" in caller_res.message.lower()

    # Worker finishes execution later and completes future
    worker_res = CommandResult(
        success=True,
        message="Manual override applied.",
        status=CommandStatus.EXECUTED,
        junction_id="J1",
        applied_phase=0,
        simulation_time=10.0,
        command_id=cmd.command_id,
        executing_thread="SumoSimulationWorker",
    )
    # Must NOT raise InvalidStateError!
    cmd.complete_execution(worker_res)
    assert cmd.future.done()
    assert cmd.future.result().status == CommandStatus.EXECUTED


# --------------------------------------------------------------------------
# Test 4: Timeout while command execution is in progress
# --------------------------------------------------------------------------
def test_timeout_while_command_execution_in_progress():
    """
    Simulates a slow TraCI operation using synchronization events.
    Verifies caller receives EXECUTION_OUTCOME_UNKNOWN and worker completes cleanly.
    """
    _start_and_wait_for_running()

    execution_started = threading.Event()
    proceed_execution = threading.Event()

    ctrl = sim_service._sim.controllers["J1"]
    original_get_phase = ctrl.get_phase

    def slow_get_phase():
        execution_started.set()
        proceed_execution.wait(timeout=2.0)
        return original_get_phase()

    ctrl.get_phase = slow_get_phase

    try:
        # Submit command with very short timeout (0.1s)
        # Using a background thread to submit
        res_container = []

        def submit_task():
            res = sim_service.request_manual_override("J1", target_phase=0, confirmed=True, timeout_s=0.1)
            res_container.append(res)

        sub_thread = threading.Thread(target=submit_task)
        sub_thread.start()

        # Wait until execution has started on worker
        assert execution_started.wait(timeout=3.0), "Worker did not begin command execution."

        # Wait for caller thread to time out
        sub_thread.join(timeout=2.0)
        assert len(res_container) == 1
        caller_res = res_container[0]

        assert caller_res.status == CommandStatus.EXECUTION_OUTCOME_UNKNOWN
        assert caller_res.rejection_reason == "IN_FLIGHT_TIMEOUT"

    finally:
        proceed_execution.set()
        ctrl.get_phase = original_get_phase


# --------------------------------------------------------------------------
# Test 5: Successful completion after caller times out
# --------------------------------------------------------------------------
def test_successful_completion_after_caller_times_out():
    """
    Verifies that when caller times out in-flight, the worker's eventual successful
    result is recorded without crashing the simulation.
    """
    cmd = SignalOverrideCommand(
        command_id="cmd_late_completion",
        session_uuid="test_session_5",
        junction_id="J2",
        target_phase=0,
        confirmed=True,
        created_at=time.time(),
        timeout_s=0.2,
    )

    assert cmd.try_transition_to_running() is True
    caller_res = cmd.handle_caller_timeout(sim_time=12.0, caller_thread="APIThread")
    assert caller_res.status == CommandStatus.EXECUTION_OUTCOME_UNKNOWN

    # Late execution result from worker
    exec_res = CommandResult(
        success=True,
        message="Manual override applied successfully.",
        status=CommandStatus.EXECUTED,
        junction_id="J2",
        applied_phase=0,
        simulation_time=12.0,
        command_id=cmd.command_id,
        executing_thread="SumoSimulationWorker",
    )
    cmd.complete_execution(exec_res)

    assert cmd.result == exec_res
    assert cmd.future.result() == exec_res


# --------------------------------------------------------------------------
# Test 6: Command raising an ordinary exception followed by a valid command
# --------------------------------------------------------------------------
def test_command_raising_ordinary_exception_followed_by_valid_command():
    """
    Verifies per-command exception isolation:
    An exception in command 1 must NOT kill the worker thread or prevent command 2.
    """
    _start_and_wait_for_running()

    # Enqueue command 1 with an invalid target that raises an exception in controller
    ctrl = sim_service._sim.controllers["J1"]
    original_get_phase = ctrl.get_phase

    call_count = {"j1": 0}

    def failing_get_phase():
        call_count["j1"] += 1
        if call_count["j1"] == 1:
            raise ValueError("Simulated unexpected controller logic failure")
        return original_get_phase()

    ctrl.get_phase = failing_get_phase

    try:
        # Command 1 fails with ValueError
        res1 = sim_service.request_manual_override("J1", target_phase=0, confirmed=True, timeout_s=3.0)
        assert res1.success is False
        assert res1.status == CommandStatus.REJECTED
        assert res1.rejection_reason == "COMMAND_EXECUTION_EXCEPTION"
        assert "Simulated unexpected controller logic failure" in res1.message

        # Simulation worker must still be running and stepping!
        time.sleep(0.5)
        assert sim_service.get_status().running is True

        # Command 2 on J2 must succeed cleanly!
        res2 = sim_service.request_manual_override("J2", target_phase=0, confirmed=True, timeout_s=3.0)
        assert res2.success is True
        assert res2.status == CommandStatus.EXECUTED

    finally:
        ctrl.get_phase = original_get_phase


# --------------------------------------------------------------------------
# Test 7: Fatal TraCI connection failure
# --------------------------------------------------------------------------
def test_fatal_traci_connection_failure():
    """
    A fatal TraCI connection error must explicitly fail the simulation session
    rather than continuing with corrupted state.
    """
    _start_and_wait_for_running()

    ctrl = sim_service._sim.controllers["J1"]
    original_get_phase = ctrl.get_phase

    def fatal_get_phase():
        raise traci.exceptions.FatalTraCIError("Connection reset by peer: fatal socket failure")

    ctrl.get_phase = fatal_get_phase

    try:
        res = sim_service.request_manual_override("J1", target_phase=0, confirmed=True, timeout_s=3.0)
        assert res.success is False
        assert res.status == CommandStatus.REJECTED
        assert res.rejection_reason == "FATAL_TRACI_ERROR"

        # Allow worker thread to process fatal exception
        time.sleep(0.5)
        status = sim_service.get_status()
        assert status.running is False, "Simulation must stop running on fatal TraCI error."

    finally:
        ctrl.get_phase = original_get_phase


# --------------------------------------------------------------------------
# Test 8: Stop requested while commands are pending
# --------------------------------------------------------------------------
def test_stop_requested_while_commands_pending():
    """All pending commands must be cleanly cancelled when simulation is stopped."""
    _start_and_wait_for_running()

    # Pause simulation to accumulate commands
    sim_service.pause_simulation()

    cmd = SignalOverrideCommand(
        command_id="cmd_pending_on_stop",
        session_uuid=sim_service._current_run_uuid or "",
        junction_id="J1",
        target_phase=0,
        confirmed=True,
        created_at=time.time(),
        timeout_s=10.0,
    )
    with sim_service._lock:
        sim_service._command_queue.put_nowait(cmd)

    # Stop simulation
    stop_ok, _ = sim_service.stop_simulation()
    assert stop_ok

    assert cmd.future.done()
    res = cmd.future.result()
    assert res.success is False
    assert res.status == CommandStatus.CANCELLED
    assert res.rejection_reason == "SIMULATION_STOPPED"


# --------------------------------------------------------------------------
# Test 9: Worker shutdown and connection closure on same thread
# --------------------------------------------------------------------------
def test_worker_shutdown_and_connection_closure_on_same_thread():
    """
    Asserts that TraCI connection closure occurs strictly on the SumoSimulationWorker thread.
    """
    _start_and_wait_for_running()

    close_threads = []
    original_close = sim_service._sim.sumo_manager.stop

    def instrumented_stop():
        close_threads.append(threading.current_thread().name)
        original_close()

    sim_service._sim.sumo_manager.stop = instrumented_stop

    caller_thread = threading.current_thread().name
    stop_ok, _ = sim_service.stop_simulation()
    assert stop_ok

    assert len(close_threads) == 1
    assert close_threads[0] == "SumoSimulationWorker"
    assert close_threads[0] != caller_thread


# --------------------------------------------------------------------------
# Test 10: Worker join timeout without API-thread TraCI access
# --------------------------------------------------------------------------
def test_worker_join_timeout_without_api_thread_traci_access(monkeypatch):
    """
    If the worker thread fails to join within timeout, stop_simulation() must
    report failure and NOT call traci.close() from the caller thread.
    """
    _start_and_wait_for_running()

    caller_traci_calls = []

    def mock_traci_close():
        caller_traci_calls.append(threading.current_thread().name)

    monkeypatch.setattr(traci, "close", mock_traci_close)

    # Simulate thread.join timeout by making join do nothing while thread stays alive
    worker_thread = sim_service._thread

    def mock_join(timeout=None):
        pass  # simulate join timing out while worker thread is still alive

    monkeypatch.setattr(worker_thread, "join", mock_join)
    monkeypatch.setattr(worker_thread, "is_alive", lambda: True)

    # stop_simulation should detect that the thread is still alive
    stop_ok, stop_msg = sim_service.stop_simulation()
    assert stop_ok is False
    assert "did not terminate within timeout" in stop_msg.lower()
    assert "shutdown pending" in stop_msg.lower()

    # The caller thread must NOT have executed traci.close()!
    assert threading.current_thread().name not in caller_traci_calls


# --------------------------------------------------------------------------
# Test 11: Session restart with old commands pending
# --------------------------------------------------------------------------
def test_session_restart_with_old_commands_pending():
    """Commands carrying a previous session UUID must be cancelled with SESSION_EXPIRED."""
    _start_and_wait_for_running()

    cmd = SignalOverrideCommand(
        command_id="cmd_old_session",
        session_uuid="run_stale_expired_uuid_888",
        junction_id="J1",
        target_phase=0,
        confirmed=True,
        created_at=time.time(),
        timeout_s=5.0,
    )
    with sim_service._lock:
        sim_service._command_queue.put_nowait(cmd)

    res = cmd.future.result(timeout=3.0)
    assert res.success is False
    assert res.status == CommandStatus.CANCELLED
    assert res.rejection_reason == "SESSION_EXPIRED"


# --------------------------------------------------------------------------
# Test 12: Concurrent manual override requests
# --------------------------------------------------------------------------
def test_concurrent_manual_override_requests():
    """Verify concurrent overrides from multiple threads execute safely without race conditions."""
    _start_and_wait_for_running(duration=60)

    num_threads = 6
    results = [None] * num_threads

    def worker_task(idx, j_id, phase):
        res = sim_service.request_manual_override(j_id, target_phase=phase, confirmed=True, timeout_s=4.0)
        results[idx] = res

    threads = []
    junction_cycle = ["J1", "J2", "J3", "J1", "J2", "J3"]
    for i in range(num_threads):
        t = threading.Thread(
            target=worker_task,
            args=(i, junction_cycle[i], 0),
            name=f"ConcurrentTestThread-{i}",
        )
        threads.append(t)
        t.start()

    for t in threads:
        t.join(timeout=5.0)
        assert not t.is_alive(), "Worker thread hung waiting for override response."

    for idx, res in enumerate(results):
        assert res is not None, f"Thread {idx} got no result"
        assert isinstance(res, CommandResult)
        assert res.status in {CommandStatus.EXECUTED, CommandStatus.REJECTED}
        assert res.executing_thread == "SumoSimulationWorker"

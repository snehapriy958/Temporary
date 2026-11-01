"""
tests/test_startup_watchdog.py

Comprehensive test suite for Phase 2B-2:
Synchronous SUMO Startup and Controlled Process Watchdogs.

18 Deterministic Verification Scenarios:
1. Successful SUMO startup and readiness acknowledgement.
2. API response waits until readiness.
3. SUMO executable missing.
4. Invalid configuration path.
5. TraCI connection failure.
6. Startup timeout.
7. Worker exception before readiness.
8. Worker exception after readiness.
9. Duplicate startup request while starting or running.
10. Graceful worker shutdown (Tier 1 without watchdog escalation).
11. Worker join timeout triggers Tier 2 watchdog.
12. Graceful SUMO process termination (process.terminate()).
13. Forced SUMO process termination (process.kill()) after grace period.
14. Watchdog never terminates an unrelated process or mismatched PID.
15. Old session watchdog cannot terminate a newer session process.
16. Repeated stop requests handle cleanly without errors.
17. Pending command cancellation during shutdown.
18. TraCI connection closure occurs strictly on the simulation worker thread.
19. Duplicate startup rejected while previous worker is cleaning up / alive.
20. Late worker after startup timeout or stop does not publish READY.
21. TraCI connection retry process handle captured and terminated on timeout.
22. HTTP simulation router status codes (400 on stop when stopped, 409 on duplicate start, 504 on timeout).
23. HTTP simulation stop returns 500 when worker fails to terminate.
24. subprocess.Popen remains identical before, during, and after TraCI startup interception.
25. An unrelated thread can launch a subprocess during SUMO startup without being captured.
26. The actual SUMO process is captured correctly with matching PID and active handle.
27. Two concurrent SUMO startup attempts serialize via _traci_startup_lock without corrupting proxy state.
28. An exception during TraCI startup restores the original module reference and releases the lock.
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import traci
from fastapi.testclient import TestClient

from backend.config import SUMO_CONFIG_PATH
from backend.main import app
from backend.simulation_service import (
    CommandResult,
    CommandStatus,
    SignalOverrideCommand,
    StartupResult,
    StartupStatus,
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


# --------------------------------------------------------------------------
# Scenario 1: Successful SUMO startup and readiness acknowledgement (Real SUMO)
# --------------------------------------------------------------------------
def test_successful_sumo_startup_and_readiness_acknowledgement():
    """Real SUMO startup: start_simulation() blocks until worker signals READY, returning PID and duration."""
    res = sim_service.start_simulation(
        mode="coordinated",
        duration=30,
        seed=42,
        step_length=1.0,
        decision_interval=5.0,
        enable_emergency=True,
        gui=False,
        startup_timeout_s=10.0,
    )
    assert res.success is True
    assert res.status == StartupStatus.READY
    assert res.pid is not None
    assert res.pid > 0
    assert res.startup_duration_s > 0.0
    assert res.run_uuid is not None

    # Verify status query
    status = sim_service.get_status()
    assert status.running is True
    assert status.status == "READY"
    assert status.pid == res.pid

    stop_ok, stop_msg = sim_service.stop_simulation()
    assert stop_ok is True


# --------------------------------------------------------------------------
# Scenario 2: API response waits until readiness
# --------------------------------------------------------------------------
def test_api_response_waits_until_readiness(monkeypatch):
    """start_simulation() blocks and does not return while worker is in STARTING or CONNECTING."""
    lifecycle_states_observed = []
    ready_barrier = threading.Event()

    original_start = sim_service._run_simulation_worker

    def slow_worker():
        # Inspect state early in worker
        time.sleep(0.05)
        lifecycle_states_observed.append(sim_service.get_status().status)
        ready_barrier.wait(timeout=2.0)
        original_start()

    # Wrap worker thread spawning
    monkeypatch.setattr(sim_service, "_run_simulation_worker", slow_worker)

    def release_worker():
        time.sleep(0.2)
        ready_barrier.set()

    releaser = threading.Thread(target=release_worker, daemon=True)
    releaser.start()

    res = sim_service.start_simulation(
        mode="coordinated",
        duration=20,
        startup_timeout_s=5.0,
    )
    releaser.join(timeout=2.0)

    assert res.success is True
    assert res.status == StartupStatus.READY
    # During worker launch, state was STARTING or CONNECTING (not RUNNING or READY)
    assert any(s in ("STARTING", "CONNECTING", "REQUESTED") for s in lifecycle_states_observed)


# --------------------------------------------------------------------------
# Scenario 3: SUMO executable missing
# --------------------------------------------------------------------------
def test_sumo_executable_missing(monkeypatch):
    """When SUMO binary is missing, worker returns clean failure with error details."""
    import traffic_service.sumo_manager
    from common.sumo_env import SumoEnvironmentError

    monkeypatch.setattr(
        traffic_service.sumo_manager,
        "require_sumo_env",
        MagicMock(side_effect=SumoEnvironmentError("SUMO executable not found.")),
    )

    res = sim_service.start_simulation(
        mode="coordinated",
        duration=20,
        startup_timeout_s=5.0,
    )
    assert res.success is False
    assert res.status == StartupStatus.FAILED
    assert "SUMO executable not found" in res.message or "SUMO" in str(res.error)

    status = sim_service.get_status()
    assert status.running is False
    assert status.status == "FAILED" or status.status == "ERROR"


# --------------------------------------------------------------------------
# Scenario 4: Invalid configuration path
# --------------------------------------------------------------------------
def test_invalid_configuration_path(monkeypatch):
    """Missing config file returns failure immediately without orphaned threads."""
    monkeypatch.setattr("backend.simulation_service.SUMO_CONFIG_PATH", Path("C:/invalid/path/sumo.sumocfg"))

    res = sim_service.start_simulation(
        mode="coordinated",
        duration=20,
        startup_timeout_s=5.0,
    )
    assert res.success is False
    assert res.status == StartupStatus.FAILED
    assert res.error == "CONFIG_NOT_FOUND" or "not found" in res.message.lower()

    # Worker thread must be cleanly joined
    if sim_service._thread:
        assert not sim_service._thread.is_alive()


# --------------------------------------------------------------------------
# Scenario 5: TraCI connection failure
# --------------------------------------------------------------------------
def test_traci_connection_failure(monkeypatch):
    """Fatal TraCI connection error during start() returns clean failure with root cause."""
    def mock_traci_start(*args, **kwargs):
        raise traci.exceptions.FatalTraCIError("Simulated TraCI socket binding error.")

    monkeypatch.setattr(traci, "start", mock_traci_start)

    res = sim_service.start_simulation(
        mode="coordinated",
        duration=20,
        startup_timeout_s=5.0,
    )
    assert res.success is False
    assert res.status == StartupStatus.FAILED
    assert "TraCI socket binding error" in res.message or "TraCI" in res.error

    status = sim_service.get_status()
    assert status.running is False


# --------------------------------------------------------------------------
# Scenario 6: Startup timeout
# --------------------------------------------------------------------------
def test_startup_timeout(monkeypatch):
    """When worker does not signal readiness within timeout, start_simulation returns timeout failure."""
    def hanging_worker():
        # Simulate worker hung during connection
        time.sleep(2.0)

    monkeypatch.setattr(sim_service, "_run_simulation_worker", hanging_worker)

    res = sim_service.start_simulation(
        mode="coordinated",
        duration=20,
        startup_timeout_s=0.3,
    )
    assert res.success is False
    assert res.status == StartupStatus.FAILED
    assert res.error == "STARTUP_TIMEOUT" or "timed out" in res.message.lower()

    status = sim_service.get_status()
    assert status.running is False


# --------------------------------------------------------------------------
# Scenario 7: Worker exception before readiness
# --------------------------------------------------------------------------
def test_worker_exception_before_readiness(monkeypatch):
    """Exception raised inside worker before readiness signals failure immediately."""
    def failing_init(*args, **kwargs):
        raise RuntimeError("Simulated failure during MultiIntersectionSimulation initialization.")

    monkeypatch.setattr("backend.simulation_service.MultiIntersectionSimulation", failing_init)

    res = sim_service.start_simulation(
        mode="coordinated",
        duration=20,
        startup_timeout_s=5.0,
    )
    assert res.success is False
    assert res.status == StartupStatus.FAILED
    assert "Simulated failure" in res.message

    status = sim_service.get_status()
    assert status.running is False


# --------------------------------------------------------------------------
# Scenario 8: Worker exception after readiness
# --------------------------------------------------------------------------
def test_worker_exception_after_readiness(monkeypatch):
    """Exception occurring in worker step loop after readiness cleans up and sets ERROR status."""
    step_count = 0

    def failing_step():
        nonlocal step_count
        step_count += 1
        if step_count >= 2:
            raise RuntimeError("Simulated runtime crash during simulationStep()")
        return float(step_count)

    # Start real simulation
    res = sim_service.start_simulation(
        mode="coordinated",
        duration=30,
        startup_timeout_s=10.0,
    )
    assert res.success is True

    # Monkeypatch step on the active manager
    sim_service._sim.sumo_manager.step = failing_step

    # Wait for crash and cleanup
    time.sleep(0.5)
    if sim_service._thread and sim_service._thread.is_alive():
        sim_service._thread.join(timeout=2.0)

    status = sim_service.get_status()
    assert status.running is False
    assert status.status == "ERROR" or sim_service._error_message is not None


# --------------------------------------------------------------------------
# Scenario 9: Duplicate startup request
# --------------------------------------------------------------------------
def test_duplicate_startup_request():
    """Second start request while first is already active is immediately rejected."""
    res1 = sim_service.start_simulation(mode="coordinated", duration=30, startup_timeout_s=10.0)
    assert res1.success is True

    # Attempt second start
    res2 = sim_service.start_simulation(mode="coordinated", duration=30, startup_timeout_s=5.0)
    assert res2.success is False
    assert res2.status == StartupStatus.FAILED
    assert "already" in res2.message.lower()

    sim_service.stop_simulation()


# --------------------------------------------------------------------------
# Scenario 10: Graceful worker shutdown (Tier 1)
# --------------------------------------------------------------------------
def test_graceful_worker_shutdown():
    """stop_simulation() terminates worker within grace period without triggering watchdog."""
    res = sim_service.start_simulation(mode="coordinated", duration=30, startup_timeout_s=10.0)
    assert res.success is True

    stop_ok, stop_msg = sim_service.stop_simulation()
    assert stop_ok is True
    assert "stopped successfully" in stop_msg.lower()
    assert sim_service._watchdog_escalated is False

    status = sim_service.get_status()
    assert status.running is False
    assert status.status in ("STOPPED", "COMPLETED")


# --------------------------------------------------------------------------
# Scenario 11: Worker join timeout triggers Tier 2 watchdog
# --------------------------------------------------------------------------
def test_worker_join_timeout_triggers_watchdog(monkeypatch):
    """When worker fails to exit within 5.0s, watchdog escalation is triggered."""
    res = sim_service.start_simulation(mode="coordinated", duration=30, startup_timeout_s=10.0)
    assert res.success is True

    worker_thread = sim_service._thread
    join_calls = []

    # Simulate thread join timeout
    def mock_join(timeout=None):
        join_calls.append(timeout)
        pass  # does not block or terminate

    monkeypatch.setattr(worker_thread, "join", mock_join)

    watchdog_called = []
    original_watchdog = sim_service._escalate_process_watchdog

    def mock_watchdog(proc, pid, uuid):
        watchdog_called.append((proc, pid, uuid))
        return original_watchdog(proc, pid, uuid)

    monkeypatch.setattr(sim_service, "_escalate_process_watchdog", mock_watchdog)

    stop_ok, stop_msg = sim_service.stop_simulation()
    assert len(watchdog_called) == 1
    assert "watchdog escalated" in stop_msg.lower()
    assert sim_service._watchdog_escalated is True


# --------------------------------------------------------------------------
# Scenario 12: Graceful SUMO process termination via process.terminate()
# --------------------------------------------------------------------------
def test_graceful_sumo_process_termination():
    """Watchdog terminates SUMO process via terminate() without calling kill()."""
    mock_process = MagicMock(spec=subprocess.Popen)
    mock_process.pid = 99911
    mock_process.poll.return_value = None  # initially alive
    mock_process.wait.return_value = 0     # terminates cleanly on wait()

    terminated = sim_service._escalate_process_watchdog(
        target_process=mock_process,
        target_pid=99911,
        target_uuid="test_run_uuid_12",
    )
    assert terminated is True
    mock_process.terminate.assert_called_once()
    mock_process.kill.assert_not_called()
    assert sim_service._watchdog_escalated is True


# --------------------------------------------------------------------------
# Scenario 13: Forced SUMO process termination via process.kill()
# --------------------------------------------------------------------------
def test_forced_sumo_process_termination_after_grace_period():
    """If process.terminate() times out, watchdog escalates to process.kill()."""
    mock_process = MagicMock(spec=subprocess.Popen)
    mock_process.pid = 99922
    mock_process.poll.return_value = None

    # First wait() call after terminate() times out; second wait() after kill() succeeds
    mock_process.wait.side_effect = [subprocess.TimeoutExpired(cmd="sumo", timeout=3.0), 0]

    terminated = sim_service._escalate_process_watchdog(
        target_process=mock_process,
        target_pid=99922,
        target_uuid="test_run_uuid_13",
    )
    assert terminated is True
    mock_process.terminate.assert_called_once()
    mock_process.kill.assert_called_once()


# --------------------------------------------------------------------------
# Scenario 14: Watchdog never terminates an unrelated process or mismatched PID
# --------------------------------------------------------------------------
def test_watchdog_never_terminates_unrelated_process():
    """If target_process.pid does not match expected target_pid, watchdog aborts."""
    mock_process = MagicMock(spec=subprocess.Popen)
    mock_process.pid = 11111  # different PID

    terminated = sim_service._escalate_process_watchdog(
        target_process=mock_process,
        target_pid=22222,  # mismatched PID
        target_uuid="test_run_uuid_14",
    )
    assert terminated is False
    mock_process.terminate.assert_not_called()
    mock_process.kill.assert_not_called()


# --------------------------------------------------------------------------
# Scenario 15: Old session watchdog cannot terminate a newer session process
# --------------------------------------------------------------------------
def test_old_session_watchdog_cannot_terminate_newer_session():
    """Watchdog belonging to Session A targets only Session A's process handle, leaving Session B intact."""
    session_a_proc = MagicMock(spec=subprocess.Popen)
    session_a_proc.pid = 30001
    session_a_proc.poll.return_value = None

    session_b_proc = MagicMock(spec=subprocess.Popen)
    session_b_proc.pid = 30002
    session_b_proc.poll.return_value = None

    # Active session is B
    sim_service._active_sumo_process = session_b_proc
    sim_service._active_sumo_pid = 30002
    sim_service._current_run_uuid = "session_b_uuid"

    # Watchdog fires for Session A
    terminated = sim_service._escalate_process_watchdog(
        target_process=session_a_proc,
        target_pid=30001,
        target_uuid="session_a_uuid",
    )
    assert terminated is True
    # Session A was terminated
    session_a_proc.terminate.assert_called_once()
    # Session B process was NEVER touched
    session_b_proc.terminate.assert_not_called()
    session_b_proc.kill.assert_not_called()


# --------------------------------------------------------------------------
# Scenario 16: Repeated stop request
# --------------------------------------------------------------------------
def test_repeated_stop_requests_handle_cleanly():
    """Successive stop requests when simulation is already stopped return False cleanly."""
    res = sim_service.start_simulation(mode="coordinated", duration=30, startup_timeout_s=10.0)
    assert res.success is True

    ok1, msg1 = sim_service.stop_simulation()
    assert ok1 is True

    ok2, msg2 = sim_service.stop_simulation()
    assert ok2 is False
    assert "not currently running" in msg2.lower()

    ok3, msg3 = sim_service.stop_simulation()
    assert ok3 is False
    assert "not currently running" in msg3.lower()


# --------------------------------------------------------------------------
# Scenario 17: Pending command cancellation during shutdown
# --------------------------------------------------------------------------
def test_pending_command_cancellation_during_shutdown():
    """Commands enqueued right as simulation stops are cancelled with SIMULATION_STOPPED."""
    res = sim_service.start_simulation(mode="coordinated", duration=30, startup_timeout_s=10.0)
    assert res.success is True

    # Enqueue command
    cmd = SignalOverrideCommand(
        command_id="cmd_shutdown_test",
        session_uuid=sim_service._current_run_uuid or "",
        junction_id="J1",
        target_phase=2,
        confirmed=True,
        created_at=time.time(),
        timeout_s=10.0,
    )
    sim_service._command_queue.put_nowait(cmd)

    # Stop simulation
    sim_service.stop_simulation()

    # The command must be cancelled with status CANCELLED and SIMULATION_STOPPED
    assert cmd.status == CommandStatus.CANCELLED
    assert cmd.future.done()
    result = cmd.future.result()
    assert result.success is False
    assert result.status == CommandStatus.CANCELLED
    assert "SIMULATION_STOPPED" in result.message


# --------------------------------------------------------------------------
# Scenario 18: TraCI connection closure occurs strictly on simulation worker thread
# --------------------------------------------------------------------------
def test_traci_closure_strictly_on_worker_thread(monkeypatch):
    """traci.close() is invoked exclusively by the simulation worker thread, never by API caller threads."""
    closing_threads = []
    original_stop = sim_service._sim

    res = sim_service.start_simulation(mode="coordinated", duration=30, startup_timeout_s=10.0)
    assert res.success is True

    real_close = traci.close

    def tracking_close():
        closing_threads.append(threading.current_thread().name)
        real_close()

    monkeypatch.setattr(traci, "close", tracking_close)

    # Caller thread triggers stop
    caller_thread_name = threading.current_thread().name
    stop_ok, _ = sim_service.stop_simulation()
    assert stop_ok is True

    # Verify that traci.close was NOT called from caller thread
    assert caller_thread_name not in closing_threads
    # And was called on SumoSimulationWorker
    if closing_threads:
        assert all("SumoSimulationWorker" in name for name in closing_threads)


# --------------------------------------------------------------------------
# Scenario 19: Duplicate startup rejected while previous worker is cleaning up / alive
# --------------------------------------------------------------------------
def test_startup_rejected_while_previous_worker_is_alive_in_cleanup():
    """Duplicate startup is strictly rejected while previous worker thread is still alive in _cleanup_sim()."""
    cleanup_started = threading.Event()
    cleanup_release = threading.Event()

    def fake_slow_worker():
        cleanup_started.set()
        cleanup_release.wait(timeout=2.0)

    slow_thread = threading.Thread(target=fake_slow_worker, name="SumoSimulationWorker")
    slow_thread.start()
    cleanup_started.wait(timeout=1.0)

    sim_service._thread = slow_thread
    try:
        res = sim_service.start_simulation(mode="coordinated", duration=30, startup_timeout_s=2.0)
        assert res.success is False
        assert res.error == "ALREADY_RUNNING"
        assert "cleaning up" in res.message.lower() or "already running" in res.message.lower()
    finally:
        cleanup_release.set()
        slow_thread.join(timeout=2.0)


def test_concurrent_startup_requests_are_synchronized():
    """Two concurrent start requests from different caller threads are synchronized; exactly one proceeds."""
    results = []

    def caller():
        res = sim_service.start_simulation(mode="coordinated", duration=15, startup_timeout_s=10.0)
        results.append(res)

    t1 = threading.Thread(target=caller)
    t2 = threading.Thread(target=caller)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    successes = [r for r in results if r.success]
    failures = [r for r in results if not r.success]
    assert len(successes) == 1
    assert len(failures) == 1
    assert failures[0].error == "ALREADY_RUNNING"


# --------------------------------------------------------------------------
# Scenario 20: Late worker after startup timeout or stop does not publish READY
# --------------------------------------------------------------------------
def test_late_worker_after_startup_timeout_does_not_publish_ready(monkeypatch):
    """If startup timeout fires before TraCI finishes starting, late worker must not publish READY or overwrite state."""
    worker_started = threading.Event()
    release_start = threading.Event()

    from traffic_service.multi_intersection_simulation import MultiIntersectionSimulation
    original_start = MultiIntersectionSimulation.start

    def delayed_start(self, seed=42):
        worker_started.set()
        release_start.wait(timeout=3.0)
        original_start(self, seed=seed)

    monkeypatch.setattr(MultiIntersectionSimulation, "start", delayed_start)

    # Start simulation with very short startup timeout
    res = sim_service.start_simulation(mode="coordinated", duration=15, startup_timeout_s=0.3)
    assert res.success is False
    assert res.error == "STARTUP_TIMEOUT"
    assert sim_service._startup_status in (StartupStatus.FAILED, "ERROR", "KILLED_BY_WATCHDOG")

    # Now release worker to finish its delayed start()
    release_start.set()
    time.sleep(0.5)

    # State must NOT have transitioned to READY
    assert sim_service._startup_status != StartupStatus.READY
    assert sim_service._running is False


# --------------------------------------------------------------------------
# Scenario 21: TraCI connection retry process handle captured and terminated on timeout
# --------------------------------------------------------------------------
def test_traci_retry_process_handle_captured_and_killed_on_timeout(monkeypatch):
    """
    During TraCI's connection retry loop, the spawned process handle is captured
    immediately via _TraciScopedSubprocessProxy and successfully terminated upon timeout.
    Exercises the actual SumoManager.start proxying mechanism without monkeypatching SumoManager.start.
    """
    spawned_procs = []

    def mock_traci_start(cmd, label="default"):
        # traci.main.subprocess is the actual _TraciScopedSubprocessProxy installed by SumoManager.start
        test_cmd = [sys.executable, "-c", "import time; time.sleep(30)", "--sumo-marker"]
        proc = traci.main.subprocess.Popen(test_cmd)
        spawned_procs.append(proc)
        # Simulate TraCI socket retry loop hanging
        time.sleep(5.0)

    monkeypatch.setattr(traci, "start", mock_traci_start)

    res = sim_service.start_simulation(mode="coordinated", duration=15, startup_timeout_s=0.4)
    assert res.success is False
    assert res.error == "STARTUP_TIMEOUT"

    assert len(spawned_procs) == 1
    proc = spawned_procs[0]
    time.sleep(0.5)
    # The process must be dead (poll() is not None)
    assert proc.poll() is not None, "Spawned process was orphaned and remained alive after startup timeout!"


# --------------------------------------------------------------------------
# Scenario 22: HTTP simulation router status codes
# --------------------------------------------------------------------------
def test_api_simulation_status_codes():
    """Verify HTTP status codes: 400 for stop when stopped, 409 for duplicate start, 504 on startup timeout."""
    client = TestClient(app)

    # 1. POST /stop when simulation is not running -> 400 Bad Request
    res_stop = client.post("/api/simulation/stop")
    assert res_stop.status_code == 400
    assert "not currently running" in res_stop.json()["detail"].lower()

    # 2. POST /start successfully
    res_start = client.post("/api/simulation/start", json={"mode": "coordinated", "duration": 30})
    assert res_start.status_code == 200
    assert res_start.json()["success"] is True

    # 3. POST /start while already running -> 409 Conflict
    res_dup = client.post("/api/simulation/start", json={"mode": "coordinated", "duration": 30})
    assert res_dup.status_code == 409
    assert "already running" in res_dup.json()["detail"].lower()

    # Clean stop
    res_stop_ok = client.post("/api/simulation/stop")
    assert res_stop_ok.status_code == 200

    # 4. POST /start with timeout -> 504 Gateway Timeout
    with patch.object(
        sim_service,
        "start_simulation",
        return_value=StartupResult(
            False,
            "Simulation startup timed out after 5.0s.",
            StartupStatus.FAILED,
            error="STARTUP_TIMEOUT",
        ),
    ):
        res_timeout = client.post("/api/simulation/start", json={"mode": "coordinated", "duration": 30})
        assert res_timeout.status_code == 504
        assert "timed out" in res_timeout.json()["detail"].lower()


# --------------------------------------------------------------------------
# Scenario 23: HTTP simulation stop returns 500 when worker fails to terminate
# --------------------------------------------------------------------------
def test_api_simulation_stop_worker_failure_returns_500():
    """POST /stop returns 500 Internal Server Error if worker thread fails to terminate within watchdog escalation."""
    client = TestClient(app)

    with patch.object(
        sim_service,
        "stop_simulation",
        return_value=(
            False,
            "Simulation worker did not terminate within timeout; shutdown pending; watchdog escalated.",
        ),
    ):
        res = client.post("/api/simulation/stop")
        assert res.status_code == 500
        assert "did not terminate" in res.json()["detail"].lower()


# --------------------------------------------------------------------------
# Scenario 24: subprocess.Popen identity preserved before, during, and after TraCI startup
# --------------------------------------------------------------------------
def test_subprocess_popen_identity_preserved_before_during_after(monkeypatch):
    """subprocess.Popen remains identical before, during, and after TraCI startup interception."""
    import sys
    orig_popen = subprocess.Popen
    orig_sys_popen = sys.modules["subprocess"].Popen
    assert orig_popen is orig_sys_popen

    during_popen = []
    real_traci_start = traci.start

    def tracking_traci_start(cmd, label="default"):
        # Check while TraCI startup is actively running inside SumoManager.start()
        during_popen.append(subprocess.Popen)
        during_popen.append(sys.modules["subprocess"].Popen)
        return real_traci_start(cmd, label=label)

    monkeypatch.setattr(traci, "start", tracking_traci_start)

    res = sim_service.start_simulation(mode="coordinated", duration=15, startup_timeout_s=10.0)
    assert res.success is True

    # During startup, global subprocess.Popen was NEVER mutated
    assert len(during_popen) == 2
    assert during_popen[0] is orig_popen
    assert during_popen[1] is orig_popen

    # After startup, global subprocess.Popen remains original and traci.main.subprocess is restored
    assert subprocess.Popen is orig_popen
    assert sys.modules["subprocess"].Popen is orig_popen
    assert traci.main.subprocess is sys.modules["subprocess"]


# --------------------------------------------------------------------------
# Scenario 25: Unrelated thread subprocess not captured during startup
# --------------------------------------------------------------------------
def test_unrelated_thread_subprocess_not_captured_during_startup(monkeypatch):
    """An unrelated thread launching a subprocess during SUMO startup is neither intercepted nor captured."""
    import sys
    unrelated_procs = []
    unrelated_finished = threading.Event()
    real_traci_start = traci.start

    def slow_traci_start(cmd, label="default"):
        def unrelated_worker():
            p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.1)"])
            unrelated_procs.append(p)
            p.wait(timeout=2.0)
            unrelated_finished.set()

        t = threading.Thread(target=unrelated_worker)
        t.start()
        unrelated_finished.wait(timeout=3.0)
        t.join(timeout=2.0)
        return real_traci_start(cmd, label=label)

    monkeypatch.setattr(traci, "start", slow_traci_start)

    res = sim_service.start_simulation(mode="coordinated", duration=15, startup_timeout_s=10.0)
    assert res.success is True

    # The captured process MUST NOT be the unrelated process
    assert len(unrelated_procs) == 1
    unrelated_pid = unrelated_procs[0].pid
    captured_pid = sim_service._active_sumo_pid
    assert captured_pid is not None
    assert captured_pid != unrelated_pid
    assert sim_service._active_sumo_process != unrelated_procs[0]


# --------------------------------------------------------------------------
# Scenario 26: Actual SUMO process captured correctly with matching PID and active handle
# --------------------------------------------------------------------------
def test_actual_sumo_process_captured_correctly():
    """Verify that the actual SUMO process handle and PID are captured correctly on real startup."""
    res = sim_service.start_simulation(mode="coordinated", duration=15, startup_timeout_s=10.0)
    assert res.success is True
    assert sim_service._active_sumo_process is not None
    assert sim_service._active_sumo_pid is not None
    assert sim_service._active_sumo_process.pid == sim_service._active_sumo_pid
    # Process is actively running
    assert sim_service._active_sumo_process.poll() is None


# --------------------------------------------------------------------------
# Scenario 27: Two concurrent SUMO startup attempts serialize via _traci_startup_lock
# --------------------------------------------------------------------------
def test_concurrent_sumo_manager_startups_serialize_safely(monkeypatch):
    """Two concurrent SumoManager startup attempts serialize via _traci_startup_lock without corrupting proxy state."""
    from traffic_service.sumo_manager import SumoManager, _traci_startup_lock

    mgr1 = SumoManager(SUMO_CONFIG_PATH, label="test_mgr1")
    mgr2 = SumoManager(SUMO_CONFIG_PATH, label="test_mgr2")

    order = []

    def tracking_start(cmd, label="default"):
        order.append(f"start_{label}")
        time.sleep(0.2)
        order.append(f"end_{label}")

    monkeypatch.setattr(traci, "start", tracking_start)

    t1 = threading.Thread(target=lambda: mgr1.start())
    t2 = threading.Thread(target=lambda: mgr2.start())

    t1.start()
    t2.start()
    t1.join(timeout=3.0)
    t2.join(timeout=3.0)

    # Must be strictly serialized: start_A, end_A, start_B, end_B (or B then A)
    assert len(order) == 4
    assert (
        order == ["start_test_mgr1", "end_test_mgr1", "start_test_mgr2", "end_test_mgr2"]
        or order == ["start_test_mgr2", "end_test_mgr2", "start_test_mgr1", "end_test_mgr1"]
    )
    # Proxy reference must be fully restored
    assert traci.main.subprocess is sys.modules["subprocess"]
    assert not _traci_startup_lock.locked()


# --------------------------------------------------------------------------
# Scenario 28: Exception during TraCI startup restores module reference and releases lock
# --------------------------------------------------------------------------
def test_traci_startup_exception_restores_module_reference(monkeypatch):
    """An exception during TraCI startup reliably restores original module reference and releases lock."""
    from traffic_service.sumo_manager import SumoManager, _traci_startup_lock
    import traci.exceptions

    mgr = SumoManager(SUMO_CONFIG_PATH, label="test_exc_mgr")

    def failing_traci_start(cmd, label="default"):
        raise traci.exceptions.FatalTraCIError("Simulated connection failure during startup")

    monkeypatch.setattr(traci, "start", failing_traci_start)

    with pytest.raises(traci.exceptions.FatalTraCIError):
        mgr.start()

    # Verify restoration
    assert traci.main.subprocess is sys.modules["subprocess"]
    assert not _traci_startup_lock.locked()



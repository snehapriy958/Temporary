"""
backend/simulation_service.py

Thread-safe background simulation orchestrator.
Bridges FastAPI with MultiIntersectionSimulation and TraCI.
Manages simulation lifecycle (start, pause, resume, stop, reset),
broadcasts telemetry, records decisions, and persists metrics to SQLite.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import queue
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import traci

from backend.config import BASE_DIR, SUMO_CONFIG_PATH, SUMO_STEP_LENGTH
from backend.database import SessionLocal
from backend.models import (
    EmergencyEventRecord,
    SignalDecisionRecord,
    SimulationRun,
    TrafficMetricRecord,
)
from backend.schemas import (
    DecisionItemSchema,
    EmergencyApproachingSchema,
    EmergencyEventItemSchema,
    EmergencyResponse,
    EmissionSchema,
    JunctionStateSchema,
    SignalInfoSchema,
    SimulationStatusResponse,
    TrafficLiveResponse,
    TrafficMetricsResponse,
)
from backend.websocket_manager import ws_manager
from traffic_service.multi_intersection_simulation import MultiIntersectionSimulation
from traffic_service.state_extractor import IntersectionState

logger = logging.getLogger("simulation_service")


class StartupStatus(str, Enum):
    REQUESTED = "REQUESTED"
    STARTING = "STARTING"
    CONNECTING = "CONNECTING"
    READY = "READY"
    FAILED = "FAILED"


class StartupResult(tuple):
    """
    Subclass of tuple providing backwards-compatible unpacking:
        ok, msg = sim_service.start_simulation(...)
    while exposing rich structured metadata for API responses, logging, and diagnostics.
    """
    success: bool
    message: str
    status: StartupStatus
    pid: Optional[int]
    startup_duration_s: float
    error: Optional[str]
    run_uuid: Optional[str]

    def __new__(
        cls,
        success: bool,
        message: str,
        status: StartupStatus,
        pid: Optional[int] = None,
        startup_duration_s: float = 0.0,
        error: Optional[str] = None,
        run_uuid: Optional[str] = None,
    ):
        instance = super().__new__(cls, (success, message))
        instance.success = success
        instance.message = message
        instance.status = status
        instance.pid = pid
        instance.startup_duration_s = startup_duration_s
        instance.error = error
        instance.run_uuid = run_uuid
        return instance

    def __repr__(self) -> str:
        return (
            f"StartupResult(success={self.success}, message='{self.message}', "
            f"status={self.status}, pid={self.pid}, "
            f"startup_duration_s={self.startup_duration_s:.3f}, error={self.error}, run_uuid={self.run_uuid})"
        )


class CommandStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    EXECUTED = "EXECUTED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"
    EXECUTION_OUTCOME_UNKNOWN = "EXECUTION_OUTCOME_UNKNOWN"


class CommandResult(tuple):
    """
    Subclass of tuple providing backwards-compatible unpacking:
        ok, msg = sim_service.request_manual_override(...)
    while exposing rich structured metadata for API responses, logging, and diagnostics.
    """
    success: bool
    message: str
    status: CommandStatus
    junction_id: Optional[str]
    applied_phase: Optional[int]
    simulation_time: float
    command_id: Optional[str]
    rejection_reason: Optional[str]
    executing_thread: Optional[str]

    def __new__(
        cls,
        success: bool,
        message: str,
        status: CommandStatus = CommandStatus.EXECUTED,
        junction_id: Optional[str] = None,
        applied_phase: Optional[int] = None,
        simulation_time: float = 0.0,
        command_id: Optional[str] = None,
        rejection_reason: Optional[str] = None,
        executing_thread: Optional[str] = None,
    ):
        instance = super().__new__(cls, (success, message))
        instance.success = success
        instance.message = message
        instance.status = status
        instance.junction_id = junction_id
        instance.applied_phase = applied_phase
        instance.simulation_time = simulation_time
        instance.command_id = command_id
        instance.rejection_reason = rejection_reason or ("" if success else message)
        instance.executing_thread = executing_thread
        return instance

    def __repr__(self) -> str:
        return (
            f"CommandResult(success={self.success}, message='{self.message}', "
            f"status={self.status}, junction_id={self.junction_id}, "
            f"applied_phase={self.applied_phase}, simulation_time={self.simulation_time}, "
            f"command_id={self.command_id}, executing_thread={self.executing_thread})"
        )


class SignalOverrideCommand:
    """
    Thread-safe command object coordinating state transitions between
    the API caller thread and the background SumoSimulationWorker thread.

    Enforces atomic transitions:
      PENDING -> RUNNING -> EXECUTED / REJECTED
      PENDING -> CANCELLED / TIMED_OUT (Caller timeout before worker execution)
      RUNNING -> EXECUTION_OUTCOME_UNKNOWN (Caller timeout while worker is executing)
    """

    def __init__(
        self,
        command_id: str,
        session_uuid: str,
        junction_id: str,
        target_phase: int,
        confirmed: bool,
        created_at: float,
        timeout_s: float,
    ) -> None:
        self.command_id = command_id
        self.session_uuid = session_uuid
        self.junction_id = junction_id
        self.target_phase = target_phase
        self.confirmed = confirmed
        self.created_at = created_at
        self.timeout_s = timeout_s

        self._state_lock = threading.Lock()
        self._status: CommandStatus = CommandStatus.PENDING
        self.future: concurrent.futures.Future[CommandResult] = concurrent.futures.Future()
        self.result: Optional[CommandResult] = None

    @property
    def status(self) -> CommandStatus:
        with self._state_lock:
            return self._status

    def is_expired(self, current_time: float) -> bool:
        return (current_time - self.created_at) > self.timeout_s

    def try_transition_to_running(self) -> bool:
        """
        Atomically transitions command from PENDING to RUNNING.
        Returns True if transition succeeded, False if already CANCELLED or TIMED_OUT.
        """
        with self._state_lock:
            if self._status == CommandStatus.PENDING:
                self._status = CommandStatus.RUNNING
                return True
            return False

    def complete_execution(self, result: CommandResult) -> None:
        """
        Atomically transitions command from RUNNING to EXECUTED or REJECTED
        and fulfills the future without throwing InvalidStateError.
        """
        with self._state_lock:
            self._status = result.status
            self.result = result
            if not self.future.done():
                self.future.set_result(result)

    def cancel_pending(self, reason: str, sim_time: float, thread_name: str) -> Optional[CommandResult]:
        """
        Cancels the command if it is still PENDING.
        """
        with self._state_lock:
            if self._status == CommandStatus.PENDING:
                self._status = CommandStatus.CANCELLED
                res = CommandResult(
                    success=False,
                    message=f"Command cancelled: {reason}",
                    status=CommandStatus.CANCELLED,
                    junction_id=self.junction_id,
                    applied_phase=self.target_phase,
                    simulation_time=sim_time,
                    command_id=self.command_id,
                    rejection_reason=reason,
                    executing_thread=thread_name,
                )
                self.result = res
                if not self.future.done():
                    self.future.set_result(res)
                return res
            return None

    def handle_caller_timeout(self, sim_time: float, caller_thread: str) -> CommandResult:
        """
        Called by the API thread when waiting on the future times out.
        Atomically determines whether the command definitely did not execute (cancelled while PENDING)
        or whether execution outcome is unknown (already RUNNING).
        """
        with self._state_lock:
            if self._status == CommandStatus.PENDING:
                self._status = CommandStatus.TIMED_OUT
                res = CommandResult(
                    success=False,
                    message=f"Command timed out after {self.timeout_s:.1f}s waiting in queue; definitely not executed.",
                    status=CommandStatus.TIMED_OUT,
                    junction_id=self.junction_id,
                    applied_phase=self.target_phase,
                    simulation_time=sim_time,
                    command_id=self.command_id,
                    rejection_reason="TIMED_OUT_IN_QUEUE",
                    executing_thread=caller_thread,
                )
                self.result = res
                if not self.future.done():
                    self.future.set_result(res)
                return res

            elif self._status == CommandStatus.RUNNING:
                # Command is actively executing on worker thread! Execution outcome unknown to caller.
                res = CommandResult(
                    success=False,
                    message=(
                        f"Command timed out after {self.timeout_s:.1f}s while executing in simulation worker. "
                        "Execution outcome is currently unknown (in-flight)."
                    ),
                    status=CommandStatus.EXECUTION_OUTCOME_UNKNOWN,
                    junction_id=self.junction_id,
                    applied_phase=self.target_phase,
                    simulation_time=sim_time,
                    command_id=self.command_id,
                    rejection_reason="IN_FLIGHT_TIMEOUT",
                    executing_thread=caller_thread,
                )
                # DO NOT cancel self.future! Let worker complete self.future cleanly without InvalidStateError.
                return res

            else:
                # Worker completed it right as timeout fired
                if self.future.done():
                    try:
                        return self.future.result()
                    except Exception:
                        pass
                return CommandResult(
                    success=False,
                    message=f"Command timed out (current status: {self._status}).",
                    status=self._status,
                    junction_id=self.junction_id,
                    applied_phase=self.target_phase,
                    simulation_time=sim_time,
                    command_id=self.command_id,
                    executing_thread=caller_thread,
                )


class SimulationService:
    """Singleton service managing background SUMO simulation lifecycle and telemetry."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sim: Optional[MultiIntersectionSimulation] = None
        self._thread: Optional[threading.Thread] = None
        self._command_queue: Optional[queue.Queue[SignalOverrideCommand]] = None

        self._running: bool = False
        self._paused: bool = False
        self._stop_requested: bool = False

        self._mode: str = "coordinated"
        self._seed: int = 42
        self._duration: int = 600
        self._step_length: float = SUMO_STEP_LENGTH
        self._decision_interval: float = 5.0
        self._enable_emergency: bool = True
        self._gui: bool = False

        self._current_sim_time: float = 0.0
        self._current_run_id: Optional[int] = None
        self._current_run_uuid: Optional[str] = None
        self._sequence_number: int = 0
        self._error_message: Optional[str] = None

        # Synchronous startup and process watchdog state
        self._startup_event: threading.Event = threading.Event()
        self._startup_result: Optional[StartupResult] = None
        self._startup_status: StartupStatus | str = "STOPPED"
        self._active_sumo_process: Optional[subprocess.Popen] = None
        self._active_sumo_pid: Optional[int] = None
        self._watchdog_escalated: bool = False

        # In-memory telemetry cache
        self._latest_states: Dict[str, IntersectionState] = {}
        self._decisions_log: List[DecisionItemSchema] = []
        self._emergency_events: List[EmergencyEventItemSchema] = []
        self._cached_metrics: Dict[str, Any] = {}

        # Loop reference for async websocket broadcasting
        self.loop: Optional[asyncio.AbstractEventLoop] = None

        # Pre-seed decisions log with initial notice
        self._decisions_log.append(
            DecisionItemSchema(
                simulation_time=0.0,
                junction_id="SYSTEM",
                current_phase=0,
                target_phase=None,
                action="INITIALIZE",
                reason="System ready for simulation initialization.",
                is_override=False,
                timestamp=datetime.utcnow().isoformat(),
            )
        )

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Sets the running asyncio event loop for threadsafe coroutine scheduling."""
        self.loop = loop

    # ------------------------------------------------------------------
    # Lifecycle Controls
    # ------------------------------------------------------------------

    def start_simulation(
        self,
        mode: str = "coordinated",
        duration: int = 600,
        seed: int = 42,
        step_length: float = 1.0,
        decision_interval: float = 5.0,
        enable_emergency: bool = True,
        gui: bool = False,
        startup_timeout_s: float = 10.0,
    ) -> StartupResult:
        """
        Starts a new simulation run in the background thread with synchronous
        readiness handshaking. Blocks caller until worker confirms READY or FAILED,
        or startup_timeout_s expires.
        """
        start_request_time = time.time()
        with self._lock:
            # Check if active simulation exists, previous worker is still terminating, or startup in progress
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

            self._mode = mode.lower()
            self._duration = duration
            self._seed = seed
            self._step_length = step_length
            self._decision_interval = decision_interval
            self._enable_emergency = enable_emergency
            self._gui = gui

            self._paused = False
            self._stop_requested = False
            self._error_message = None
            self._current_sim_time = 0.0
            self._latest_states = {}
            self._decisions_log = []
            self._emergency_events = []
            self._cached_metrics = {}
            self._active_sumo_process = None
            self._active_sumo_pid = None
            self._watchdog_escalated = False

            # Reset startup synchronization
            self._startup_event.clear()
            self._startup_result = None
            self._startup_status = StartupStatus.REQUESTED

            run_uuid = f"run_{uuid.uuid4().hex[:12]}"
            self._current_run_uuid = run_uuid
            self._sequence_number = 0
            self._command_queue = queue.Queue(maxsize=32)

            # Create Database Record
            db = SessionLocal()
            try:
                run_rec = SimulationRun(
                    run_uuid=run_uuid,
                    mode=self._mode,
                    status="STARTING",
                    seed=self._seed,
                    duration_requested=self._duration,
                    duration_simulated=0.0,
                    started_at=datetime.utcnow(),
                )
                db.add(run_rec)
                db.commit()
                db.refresh(run_rec)
                self._current_run_id = run_rec.id
            except Exception as exc:
                db.rollback()
                logger.error(f"Failed to create simulation run record: {exc}")
                self._current_run_id = None
            finally:
                db.close()

            logger.info(
                f"Simulation startup requested (UUID: {run_uuid}, mode: {self._mode}, timeout: {startup_timeout_s}s)"
            )

            # Spawn Worker Thread
            self._thread = threading.Thread(
                target=self._run_simulation_worker,
                daemon=True,
                name="SumoSimulationWorker",
            )
            self._thread.start()

        # Wait outside lock for worker thread to signal readiness or failure
        signaled = self._startup_event.wait(timeout=startup_timeout_s)

        if not signaled:
            # Startup timed out!
            elapsed = time.time() - start_request_time
            logger.critical(
                f"Simulation startup timed out after {elapsed:.2f}s (Session: {run_uuid}). "
                "Initiating watchdog cleanup..."
            )
            with self._lock:
                self._startup_status = StartupStatus.FAILED
                self._error_message = f"Simulation startup timed out after {startup_timeout_s:.1f}s."
                self._stop_requested = True
                proc_to_kill = self._active_sumo_process
                pid_to_kill = self._active_sumo_pid

            # Escalate watchdog if process was launched
            if proc_to_kill or pid_to_kill:
                self._escalate_process_watchdog(proc_to_kill, pid_to_kill, run_uuid)

            # Join worker thread
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=2.0)

            # Finalize cleanup with lock
            with self._lock:
                self._cleanup_sim(final_status="ERROR")

            return StartupResult(
                False,
                f"Simulation startup timed out after {startup_timeout_s:.1f}s.",
                StartupStatus.FAILED,
                pid=pid_to_kill,
                startup_duration_s=elapsed,
                error="STARTUP_TIMEOUT",
                run_uuid=run_uuid,
            )

        # Worker signaled: inspect startup result
        res = self._startup_result
        if res is None:
            with self._lock:
                res = StartupResult(
                    False,
                    "Simulation startup failed with unknown state.",
                    StartupStatus.FAILED,
                    run_uuid=run_uuid,
                )

        if res.success:
            with self._lock:
                self._running = True
                self._startup_status = StartupStatus.READY
                self._update_db_status("RUNNING")
                self._record_decision(
                    sim_time=0.0,
                    junction_id="SYSTEM",
                    current_phase=0,
                    target_phase=None,
                    action="START",
                    reason=f"Started {self._mode.upper()} simulation (Seed: {self._seed}, PID: {res.pid}, Duration: {self._duration}s).",
                )
            logger.info(
                f"Simulation startup confirmed READY (UUID: {run_uuid}, PID: {res.pid}, duration: {res.startup_duration_s:.2f}s)"
            )
            return res
        else:
            # Worker failed during startup
            logger.error(
                f"Simulation startup FAILED (UUID: {run_uuid}, duration: {res.startup_duration_s:.2f}s, reason: {res.message})"
            )
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=2.0)
            return res

    def pause_simulation(self) -> Tuple[bool, str]:
        """Safely pauses the running simulation."""
        with self._lock:
            if not self._running:
                return False, "Simulation is not currently running."
            if self._paused:
                return False, "Simulation is already paused."

            self._paused = True
            self._record_decision(
                sim_time=self._current_sim_time,
                junction_id="SYSTEM",
                current_phase=0,
                target_phase=None,
                action="PAUSE",
                reason="Operator paused simulation stepping.",
            )
            self._update_db_status("PAUSED")
            return True, "Simulation paused successfully."

    def resume_simulation(self) -> Tuple[bool, str]:
        """Resumes a paused simulation."""
        with self._lock:
            if not self._running:
                return False, "Simulation is not currently running."
            if not self._paused:
                return False, "Simulation is not paused."

            self._paused = False
            self._record_decision(
                sim_time=self._current_sim_time,
                junction_id="SYSTEM",
                current_phase=0,
                target_phase=None,
                action="RESUME",
                reason="Operator resumed simulation execution.",
            )
            self._update_db_status("RUNNING")
            return True, "Simulation resumed successfully."

    def _escalate_process_watchdog(
        self,
        target_process: Optional[subprocess.Popen],
        target_pid: Optional[int],
        target_uuid: Optional[str],
    ) -> bool:
        """
        Controlled Tier 2 OS-level process watchdog escalation.
        Operates strictly on the verified subprocess.Popen handle and PID
        belonging to the specified session.
        Never executes global taskkill or pkill commands.
        Never calls TraCI methods from this thread.
        """
        if not target_process and target_pid is None:
            logger.warning("Watchdog escalation skipped: No active process handle or PID recorded.")
            return False

        logger.critical(
            f"WATCHDOG TRIGGERED: Terminating unresponsive SUMO process for Session UUID={target_uuid}, PID={target_pid}."
        )

        with self._lock:
            self._watchdog_escalated = True
            self._record_decision(
                sim_time=self._current_sim_time,
                junction_id="SYSTEM",
                current_phase=0,
                target_phase=None,
                action="WATCHDOG_TERMINATION",
                reason=f"Watchdog escalated: Terminating unresponsive SUMO process PID {target_pid} (Session: {target_uuid}).",
            )

        # Session PID verification: ensure handle matches target_pid
        if target_process is not None and target_pid is not None:
            if target_process.pid != target_pid:
                logger.error(
                    f"PID mismatch during watchdog escalation: handle PID {target_process.pid} != target PID {target_pid}. Aborting termination."
                )
                return False

        # If process object exists and has already exited, nothing to do
        if target_process is not None and target_process.poll() is not None:
            logger.info(f"Target process PID {target_pid} already exited with code {target_process.returncode}.")
            return True

        # Tier 2a: Graceful process termination via target_process.terminate()
        terminated_ok = False
        if target_process is not None:
            try:
                logger.info(f"Watchdog: Sending terminate() to PID {target_pid}...")
                target_process.terminate()
                target_process.wait(timeout=3.0)
                logger.info(f"Target process PID {target_pid} terminated successfully via terminate().")
                terminated_ok = True
            except subprocess.TimeoutExpired:
                logger.warning(f"Target process PID {target_pid} did not terminate within 3.0s; escalating to kill()...")
            except Exception as e:
                logger.warning(f"Error calling terminate() on process handle: {e}")

            if not terminated_ok:
                # Tier 2b: Forced process termination via target_process.kill()
                try:
                    logger.critical(f"Watchdog: Sending kill() to PID {target_pid}...")
                    target_process.kill()
                    target_process.wait(timeout=2.0)
                    logger.info(f"Target process PID {target_pid} terminated successfully via kill().")
                    terminated_ok = True
                except subprocess.TimeoutExpired:
                    logger.error(f"Target process PID {target_pid} failed to terminate within 2.0s after kill().")
                except Exception as e:
                    logger.error(f"Error calling kill() on process handle: {e}")

        return terminated_ok

    def stop_simulation(self) -> Tuple[bool, str]:
        """
        Thread-safely requests the simulation worker to stop and wait for clean termination.
        TraCI resources are closed EXCLUSIVELY by the simulation worker thread in its finally block.
        If the worker thread fails to terminate within 5.0s, the Tier 2 process watchdog
        escalates to terminate the specific SUMO process at the OS level.
        """
        shutdown_request_time = time.time()
        with self._lock:
            # If not running and worker thread is not alive, reject
            if not self._running and not self._sim and (not self._thread or not self._thread.is_alive()):
                return False, "Simulation is not currently running."

            self._stop_requested = True
            self._paused = False
            target_proc = self._active_sumo_process
            target_pid = self._active_sumo_pid
            target_uuid = self._current_run_uuid

        logger.info(
            f"Shutdown requested for session {target_uuid} (PID: {target_pid}) at {datetime.utcnow().isoformat()}"
        )

        # Tier 1: Wait for worker thread to finish its execution and finally cleanup outside lock
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)

            # Tier 2: Watchdog escalation if worker thread is still alive after Tier 1 grace period
            if self._thread.is_alive():
                logger.warning(
                    f"Simulation worker thread did not terminate within 5.0s join timeout (Session: {target_uuid}). "
                    "Escalating to Tier 2 process watchdog."
                )
                self._escalate_process_watchdog(target_proc, target_pid, target_uuid)

                # Wait up to 2.0s for worker thread to exit now that process is killed / socket broken
                self._thread.join(timeout=2.0)
                if self._thread.is_alive():
                    logger.critical(
                        f"Simulation worker thread remained alive even after watchdog termination (Session: {target_uuid})."
                    )
                    return False, "Simulation worker did not terminate within timeout; shutdown pending; watchdog escalated."
                else:
                    logger.info(f"Worker thread exited after watchdog termination (Session: {target_uuid}).")
                    return True, "Simulation stopped via watchdog process termination."

        graceful_duration = time.time() - shutdown_request_time
        logger.info(f"Graceful simulation shutdown succeeded in {graceful_duration:.2f}s (Session: {target_uuid}).")
        return True, "Simulation stopped successfully and resources released."

    def reset_simulation(self) -> Tuple[bool, str]:
        """Resets the simulation state and cleans up resources."""
        ok, msg = self.stop_simulation()
        if not ok and self._thread and self._thread.is_alive():
            return False, f"Cannot reset simulation: {msg}"

        with self._lock:
            self._current_sim_time = 0.0
            self._latest_states = {}
            self._cached_metrics = {}
            self._error_message = None
            self._active_sumo_process = None
            self._active_sumo_pid = None
            self._watchdog_escalated = False
            self._startup_status = "STOPPED"
            self._sequence_number = 0
            self._current_run_uuid = None
            self._record_decision(
                sim_time=0.0,
                junction_id="SYSTEM",
                current_phase=0,
                target_phase=None,
                action="RESET",
                reason="Simulation state reset by operator.",
            )
            return True, "Simulation reset to clean state."

    def _on_process_spawned(self, proc: subprocess.Popen, pid: Optional[int]) -> None:
        """Callback invoked by SumoManager the exact instant subprocess.Popen is executed."""
        with self._lock:
            self._active_sumo_process = proc
            self._active_sumo_pid = pid
            logger.info(f"Captured spawned SUMO process handle: PID {pid} (Session: {self._current_run_uuid})")

    # ------------------------------------------------------------------
    # Worker Thread
    # ------------------------------------------------------------------

    def _run_simulation_worker(self) -> None:
        """Internal background worker running the SUMO simulation loop."""
        start_worker_time = time.time()
        session_uuid = self._current_run_uuid
        with self._lock:
            self._startup_status = StartupStatus.STARTING

        config_path = SUMO_CONFIG_PATH
        if not config_path.is_file():
            err_msg = f"SUMO config file not found: {config_path}"
            logger.error(err_msg)
            startup_res = StartupResult(
                False,
                err_msg,
                StartupStatus.FAILED,
                startup_duration_s=time.time() - start_worker_time,
                error="CONFIG_NOT_FOUND",
                run_uuid=session_uuid,
            )
            with self._lock:
                self._startup_status = StartupStatus.FAILED
                self._error_message = err_msg
                self._startup_result = startup_res
                self._startup_event.set()
                self._cleanup_sim(final_status="ERROR")
            return

        final_st = "STOPPED"
        sim: Optional[MultiIntersectionSimulation] = None
        try:
            with self._lock:
                self._startup_status = StartupStatus.STARTING

            sim = MultiIntersectionSimulation(
                sumocfg_path=config_path,
                mode=self._mode,
                gui=self._gui,
                step_length=self._step_length,
                decision_interval=self._decision_interval,
                enable_emergency=self._enable_emergency,
                on_process_spawned=self._on_process_spawned,
            )
            with self._lock:
                # Cancel if shutdown or session replaced before connection
                if self._stop_requested or self._current_run_uuid != session_uuid:
                    logger.warning(
                        f"Worker for session {session_uuid} was cancelled before sim.start() was called. Aborting."
                    )
                    return
                self._sim = sim
                self._startup_status = StartupStatus.CONNECTING

            logger.info(f"Worker starting SUMO/TraCI (Session: {session_uuid}, seed: {self._seed})...")
            sim.start(seed=self._seed)

            # Store confirmed process handle and PID
            proc = sim.process
            pid = sim.pid
            with self._lock:
                if proc is not None:
                    self._active_sumo_process = proc
                if pid is not None:
                    self._active_sumo_pid = pid

            # Validate connection readiness
            if not sim.sumo_manager.is_running:
                raise RuntimeError("SUMO manager reported not running after start().")

            startup_dur = time.time() - start_worker_time
            startup_res = StartupResult(
                True,
                f"Simulation started in {self._mode} mode (UUID: {session_uuid}, PID: {pid})",
                StartupStatus.READY,
                pid=pid,
                startup_duration_s=startup_dur,
                run_uuid=session_uuid,
            )
            with self._lock:
                # Late worker / timeout guard:
                # Do NOT publish READY if stop was requested, if startup already timed out,
                # or if the active session UUID no longer matches this worker's session_uuid!
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

                self._startup_status = StartupStatus.READY
                self._startup_result = startup_res
                self._startup_event.set()

            logger.info(
                f"SUMO TraCI connection initialized and ready (Session: {session_uuid}, PID: {pid}, duration: {startup_dur:.2f}s)."
            )

            step_counter = 0
            while not self._stop_requested:
                # Check pause
                if self._paused:
                    time.sleep(0.1)
                    continue

                # Process queued TraCI commands exclusively on worker thread prior to simulationStep()
                self._process_command_queue(sim, self._current_sim_time)

                # Step simulation
                sim_time = sim.sumo_manager.step()
                states = sim.get_states(sim_time)

                # Process emergency preemption if enabled
                if self._enable_emergency:
                    sim.emergency_coordinator.update(sim_time)
                    self._check_emergency_progress(sim, sim_time)

                # Coordinated / Baseline Decision Control
                if sim_time >= sim._next_decision_time:
                    sim._next_decision_time += sim.decision_interval
                    if sim.mode == "coordinated":
                        self._run_coordinated_with_logging(sim, states, sim_time)

                # Collect Metrics
                emergency_duration = (
                    sim.emergency_coordinator.metrics.total_traversal_duration
                    if sim.emergency_coordinator.metrics.completed
                    else 0.0
                )
                sim.metrics_collector.record_step(sim_time, states, emergency_duration=emergency_duration)

                # Update in-memory telemetry
                with self._lock:
                    self._current_sim_time = sim_time
                    self._latest_states = states
                    self._cached_metrics = self._extract_metrics_summary(sim, states, sim_time)

                # Periodic DB write (every 5 seconds)
                step_counter += 1
                if step_counter % int(max(1, 5.0 / self._step_length)) == 0:
                    self._persist_metrics_snapshot(sim_time)

                # Broadcast live telemetry over WebSocket
                self._broadcast_telemetry()

                # Check if target duration reached
                if sim_time >= self._duration:
                    logger.info(f"Target duration {self._duration}s reached.")
                    final_st = "COMPLETED"
                    break

                # Sleep to synchronize with real-time if necessary
                time.sleep(0.02)

            if final_st != "COMPLETED":
                final_st = "STOPPED"

        except Exception as exc:
            startup_dur = time.time() - start_worker_time
            err_msg = str(exc)
            logger.exception(f"Simulation worker exception (Session: {session_uuid}): {err_msg}")
            with self._lock:
                self._error_message = err_msg
                # If startup has not completed yet, signal failure to waiting caller
                if not self._startup_event.is_set():
                    self._startup_status = StartupStatus.FAILED
                    self._startup_result = StartupResult(
                        False,
                        f"Simulation startup failed: {err_msg}",
                        StartupStatus.FAILED,
                        pid=self._active_sumo_pid,
                        startup_duration_s=startup_dur,
                        error=err_msg,
                        run_uuid=session_uuid,
                    )
                    self._startup_event.set()
            final_st = "ERROR"
        finally:
            with self._lock:
                self._cleanup_sim(final_status=final_st)

    def _cleanup_sim(self, final_status: str = "STOPPED") -> None:
        """Safely closes TraCI, updates database, and resets state flags."""
        executing_thread = threading.current_thread().name
        logger.info(f"Cleaning up simulation resources (invoked by thread: {executing_thread}, status: {final_status})")

        if self._watchdog_escalated:
            final_status = "KILLED_BY_WATCHDOG"

        if self._sim:
            try:
                self._sim.close()
            except (traci.exceptions.FatalTraCIError, ConnectionError, BrokenPipeError, Exception) as e:
                logger.warning(f"Error during sim.close(): {e}")
            self._sim = None

        self._active_sumo_process = None
        self._active_sumo_pid = None
        self._running = False
        self._paused = False
        self._stop_requested = False
        if not self._watchdog_escalated:
            self._startup_status = final_status
        else:
            self._startup_status = "KILLED_BY_WATCHDOG"

        # Drain and cleanly cancel any pending commands
        if self._command_queue is not None:
            while not self._command_queue.empty():
                try:
                    cmd = self._command_queue.get_nowait()
                    cmd.cancel_pending("SIMULATION_STOPPED", self._current_sim_time, executing_thread)
                except queue.Empty:
                    break
            self._command_queue = None

        # Broadcast terminal state update to active WebSocket clients
        self._broadcast_telemetry()

        # Finalize Database record
        if self._current_run_id:
            db = SessionLocal()
            try:
                run_rec = db.query(SimulationRun).filter(SimulationRun.id == self._current_run_id).first()
                if run_rec:
                    run_rec.status = final_status
                    run_rec.completed_at = datetime.utcnow()
                    run_rec.duration_simulated = self._current_sim_time
                    if self._error_message:
                        run_rec.error_message = self._error_message
                    if self._cached_metrics:
                        run_rec.summary_metrics_json = json.dumps(self._cached_metrics)
                    db.commit()
            except Exception as exc:
                db.rollback()
                logger.error(f"Failed to update final run status in DB: {exc}")
            finally:
                db.close()

        # Final broadcast
        self._broadcast_telemetry()

    # ------------------------------------------------------------------
    # Telemetry Extraction & Persistence
    # ------------------------------------------------------------------

    def _extract_metrics_summary(
        self,
        sim: MultiIntersectionSimulation,
        states: Dict[str, IntersectionState],
        sim_time: float,
    ) -> Dict[str, Any]:
        """Calculates consolidated corridor metrics from states and collector."""
        summary = sim.metrics_collector.compute_summary()
        total_veh = sum(st.vehicle_count for st in states.values())
        mean_speed = sum(st.average_speed_kmh for st in states.values()) / max(1, len(states))
        mean_q = sum(st.total_queue for st in states.values()) / max(1, len(states))
        max_q = max((st.total_queue for st in states.values()), default=0)
        total_wait = sum(st.total_waiting_time for st in states.values())

        return {
            "simulation_time": sim_time,
            "total_vehicles": total_veh,
            "throughput_vehicles": summary.total_corridor_trips_completed,
            "mean_speed_kmh": round(mean_speed, 2),
            "total_corridor_waiting_time_s": round(total_wait, 2),
            "mean_corridor_queue": round(mean_q, 2),
            "max_corridor_queue": max_q,
            "total_co2_kg": round(summary.total_co2_kg, 4),
            "total_nox_g": round(summary.total_nox_g, 4),
            "total_fuel_liters": round(summary.total_fuel_liters, 4),
            "emergency_traversal_duration_s": round(summary.emergency_traversal_duration_s, 2),
            "junction_queues": {j: st.total_queue for j, st in states.items()},
        }

    def _persist_metrics_snapshot(self, sim_time: float) -> None:
        """Stores periodic metric snapshots in SQLite."""
        if not self._current_run_id or not self._cached_metrics:
            return

        db = SessionLocal()
        try:
            m = self._cached_metrics
            rec = TrafficMetricRecord(
                run_id=self._current_run_id,
                simulation_time=sim_time,
                total_vehicles=m.get("total_vehicles", 0),
                throughput_vehicles=m.get("throughput_vehicles", 0),
                mean_speed_kmh=m.get("mean_speed_kmh", 0.0),
                mean_queue=m.get("mean_corridor_queue", 0.0),
                max_queue=m.get("max_corridor_queue", 0),
                total_waiting_time=m.get("total_corridor_waiting_time_s", 0.0),
                co2_kg=m.get("total_co2_kg", 0.0),
                nox_g=m.get("total_nox_g", 0.0),
                fuel_liters=m.get("total_fuel_liters", 0.0),
            )
            db.add(rec)
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.warning(f"Error persisting traffic metrics snapshot: {exc}")
        finally:
            db.close()

    def _check_emergency_progress(self, sim: MultiIntersectionSimulation, sim_time: float) -> None:
        """Monitors emergency coordinator for preemption events."""
        metrics = sim.emergency_coordinator.metrics
        locked_junctions = [
            j for j, ctrl in sim.controllers.items() if ctrl.emergency_locked
        ]

        if locked_junctions and not self._emergency_events:
            event = EmergencyEventItemSchema(
                simulation_time=sim_time,
                vehicle_id=metrics.vehicle_id or "AMBULANCE_01",
                affected_corridor="Hosur Road (J1 -> J2 -> J3)",
                preemption_active=True,
                arrival_time=metrics.j1_arrival_time,
                clearance_time=metrics.j3_clearance_time,
                traversal_duration=metrics.total_traversal_duration,
                completed=metrics.completed,
            )
            self._emergency_events.append(event)
            self._record_decision(
                sim_time=sim_time,
                junction_id="CORRIDOR",
                current_phase=0,
                target_phase=2,
                action="EMERGENCY_PREEMPTION",
                reason=f"Emergency wave priority granted for ambulance {metrics.vehicle_id}. Preemption locked at {locked_junctions}.",
            )

        if metrics.completed and self._emergency_events:
            self._emergency_events[-1].completed = True
            self._emergency_events[-1].preemption_active = False
            self._emergency_events[-1].traversal_duration = metrics.total_traversal_duration

    def _run_coordinated_with_logging(
        self,
        sim: MultiIntersectionSimulation,
        states: Dict[str, IntersectionState],
        sim_time: float,
    ) -> None:
        """Executes coordinated control logic while capturing rationales."""
        # J2 adaptive controller
        j2_ctrl = sim.controllers["J2"]
        if not j2_ctrl.emergency_locked and j2_ctrl.is_green():
            j2_state = states["J2"]
            curr_phase = j2_ctrl.get_phase()
            hosur_q = j2_state.approach_queues.get("corridor_hosur", 0)
            madiwala_q = j2_state.approach_queues.get("madiwala", 0)
            upstream_inflow_bonus = int(sim.hub.get_expected_inflow("J2") * 5)
            effective_hosur_q = hosur_q + upstream_inflow_bonus
            elapsed = j2_ctrl.get_green_elapsed(sim_time)

            if curr_phase == 0:  # Hosur Green
                if elapsed >= j2_ctrl.min_green and madiwala_q > effective_hosur_q + 2:
                    j2_ctrl.request_switch(target_green_phase=2, sim_time=sim_time)
                    self._record_decision(
                        sim_time, "J2", 0, 2, "SWITCH",
                        f"Cross-traffic demand (Madiwala: {madiwala_q} veh) exceeded Hosur pressure ({effective_hosur_q} veh)."
                    )
                elif effective_hosur_q > 0 and effective_hosur_q >= madiwala_q:
                    j2_ctrl.extend_current_green(sim_time)
                    self._record_decision(
                        sim_time, "J2", 0, 0, "EXTEND",
                        f"Extended Hosur Road green phase. Inflow bonus: +{upstream_inflow_bonus} vehicles from J1."
                    )
            elif curr_phase == 2:  # Madiwala Green
                if elapsed >= j2_ctrl.min_green and effective_hosur_q > madiwala_q + 2:
                    j2_ctrl.request_switch(target_green_phase=0, sim_time=sim_time)
                    self._record_decision(
                        sim_time, "J2", 2, 0, "SWITCH",
                        f"Corridor arterial queue ({effective_hosur_q} veh) reclaimed green from Madiwala ({madiwala_q} veh)."
                    )
                elif madiwala_q > 0 and madiwala_q >= effective_hosur_q:
                    j2_ctrl.extend_current_green(sim_time)

        # J1 & J3 Progression Alignment
        for j_id, target_corridor_phase in [("J1", 2), ("J3", 2)]:
            ctrl = sim.controllers[j_id]
            if not ctrl.emergency_locked and ctrl.is_green():
                q_corridor = states[j_id].approach_queues.get("corridor_hosur", 0)
                q_cross = states[j_id].approach_queues.get("side_cross", 0)
                curr_p = ctrl.get_phase()
                elapsed = ctrl.get_green_elapsed(sim_time)

                if curr_p == target_corridor_phase:
                    if q_corridor > 0 and elapsed < ctrl.max_green:
                        ctrl.extend_current_green(sim_time)
                    elif elapsed >= ctrl.min_green and q_cross > q_corridor + 2:
                        ctrl.request_switch(target_green_phase=0, sim_time=sim_time)
                        self._record_decision(
                            sim_time, j_id, curr_p, 0, "SWITCH",
                            f"Side-cross queue ({q_cross} veh) exceeded corridor queue ({q_corridor} veh)."
                        )
                else:
                    if elapsed >= ctrl.min_green and q_corridor > q_cross:
                        ctrl.request_switch(target_green_phase=target_corridor_phase, sim_time=sim_time)
                        self._record_decision(
                            sim_time, j_id, curr_p, target_corridor_phase, "SWITCH",
                            f"Corridor progression aligned green phase {target_corridor_phase}."
                        )

    def _record_decision(
        self,
        sim_time: float,
        junction_id: str,
        current_phase: int,
        target_phase: Optional[int],
        action: str,
        reason: str,
        is_override: bool = False,
    ) -> None:
        """Appends decision to in-memory history and database."""
        item = DecisionItemSchema(
            id=len(self._decisions_log) + 1,
            simulation_time=sim_time,
            junction_id=junction_id,
            current_phase=current_phase,
            target_phase=target_phase,
            action=action,
            reason=reason,
            is_override=is_override,
            timestamp=datetime.utcnow().isoformat(),
        )
        self._decisions_log.append(item)
        if len(self._decisions_log) > 200:
            self._decisions_log.pop(0)

        # Save to DB if run active
        if self._current_run_id:
            db = SessionLocal()
            try:
                rec = SignalDecisionRecord(
                    run_id=self._current_run_id,
                    simulation_time=sim_time,
                    junction_id=junction_id,
                    current_phase=current_phase,
                    target_phase=target_phase,
                    action=action,
                    reason=reason,
                    is_override=is_override,
                )
                db.add(rec)
                db.commit()
            except Exception:
                db.rollback()
            finally:
                db.close()

    def _update_db_status(self, status: str) -> None:
        """Updates status of the current simulation run in database."""
        if not self._current_run_id:
            return
        db = SessionLocal()
        try:
            run_rec = db.query(SimulationRun).filter(SimulationRun.id == self._current_run_id).first()
            if run_rec:
                run_rec.status = status
                db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()

    def _broadcast_telemetry(self) -> None:
        """Schedules WebSocket broadcast on the main event loop."""
        if not self.loop or not self.loop.is_running():
            return

        with self._lock:
            self._sequence_number += 1
            seq = self._sequence_number
            session_uuid = self._current_run_uuid
            sim_time = self._current_sim_time
            running = self._running
            paused = self._paused
            mode = self._mode

        payload = {
            "type": "TRAFFIC_UPDATE",
            "sequence_number": seq,
            "session_uuid": session_uuid,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "simulation_time": sim_time,
            "status": "RUNNING" if running and not paused else ("PAUSED" if paused else "STOPPED"),
            "mode": mode,
            "metrics": self.get_metrics(),
            "junctions": self.get_live_junctions(),
            "signals": self.get_signals(),
            "emergencies": self.get_emergencies(),
            "decisions": [d.model_dump() for d in self._decisions_log[-5:]],
        }

        try:
            ws_manager.submit_telemetry(payload, self.loop)
        except Exception as exc:
            logger.debug(f"Broadcast threadsafe scheduling error: {exc}")

    # ------------------------------------------------------------------
    # Thread-Safe TraCI Command Queue & Manual Operator Override
    # ------------------------------------------------------------------

    def _process_command_queue(
        self,
        sim: MultiIntersectionSimulation,
        current_sim_time: float,
    ) -> None:
        """
        Processes pending traffic-signal override commands exclusively inside
        the simulation worker thread prior to simulationStep().

        Enforces:
          - Atomic PENDING -> RUNNING state transition.
          - Session matching (stale commands rejected).
          - Non-expired timeout checks.
          - Emergency green-wave preemption priority (rejects if junction is locked).
          - Legal phase indexes {0, 1, 2, 3}.
          - Minimum green constraints and yellow clearance transitions.
          - Per-command exception isolation (non-fatal errors do not kill worker).
          - Explicit simulation failure on fatal TraCI connection errors.
        """
        if self._command_queue is None:
            return

        worker_thread_name = threading.current_thread().name
        now = time.time()

        while not self._command_queue.empty():
            try:
                cmd = self._command_queue.get_nowait()
            except queue.Empty:
                break

            try:
                # 1. Check expiration or already cancelled/timed out while PENDING
                if cmd.is_expired(now):
                    cmd.cancel_pending("TIMED_OUT", current_sim_time, worker_thread_name)
                    continue

                if not cmd.try_transition_to_running():
                    # Caller cancelled or timed out while PENDING; definitely do not execute
                    logger.debug(f"Command {cmd.command_id} was cancelled/timed-out before worker execution.")
                    continue

                # 2. Check session validity (stale run rejection)
                if cmd.session_uuid != self._current_run_uuid:
                    res = CommandResult(
                        success=False,
                        message=f"Command rejected: Session {cmd.session_uuid} does not match active session {self._current_run_uuid}.",
                        status=CommandStatus.CANCELLED,
                        junction_id=cmd.junction_id,
                        applied_phase=cmd.target_phase,
                        simulation_time=current_sim_time,
                        command_id=cmd.command_id,
                        rejection_reason="SESSION_EXPIRED",
                        executing_thread=worker_thread_name,
                    )
                    cmd.complete_execution(res)
                    continue

                # 3. Check junction controller
                ctrl = sim.controllers.get(cmd.junction_id)
                if ctrl is None:
                    res = CommandResult(
                        success=False,
                        message=f"Invalid junction ID '{cmd.junction_id}'. Must be J1, J2, or J3.",
                        status=CommandStatus.REJECTED,
                        junction_id=cmd.junction_id,
                        applied_phase=cmd.target_phase,
                        simulation_time=current_sim_time,
                        command_id=cmd.command_id,
                        rejection_reason="INVALID_JUNCTION",
                        executing_thread=worker_thread_name,
                    )
                    cmd.complete_execution(res)
                    continue

                # 4. Check Emergency Priority Lock (Invariant: Priority over manual override)
                if ctrl.emergency_locked:
                    curr_p = ctrl.get_phase()
                    res = CommandResult(
                        success=False,
                        message=f"Override rejected: Junction {cmd.junction_id} is locked by active Emergency Green Wave priority.",
                        status=CommandStatus.REJECTED,
                        junction_id=cmd.junction_id,
                        applied_phase=curr_p,
                        simulation_time=current_sim_time,
                        command_id=cmd.command_id,
                        rejection_reason="EMERGENCY_LOCKED",
                        executing_thread=worker_thread_name,
                    )
                    cmd.complete_execution(res)
                    with self._lock:
                        self._record_decision(
                            sim_time=current_sim_time,
                            junction_id=cmd.junction_id,
                            current_phase=curr_p,
                            target_phase=cmd.target_phase,
                            action="OVERRIDE_REJECTED",
                            reason="Rejected manual switch: Junction is locked by active emergency vehicle priority.",
                            is_override=True,
                        )
                    continue

                # 5. Validate phase
                valid_phases = {0, 1, 2, 3}
                if cmd.target_phase not in valid_phases:
                    curr_p = ctrl.get_phase()
                    res = CommandResult(
                        success=False,
                        message=f"Invalid phase index {cmd.target_phase}. Valid phases for {cmd.junction_id} are {sorted(list(valid_phases))}.",
                        status=CommandStatus.REJECTED,
                        junction_id=cmd.junction_id,
                        applied_phase=curr_p,
                        simulation_time=current_sim_time,
                        command_id=cmd.command_id,
                        rejection_reason="INVALID_PHASE",
                        executing_thread=worker_thread_name,
                    )
                    cmd.complete_execution(res)
                    continue

                current_phase = ctrl.get_phase()

                # 6. Already in target phase (NOOP)
                if current_phase == cmd.target_phase:
                    res = CommandResult(
                        success=True,
                        message=f"Manual override applied: Junction {cmd.junction_id} is already in target phase {cmd.target_phase}.",
                        status=CommandStatus.EXECUTED,
                        junction_id=cmd.junction_id,
                        applied_phase=cmd.target_phase,
                        simulation_time=current_sim_time,
                        command_id=cmd.command_id,
                        executing_thread=worker_thread_name,
                    )
                    cmd.complete_execution(res)
                    with self._lock:
                        self._record_decision(
                            sim_time=current_sim_time,
                            junction_id=cmd.junction_id,
                            current_phase=current_phase,
                            target_phase=cmd.target_phase,
                            action="MANUAL_OVERRIDE_NOOP",
                            reason=f"Operator requested phase switch to {cmd.target_phase}; junction already in phase {current_phase}.",
                            is_override=True,
                        )
                    continue

                # 7. Check green phase & min_green constraint
                if current_phase in ctrl.green_phases:
                    elapsed = ctrl.get_green_elapsed(current_sim_time)
                    if elapsed < ctrl.min_green:
                        remaining = ctrl.min_green - elapsed
                        msg = (
                            f"Override rejected: Minimum green time active on {cmd.junction_id} "
                            f"(elapsed {elapsed:.1f}s < min {ctrl.min_green:.1f}s). Remaining: {remaining:.1f}s."
                        )
                        res = CommandResult(
                            success=False,
                            message=msg,
                            status=CommandStatus.REJECTED,
                            junction_id=cmd.junction_id,
                            applied_phase=current_phase,
                            simulation_time=current_sim_time,
                            command_id=cmd.command_id,
                            rejection_reason="MIN_GREEN_ACTIVE",
                            executing_thread=worker_thread_name,
                        )
                        cmd.complete_execution(res)
                        with self._lock:
                            self._record_decision(
                                sim_time=current_sim_time,
                                junction_id=cmd.junction_id,
                                current_phase=current_phase,
                                target_phase=cmd.target_phase,
                                action="OVERRIDE_REJECTED",
                                reason=f"Rejected manual switch: Minimum green time active ({elapsed:.1f}s < {ctrl.min_green:.1f}s).",
                                is_override=True,
                            )
                        continue

                    # Min green satisfied: initiate switch through yellow transition
                    switch_ok = ctrl.request_switch(target_green_phase=cmd.target_phase, sim_time=current_sim_time)
                    if switch_ok:
                        msg = f"Manual override successfully applied to {cmd.junction_id}: phase switched to {cmd.target_phase}."
                        res = CommandResult(
                            success=True,
                            message=msg,
                            status=CommandStatus.EXECUTED,
                            junction_id=cmd.junction_id,
                            applied_phase=cmd.target_phase,
                            simulation_time=current_sim_time,
                            command_id=cmd.command_id,
                            executing_thread=worker_thread_name,
                        )
                        cmd.complete_execution(res)
                        with self._lock:
                            self._record_decision(
                                sim_time=current_sim_time,
                                junction_id=cmd.junction_id,
                                current_phase=current_phase,
                                target_phase=cmd.target_phase,
                                action="MANUAL_OVERRIDE",
                                reason=f"Operator manually forced phase switch to {cmd.target_phase}.",
                                is_override=True,
                            )
                    else:
                        msg = f"Override rejected: Junction {cmd.junction_id} could not execute switch."
                        res = CommandResult(
                            success=False,
                            message=msg,
                            status=CommandStatus.REJECTED,
                            junction_id=cmd.junction_id,
                            applied_phase=current_phase,
                            simulation_time=current_sim_time,
                            command_id=cmd.command_id,
                            rejection_reason="SWITCH_FAILED",
                            executing_thread=worker_thread_name,
                        )
                        cmd.complete_execution(res)
                    continue

                # 8. In yellow clearance phase
                if ctrl.is_yellow(current_phase):
                    msg = f"Override rejected: Junction {cmd.junction_id} is currently clearing yellow phase {current_phase}."
                    res = CommandResult(
                        success=False,
                        message=msg,
                        status=CommandStatus.REJECTED,
                        junction_id=cmd.junction_id,
                        applied_phase=current_phase,
                        simulation_time=current_sim_time,
                        command_id=cmd.command_id,
                        rejection_reason="CLEARING_YELLOW",
                        executing_thread=worker_thread_name,
                    )
                    cmd.complete_execution(res)
                    with self._lock:
                        self._record_decision(
                            sim_time=current_sim_time,
                            junction_id=cmd.junction_id,
                            current_phase=current_phase,
                            target_phase=cmd.target_phase,
                            action="OVERRIDE_REJECTED",
                            reason=f"Rejected manual switch: Junction is in yellow clearance phase {current_phase}.",
                            is_override=True,
                        )
                    continue

            except (traci.exceptions.FatalTraCIError, ConnectionError, BrokenPipeError) as fatal_exc:
                logger.critical(
                    f"Fatal TraCI connection failure during command execution "
                    f"(command_id={cmd.command_id}, session={cmd.session_uuid}, junction={cmd.junction_id}): {fatal_exc}",
                    exc_info=True,
                )
                fail_res = CommandResult(
                    success=False,
                    message=f"Fatal TraCI connection failure: {fatal_exc}",
                    status=CommandStatus.REJECTED,
                    junction_id=cmd.junction_id,
                    applied_phase=cmd.target_phase,
                    simulation_time=current_sim_time,
                    command_id=cmd.command_id,
                    rejection_reason="FATAL_TRACI_ERROR",
                    executing_thread=worker_thread_name,
                )
                cmd.complete_execution(fail_res)
                raise

            except Exception as cmd_exc:
                logger.exception(
                    f"Command execution error (command_id={cmd.command_id}, session={cmd.session_uuid}, "
                    f"junction={cmd.junction_id}): {cmd_exc}"
                )
                fail_res = CommandResult(
                    success=False,
                    message=f"Command execution error: {cmd_exc}",
                    status=CommandStatus.REJECTED,
                    junction_id=cmd.junction_id,
                    applied_phase=cmd.target_phase,
                    simulation_time=current_sim_time,
                    command_id=cmd.command_id,
                    rejection_reason="COMMAND_EXECUTION_EXCEPTION",
                    executing_thread=worker_thread_name,
                )
                cmd.complete_execution(fail_res)
                # Continue loop to process remaining commands safely

    def request_manual_override(
        self,
        junction_id: str,
        target_phase: int,
        confirmed: bool,
        timeout_s: float = 3.0,
    ) -> CommandResult:
        """
        Enqueues an operator-confirmed manual phase override onto the simulation worker's
        thread-safe TraCI command queue.

        The calling thread NEVER touches TraCI directly. The command is processed exclusively
        by the SumoSimulationWorker thread prior to simulationStep().

        Returns a CommandResult (unpacks as (success: bool, message: str) for backward compatibility).
        """
        caller_thread_name = threading.current_thread().name

        if not confirmed:
            return CommandResult(
                success=False,
                message="Manual override requires explicit operator confirmation.",
                status=CommandStatus.REJECTED,
                junction_id=junction_id,
                applied_phase=target_phase,
                simulation_time=self._current_sim_time,
                rejection_reason="UNCONFIRMED",
                executing_thread=caller_thread_name,
            )

        with self._lock:
            if not self._running or self._stop_requested or not self._sim or self._command_queue is None:
                return CommandResult(
                    success=False,
                    message="Cannot override: Simulation is not currently running.",
                    status=CommandStatus.REJECTED,
                    junction_id=junction_id,
                    applied_phase=target_phase,
                    simulation_time=self._current_sim_time,
                    rejection_reason="SIMULATION_NOT_RUNNING",
                    executing_thread=caller_thread_name,
                )

            junction_id_upper = junction_id.upper()
            if junction_id_upper not in self._sim.controllers:
                return CommandResult(
                    success=False,
                    message=f"Invalid junction ID '{junction_id}'. Must be J1, J2, or J3.",
                    status=CommandStatus.REJECTED,
                    junction_id=junction_id,
                    applied_phase=target_phase,
                    simulation_time=self._current_sim_time,
                    rejection_reason="INVALID_JUNCTION",
                    executing_thread=caller_thread_name,
                )

            valid_phases = {0, 1, 2, 3}
            if target_phase not in valid_phases:
                return CommandResult(
                    success=False,
                    message=f"Invalid phase index {target_phase}. Valid phases for {junction_id_upper} are {sorted(list(valid_phases))}.",
                    status=CommandStatus.REJECTED,
                    junction_id=junction_id_upper,
                    applied_phase=target_phase,
                    simulation_time=self._current_sim_time,
                    rejection_reason="INVALID_PHASE",
                    executing_thread=caller_thread_name,
                )

            ctrl = self._sim.controllers[junction_id_upper]
            if ctrl.emergency_locked:
                return CommandResult(
                    success=False,
                    message=f"Override rejected: Junction {junction_id_upper} is locked by active Emergency Green Wave priority.",
                    status=CommandStatus.REJECTED,
                    junction_id=junction_id_upper,
                    applied_phase=target_phase,
                    simulation_time=self._current_sim_time,
                    rejection_reason="EMERGENCY_LOCKED",
                    executing_thread=caller_thread_name,
                )

            cmd_id = f"cmd_{uuid.uuid4().hex[:8]}"
            cmd = SignalOverrideCommand(
                command_id=cmd_id,
                session_uuid=self._current_run_uuid or "",
                junction_id=junction_id_upper,
                target_phase=target_phase,
                confirmed=confirmed,
                created_at=time.time(),
                timeout_s=timeout_s,
            )

            try:
                self._command_queue.put_nowait(cmd)
            except queue.Full:
                return CommandResult(
                    success=False,
                    message=f"Command queue is full (capacity {self._command_queue.maxsize}). Request rejected.",
                    status=CommandStatus.REJECTED,
                    junction_id=junction_id_upper,
                    applied_phase=target_phase,
                    simulation_time=self._current_sim_time,
                    command_id=cmd_id,
                    rejection_reason="QUEUE_FULL",
                    executing_thread=caller_thread_name,
                )

        # Wait outside lock so worker thread is not blocked
        try:
            return cmd.future.result(timeout=timeout_s)
        except concurrent.futures.TimeoutError:
            return cmd.handle_caller_timeout(self._current_sim_time, caller_thread_name)

    # ------------------------------------------------------------------
    # Public Getters for API
    # ------------------------------------------------------------------

    def get_status(self) -> SimulationStatusResponse:
        """Returns comprehensive status of current simulation."""
        with self._lock:
            is_actively_running = self._running and self._startup_status == StartupStatus.READY
            current_status = (
                self._startup_status.value
                if isinstance(self._startup_status, StartupStatus)
                else str(self._startup_status)
            )
            return SimulationStatusResponse(
                running=is_actively_running,
                paused=self._paused,
                simulation_time=self._current_sim_time,
                duration=self._duration,
                mode=self._mode,
                seed=self._seed,
                controller="Coordinated Adaptive (Inflow-Aware + Green Wave)" if self._mode == "coordinated" else "Fixed-Time Baseline",
                junctions=["J1", "J2", "J3"],
                error=self._error_message,
                status=current_status,
                pid=self._active_sumo_pid,
                run_uuid=self._current_run_uuid,
                sequence_number=self._sequence_number,
            )

    def get_sequence_number(self) -> int:
        """Returns the current monotonic sequence number for the active simulation session."""
        with self._lock:
            return self._sequence_number

    def get_live_junctions(self) -> Dict[str, Any]:
        """Returns latest extracted junction states."""
        with self._lock:
            result = {}
            for j_id in ["J1", "J2", "J3"]:
                st = self._latest_states.get(j_id)
                if st:
                    em = st.emissions
                    emergencies_list = [
                        EmergencyApproachingSchema(
                            vehicle_id=e.vehicle_id,
                            approach=e.approach,
                            distance_to_stopline_m=round(e.distance_to_stopline_m, 1),
                            speed_mps=round(e.speed_mps, 1),
                            estimated_arrival_s=round(e.estimated_arrival_s, 1),
                        )
                        for e in st.approaching_emergency_vehicles
                    ]
                    result[j_id] = JunctionStateSchema(
                        junction_id=j_id,
                        tls_id=st.tls_id,
                        simulation_time=st.simulation_time,
                        current_phase=st.current_phase,
                        phase_duration=st.phase_duration,
                        phase_elapsed=st.phase_elapsed,
                        time_to_switch=st.time_to_switch,
                        approach_queues=st.approach_queues,
                        total_queue=st.total_queue,
                        average_speed_kmh=round(st.average_speed_kmh, 2),
                        total_waiting_time=round(st.total_waiting_time, 2),
                        vehicle_count=st.vehicle_count,
                        vehicle_ids=st.vehicle_ids,
                        emissions=EmissionSchema(
                            co2_mg_s=round(em.co2_mg_s, 2),
                            nox_mg_s=round(em.nox_mg_s, 2),
                            fuel_ml_s=round(em.fuel_ml_s, 2),
                            co_mg_s=round(em.co_mg_s, 2),
                            pmx_mg_s=round(em.pmx_mg_s, 2),
                            accumulated_co2_kg=round(em.accumulated_co2_kg, 4),
                            accumulated_fuel_liters=round(em.accumulated_fuel_liters, 4),
                        ),
                        emergency_present=len(emergencies_list) > 0,
                        approaching_emergency_vehicles=emergencies_list,
                    ).model_dump()
                else:
                    # Default placeholder if not yet stepped
                    result[j_id] = JunctionStateSchema(
                        junction_id=j_id,
                        tls_id="",
                        simulation_time=self._current_sim_time,
                        current_phase=0,
                        phase_duration=0.0,
                        phase_elapsed=0.0,
                        time_to_switch=0.0,
                    ).model_dump()
            return result

    def get_metrics(self) -> Dict[str, Any]:
        """Returns corridor-wide metrics summary."""
        with self._lock:
            if self._cached_metrics:
                return self._cached_metrics
            return {
                "simulation_time": self._current_sim_time,
                "total_vehicles": 0,
                "throughput_vehicles": 0,
                "mean_speed_kmh": 0.0,
                "total_corridor_waiting_time_s": 0.0,
                "mean_corridor_queue": 0.0,
                "max_corridor_queue": 0,
                "total_co2_kg": 0.0,
                "total_nox_g": 0.0,
                "total_fuel_liters": 0.0,
                "emergency_traversal_duration_s": 0.0,
                "junction_queues": {"J1": 0, "J2": 0, "J3": 0},
            }

    def get_signals(self) -> Dict[str, Any]:
        """Returns signal controllers status for J1, J2, J3."""
        with self._lock:
            signals = {}
            for j_id in ["J1", "J2", "J3"]:
                st = self._latest_states.get(j_id)
                ctrl = self._sim.controllers.get(j_id) if self._sim else None
                curr_phase = st.current_phase if st else 0
                is_grn = ctrl.is_green(curr_phase) if ctrl else (curr_phase in {0, 2})
                is_yel = ctrl.is_yellow(curr_phase) if ctrl else (curr_phase in {1, 3})
                locked = ctrl.emergency_locked if ctrl else False

                signals[j_id] = SignalInfoSchema(
                    junction_id=j_id,
                    tls_id=st.tls_id if st else "",
                    current_phase=curr_phase,
                    is_green=is_grn,
                    is_yellow=is_yel,
                    phase_elapsed=st.phase_elapsed if st else 0.0,
                    time_to_switch=st.time_to_switch if st else 0.0,
                    min_green=ctrl.min_green if ctrl else 15.0,
                    max_green=ctrl.max_green if ctrl else 60.0,
                    emergency_locked=locked,
                    approach_queues=st.approach_queues if st else {},
                ).model_dump()
            return signals

    def get_emergencies(self) -> Dict[str, Any]:
        """Returns emergency alerts and traversal performance."""
        with self._lock:
            locked = []
            active_veh = None
            if self._sim and self._enable_emergency:
                coord = self._sim.emergency_coordinator
                locked = [j for j, ctrl in self._sim.controllers.items() if ctrl.emergency_locked]
                if coord.metrics.vehicle_id and not coord.metrics.completed:
                    active_veh = coord.metrics.vehicle_id

            return EmergencyResponse(
                active_emergency=len(locked) > 0 or active_veh is not None,
                emergency_locked_junctions=locked,
                total_completed_events=len([e for e in self._emergency_events if e.completed]),
                active_vehicle_id=active_veh,
                events=list(self._emergency_events),
            ).model_dump()

    def get_decisions(self) -> List[DecisionItemSchema]:
        """Returns controller decisions history."""
        with self._lock:
            return list(self._decisions_log)


# Global singleton instance
sim_service = SimulationService()

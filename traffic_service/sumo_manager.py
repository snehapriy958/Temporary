"""
traffic_service/sumo_manager.py

Robust SUMO subprocess and TraCI lifecycle management.
Ensures safe startup, stepping, and clean shutdown across runs and seeds.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

import traci
import traci.main

from common.sumo_env import require_sumo_env, SumoEnvironment

logger = logging.getLogger("sumo_manager")

# Narrowly-scoped lock ensuring serialized TraCI module proxying during startup
_traci_startup_lock = threading.Lock()


class _TraciScopedSubprocessProxy:
    """
    Scoped module proxy for traci.main.subprocess.
    Preserves sys.modules['subprocess'] and subprocess.Popen globally,
    intercepting Popen calls strictly within traci.main and filtering
    for the target SUMO command.
    """

    def __init__(
        self,
        real_module: Any,
        expected_config_path: str,
        on_process_spawned: Optional[Callable[[subprocess.Popen, Optional[int]], None]] = None,
    ) -> None:
        self._real_module = real_module
        self._expected_config = expected_config_path
        self._on_process_spawned = on_process_spawned
        self.captured_process: Optional[subprocess.Popen] = None
        self.captured_pid: Optional[int] = None

    def Popen(self, *args: Any, **kwargs: Any) -> subprocess.Popen:
        proc = self._real_module.Popen(*args, **kwargs)

        # Inspect command line to ensure only the intended SUMO command is captured
        cmd_args = args[0] if args else kwargs.get("args", [])
        cmd_str = " ".join(cmd_args) if isinstance(cmd_args, (list, tuple)) else str(cmd_args)

        is_sumo = "sumo" in cmd_str.lower() or self._expected_config.lower() in cmd_str.lower()
        if is_sumo:
            self.captured_process = proc
            if hasattr(proc, "pid"):
                self.captured_pid = proc.pid
            logger.info(f"Captured spawned SUMO process via scoped proxy: PID {self.captured_pid}")
            if self._on_process_spawned:
                try:
                    self._on_process_spawned(proc, self.captured_pid)
                except Exception as cb_err:
                    logger.warning(f"Error in on_process_spawned callback: {cb_err}")
        else:
            logger.debug(f"Ignoring non-SUMO subprocess spawned during proxy window: {cmd_str[:60]}")
        return proc

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real_module, name)


class SumoManager:
    """Manages starting, stepping, and closing the SUMO simulator via TraCI."""

    def __init__(
        self,
        sumocfg_path: Path | str,
        gui: bool = False,
        step_length: float = 1.0,
        label: str = "default",
        on_process_spawned: Optional[Callable[[subprocess.Popen, Optional[int]], None]] = None,
    ) -> None:
        self.sumocfg_path = Path(sumocfg_path).resolve()
        if not self.sumocfg_path.is_file():
            raise FileNotFoundError(f"SUMO configuration file not found: {self.sumocfg_path}")
        self.gui = gui
        self.step_length = step_length
        self.label = label
        self.on_process_spawned = on_process_spawned
        self.env: SumoEnvironment = require_sumo_env()
        self._is_running: bool = False
        self._process: Optional[subprocess.Popen] = None
        self._pid: Optional[int] = None

    @property
    def is_running(self) -> bool:
        has_conn = False
        try:
            has_conn = traci.connection.has(self.label)
        except Exception:
            has_conn = traci.isLoaded()
        return self._is_running and has_conn

    @property
    def process(self) -> Optional[subprocess.Popen]:
        """Returns the subprocess.Popen handle for the active SUMO instance, if available."""
        return self._process

    @property
    def pid(self) -> Optional[int]:
        """Returns the OS PID for the active SUMO instance, if available."""
        return self._pid

    def _handle_process_spawned(self, proc: subprocess.Popen, pid: Optional[int]) -> None:
        """Internal callback invoked by _TraciScopedSubprocessProxy when SUMO is spawned."""
        self._process = proc
        self._pid = pid
        if self.on_process_spawned:
            try:
                self.on_process_spawned(proc, pid)
            except Exception as cb_err:
                logger.warning(f"Error in on_process_spawned callback: {cb_err}")

    def start(self, seed: int = 42, additional_args: Sequence[str] | None = None) -> None:
        """Starts the SUMO process and initializes the TraCI connection."""
        try:
            if hasattr(traci, "connection") and traci.connection.has(self.label):
                try:
                    con = traci.getConnection(self.label)
                    con.close(wait=False)
                except Exception:
                    pass
                if hasattr(traci.connection, "_connections"):
                    traci.connection._connections.pop(self.label, None)
                    if traci.connection._connections.get("") == con:
                        traci.connection._connections.pop("", None)
        except Exception:
            pass

        if traci.isLoaded():
            try:
                traci.close()
            except Exception:
                pass

        binary = str(self.env.sumo_gui_binary if self.gui else self.env.sumo_binary)

        cmd = [
            binary,
            "-c", str(self.sumocfg_path),
            "--step-length", str(self.step_length),
            "--seed", str(seed),
            "--step-log.period", "0",
            "--no-step-log", "true",
            "--time-to-teleport", "300",
        ]

        if additional_args:
            cmd.extend(additional_args)

        # Intercept TraCI SUMO startup via isolated scoped proxy on traci.main.subprocess.
        # Preserves sys.modules['subprocess'] and subprocess.Popen globally, ensuring
        # zero impact on other threads or application components.
        # Synchronized via _traci_startup_lock to serialize proxy installation.
        with _traci_startup_lock:
            original_module = traci.main.subprocess
            proxy = _TraciScopedSubprocessProxy(
                real_module=original_module,
                expected_config_path=str(self.sumocfg_path),
                on_process_spawned=self._handle_process_spawned,
            )
            traci.main.subprocess = proxy
            try:
                traci.start(cmd, label=self.label)
                self._is_running = True
            finally:
                traci.main.subprocess = original_module
                if proxy.captured_process is not None:
                    self._process = proxy.captured_process
                    self._pid = proxy.captured_pid

        try:
            con = traci.getConnection(self.label)
            con_proc = getattr(con, "_process", None)
            if con_proc is not None:
                self._process = con_proc
                self._pid = getattr(con_proc, "pid", self._pid)
                logger.info(f"SUMO connection confirmed: PID {self._pid} (label: '{self.label}')")
        except Exception as exc:
            logger.debug(f"Could not retrieve TraCI connection process handle: {exc}")

    def step(self) -> float:
        """Advances the simulation by one step and returns the current simulation time."""
        if not self.is_running:
            raise RuntimeError("Cannot advance step: SUMO is not currently running.")
        traci.simulationStep()
        return traci.simulation.getTime()

    def get_time(self) -> float:
        """Returns the current simulation time in seconds."""
        if not self.is_running:
            return 0.0
        return traci.simulation.getTime()

    def stop(self) -> None:
        """Closes the TraCI connection cleanly."""
        process = self._process
        try:
            if hasattr(traci, "connection") and traci.connection.has(self.label):
                con = None
                try:
                    con = traci.getConnection(self.label)
                    con.close(wait=False)
                except Exception:
                    pass
                if hasattr(traci.connection, "_connections"):
                    traci.connection._connections.pop(self.label, None)
                    if con is not None and traci.connection._connections.get("") == con:
                        traci.connection._connections.pop("", None)
        except Exception:
            pass

        if traci.isLoaded():
            try:
                traci.close(wait=False)
            except Exception as exc:
                logger.debug("TraCI global close fallback failed: %s", exc)

        if process is not None:
            try:
                if process.poll() is None:
                    try:
                        return_code = process.wait(timeout=2.0)
                        logger.debug(
                            "SUMO exited after TraCI close (PID %s, return code %s).",
                            process.pid,
                            return_code,
                        )
                    except subprocess.TimeoutExpired:
                        logger.warning(
                            "SUMO PID %s did not exit within 2.0s after TraCI close; terminating.",
                            process.pid,
                        )
                        process.terminate()
                        try:
                            process.wait(timeout=2.0)
                        except subprocess.TimeoutExpired:
                            logger.error(
                                "SUMO PID %s did not exit after terminate; killing as final fallback.",
                                process.pid,
                            )
                            process.kill()
                            process.wait()
            except Exception as exc:
                logger.warning("Error while reaping SUMO process PID %s: %s", process.pid, exc)

        self._is_running = False
        self._process = None
        self._pid = None

    def __enter__(self) -> SumoManager:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.stop()

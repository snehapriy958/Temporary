"""Bounded API stop-endpoint and SUMO termination-path probe."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEMO_SITE_PACKAGES = ROOT / ".venv-demo" / "Lib" / "site-packages"
if DEMO_SITE_PACKAGES.is_dir():
    sys.path.append(str(DEMO_SITE_PACKAGES))

from fastapi.testclient import TestClient
from backend.main import app
from backend.simulation_service import sim_service

OUTPUT = ROOT / "scratch" / "p6_7_stop_endpoint_results.json"
if OUTPUT.exists():
    raise FileExistsError(f"Refusing to overwrite existing evidence: {OUTPUT}")
if os.environ.get("DATABASE_URL") != "sqlite:///./demo_audit_disposable.db":
    raise RuntimeError("Expected disposable DATABASE_URL")

spawned = []
original_callback = sim_service._on_process_spawned


def capture_process(proc, pid):
    original_terminate = proc.terminate
    record = {"pid": pid, "terminate_called": False}

    def observe_terminate():
        record["terminate_called"] = True
        return original_terminate()

    proc.terminate = observe_terminate
    spawned.append((proc, record))
    original_callback(proc, pid)


sim_service._on_process_spawned = capture_process
try:
    with TestClient(app) as client:
        started = client.post("/api/simulation/start", json={
            "mode": "baseline",
            "duration": 120,
            "seed": 99,
            "step_length": 1,
            "decision_interval": 5,
            "enable_emergency": False,
            "gui": False,
            "startup_timeout_s": 20,
        })
        if started.status_code != 200:
            raise AssertionError(f"Start failed: {started.status_code} {started.text}")
        stop = client.post("/api/simulation/stop")
        worker = sim_service._thread
        if worker:
            worker.join(timeout=15)
        status = client.get("/api/simulation/status").json()
        sim = sim_service._sim
    proc, process_record = spawned[-1]
    result = {
        "start_status": started.status_code,
        "stop_status": stop.status_code,
        "stop_response": stop.json(),
        "final_status": status,
        "worker_stopped": bool(worker and not worker.is_alive()),
        "backend_simulation_cleared": sim is None,
        "backend_pid_cleared": status.get("pid") is None,
        "sumo_pid": process_record["pid"],
        "sumo_terminate_called_by_manager": process_record["terminate_called"],
        "sumo_return_code": proc.poll(),
        "sumo_process_reaped": proc.poll() is not None,
    }
    result["overall"] = "PASSED" if all((
        result["start_status"] == 200,
        result["stop_status"] == 200,
        result["worker_stopped"],
        result["backend_simulation_cleared"],
        result["backend_pid_cleared"],
        result["sumo_terminate_called_by_manager"],
        result["sumo_process_reaped"],
    )) else "FAILED"
    if result["overall"] != "PASSED":
        raise AssertionError(json.dumps(result, indent=2))
    OUTPUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
finally:
    sim_service._on_process_spawned = original_callback

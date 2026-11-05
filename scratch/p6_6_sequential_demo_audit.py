"""Sequential backend/API rehearsal across all four demo controllers."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DEMO_SITE_PACKAGES = ROOT / ".venv-demo" / "Lib" / "site-packages"
if DEMO_SITE_PACKAGES.is_dir():
    sys.path.append(str(DEMO_SITE_PACKAGES))

from fastapi.testclient import TestClient
from backend.main import app
import backend.simulation_service as simulation_service_module
from backend.simulation_service import sim_service


OUTPUT = ROOT / "scratch" / "p6_6_sequential_demo_results2.json"
if OUTPUT.exists():
    raise FileExistsError(f"Refusing to overwrite existing evidence: {OUTPUT}")
os.environ.setdefault("DATABASE_URL", "sqlite:///./demo_audit_disposable.db")

original_simulation_class = simulation_service_module.MultiIntersectionSimulation
instances: list[Any] = []
spawned_processes: list[Any] = []


class AuditedSimulation(original_simulation_class):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.audit_phases = {j: set() for j in ("J1", "J2", "J3")}
        self.audit_operations: list[dict[str, str]] = []
        if self.marl_controller is not None:
            original_apply = self.marl_controller.apply_decisions

            def capture(decisions, sim_time):
                operations = original_apply(decisions, sim_time)
                self.audit_operations.append(operations)
                return operations

            self.marl_controller.apply_decisions = capture
        instances.append(self)

    def get_states(self, sim_time):
        states = super().get_states(sim_time)
        for junction, state in states.items():
            self.audit_phases[junction].add(int(state.current_phase))
        return states


def exact_checkpoint_weights(sim, algorithm: str, relpath: str) -> bool:
    payload = json.loads((ROOT / relpath).read_text(encoding="utf-8"))
    key = "weights" if algorithm == "ppo" else "q_network_weights"
    for junction, agent in sim.marl_controller.agents.items():
        loaded = agent.get_state_dict()[key]
        stored = payload["agents"][junction][key]
        if not all(np.array_equal(np.asarray(loaded[k]), np.asarray(stored[k])) for k in stored):
            return False
    return True


def run_one(client: TestClient, mode: str, duration: int, checkpoint: str | None = None) -> dict[str, Any]:
    payload = {
        "mode": mode,
        "duration": duration,
        "seed": 99,
        "step_length": 1.0,
        "decision_interval": 5.0,
        "enable_emergency": False,
        "gui": False,
        "startup_timeout_s": 20.0,
    }
    if checkpoint:
        payload["checkpoint_path"] = checkpoint
    response = client.post("/api/simulation/start", json=payload)
    if response.status_code != 200:
        raise AssertionError(f"{mode} start failed: {response.status_code} {response.text}")
    run_uuid = sim_service._current_run_uuid
    worker = sim_service._thread
    if worker is None:
        raise AssertionError(f"{mode} start returned without a worker")
    worker.join(timeout=45)
    if worker.is_alive():
        client.post("/api/simulation/stop")
        worker.join(timeout=15)
        raise TimeoutError(f"{mode} did not finish within the bounded join")

    sim = instances[-1]
    status = client.get("/api/simulation/status").json()
    metrics = client.get("/api/traffic/metrics").json()
    pid_match = __import__("re").search(r"PID: (\d+)", response.json()["message"])
    pid = int(pid_match.group(1)) if pid_match else None
    proc = spawned_processes[-1] if spawned_processes else None
    result = {
        "mode": mode,
        "run_uuid": run_uuid,
        "checkpoint_path": checkpoint,
        "start_http_status": response.status_code,
        "final_status": status,
        "final_metrics": metrics,
        "phase_ids_observed": {j: sorted(phases) for j, phases in sim.audit_phases.items()},
        "action_dispatch_count": len(sim.audit_operations),
        "sample_executed_operations": sim.audit_operations[:2],
        "sumo_pid": pid,
        "sumo_process_returncode": proc.poll() if proc else None,
        "sumo_running_after_run": sim.sumo_manager.is_running,
        "service_sim_is_none_after_cleanup": sim_service._sim is None,
        "worker_stopped": not worker.is_alive(),
        "checkpoint_weights_exact_match": (
            exact_checkpoint_weights(sim, "ppo", checkpoint) if mode == "marl_ppo" else
            exact_checkpoint_weights(sim, "dqn", checkpoint) if mode == "marl_dqn" else None
        ),
    }
    if status.get("run_uuid") != run_uuid or status.get("status") != "COMPLETED":
        raise AssertionError(f"Unexpected terminal state for {mode}: {status}")
    if status.get("pid") is not None or sim.sumo_manager.is_running or sim_service._sim is not None or worker.is_alive():
        raise AssertionError(f"Lifecycle cleanup failed for {mode}")
    if proc is None or proc.poll() is None:
        raise AssertionError(f"SUMO subprocess did not exit for {mode}")
    if any(len(sim.audit_phases.get(j, set())) < 2 for j in ("J1", "J2", "J3")):
        raise AssertionError(f"Not all junction phases changed for {mode}: {sim.audit_phases}")
    if mode in ("marl_ppo", "marl_dqn"):
        if result["checkpoint_weights_exact_match"] is not True or len(sim.audit_operations) < 2:
            raise AssertionError(f"Checkpoint inference/dispatch missing for {mode}")
        if not all(set(x) == {"J1", "J2", "J3"} for x in sim.audit_operations):
            raise AssertionError(f"MARL dispatch missed junction(s) for {mode}")
    result["result"] = "PASSED"
    return result


simulation_service_module.MultiIntersectionSimulation = AuditedSimulation
original_spawn_callback = sim_service._on_process_spawned
def capture_spawned_process(proc, pid):
    spawned_processes.append(proc)
    original_spawn_callback(proc, pid)
sim_service._on_process_spawned = capture_spawned_process
try:
    with TestClient(app) as client:
        runs = [
            run_one(client, "baseline", 120),
            run_one(client, "coordinated", 120),
            run_one(client, "marl_ppo", 90, "checkpoints/p6/ppo_stage_a_best.json"),
            run_one(client, "marl_dqn", 90, "checkpoints/p6/dqn_stage_a_best.json"),
        ]
    result = {
        "database_url": os.environ["DATABASE_URL"],
        "runs_in_sequence": [x["mode"] for x in runs],
        "runs": runs,
        "run_uuids_unique": len({x["run_uuid"] for x in runs}) == len(runs),
        "all_runs_passed": all(x["result"] == "PASSED" for x in runs),
        "overall": "PASSED",
    }
    OUTPUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
finally:
    sim_service._on_process_spawned = original_spawn_callback
    simulation_service_module.MultiIntersectionSimulation = original_simulation_class

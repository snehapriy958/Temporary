"""Bounded API-to-SUMO verification for P6.5 approved PPO/DQN checkpoints."""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

# Reuse the already-created, read-only demo package tree alongside the existing
# torch-enabled audit interpreter. This does not install into or alter either venv.
ROOT = Path(__file__).resolve().parents[1]
DEMO_SITE_PACKAGES = ROOT / ".venv-demo" / "Lib" / "site-packages"
if DEMO_SITE_PACKAGES.is_dir():
    sys.path.append(str(DEMO_SITE_PACKAGES))

import numpy as np
from fastapi.testclient import TestClient

from backend.main import app
import backend.simulation_service as simulation_service_module
from backend.simulation_service import sim_service


OUTPUT = ROOT / "scratch" / "p6_5_api_run_results_verified3.json"
if OUTPUT.exists():
    raise FileExistsError(f"Refusing to overwrite existing evidence: {OUTPUT}")

SUMO_HOME = os.environ.get("SUMO_HOME")
if not SUMO_HOME:
    raise EnvironmentError("SUMO_HOME must point at the installed SUMO distribution")

os.environ.setdefault("DATABASE_URL", "sqlite:///./demo_audit_disposable.db")
os.environ.setdefault("PYTHONPATH", f"{SUMO_HOME}\\tools;{ROOT}")

original_simulation_class = simulation_service_module.MultiIntersectionSimulation
instances: list[Any] = []


class AuditedSimulation(original_simulation_class):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.audit_actions: list[dict[str, Any]] = []
        self.audit_phases: dict[str, set[int]] = {j: set() for j in ("J1", "J2", "J3")}
        if self.marl_controller is not None:
            original_apply = self.marl_controller.apply_decisions

            def capture_apply(decisions, sim_time):
                operations = original_apply(decisions, sim_time)
                self.audit_actions.append({
                    "time": float(sim_time),
                    "actions": {j: int(d["action"]) for j, d in decisions.items()},
                    "operations": operations,
                })
                return operations

            self.marl_controller.apply_decisions = capture_apply
        instances.append(self)

    def get_states(self, sim_time):
        states = super().get_states(sim_time)
        for junction, state in states.items():
            self.audit_phases.setdefault(junction, set()).add(int(state.current_phase))
        return states


def loaded_agent_weights_match(sim, algorithm: str, checkpoint: Path) -> bool:
    payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    state_key = "weights" if algorithm == "ppo" else "q_network_weights"
    for junction, agent in sim.marl_controller.agents.items():
        model_weights = agent.get_state_dict()[state_key]
        checkpoint_weights = payload["agents"][junction][state_key]
        if not all(
            np.allclose(np.asarray(model_weights[k]), np.asarray(checkpoint_weights[k]), rtol=0, atol=0)
            for k in checkpoint_weights
        ):
            return False
    return True


def run_controller(client: TestClient, mode: str, algorithm: str, relative_path: str) -> dict[str, Any]:
    checkpoint = ROOT / relative_path
    start = client.post(
        "/api/simulation/start",
        json={
            "mode": mode,
            "duration": 90,
            "seed": 99,
            "step_length": 1.0,
            "decision_interval": 5.0,
            "enable_emergency": False,
            "gui": False,
            "startup_timeout_s": 20.0,
            "checkpoint_path": relative_path.replace("\\", "/"),
        },
    )
    if start.status_code != 200:
        raise AssertionError(f"API start failed for {mode}: {start.status_code} {start.text}")
    if not sim_service._thread:
        raise AssertionError("API returned success without a simulation worker")
    sim_service._thread.join(timeout=30)
    if sim_service._thread.is_alive():
        raise AssertionError(f"{mode} worker did not finish within 30 seconds")
    status_response = client.get("/api/simulation/status")
    status = status_response.json()
    sim = instances[-1]
    if sim.mode != mode or sim.marl_controller is None:
        raise AssertionError(f"Wrong controller constructed for {mode}")
    if list(sim.marl_controller.agents) != ["J1", "J2", "J3"]:
        raise AssertionError(f"Unexpected junction ordering for {mode}: {list(sim.marl_controller.agents)}")
    if not loaded_agent_weights_match(sim, algorithm, checkpoint):
        raise AssertionError(f"Loaded agent weights do not exactly match the requested checkpoint for {mode}")
    if len(sim.audit_actions) < 2:
        raise AssertionError(f"Insufficient live inference/dispatch calls for {mode}: {len(sim.audit_actions)}")
    if not all(set(run["operations"]) == {"J1", "J2", "J3"} for run in sim.audit_actions):
        raise AssertionError(f"Dispatch did not address every junction for {mode}")
    if not any(
        "REQUEST_SWITCH_TARGET_" in operation and operation.endswith("_OK")
        for run in sim.audit_actions for operation in run["operations"].values()
    ):
        raise AssertionError(f"No accepted signal switch was observed for {mode}")
    if not all(len(sim.audit_phases.get(j, set())) >= 2 for j in ("J1", "J2", "J3")):
        raise AssertionError(f"No observed SUMO phase change at every junction for {mode}: {sim.audit_phases}")
    if status.get("simulation_time") < 90 or status.get("status") not in ("COMPLETED", "STOPPED"):
        raise AssertionError(f"Unexpected final simulation status for {mode}: {status}")
    if sim.sumo_manager.is_running:
        raise AssertionError(f"SUMO remains running after {mode} completed")

    return {
        "mode": mode,
        "requested_checkpoint": relative_path,
        "checkpoint_version": json.loads(checkpoint.read_text(encoding="utf-8"))["algorithm_version"],
        "loaded_all_agent_weights_exact_match": True,
        "agents": list(sim.marl_controller.agents),
        "start_response": start.json(),
        "final_status": status,
        "decision_interval_count": len(sim.audit_actions),
        "sample_decisions": sim.audit_actions[:3],
        "phase_ids_observed": {j: sorted(phases) for j, phases in sim.audit_phases.items()},
        "sumo_running_after_completion": sim.sumo_manager.is_running,
        "result": "PASSED",
    }


logging.basicConfig(level=logging.INFO)
handler = logging.StreamHandler()
handler.setLevel(logging.INFO)
logging.getLogger("simulation_service").addHandler(handler)
logging.getLogger("marl_controller").addHandler(handler)

try:
    simulation_service_module.MultiIntersectionSimulation = AuditedSimulation
    results: dict[str, Any] = {
        "database_url": os.environ["DATABASE_URL"],
        "duration_s": 90,
        "seed": 99,
        "emergency_enabled": False,
        "runs": [],
    }
    with TestClient(app) as client:
        for mode, algorithm, path in (
            ("marl_ppo", "ppo", "checkpoints/p6/ppo_stage_a_best.json"),
            ("marl_dqn", "dqn", "checkpoints/p6/dqn_stage_a_best.json"),
        ):
            results["runs"].append(run_controller(client, mode, algorithm, path))
    results["overall"] = "PASSED"
    OUTPUT.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))
finally:
    simulation_service_module.MultiIntersectionSimulation = original_simulation_class
    logging.getLogger("simulation_service").removeHandler(handler)
    logging.getLogger("marl_controller").removeHandler(handler)

"""Five-run P6.7 sequential API/SUMO rehearsal with lifecycle evidence."""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DEMO_SITE_PACKAGES = ROOT / ".venv-demo" / "Lib" / "site-packages"
if DEMO_SITE_PACKAGES.is_dir():
    sys.path.append(str(DEMO_SITE_PACKAGES))

import traci
from fastapi.testclient import TestClient

from backend.main import app
import backend.simulation_service as simulation_service_module
from backend.simulation_service import sim_service
from traffic_service.emergency_wave import EmergencyWaveCoordinator

OUTPUT = ROOT / "scratch" / "p6_7_sequential_rehearsal_results.json"
if OUTPUT.exists():
    raise FileExistsError(f"Refusing to overwrite existing evidence: {OUTPUT}")
if os.environ.get("DATABASE_URL") != "sqlite:///./demo_audit_disposable.db":
    raise RuntimeError("Expected disposable DATABASE_URL")

JUNCTIONS = ("J1", "J2", "J3")
AMBULANCE_ID = "ambulance_0"
EXPECTED_ROUTE = ["172853382#2", "172853382#3", "1148717038#0", "40696223#1"]
ROUTE_INDEX = {edge: index for index, edge in enumerate(EXPECTED_ROUTE)}
PRIORITY_PHASES = {"J1": 2, "J2": 0, "J3": 2}
YELLOW_PHASES = {"J1": {1, 3}, "J2": {1, 3}, "J3": {1, 3}}
CONFLICT_LANES = {
    "J1": {"-148697299_0"},
    "J2": {"92196679#0_0", "92196679#0_1"},
    "J3": {"-744783934_0"},
}

original_simulation_class = simulation_service_module.MultiIntersectionSimulation
original_update = EmergencyWaveCoordinator.update
original_coordinated = simulation_service_module.SimulationService._run_coordinated_with_logging
original_spawn_callback = sim_service._on_process_spawned
instances: list[Any] = []
spawned_processes: list[Any] = []
active_audit: dict[str, Any] | None = None


class AuditedSimulation(original_simulation_class):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.audit_phases = {junction: set() for junction in JUNCTIONS}
        self.audit_samples = {junction: {"vehicle_count_max": 0, "positive_speed_samples": 0} for junction in JUNCTIONS}
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
            sample = self.audit_samples[junction]
            sample["vehicle_count_max"] = max(sample["vehicle_count_max"], int(state.vehicle_count))
            if state.average_speed_kmh > 0:
                sample["positive_speed_samples"] += 1
        return states


def checkpoint_matches(sim, algorithm: str, relpath: str) -> bool:
    payload = json.loads((ROOT / relpath).read_text(encoding="utf-8"))
    key = "weights" if algorithm == "ppo" else "q_network_weights"
    for junction, agent in sim.marl_controller.agents.items():
        loaded = agent.get_state_dict()[key]
        saved = payload["agents"][junction][key]
        if not all(np.array_equal(np.asarray(loaded[name]), np.asarray(saved[name])) for name in saved):
            return False
    return True


def emergency_snapshot(coordinator, sim_time: float) -> dict[str, Any]:
    try:
        vehicle_ids = traci.vehicle.getIDList()
    except Exception:
        vehicle_ids = []
    vehicle = None
    if AMBULANCE_ID in vehicle_ids:
        vehicle = {
            "id": AMBULANCE_ID,
            "edge": traci.vehicle.getRoadID(AMBULANCE_ID),
            "speed_mps": float(traci.vehicle.getSpeed(AMBULANCE_ID)),
        }
    signals = {}
    for junction, controller in coordinator.controllers.items():
        phase = int(controller.get_phase())
        state = traci.trafficlight.getRedYellowGreenState(controller.tls_id)
        conflict_green_lanes = []
        if phase == PRIORITY_PHASES[junction]:
            controlled_links = traci.trafficlight.getControlledLinks(controller.tls_id)
            for link_index, color in enumerate(state):
                if color not in ("g", "G") or link_index >= len(controlled_links):
                    continue
                for link in controlled_links[link_index]:
                    if link[0] in CONFLICT_LANES[junction]:
                        conflict_green_lanes.append(link[0])
        signals[junction] = {
            "phase": phase,
            "ryg_state": state,
            "emergency_locked": bool(controller.emergency_locked),
            "conflicting_approach_green_lanes": sorted(set(conflict_green_lanes)),
        }
    return {
        "simulation_time_s": float(sim_time),
        "stage": coordinator.current_stage,
        "vehicle": vehicle,
        "signals": signals,
        "completed": bool(coordinator.metrics.completed),
        "traversal_duration_s": float(coordinator.metrics.total_traversal_duration),
    }


def audited_emergency_update(self, sim_time: float) -> None:
    before = {junction: int(controller.get_phase()) for junction, controller in self.controllers.items()}
    was_active = self.active_emergency_id is not None
    original_update(self, sim_time)
    if active_audit is None:
        return
    try:
        ids = traci.vehicle.getIDList()
    except Exception:
        ids = []
    if AMBULANCE_ID in ids or was_active or self.active_emergency_id == AMBULANCE_ID or self.metrics.completed:
        item = emergency_snapshot(self, sim_time)
        item["detected_this_step"] = (not was_active and self.active_emergency_id == AMBULANCE_ID)
        item["phase_before_update"] = before
        active_audit["emergency_observations"].append(item)
        vehicle = item["vehicle"]
        if vehicle and vehicle["edge"] in ROUTE_INDEX:
            if not active_audit["route_edges_seen"] or active_audit["route_edges_seen"][-1] != vehicle["edge"]:
                active_audit["route_edges_seen"].append(vehicle["edge"])
        for junction, signal in item["signals"].items():
            if signal["emergency_locked"] and signal["phase"] == PRIORITY_PHASES[junction]:
                active_audit["priority_green_events"].setdefault(junction, {
                    "simulation_time_s": float(sim_time),
                    "phase": signal["phase"],
                    "ryg_state": signal["ryg_state"],
                    "vehicle_edge": vehicle["edge"] if vehicle else None,
                    "phase_before_update": before[junction],
                    "conflicting_approach_green_lanes": signal["conflicting_approach_green_lanes"],
                    "yellow_seen_before_priority": any(
                        previous["simulation_time_s"] <= sim_time
                        and previous["signals"][junction]["phase"] in YELLOW_PHASES[junction]
                        for previous in active_audit["emergency_observations"][-12:]
                    ),
                })


def audited_coordinated(self, sim, states, sim_time):
    original_coordinated(self, sim, states, sim_time)
    if active_audit is not None and sim.emergency_coordinator.metrics.completed:
        active_audit["normal_control_after_release"].append({
            "simulation_time_s": float(sim_time),
            "locks": {junction: bool(controller.emergency_locked) for junction, controller in sim.controllers.items()},
            "decision_log_count": len(self._decisions_log),
        })


def capture_process(proc, pid):
    spawned_processes.append(proc)
    original_spawn_callback(proc, pid)


def run_one(client, mode: str, duration: int, seed: int, emergency: bool, checkpoint: str | None = None):
    global active_audit
    active_audit = {
        "emergency_observations": [],
        "route_edges_seen": [],
        "priority_green_events": {},
        "normal_control_after_release": [],
    }
    payload = {
        "mode": mode,
        "duration": duration,
        "seed": seed,
        "step_length": 1.0,
        "decision_interval": 5.0,
        "enable_emergency": emergency,
        "gui": False,
        "startup_timeout_s": 20.0,
    }
    if checkpoint:
        payload["checkpoint_path"] = checkpoint
    start_wall = time.time()
    response = client.post("/api/simulation/start", json=payload)
    if response.status_code != 200:
        raise AssertionError(f"Start failed {mode}: {response.status_code}: {response.text}")
    response_data = response.json()
    uuid_match = re.search(r"UUID: ([^,)]+)", response_data["message"])
    run_id = uuid_match.group(1) if uuid_match else sim_service._current_run_uuid
    worker = sim_service._thread
    if worker is None:
        raise AssertionError(f"No worker for {mode}")
    worker.join(timeout=90)
    if worker.is_alive():
        client.post("/api/simulation/stop")
        worker.join(timeout=15)
        raise TimeoutError(f"Timed out while running {mode}")
    sim = instances[-1]
    process = spawned_processes[-1] if spawned_processes else None
    status = client.get("/api/simulation/status").json()
    metrics = client.get("/api/traffic/metrics").json()
    live = client.get("/api/traffic/live").json()
    result = {
        "run_id": run_id,
        "mode": mode,
        "checkpoint_path": checkpoint,
        "request": payload,
        "start_http_status": response.status_code,
        "start_wall_time_epoch": start_wall,
        "finish_wall_time_epoch": time.time(),
        "final_status": status,
        "metrics": metrics,
        "live_status": live.get("status"),
        "junction_phase_ids_observed": {junction: sorted(phases) for junction, phases in sim.audit_phases.items()},
        "junction_traffic_samples": sim.audit_samples,
        "positive_vehicle_motion_observed": any(
            sample["positive_speed_samples"] > 0
            for sample in sim.audit_samples.values()
        ),
        "marl_action_dispatch_count": len(sim.audit_operations),
        "marl_dispatch_included_all_junctions": bool(sim.audit_operations) and all(
            set(operation) == set(JUNCTIONS) for operation in sim.audit_operations
        ) if mode in ("marl_ppo", "marl_dqn") else None,
        "checkpoint_weights_exact_match": (
            checkpoint_matches(sim, "ppo", checkpoint) if mode == "marl_ppo" else
            checkpoint_matches(sim, "dqn", checkpoint) if mode == "marl_dqn" else None
        ),
        "sumo_pid": process.pid if process else None,
        "sumo_return_code": process.poll() if process else None,
        "sumo_process_reaped": bool(process is not None and process.poll() is not None),
        "backend_simulation_cleared": sim_service._sim is None,
        "backend_pid_cleared": status.get("pid") is None,
        "worker_stopped": not worker.is_alive(),
        "sumo_manager_not_running": not sim.sumo_manager.is_running,
    }
    if emergency:
        event_response = client.get("/api/emergencies").json()
        result.update(active_audit)
        result["emergency_api"] = event_response
        result["ambulance_route_complete"] = active_audit["route_edges_seen"] == EXPECTED_ROUTE
        result["priority_green_at_all_junctions"] = set(active_audit["priority_green_events"]) == set(JUNCTIONS)
        result["no_conflicting_green"] = all(
            not event["conflicting_approach_green_lanes"]
            for event in active_audit["priority_green_events"].values()
        )
        result["yellow_clearance_observed_at_j2"] = active_audit["priority_green_events"].get("J2", {}).get("yellow_seen_before_priority", False)
        result["normal_control_resumed"] = bool(active_audit["normal_control_after_release"])
    passed = (
        status.get("run_uuid") == run_id
        and status.get("status") == "COMPLETED"
        and status.get("error") is None
        and all(len(phases) >= 2 for phases in result["junction_phase_ids_observed"].values())
        and result["positive_vehicle_motion_observed"]
        and result["sumo_process_reaped"]
        and result["backend_simulation_cleared"]
        and result["backend_pid_cleared"]
        and result["worker_stopped"]
        and result["sumo_manager_not_running"]
    )
    if mode in ("marl_ppo", "marl_dqn"):
        passed = passed and result["checkpoint_weights_exact_match"] and result["marl_dispatch_included_all_junctions"]
    if emergency:
        passed = passed and all((
            result["ambulance_route_complete"],
            result["priority_green_at_all_junctions"],
            result["no_conflicting_green"],
            result["yellow_clearance_observed_at_j2"],
            result["normal_control_resumed"],
        ))
    result["result"] = "PASSED" if passed else "FAILED"
    if not passed:
        raise AssertionError(f"Run failed acceptance checks: {json.dumps(result, indent=2)}")
    return result


def main():
    global active_audit
    logging.basicConfig(level=logging.INFO)
    simulation_service_module.MultiIntersectionSimulation = AuditedSimulation
    simulation_service_module.SimulationService._run_coordinated_with_logging = audited_coordinated
    EmergencyWaveCoordinator.update = audited_emergency_update
    sim_service._on_process_spawned = capture_process
    runs = []
    try:
        with TestClient(app) as client:
            runs.append(run_one(client, "baseline", 120, 99, False))
            runs.append(run_one(client, "coordinated", 120, 99, False))
            runs.append(run_one(client, "marl_ppo", 90, 99, False, "checkpoints/p6/ppo_stage_a_best.json"))
            runs.append(run_one(client, "marl_dqn", 90, 99, False, "checkpoints/p6/dqn_stage_a_best.json"))
            runs.append(run_one(client, "coordinated", 500, 42, True))
        result = {
            "database_url": os.environ["DATABASE_URL"],
            "runs_in_required_order": [run["mode"] + ("_emergency" if run["request"]["enable_emergency"] else "") for run in runs],
            "unique_run_ids": len({run["run_id"] for run in runs}) == 5,
            "all_runs_passed": all(run["result"] == "PASSED" for run in runs),
            "runs": runs,
            "sumo_shutdown_source_finding": {
                "traci_close_wait_false": True,
                "manager_terminates_process_if_still_running": True,
                "source_file": "traffic_service/sumo_manager.py",
                "process_return_codes": [run["sumo_return_code"] for run in runs],
                "processes_reaped": all(run["sumo_process_reaped"] for run in runs),
                "backend_reported_errors": [run["final_status"]["error"] for run in runs],
            },
            "overall": "PASSED" if all(run["result"] == "PASSED" for run in runs) else "FAILED",
        }
        OUTPUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, indent=2))
    finally:
        sim_service._on_process_spawned = original_spawn_callback
        EmergencyWaveCoordinator.update = original_update
        simulation_service_module.SimulationService._run_coordinated_with_logging = original_coordinated
        simulation_service_module.MultiIntersectionSimulation = original_simulation_class
        active_audit = None


if __name__ == "__main__":
    main()

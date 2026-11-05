"""Timestamped API-to-SUMO ambulance preemption verification for P6.6."""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

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


OUTPUT = ROOT / "scratch" / "p6_6_emergency_api_results6.json"
if OUTPUT.exists():
    raise FileExistsError(f"Refusing to overwrite existing evidence: {OUTPUT}")

os.environ.setdefault("DATABASE_URL", "sqlite:///./demo_audit_disposable.db")
EXPECTED_ID = "ambulance_0"
EXPECTED_ROUTE_EDGES = ["172853382#2", "172853382#3", "1148717038#0", "40696223#1"]
ROUTE_INDEX = {edge: i for i, edge in enumerate(EXPECTED_ROUTE_EDGES)}
PRIORITY_PHASES = {"J1": 2, "J2": 0, "J3": 2}
YELLOW_PHASES = {"J1": {1, 3}, "J2": {1, 3}, "J3": {1, 3}}
CONFLICTING_APPROACH_LANES = {
    "J1": {"-148697299_0"},
    "J2": {"92196679#0_0", "92196679#0_1"},
    "J3": {"-744783934_0"},
}
observations: list[dict[str, Any]] = []
route_edges_seen: list[str] = []
last_phase: dict[str, int] = {}
emergency_green_events: dict[str, dict[str, Any]] = {}
normal_control_after_release: list[dict[str, Any]] = []

original_update = EmergencyWaveCoordinator.update
original_control = simulation_service_module.SimulationService._run_coordinated_with_logging


def snapshot(coordinator: EmergencyWaveCoordinator, sim_time: float, stage: str) -> dict[str, Any]:
    signal_data = {}
    for junction, controller in coordinator.controllers.items():
        phase = controller.get_phase()
        try:
            state = traci.trafficlight.getRedYellowGreenState(controller.tls_id)
            next_switch = float(traci.trafficlight.getNextSwitch(controller.tls_id))
            phase_duration = float(traci.trafficlight.getPhaseDuration(controller.tls_id))
        except Exception:
            state = ""
            next_switch = None
            phase_duration = None
        conflicting_green_lanes = []
        if phase == PRIORITY_PHASES.get(junction):
            try:
                controlled_links = traci.trafficlight.getControlledLinks(controller.tls_id)
                for link_index, color in enumerate(state):
                    if color not in ("g", "G") or link_index >= len(controlled_links):
                        continue
                    for link in controlled_links[link_index]:
                        if link[0] in CONFLICTING_APPROACH_LANES[junction]:
                            conflicting_green_lanes.append(link[0])
            except Exception:
                conflicting_green_lanes = ["UNVERIFIED_CONTROLLED_LINKS"]
        signal_data[junction] = {
            "phase": phase,
            "state": state,
            "next_switch_time_s": next_switch,
            "phase_duration_s": phase_duration,
            "conflicting_approach_green_lanes": sorted(set(conflicting_green_lanes)),
            "emergency_locked": bool(controller.emergency_locked),
            "priority_phase": controller.emergency_priority_phase,
        }
    vehicle = None
    try:
        if EXPECTED_ID in traci.vehicle.getIDList():
            vehicle = {
                "id": EXPECTED_ID,
                "type": traci.vehicle.getTypeID(EXPECTED_ID),
                "edge": traci.vehicle.getRoadID(EXPECTED_ID),
                "speed_mps": float(traci.vehicle.getSpeed(EXPECTED_ID)),
                "lane_position_m": float(traci.vehicle.getLanePosition(EXPECTED_ID)),
            }
    except Exception:
        pass
    return {
        "simulation_time_s": float(sim_time),
        "stage": stage,
        "vehicle": vehicle,
        "signals": signal_data,
        "metrics": {
            "j1_clearance_time_s": coordinator.metrics.j1_clearance_time,
            "j2_clearance_time_s": coordinator.metrics.j2_clearance_time,
            "j3_clearance_time_s": coordinator.metrics.j3_clearance_time,
            "completed": coordinator.metrics.completed,
            "total_traversal_duration_s": coordinator.metrics.total_traversal_duration,
        },
    }


def audited_update(self, sim_time: float) -> None:
    global last_phase
    pre_active = self.active_emergency_id
    pre_signal_phases = {j: c.get_phase() for j, c in self.controllers.items()}
    try:
        ids_before = traci.vehicle.getIDList()
    except Exception:
        ids_before = []
    was_detected = self.active_emergency_id is not None
    original_update(self, sim_time)
    if EXPECTED_ID in ids_before or was_detected or self.active_emergency_id == EXPECTED_ID or self.metrics.completed:
        event = snapshot(self, sim_time, self.current_stage)
        event["new_detection"] = (not was_detected and self.active_emergency_id == EXPECTED_ID)
        event["phase_before_update"] = pre_signal_phases
        event["active_emergency_id"] = self.active_emergency_id
        event["phase_transition"] = {
            j: {"from": pre_signal_phases[j], "to": event["signals"][j]["phase"]}
            for j in self.controllers
            if pre_signal_phases[j] != event["signals"][j]["phase"]
        }
        observations.append(event)

        vehicle = event["vehicle"]
        if vehicle and vehicle["edge"] in ROUTE_INDEX:
            edge = vehicle["edge"]
            if not route_edges_seen or route_edges_seen[-1] != edge:
                route_edges_seen.append(edge)

        for junction, signal in event["signals"].items():
            if signal["emergency_locked"] and signal["phase"] == PRIORITY_PHASES[junction]:
                emergency_green_events.setdefault(junction, {
                    "simulation_time_s": float(sim_time),
                    "phase": signal["phase"],
                    "ryg_state": signal["state"],
                    "vehicle_edge": vehicle["edge"] if vehicle else None,
                    "phase_before_lock": pre_signal_phases[junction],
                    "conflicting_approach_green_lanes": signal["conflicting_approach_green_lanes"],
                    "yellow_seen_before_lock": any(
                        record["simulation_time_s"] <= sim_time
                        and record["signals"][junction]["phase"] in YELLOW_PHASES[junction]
                        for record in observations[-12:]
                    ),
                })
        last_phase = {j: signal["phase"] for j, signal in event["signals"].items()}


def audited_coordinated_control(self, sim, states, sim_time):
    original_control(self, sim, states, sim_time)
    if sim.emergency_coordinator.metrics.completed:
        normal_control_after_release.append({
            "simulation_time_s": float(sim_time),
            "phase_ids": {j: int(c.get_phase()) for j, c in sim.controllers.items()},
            "locks": {j: bool(c.emergency_locked) for j, c in sim.controllers.items()},
            "decision_log_count": len(self._decisions_log),
        })


def main() -> dict[str, Any]:
    if os.environ.get("DATABASE_URL") != "sqlite:///./demo_audit_disposable.db":
        raise RuntimeError("Expected disposable DATABASE_URL")
    logging.basicConfig(level=logging.INFO)
    EmergencyWaveCoordinator.update = audited_update
    simulation_service_module.SimulationService._run_coordinated_with_logging = audited_coordinated_control
    result: dict[str, Any] = {
        "database_url": os.environ["DATABASE_URL"],
        "mode": "coordinated",
        "duration_s": 1000,
        "seed": 42,
        "enable_emergency": True,
        "vehicle_id": EXPECTED_ID,
        "route_edges_expected": EXPECTED_ROUTE_EDGES,
    }
    try:
        with TestClient(app) as client:
            response = client.post("/api/simulation/start", json={
                "mode": "coordinated",
                "duration": 1000,
                "seed": 42,
                "step_length": 1.0,
                "decision_interval": 5.0,
                "enable_emergency": True,
                "gui": False,
                "startup_timeout_s": 20.0,
            })
            result["start_response"] = {"status_code": response.status_code, "body": response.json()}
            if response.status_code != 200:
                raise RuntimeError(f"API simulation start failed: {response.text}")
            run_thread = sim_service._thread
            if run_thread is None:
                raise RuntimeError("API start returned without a worker thread")
            run_thread.join(timeout=90)
            result["worker_joined"] = not run_thread.is_alive()
            if run_thread.is_alive():
                client.post("/api/simulation/stop")
                run_thread.join(timeout=20)
                raise TimeoutError("Emergency scenario did not finish within the 90-second wall-clock bound")
            result["final_status"] = client.get("/api/simulation/status").json()
            result["final_metrics"] = client.get("/api/traffic/metrics").json()
            result["final_emergencies"] = client.get("/api/emergencies").json()

        sim = getattr(sim_service, "_sim", None)
        # Worker cleanup clears service._sim, so the captured process state is also reflected
        # in the terminal API status (PID null); no process remains if this bounded run passed.
        result["observations"] = observations
        result["route_edges_seen"] = route_edges_seen
        result["emergency_green_events"] = emergency_green_events
        result["normal_control_after_release"] = normal_control_after_release[:5]
        result["normal_control_calls_after_release"] = len(normal_control_after_release)
        result["completed"] = bool(result.get("final_status", {}).get("status") == "COMPLETED")
        result["ambulance_route_complete"] = route_edges_seen == EXPECTED_ROUTE_EDGES
        result["emergency_completed"] = any(o["metrics"]["completed"] for o in observations)
        result["all_junctions_emergency_green"] = set(emergency_green_events) == {"J1", "J2", "J3"}
        result["no_conflicting_approach_green_during_priority"] = all(
            not event["conflicting_approach_green_lanes"]
            for event in emergency_green_events.values()
        )
        result["normal_control_resumed"] = bool(normal_control_after_release)
        result["overall"] = "PASSED" if all((
            result["completed"], result["ambulance_route_complete"], result["emergency_completed"],
            result["all_junctions_emergency_green"], result["no_conflicting_approach_green_during_priority"],
            result["normal_control_resumed"],
            result["final_status"].get("pid") is None,
        )) else "PARTIAL"
        OUTPUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, indent=2))
        return result
    finally:
        EmergencyWaveCoordinator.update = original_update
        simulation_service_module.SimulationService._run_coordinated_with_logging = original_control


if __name__ == "__main__":
    main()

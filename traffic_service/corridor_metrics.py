"""
traffic_service/corridor_metrics.py

Corridor-level metrics collection and evaluation engine.
Computes end-to-end corridor travel times, progression delay, throughput,
average corridor speeds, emergency clearance, and cumulative emissions (CO2, NOx, fuel).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional
import traci

from .state_extractor import (
    FUEL_DENSITY_MG_PER_LITER,
    FUEL_DENSITY_MG_PER_ML,
    IntersectionState,
)


@dataclass
class CorridorMetricsSummary:
    """Summary of corridor performance across an episode."""
    simulation_duration: float = 0.0
    total_vehicles_inserted: int = 0
    total_corridor_trips_completed: int = 0
    mean_corridor_travel_time_s: float = 0.0
    mean_corridor_speed_kmh: float = 0.0
    total_corridor_waiting_time_s: float = 0.0
    mean_corridor_queue: float = 0.0
    max_corridor_queue: int = 0
    total_co2_kg: float = 0.0
    total_nox_g: float = 0.0
    total_fuel_liters: float = 0.0
    emergency_traversal_duration_s: float = 0.0
    # Per-junction breakdowns
    j1_mean_queue: float = 0.0
    j2_mean_queue: float = 0.0
    j3_mean_queue: float = 0.0


class CorridorMetricsCollector:
    """
    Monitors vehicles entering, traversing, and exiting the Hosur corridor (J1 -> J2 -> J3).
    Logs per-step data and produces aggregate statistical summaries.
    """

    def __init__(
        self,
        entry_edge: str = "172853382#2",
        exit_edge: str = "40696223#1",
        step_length: float = 1.0,
    ) -> None:
        self.entry_edge = entry_edge
        self.exit_edge = exit_edge
        self.step_length = step_length

        # Vehicle trip tracking: veh_id -> entry_time
        self._trip_entry_times: Dict[str, float] = {}
        self._completed_travel_times: List[float] = []

        # History per simulation step
        self.step_records: List[Dict[str, float]] = []

        # Emission accumulators
        self.cumulative_co2_mg: float = 0.0
        self.cumulative_nox_mg: float = 0.0
        self.cumulative_fuel_mg: float = 0.0

    @property
    def cumulative_fuel_ml(self) -> float:
        """Volumetric cumulative fuel in ml, derived from mass and standard fuel density."""
        return self.cumulative_fuel_mg / FUEL_DENSITY_MG_PER_ML

    def record_step(
        self,
        sim_time: float,
        states: Dict[str, IntersectionState],
        emergency_duration: float = 0.0,
    ) -> None:
        """Records traffic and emission state at the current simulation step."""
        # 1. Update trip traversal tracking via entry and exit edges directly
        try:
            entry_vehs = traci.edge.getLastStepVehicleIDs(self.entry_edge)
            exit_vehs = traci.edge.getLastStepVehicleIDs(self.exit_edge)
            active_count = traci.vehicle.getIDCount()
        except traci.TraCIException:
            entry_vehs, exit_vehs, active_count = [], [], 0

        for veh_id in entry_vehs:
            if veh_id not in self._trip_entry_times:
                self._trip_entry_times[veh_id] = sim_time

        for veh_id in exit_vehs:
            if veh_id in self._trip_entry_times:
                entry_time = self._trip_entry_times.pop(veh_id)
                travel_time = max(1.0, sim_time - entry_time)
                self._completed_travel_times.append(travel_time)

        # 2. Accumulate corridor emissions via edge-level queries
        corridor_edges = [
            "172853382#2", "172853382#3", "464465165#0", "92196679#0",
            "1148717038#0", "40696223#1", "-148697299", "-744783934",
        ]
        step_co2 = 0.0
        step_nox = 0.0
        step_fuel_mg = 0.0
        for edge_id in corridor_edges:
            try:
                step_co2 += traci.edge.getCO2Emission(edge_id)
                step_nox += traci.edge.getNOxEmission(edge_id)
                step_fuel_mg += traci.edge.getFuelConsumption(edge_id)
            except traci.TraCIException:
                pass

        self.cumulative_co2_mg += step_co2 * self.step_length
        self.cumulative_nox_mg += step_nox * self.step_length
        self.cumulative_fuel_mg += step_fuel_mg * self.step_length

        # 3. Aggregate junction queues and speeds
        j1_state = states.get("J1")
        j2_state = states.get("J2")
        j3_state = states.get("J3")

        j1_q = j1_state.total_queue if j1_state else 0
        j2_q = j2_state.total_queue if j2_state else 0
        j3_q = j3_state.total_queue if j3_state else 0
        total_corridor_q = j1_q + j2_q + j3_q

        total_wait = sum(s.total_waiting_time for s in states.values())
        speeds = [s.average_speed_kmh for s in states.values() if s.vehicle_count > 0]
        avg_speed = (sum(speeds) / len(speeds)) if speeds else 0.0

        record = {
            "time": sim_time,
            "j1_queue": j1_q,
            "j2_queue": j2_q,
            "j3_queue": j3_q,
            "total_corridor_queue": total_corridor_q,
            "average_speed_kmh": avg_speed,
            "total_waiting_time": total_wait,
            "active_vehicles": active_count,
            "step_co2_mg": step_co2,
            "step_fuel_ml": step_fuel_mg / FUEL_DENSITY_MG_PER_ML,
            "cumulative_co2_kg": self.cumulative_co2_mg / 1_000_000.0,
            "cumulative_fuel_liters": self.cumulative_fuel_mg / FUEL_DENSITY_MG_PER_LITER,
            "emergency_duration": emergency_duration,
        }
        self.step_records.append(record)

    def compute_summary(self, emergency_duration: float = 0.0) -> CorridorMetricsSummary:
        """Calculates final aggregate metrics for the run."""
        if not self.step_records:
            return CorridorMetricsSummary()

        sim_dur = self.step_records[-1]["time"]
        mean_travel_time = (
            sum(self._completed_travel_times) / len(self._completed_travel_times)
            if self._completed_travel_times
            else 0.0
        )

        queues = [r["total_corridor_queue"] for r in self.step_records]
        speeds = [r["average_speed_kmh"] for r in self.step_records]
        waits = [r["total_waiting_time"] for r in self.step_records]

        j1_queues = [r["j1_queue"] for r in self.step_records]
        j2_queues = [r["j2_queue"] for r in self.step_records]
        j3_queues = [r["j3_queue"] for r in self.step_records]

        return CorridorMetricsSummary(
            simulation_duration=sim_dur,
            total_vehicles_inserted=len(self._trip_entry_times) + len(self._completed_travel_times),
            total_corridor_trips_completed=len(self._completed_travel_times),
            mean_corridor_travel_time_s=mean_travel_time,
            mean_corridor_speed_kmh=sum(speeds) / len(speeds) if speeds else 0.0,
            total_corridor_waiting_time_s=sum(waits) / len(waits) if waits else 0.0,
            mean_corridor_queue=sum(queues) / len(queues) if queues else 0.0,
            max_corridor_queue=max(queues) if queues else 0,
            total_co2_kg=self.cumulative_co2_mg / 1_000_000.0,
            total_nox_g=self.cumulative_nox_mg / 1_000.0,
            total_fuel_liters=round(self.cumulative_fuel_mg / FUEL_DENSITY_MG_PER_LITER, 4),
            emergency_traversal_duration_s=emergency_duration,
            j1_mean_queue=sum(j1_queues) / len(j1_queues) if j1_queues else 0.0,
            j2_mean_queue=sum(j2_queues) / len(j2_queues) if j2_queues else 0.0,
            j3_mean_queue=sum(j3_queues) / len(j3_queues) if j3_queues else 0.0,
        )

    def export_csv(self, output_path: Path | str) -> None:
        """Exports step-by-step metrics to a CSV file."""
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not self.step_records:
            return

        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(self.step_records[0].keys()))
            writer.writeheader()
            writer.writerows(self.step_records)

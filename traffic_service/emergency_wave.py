"""
traffic_service/emergency_wave.py

Corridor-wide emergency vehicle green wave preemption (J1 -> J2 -> J3).
Coordinates progressive priority signals along the corridor, ensuring
the ambulance encounters clear green phases while minimizing side-street disruption.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence
import traci

from .communication import CorridorCommunicationHub
from .signal_controller import SignalController

DEFAULT_CORRIDOR_EDGES = (
    "172853382#2",   # J1 approach
    "172853382#3",   # J1 to J2 connecting edge
    "1148717038#0",  # J2 to J3 connecting edge
    "40696223#1",    # J3 exit edge
)


@dataclass
class EmergencyTraversalMetrics:
    """Performance metrics for an emergency corridor run."""
    vehicle_id: str = ""
    start_time: float = 0.0
    j1_arrival_time: float = 0.0
    j1_clearance_time: float = 0.0
    j2_arrival_time: float = 0.0
    j2_clearance_time: float = 0.0
    j3_arrival_time: float = 0.0
    j3_clearance_time: float = 0.0
    completed: bool = False
    total_traversal_duration: float = 0.0


class EmergencyWaveCoordinator:
    """
    Orchestrates the progressive green-wave along J1 -> J2 -> J3.
    Tracks vehicle position, initiates preemption at downstream signals,
    and safely releases signals once the ambulance passes.
    """

    def __init__(
        self,
        controllers: Dict[str, SignalController],  # {"J1": ctrl1, "J2": ctrl2, "J3": ctrl3}
        communication_hub: CorridorCommunicationHub,
        corridor_phases: Dict[str, int],  # {"J1": 2, "J2": 0, "J3": 2} priority corridor green
        corridor_edges: Optional[Sequence[str]] = None,
        advance_preemption_seconds: float = 12.0,  # seconds before ETA to start clearing
    ) -> None:
        self.controllers = controllers
        self.hub = communication_hub
        self.corridor_phases = corridor_phases
        self.advance_preemption_seconds = advance_preemption_seconds

        edges = list(corridor_edges) if corridor_edges is not None else list(DEFAULT_CORRIDOR_EDGES)
        if len(edges) < 4:
            raise ValueError(
                "corridor_edges must contain at least 4 edges: "
                "[j1_approach, j1_to_j2, j2_to_j3, j3_exit]"
            )

        self.corridor_edges = edges
        self.j1_approach_edge = edges[0]
        self.j1_to_j2_edge = edges[1]
        self.j2_to_j3_edge = edges[2]
        self.j3_exit_edge = edges[3]

        self.active_emergency_id: Optional[str] = None
        self.current_stage: str = "IDLE"  # 'APPROACHING_J1', 'AT_J1', 'J1_TO_J2', 'AT_J2', 'J2_TO_J3', 'AT_J3', 'CLEARED'
        self.metrics: EmergencyTraversalMetrics = EmergencyTraversalMetrics()

    def update(self, sim_time: float) -> None:
        """Step function called every simulation second to manage corridor preemption."""
        # Detect active emergency vehicle in the simulation
        if not self.active_emergency_id:
            try:
                for veh_id in traci.vehicle.getIDList():
                    vtype = traci.vehicle.getTypeID(veh_id).lower()
                    if "ambulance" in vtype or "emergency" in vtype:
                        edge = traci.vehicle.getRoadID(veh_id)
                        if edge in [self.j1_approach_edge, self.j1_to_j2_edge, self.j2_to_j3_edge]:
                            self.active_emergency_id = veh_id
                            self.metrics.vehicle_id = veh_id
                            self.metrics.start_time = sim_time
                            break
            except traci.TraCIException:
                return

        if not self.active_emergency_id:
            return

        # Check if vehicle still exists in simulation
        try:
            current_edge = traci.vehicle.getRoadID(self.active_emergency_id)
            speed = traci.vehicle.getSpeed(self.active_emergency_id)
            pos = traci.vehicle.getLanePosition(self.active_emergency_id)
            lane_len = traci.lane.getLength(traci.vehicle.getLaneID(self.active_emergency_id))
            dist_to_end = max(0.0, lane_len - pos)
        except traci.TraCIException:
            # Vehicle completed or left
            if self.current_stage != "CLEARED":
                self._handle_completion(sim_time)
            return

        etas = self._calculate_etas(current_edge, dist_to_end, speed)
        self.hub.broadcast_emergency(
            ambulance_id=self.active_emergency_id,
            current_location=current_edge,
            etas=etas,
            timestamp=sim_time,
        )

        # ----------------------------------------------------
        # Progressive Corridor Preemption Stage Machine
        # ----------------------------------------------------

        # Stage 1: Approaching / Traversing J1
        if current_edge == self.j1_approach_edge:
            self.current_stage = "APPROACHING_J1"
            self.controllers["J1"].lock_emergency_priority(
                corridor_green_phase=self.corridor_phases["J1"],
                sim_time=sim_time,
            )
            # Advance notice to J2 if close to J1
            if etas.get("J2", 999.0) <= self.advance_preemption_seconds:
                self.controllers["J2"].lock_emergency_priority(
                    corridor_green_phase=self.corridor_phases["J2"],
                    sim_time=sim_time,
                )

        # Stage 2: Between J1 and J2
        elif current_edge == self.j1_to_j2_edge:
            if self.metrics.j1_clearance_time == 0.0:
                self.metrics.j1_clearance_time = sim_time
                self.controllers["J1"].release_emergency_priority()

            self.current_stage = "J1_TO_J2"
            # Ensure J2 has priority green locked
            self.controllers["J2"].lock_emergency_priority(
                corridor_green_phase=self.corridor_phases["J2"],
                sim_time=sim_time,
            )

            # Advance notice to J3
            if etas.get("J3", 999.0) <= self.advance_preemption_seconds:
                self.controllers["J3"].lock_emergency_priority(
                    corridor_green_phase=self.corridor_phases["J3"],
                    sim_time=sim_time,
                )

        # Stage 3: Between J2 and J3
        elif current_edge == self.j2_to_j3_edge:
            if self.metrics.j2_clearance_time == 0.0:
                self.metrics.j2_clearance_time = sim_time
                self.controllers["J2"].release_emergency_priority()

            self.current_stage = "J2_TO_J3"
            # Ensure J3 has priority green locked
            self.controllers["J3"].lock_emergency_priority(
                corridor_green_phase=self.corridor_phases["J3"],
                sim_time=sim_time,
            )

        # Stage 4: Past J3 (Exiting corridor)
        elif current_edge == self.j3_exit_edge:
            self._handle_completion(sim_time)

    def _calculate_etas(self, current_edge: str, dist_to_end: float, speed: float) -> Dict[str, float]:
        """Calculates estimated arrival time at each downstream intersection."""
        eff_speed = max(speed, 10.0)  # assume at least 10 m/s for emergency vehicle
        etas: Dict[str, float] = {}

        if current_edge == self.j1_approach_edge:
            etas["J1"] = dist_to_end / eff_speed
            etas["J2"] = etas["J1"] + (180.0 / eff_speed)  # J1 to J2 edge length approx
            etas["J3"] = etas["J2"] + (190.0 / eff_speed)  # J2 to J3 edge length approx
        elif current_edge == self.j1_to_j2_edge:
            etas["J1"] = 0.0
            etas["J2"] = dist_to_end / eff_speed
            etas["J3"] = etas["J2"] + (190.0 / eff_speed)
        elif current_edge == self.j2_to_j3_edge:
            etas["J1"] = 0.0
            etas["J2"] = 0.0
            etas["J3"] = dist_to_end / eff_speed
        else:
            etas["J1"] = 0.0
            etas["J2"] = 0.0
            etas["J3"] = 0.0

        return etas

    def _handle_completion(self, sim_time: float) -> None:
        """Cleans up all locks when ambulance successfully clears the corridor."""
        self.current_stage = "CLEARED"
        self.metrics.j3_clearance_time = sim_time
        self.metrics.completed = True
        self.metrics.total_traversal_duration = max(0.0, sim_time - self.metrics.start_time)

        for ctrl in self.controllers.values():
            ctrl.release_emergency_priority()

        self.hub.clear_emergency(sim_time)
        self.active_emergency_id = None

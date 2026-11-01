"""
traffic_service/state_extractor.py

Generic, modular intersection state extraction and emissions tracker.
Extracts queue lengths, wait times, vehicle speeds, signal phases,
emergency vehicle detection, and CO2/NOx/fuel emissions for ANY junction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import traci


# Standard automotive fuel density (HBEFA / Euro 4 / BS-VI petrol reference)
# 1 Liter = 1,000 ml; density = 0.750 kg/L = 750 g/L = 750,000 mg/L = 750 mg/ml
FUEL_DENSITY_MG_PER_LITER: float = 750_000.0
FUEL_DENSITY_MG_PER_ML: float = 750.0


@dataclass
class EmissionSnapshot:
    """Instantaneous and accumulated emissions for vehicles in an intersection zone."""
    co2_mg_s: float = 0.0          # instantaneous CO2 (mg/s)
    nox_mg_s: float = 0.0          # instantaneous NOx (mg/s)
    fuel_ml_s: float = 0.0         # instantaneous Fuel volumetric rate (ml/s) converted from mg/s
    co_mg_s: float = 0.0           # instantaneous Carbon Monoxide (mg/s)
    pmx_mg_s: float = 0.0          # instantaneous Particulate Matter (mg/s)
    accumulated_co2_kg: float = 0.0
    accumulated_fuel_liters: float = 0.0


@dataclass
class ApproachingEmergencyVehicle:
    """Details of an emergency vehicle approaching an intersection."""
    vehicle_id: str
    approach: str
    lane_id: str
    distance_to_stopline_m: float
    speed_mps: float
    estimated_arrival_s: float


@dataclass
class IntersectionState:
    """Generic snapshot of an intersection's state at a simulation timestep."""
    junction_id: str
    tls_id: str
    simulation_time: float
    current_phase: int
    phase_duration: float
    phase_elapsed: float
    time_to_switch: float
    approach_queues: Dict[str, int] = field(default_factory=dict)
    total_queue: int = 0
    average_speed_mps: float = 0.0
    average_speed_kmh: float = 0.0
    total_waiting_time: float = 0.0
    vehicle_count: int = 0
    vehicle_ids: List[str] = field(default_factory=list)
    emissions: EmissionSnapshot = field(default_factory=EmissionSnapshot)
    approaching_emergency_vehicles: List[ApproachingEmergencyVehicle] = field(default_factory=list)


class IntersectionStateExtractor:
    """
    Modular state extractor for a given traffic-light junction.
    Decoupled from specific junctions and approaches.
    """

    def __init__(
        self,
        junction_id: str,
        tls_id: str,
        approach_lanes: Dict[str, List[str]],
        queue_speed_threshold: float = 1.0,
        emergency_detection_distance: float = 250.0,
    ) -> None:
        self.junction_id = junction_id
        self.tls_id = tls_id
        self.approach_lanes = approach_lanes
        self.queue_speed_threshold = queue_speed_threshold
        self.emergency_detection_distance = emergency_detection_distance

        # Flattened list of all incoming approach lanes
        self.all_incoming_lanes: List[str] = [
            lane for lanes in approach_lanes.values() for lane in lanes
        ]

        # Accumulated metrics
        self.total_co2_mg: float = 0.0
        self.total_fuel_mg: float = 0.0

    @property
    def total_fuel_ml(self) -> float:
        """Volumetric fuel accumulation in ml, derived from mass and standard fuel density."""
        return self.total_fuel_mg / FUEL_DENSITY_MG_PER_ML

    def get_lane_queue(self, lane_id: str) -> int:
        """Counts vehicles on the specified lane with speed <= queue_speed_threshold."""
        try:
            vehicle_ids = traci.lane.getLastStepVehicleIDs(lane_id)
        except traci.TraCIException:
            return 0

        queue = 0
        for veh_id in vehicle_ids:
            try:
                if traci.vehicle.getSpeed(veh_id) <= self.queue_speed_threshold:
                    queue += 1
            except traci.TraCIException:
                pass
        return queue

    def get_approach_queue(self, approach_name: str) -> int:
        """Computes queue count across all lanes for a named approach."""
        lanes = self.approach_lanes.get(approach_name, [])
        return sum(self.get_lane_queue(lane) for lane in lanes)

    def extract_phase_info(self, sim_time: float) -> tuple[int, float, float, float]:
        """Extracts (current_phase, phase_duration, phase_elapsed, time_to_switch)."""
        try:
            current_phase = traci.trafficlight.getPhase(self.tls_id)
            next_switch = traci.trafficlight.getNextSwitch(self.tls_id)
            phase_duration = traci.trafficlight.getPhaseDuration(self.tls_id)
            time_to_switch = max(0.0, next_switch - sim_time)
            phase_elapsed = max(0.0, phase_duration - time_to_switch)
            return current_phase, phase_duration, phase_elapsed, time_to_switch
        except traci.TraCIException:
            return 0, 0.0, 0.0, 0.0

    def extract_emissions(self, step_length: float = 1.0) -> EmissionSnapshot:
        """
        Extracts instantaneous and accumulated emissions across all approach lanes.

        TraCI return units:
          - getCO2Emission: mg/s
          - getNOxEmission: mg/s
          - getFuelConsumption: mg/s (mass flow rate)
          - getCOEmission: mg/s
          - getPMxEmission: mg/s
        """
        co2_mg_s = 0.0
        nox_mg_s = 0.0
        fuel_mg_s = 0.0
        co_mg_s = 0.0
        pmx_mg_s = 0.0

        for lane_id in self.all_incoming_lanes:
            try:
                co2_mg_s += traci.lane.getCO2Emission(lane_id)
                nox_mg_s += traci.lane.getNOxEmission(lane_id)
                fuel_mg_s += traci.lane.getFuelConsumption(lane_id)
                co_mg_s += traci.lane.getCOEmission(lane_id)
                pmx_mg_s += traci.lane.getPMxEmission(lane_id)
            except traci.TraCIException:
                pass

        self.total_co2_mg += co2_mg_s * step_length
        self.total_fuel_mg += fuel_mg_s * step_length

        # Convert fuel mass rate (mg/s) to volumetric flow rate (ml/s) using standard density
        fuel_ml_s = fuel_mg_s / FUEL_DENSITY_MG_PER_ML

        # Convert accumulated fuel mass (mg) to volume in liters
        accumulated_fuel_liters = self.total_fuel_mg / FUEL_DENSITY_MG_PER_LITER

        return EmissionSnapshot(
            co2_mg_s=co2_mg_s,
            nox_mg_s=nox_mg_s,
            fuel_ml_s=fuel_ml_s,
            co_mg_s=co_mg_s,
            pmx_mg_s=pmx_mg_s,
            accumulated_co2_kg=self.total_co2_mg / 1_000_000.0,
            accumulated_fuel_liters=accumulated_fuel_liters,
        )

    def detect_emergency_vehicles(self) -> List[ApproachingEmergencyVehicle]:
        """Scans approach lanes for ambulances within the detection horizon."""
        detected = []
        for approach_name, lanes in self.approach_lanes.items():
            for lane_id in lanes:
                try:
                    veh_ids = traci.lane.getLastStepVehicleIDs(lane_id)
                    lane_length = traci.lane.getLength(lane_id)
                except traci.TraCIException:
                    continue

                for veh_id in veh_ids:
                    try:
                        vtype = traci.vehicle.getTypeID(veh_id).lower()
                        if "ambulance" in vtype or "emergency" in vtype:
                            pos = traci.vehicle.getLanePosition(veh_id)
                            dist_to_stopline = max(0.0, lane_length - pos)
                            speed = traci.vehicle.getSpeed(veh_id)
                            eta = (dist_to_stopline / speed) if speed > 1.0 else (dist_to_stopline / 1.0)

                            if dist_to_stopline <= self.emergency_detection_distance:
                                detected.append(
                                    ApproachingEmergencyVehicle(
                                        vehicle_id=veh_id,
                                        approach=approach_name,
                                        lane_id=lane_id,
                                        distance_to_stopline_m=dist_to_stopline,
                                        speed_mps=speed,
                                        estimated_arrival_s=eta,
                                    )
                                )
                    except traci.TraCIException:
                        pass
        return detected

    def extract(self, sim_time: float, step_length: float = 1.0) -> IntersectionState:
        """Gathers the complete state snapshot for this intersection."""
        curr_phase, duration, elapsed, time_to_switch = self.extract_phase_info(sim_time)

        # Collect approach queues
        approach_queues = {
            app_name: sum(self.get_lane_queue(l) for l in lanes)
            for app_name, lanes in self.approach_lanes.items()
        }
        total_queue = sum(approach_queues.values())

        # Collect vehicles on all approach lanes
        all_vehs: List[str] = []
        speeds: List[float] = []
        total_wait = 0.0

        for lane_id in self.all_incoming_lanes:
            try:
                lane_vehs = traci.lane.getLastStepVehicleIDs(lane_id)
            except traci.TraCIException:
                lane_vehs = []

            for veh_id in lane_vehs:
                if veh_id not in all_vehs:
                    all_vehs.append(veh_id)
                    try:
                        speeds.append(traci.vehicle.getSpeed(veh_id))
                        total_wait += traci.vehicle.getAccumulatedWaitingTime(veh_id)
                    except traci.TraCIException:
                        pass

        vehicle_count = len(all_vehs)
        avg_speed_mps = (sum(speeds) / vehicle_count) if vehicle_count > 0 else 0.0
        avg_speed_kmh = avg_speed_mps * 3.6

        # Emissions
        emissions = self.extract_emissions(step_length=step_length)

        # Emergency
        emergency_vehs = self.detect_emergency_vehicles()

        return IntersectionState(
            junction_id=self.junction_id,
            tls_id=self.tls_id,
            simulation_time=sim_time,
            current_phase=curr_phase,
            phase_duration=duration,
            phase_elapsed=elapsed,
            time_to_switch=time_to_switch,
            approach_queues=approach_queues,
            total_queue=total_queue,
            average_speed_mps=avg_speed_mps,
            average_speed_kmh=avg_speed_kmh,
            total_waiting_time=total_wait,
            vehicle_count=vehicle_count,
            vehicle_ids=all_vehs,
            emissions=emissions,
            approaching_emergency_vehicles=emergency_vehs,
        )

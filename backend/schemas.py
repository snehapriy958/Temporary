"""
backend/schemas.py

Pydantic request and response models for REST API and WebSocket payloads.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ----------------------------------------------------
# Health & Simulation Control Schemas
# ----------------------------------------------------

class HealthResponse(BaseModel):
    status: str = "ok"
    sumo_available: bool = True
    sumo_version: str = "Unknown"
    active_simulation: bool = False
    message: str = "Backend operational"


class SimulationStartRequest(BaseModel):
    mode: str = Field("coordinated", description="Simulation mode: 'baseline' or 'coordinated'")
    duration: int = Field(600, ge=10, le=7200, description="Simulation duration in seconds")
    seed: int = Field(42, description="Random seed for traffic generation")
    step_length: float = Field(1.0, gt=0.0, le=5.0, description="SUMO simulation step length in seconds")
    decision_interval: float = Field(5.0, gt=0.0, le=60.0, description="Adaptive controller decision interval")
    enable_emergency: bool = Field(True, description="Enable emergency vehicle green wave preemption")
    gui: bool = Field(False, description="Launch with sumo-gui (headless if False)")
    startup_timeout_s: float = Field(10.0, ge=1.0, le=60.0, description="Timeout waiting for SUMO/TraCI startup and readiness acknowledgement")


class SimulationStatusResponse(BaseModel):
    running: bool
    paused: bool
    simulation_time: float
    duration: int
    mode: str
    seed: int
    controller: str
    junctions: List[str]
    error: Optional[str] = None
    status: Optional[str] = None
    pid: Optional[int] = None
    run_uuid: Optional[str] = None
    sequence_number: Optional[int] = 0


class CommandResponse(BaseModel):
    success: bool
    message: str
    simulation_time: float = 0.0


# ----------------------------------------------------
# Traffic & Intersection State Schemas
# ----------------------------------------------------

class EmissionSchema(BaseModel):
    co2_mg_s: float = 0.0
    nox_mg_s: float = 0.0
    fuel_ml_s: float = 0.0
    co_mg_s: float = 0.0
    pmx_mg_s: float = 0.0
    accumulated_co2_kg: float = 0.0
    accumulated_fuel_liters: float = 0.0


class EmergencyApproachingSchema(BaseModel):
    vehicle_id: str
    approach: str
    distance_to_stopline_m: float
    speed_mps: float
    estimated_arrival_s: float


class JunctionStateSchema(BaseModel):
    junction_id: str
    tls_id: str
    simulation_time: float
    current_phase: int
    phase_duration: float
    phase_elapsed: float
    time_to_switch: float
    approach_queues: Dict[str, int] = Field(default_factory=dict)
    total_queue: int = 0
    average_speed_kmh: float = 0.0
    total_waiting_time: float = 0.0
    vehicle_count: int = 0
    vehicle_ids: List[str] = Field(default_factory=list)
    emissions: EmissionSchema = Field(default_factory=EmissionSchema)
    emergency_present: bool = False
    approaching_emergency_vehicles: List[EmergencyApproachingSchema] = Field(default_factory=list)


class TrafficLiveResponse(BaseModel):
    simulation_time: float
    status: str
    junctions: Dict[str, JunctionStateSchema]


class TrafficMetricsResponse(BaseModel):
    simulation_time: float
    total_vehicles: int
    throughput_vehicles: int
    mean_speed_kmh: float
    total_corridor_waiting_time_s: float
    mean_corridor_queue: float
    max_corridor_queue: int
    total_co2_kg: float
    total_nox_g: float
    total_fuel_liters: float
    emergency_traversal_duration_s: float
    junction_queues: Dict[str, float] = Field(default_factory=dict)


# ----------------------------------------------------
# Signal Status & Manual Override Schemas
# ----------------------------------------------------

class SignalInfoSchema(BaseModel):
    junction_id: str
    tls_id: str
    current_phase: int
    is_green: bool
    is_yellow: bool
    phase_elapsed: float
    time_to_switch: float
    min_green: float
    max_green: float
    emergency_locked: bool
    approach_queues: Dict[str, int]


class SignalsResponse(BaseModel):
    simulation_time: float
    signals: Dict[str, SignalInfoSchema]


class SignalOverrideRequest(BaseModel):
    junction_id: str = Field(..., description="Target junction ID (J1, J2, or J3)")
    target_phase: int = Field(..., ge=0, le=10, description="Target green/yellow phase index")
    confirmed: bool = Field(False, description="Operator confirmation of manual override")


class SignalOverrideResponse(BaseModel):
    success: bool
    message: str
    junction_id: str
    applied_phase: int
    simulation_time: float


# ----------------------------------------------------
# Emergency Events Schemas
# ----------------------------------------------------

class EmergencyEventItemSchema(BaseModel):
    id: Optional[int] = None
    simulation_time: float
    vehicle_id: str
    affected_corridor: str
    preemption_active: bool
    arrival_time: float
    clearance_time: float
    traversal_duration: float
    completed: bool


class EmergencyResponse(BaseModel):
    active_emergency: bool
    emergency_locked_junctions: List[str]
    total_completed_events: int
    active_vehicle_id: Optional[str] = None
    events: List[EmergencyEventItemSchema]


# ----------------------------------------------------
# Risk & Accident Schemas
# ----------------------------------------------------

class RiskZoneItemSchema(BaseModel):
    zone_id: str
    zone_name: str
    risk_level: str
    composite_risk_score: float
    total_crashes: int
    fatal_crashes: int
    center_latitude: float
    center_longitude: float
    associated_junction: Optional[str] = None
    affected_edges: List[str] = Field(default_factory=list)
    safety_advisory: str


class HotspotItemSchema(BaseModel):
    hotspot_id: str
    blackspot_count: int
    total_crashes: int
    fatal_crashes: int
    severity_score: float
    center_latitude: float
    center_longitude: float
    corridor_relevance: str


class RisksResponse(BaseModel):
    total_zones: int
    critical_zones: int
    high_zones: int
    risk_zones: List[RiskZoneItemSchema]
    hotspots: List[HotspotItemSchema]


# ----------------------------------------------------
# Decisions Schemas
# ----------------------------------------------------

class DecisionItemSchema(BaseModel):
    id: Optional[int] = None
    simulation_time: float
    junction_id: str
    current_phase: int
    target_phase: Optional[int] = None
    action: str
    reason: str
    is_override: bool = False
    timestamp: Optional[str] = None


class DecisionsResponse(BaseModel):
    total_decisions: int
    decisions: List[DecisionItemSchema]


# ----------------------------------------------------
# Experiment & Comparison Schemas
# ----------------------------------------------------

class ControllerMetricComparison(BaseModel):
    controller_name: str
    status: str  # "Implemented", "Not implemented"
    description: str
    mean_travel_time_s: Optional[float] = None
    mean_speed_kmh: Optional[float] = None
    total_waiting_time_s: Optional[float] = None
    mean_queue: Optional[float] = None
    total_co2_kg: Optional[float] = None
    total_fuel_liters: Optional[float] = None
    emergency_traversal_duration_s: Optional[float] = None
    notes: Optional[str] = None


class ExperimentCompareResponse(BaseModel):
    network: str = "Silk Board Corridor (J1 -> J2 -> J3)"
    benchmark_duration_s: int = 600
    controllers: List[ControllerMetricComparison]


class ExperimentHistoryItem(BaseModel):
    id: int
    run_uuid: str
    mode: str
    status: str
    seed: int
    duration_requested: int
    duration_simulated: float
    started_at: str
    completed_at: Optional[str] = None
    summary_metrics: Optional[Dict[str, Any]] = None

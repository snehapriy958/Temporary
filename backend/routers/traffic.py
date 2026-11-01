"""
backend/routers/traffic.py

Real-time traffic state and corridor metrics endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter
from backend.schemas import TrafficLiveResponse, TrafficMetricsResponse
from backend.simulation_service import sim_service

router = APIRouter(prefix="/api/traffic", tags=["Traffic"])


@router.get("/live", response_model=TrafficLiveResponse)
def get_live_traffic() -> TrafficLiveResponse:
    """Returns latest traffic state, vehicle counts, queues, and speeds for J1, J2, J3."""
    status_obj = sim_service.get_status()
    st_str = "RUNNING" if status_obj.running and not status_obj.paused else ("PAUSED" if status_obj.paused else "STOPPED")
    return TrafficLiveResponse(
        simulation_time=status_obj.simulation_time,
        status=st_str,
        junctions=sim_service.get_live_junctions(),
    )


@router.get("/metrics", response_model=TrafficMetricsResponse)
def get_traffic_metrics() -> TrafficMetricsResponse:
    """Returns aggregated corridor metrics: throughput, wait time, queue, speed, emissions."""
    data = sim_service.get_metrics()
    return TrafficMetricsResponse(
        simulation_time=data.get("simulation_time", 0.0),
        total_vehicles=data.get("total_vehicles", 0),
        throughput_vehicles=data.get("throughput_vehicles", 0),
        mean_speed_kmh=data.get("mean_speed_kmh", 0.0),
        total_corridor_waiting_time_s=data.get("total_corridor_waiting_time_s", 0.0),
        mean_corridor_queue=data.get("mean_corridor_queue", 0.0),
        max_corridor_queue=data.get("max_corridor_queue", 0),
        total_co2_kg=data.get("total_co2_kg", 0.0),
        total_nox_g=data.get("total_nox_g", 0.0),
        total_fuel_liters=data.get("total_fuel_liters", 0.0),
        emergency_traversal_duration_s=data.get("emergency_traversal_duration_s", 0.0),
        junction_queues=data.get("junction_queues", {}),
    )

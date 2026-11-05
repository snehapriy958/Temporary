"""Tests for truthful optional emergency traversal telemetry."""

from types import SimpleNamespace

from backend.schemas import TrafficMetricsResponse
from backend.simulation_service import SimulationService


class SummaryCollector:
    def compute_summary(self, emergency_duration=None, emergency_cleared=False):
        duration = emergency_duration if emergency_cleared else None
        return SimpleNamespace(
            current_active_vehicles=0,
            total_corridor_trips_completed=0,
            mean_corridor_travel_time_s=None,
            mean_corridor_speed_kmh=0.0,
            mean_instantaneous_waiting_time_s=5.0,
            cumulative_delay_veh_s=23.0,
            max_corridor_queue=0,
            total_co2_kg=0.0,
            total_nox_g=0.0,
            total_fuel_liters=0.0,
            emergency_traversal_duration_s=duration,
        )


def make_simulation(completed: bool, duration: float):
    return SimpleNamespace(
        emergency_coordinator=SimpleNamespace(
            metrics=SimpleNamespace(completed=completed, total_traversal_duration=duration)
        ),
        metrics_collector=SummaryCollector(),
    )


def test_completed_emergency_duration_is_reported_by_live_metrics():
    metrics = SimulationService()._extract_metrics_summary(
        make_simulation(completed=True, duration=37.0),
        states={},
        sim_time=458.0,
    )

    assert metrics["emergency_traversal_duration_s"] == 37.0
    assert metrics["mean_speed_kmh"] is None
    assert metrics["mean_corridor_travel_time_s"] is None
    assert metrics["mean_instantaneous_waiting_time_s"] == 5.0
    assert metrics["cumulative_delay_veh_s"] == 23.0
    assert metrics["cumulative_waiting_time_s"] == 23.0
    response = TrafficMetricsResponse(**metrics)
    assert response.emergency_traversal_duration_s == 37.0


def test_unobserved_emergency_duration_is_null_not_zero():
    metrics = SimulationService()._extract_metrics_summary(
        make_simulation(completed=False, duration=0.0),
        states={},
        sim_time=100.0,
    )

    assert metrics["emergency_traversal_duration_s"] is None
    response = TrafficMetricsResponse(**metrics)
    assert response.emergency_traversal_duration_s is None

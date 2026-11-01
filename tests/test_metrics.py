"""
tests/test_metrics.py

Unit tests for corridor metrics aggregation, trip traversal times, and emission snapshots.
"""

import pytest
from traffic_service.corridor_metrics import (
    CorridorMetricsCollector,
    CorridorMetricsSummary,
    FUEL_DENSITY_MG_PER_LITER,
    FUEL_DENSITY_MG_PER_ML,
)
from traffic_service.state_extractor import EmissionSnapshot, IntersectionState


def test_empty_metrics_summary():
    collector = CorridorMetricsCollector()
    summary = collector.compute_summary()
    assert summary.total_corridor_trips_completed == 0
    assert summary.mean_corridor_travel_time_s == 0.0
    assert summary.total_co2_kg == 0.0


def test_metrics_accumulation():
    collector = CorridorMetricsCollector()

    dummy_states = {
        "J1": IntersectionState(
            junction_id="J1",
            tls_id="1617743335",
            simulation_time=1.0,
            current_phase=2,
            phase_duration=41.0,
            phase_elapsed=1.0,
            time_to_switch=40.0,
            total_queue=5,
            average_speed_kmh=35.0,
            total_waiting_time=12.0,
            vehicle_count=5,
            emissions=EmissionSnapshot(co2_mg_s=1500.0, fuel_ml_s=1.2),
        ),
        "J2": IntersectionState(
            junction_id="J2",
            tls_id="J2_TLS",
            simulation_time=1.0,
            current_phase=0,
            phase_duration=39.0,
            phase_elapsed=1.0,
            time_to_switch=38.0,
            total_queue=8,
            average_speed_kmh=30.0,
            total_waiting_time=25.0,
            vehicle_count=8,
            emissions=EmissionSnapshot(co2_mg_s=2500.0, fuel_ml_s=2.0),
        ),
        "J3": IntersectionState(
            junction_id="J3",
            tls_id="J3_TLS",
            simulation_time=1.0,
            current_phase=2,
            phase_duration=41.0,
            phase_elapsed=1.0,
            time_to_switch=40.0,
            total_queue=4,
            average_speed_kmh=40.0,
            total_waiting_time=8.0,
            vehicle_count=4,
            emissions=EmissionSnapshot(co2_mg_s=1200.0, fuel_ml_s=1.0),
        ),
    }

    # Simulate 2 steps manually
    collector.step_records.append({
        "time": 1.0,
        "j1_queue": 5,
        "j2_queue": 8,
        "j3_queue": 4,
        "total_corridor_queue": 17,
        "average_speed_kmh": 35.0,
        "total_waiting_time": 45.0,
        "active_vehicles": 17,
        "step_co2_mg": 5200.0,
        "step_fuel_ml": 4.2,
        "cumulative_co2_kg": 0.0052,
        "cumulative_fuel_liters": 0.0042,
        "emergency_duration": 0.0,
    })

    collector._completed_travel_times = [42.0, 48.0, 50.0]
    collector.cumulative_co2_mg = 5200.0
    collector.cumulative_fuel_mg = 3150.0

    summary = collector.compute_summary(emergency_duration=35.5)

    assert summary.total_corridor_trips_completed == 3
    assert pytest.approx(summary.mean_corridor_travel_time_s, 0.01) == 46.67
    assert summary.emergency_traversal_duration_s == 35.5
    assert summary.max_corridor_queue == 17
    assert summary.j1_mean_queue == 5.0
    assert summary.j2_mean_queue == 8.0
    assert summary.j3_mean_queue == 4.0
    assert pytest.approx(summary.total_co2_kg, 0.0001) == 0.0052
    assert pytest.approx(summary.total_fuel_liters, 0.0001) == 0.0042


def test_fuel_consumption_unit_conversion():
    """
    Verifies that fuel consumption conversion from TraCI mass rate (mg/s)
    to volumetric units (ml/s, Liters) uses standard automotive fuel density
    (750,000 mg/L = 750 mg/ml = 0.75 kg/L) and yields physically consistent outputs.
    """
    # 1. Density constants
    assert FUEL_DENSITY_MG_PER_LITER == 750_000.0
    assert FUEL_DENSITY_MG_PER_ML == 750.0

    # 2. Known input test: 750,000 mg of fuel mass must equal exactly 1.0 Liter
    mass_1_liter_mg = 750_000.0
    vol_liters = mass_1_liter_mg / FUEL_DENSITY_MG_PER_LITER
    assert pytest.approx(vol_liters, 1e-6) == 1.0

    # 3. Known flow rate test: 1500 mg/s of fuel mass must equal 2.0 ml/s
    rate_mg_s = 1500.0
    vol_rate_ml_s = rate_mg_s / FUEL_DENSITY_MG_PER_ML
    assert pytest.approx(vol_rate_ml_s, 1e-6) == 2.0

    # 4. Collector accumulation over steps
    collector = CorridorMetricsCollector(step_length=1.0)
    # Simulate a steady rate of 750 mg/s for 100 seconds = 75,000 mg = 0.1 Liters
    collector.step_records.append({
        "time": 100.0,
        "j1_queue": 0, "j2_queue": 0, "j3_queue": 0,
        "total_corridor_queue": 0, "average_speed_kmh": 40.0,
        "total_waiting_time": 0.0, "active_vehicles": 1,
        "step_co2_mg": 2314.0, "step_fuel_ml": 1.0,
        "cumulative_co2_kg": 0.2314, "cumulative_fuel_liters": 0.1,
        "emergency_duration": 0.0,
    })
    collector.cumulative_fuel_mg = 75_000.0
    summary = collector.compute_summary()
    assert pytest.approx(summary.total_fuel_liters, 1e-4) == 0.1

    # Check property backward compatibility
    assert pytest.approx(collector.cumulative_fuel_ml, 1e-4) == 100.0

    # 5. Stoichiometric physical plausibility:
    # Combustion of 1.0 kg of gasoline produces ~3.085 kg of CO2 (HBEFA standard)
    fuel_mass_kg = 1.0
    co2_mass_kg = fuel_mass_kg * 3.085
    fuel_volume_liters = (fuel_mass_kg * 1_000_000.0) / FUEL_DENSITY_MG_PER_LITER
    # 1 kg of fuel is ~1.333 Liters; ratio of CO2 kg to fuel Liters is ~2.314 kg CO2 / Liter
    co2_per_liter = co2_mass_kg / fuel_volume_liters
    assert pytest.approx(co2_per_liter, 0.05) == 2.314

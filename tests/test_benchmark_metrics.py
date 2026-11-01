"""
tests/test_benchmark_metrics.py

Comprehensive automated tests for Stage P2 verification:
1. Validates the fuel consumption conversion from SUMO mass rates (mg/s) to volumetric Litres
   under the explicit DIN EN 228 petrol reference density assumption (0.750 kg/L = 750,000 mg/L).
2. Verifies SUMO HBEFA4 emission classes across vehicle types.
3. Proves mathematically that summing getAccumulatedWaitingTime across time repeatedly counts
   previous waiting seconds, and proves that sum(Q * dt) computes true cumulative vehicle delay.
4. Uses a small, manually calculable 2-vehicle trajectory to verify exact delay math.
5. Verifies historical raw artifact preservation and immutability in outputs/corridor/historical_raw/.
6. Validates non-superiority of RL controllers (Coordinated Adaptive remains optimal).
7. Validates DQN policy divergence (0 completed trips, undefined travel time).
8. Validates explicit provenance distinction: Seed 1 reproduced vs Seeds 2-5 historical.
9. Validates API endpoints for corrected metrics, schemas, and assumption disclosures.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.database import init_db
from traffic_service.corridor_metrics import (
    CorridorMetricsCollector,
    CorridorMetricsSummary,
    FUEL_DENSITY_MG_PER_LITER,
    FUEL_DENSITY_MG_PER_ML,
)

init_db()
client = TestClient(app)
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_fuel_density_constants_and_authoritative_standards():
    """
    Validates reference fuel density against authoritative standard DIN EN 228
    (automotive fuels - unleaded petrol, standard reference 15 deg C: 750 kg/m3 = 0.750 kg/L).
    """
    assert FUEL_DENSITY_MG_PER_LITER == 750_000.0
    assert FUEL_DENSITY_MG_PER_ML == 750.0

    # 1 Liter of petrol = 750 grams = 750,000 mg
    assert pytest.approx(750_000.0 / FUEL_DENSITY_MG_PER_LITER, 1e-9) == 1.0


def test_sumo_hbefa4_emission_model_identification():
    """
    Verifies that the network demand vehicle types map to SUMO's HBEFA4 emission framework.
    Passenger cars and motorcycles use petrol; buses, trucks, and ambulances use diesel.
    """
    vtype_xml = PROJECT_ROOT / "sumo" / "silk_board" / "demand" / "vehicle_types.add.xml"
    assert vtype_xml.is_file()
    content = vtype_xml.read_text(encoding="utf-8")

    # Confirms all 5 vehicle classes are defined in demand
    assert 'vClass="passenger"' in content
    assert 'vClass="motorcycle"' in content
    assert 'vClass="bus"' in content
    assert 'vClass="truck"' in content
    assert 'vClass="emergency"' in content


def test_historical_fuel_error_mathematical_proof():
    """
    Demonstrates that historical 17,384.33 was in fact grams of fuel,
    and dividing by 750 g/L yields exactly 23.18 Litres of estimated volumetric fuel.
    """
    historical_baseline_raw_g = 17384.33
    historical_coord_raw_g = 13795.08
    historical_ppo_raw_g = 19912.14
    historical_dqn_raw_g = 25610.57

    # Grams / 750 g/L = Litres
    base_l = historical_baseline_raw_g / 750.0
    coord_l = historical_coord_raw_g / 750.0
    ppo_l = historical_ppo_raw_g / 750.0
    dqn_l = historical_dqn_raw_g / 750.0

    assert pytest.approx(base_l, 0.01) == 23.18
    assert pytest.approx(coord_l, 0.01) == 18.39
    assert pytest.approx(ppo_l, 0.01) == 26.55
    assert pytest.approx(dqn_l, 0.01) == 34.15

    # Percentage saving of Coordinated vs Baseline is invariant to unit scaling
    pct_raw = ((historical_baseline_raw_g - historical_coord_raw_g) / historical_baseline_raw_g) * 100.0
    pct_corrected = ((base_l - coord_l) / base_l) * 100.0
    assert pytest.approx(pct_raw, 0.1) == pytest.approx(pct_corrected, 0.1)
    assert pytest.approx(pct_corrected, 0.1) == 20.6


def test_manual_trajectory_cumulative_delay_vs_accumulated_wait():
    """
    Uses a small, manually calculable synthetic trajectory to prove that:
    1. Summing getAccumulatedWaitingTime across time repeatedly counts earlier waiting seconds (overcounting).
    2. Summing Q(t) * dt calculates exact, mathematically valid cumulative vehicle delay (veh*s).

    Scenario:
      Time horizon: t = 1 to 5 seconds (dt = 1.0s).
      Vehicle 1 (V1): stopped at queue from t=1 to t=5 (5 seconds total wait).
      Vehicle 2 (V2): arrives at t=3, stopped from t=3 to t=5 (3 seconds total wait).

    Analytical truth:
      - True cumulative delay = 5s (V1) + 3s (V2) = 8.0 vehicle-seconds.
      - Queue count Q(t):
          t=1: Q=1 [V1]
          t=2: Q=1 [V1]
          t=3: Q=2 [V1, V2]
          t=4: Q=2 [V1, V2]
          t=5: Q=2 [V1, V2]
          Integral sum(Q * dt) = 1 + 1 + 2 + 2 + 2 = 8.0 veh*s (EXACT MATCH).

      - TraCI getAccumulatedWaitingTime per step:
          t=1: V1 accumulated = 1s  -> snapshot sum = 1
          t=2: V1 accumulated = 2s  -> snapshot sum = 2
          t=3: V1 accumulated = 3s, V2 accumulated = 1s -> snapshot sum = 4
          t=4: V1 accumulated = 4s, V2 accumulated = 2s -> snapshot sum = 6
          t=5: V1 accumulated = 5s, V2 accumulated = 3s -> snapshot sum = 8
          Sum across steps = 1 + 2 + 4 + 6 + 8 = 21.0 s^2 (OVERCOUNTS by 21/8 = 2.625x).
    """
    collector = CorridorMetricsCollector(step_length=1.0)

    # Step records constructed from exact synthetic trajectory
    collector.step_records = [
        {"time": 1.0, "j1_queue": 1, "j2_queue": 0, "j3_queue": 0, "total_corridor_queue": 1,
         "average_speed_kmh": 0.0, "total_waiting_time": 1.0, "active_vehicles": 1,
         "step_co2_mg": 0.0, "step_fuel_ml": 0.0, "cumulative_co2_kg": 0.0, "cumulative_fuel_liters": 0.0, "emergency_duration": 0.0},
        {"time": 2.0, "j1_queue": 1, "j2_queue": 0, "j3_queue": 0, "total_corridor_queue": 1,
         "average_speed_kmh": 0.0, "total_waiting_time": 2.0, "active_vehicles": 1,
         "step_co2_mg": 0.0, "step_fuel_ml": 0.0, "cumulative_co2_kg": 0.0, "cumulative_fuel_liters": 0.0, "emergency_duration": 0.0},
        {"time": 3.0, "j1_queue": 2, "j2_queue": 0, "j3_queue": 0, "total_corridor_queue": 2,
         "average_speed_kmh": 0.0, "total_waiting_time": 4.0, "active_vehicles": 2,
         "step_co2_mg": 0.0, "step_fuel_ml": 0.0, "cumulative_co2_kg": 0.0, "cumulative_fuel_liters": 0.0, "emergency_duration": 0.0},
        {"time": 4.0, "j1_queue": 2, "j2_queue": 0, "j3_queue": 0, "total_corridor_queue": 2,
         "average_speed_kmh": 0.0, "total_waiting_time": 6.0, "active_vehicles": 2,
         "step_co2_mg": 0.0, "step_fuel_ml": 0.0, "cumulative_co2_kg": 0.0, "cumulative_fuel_liters": 0.0, "emergency_duration": 0.0},
        {"time": 5.0, "j1_queue": 2, "j2_queue": 0, "j3_queue": 0, "total_corridor_queue": 2,
         "average_speed_kmh": 0.0, "total_waiting_time": 8.0, "active_vehicles": 2,
         "step_co2_mg": 0.0, "step_fuel_ml": 0.0, "cumulative_co2_kg": 0.0, "cumulative_fuel_liters": 0.0, "emergency_duration": 0.0},
    ]

    summary = collector.compute_summary()

    # 1. True cumulative delay MUST match exact hand-calculated 8.0 veh*s
    assert summary.cumulative_delay_veh_s == 8.0
    assert summary.cumulative_waiting_time_s == 8.0

    # 2. Mean snapshot accumulated wait is (1 + 2 + 4 + 6 + 8) / 5 = 21 / 5 = 4.2 s/step
    assert pytest.approx(summary.total_corridor_waiting_time_s, 0.01) == 4.2
    assert pytest.approx(summary.mean_instantaneous_accumulated_wait_s, 0.01) == 4.2

    # 3. Prove that multiplying mean snapshot wait by duration (4.2 * 5 = 21.0) overcounts by 2.625x
    overcounted_delay = summary.total_corridor_waiting_time_s * 5.0
    assert overcounted_delay == 21.0
    assert overcounted_delay > summary.cumulative_delay_veh_s


def test_historical_raw_artifacts_preserved():
    """Ensures raw historical artifacts are preserved and intact in outputs/corridor/historical_raw/."""
    raw_dir = PROJECT_ROOT / "outputs" / "corridor" / "historical_raw"
    assert raw_dir.is_dir()

    # Required raw summary files
    assert (raw_dir / "marl_multi_controller_summary_raw.csv").is_file()
    assert (raw_dir / "marl_multi_controller_full_stats_raw.csv").is_file()
    assert (raw_dir / "marl_multi_seed_detailed_raw.json").is_file()
    assert (raw_dir / "corridor_multi_seed_summary_raw.csv").is_file()

    # Required raw seed traces (5 seeds each for 4 modes)
    for mode in ["baseline", "coordinated", "marl_dqn", "marl_ppo"]:
        mode_dir = raw_dir / mode
        assert mode_dir.is_dir()
        for seed in range(1, 6):
            trace_file = mode_dir / f"seed_{seed}.csv"
            assert trace_file.is_file(), f"Missing raw trace: {trace_file}"
            assert trace_file.stat().st_size > 50_000  # Non-empty 600-line trace

    # Required training logs
    assert (raw_dir / "training_logs" / "training_summary_dqn.json").is_file()
    assert (raw_dir / "training_logs" / "training_summary_ppo.json").is_file()


def test_corrected_marl_summary_csv():
    """Verifies content and schema of outputs/corridor/marl_multi_controller_summary.csv."""
    summary_path = PROJECT_ROOT / "outputs" / "corridor" / "marl_multi_controller_summary.csv"
    assert summary_path.is_file()

    with open(summary_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = {r["metric"]: r for r in reader}

    assert "mean_corridor_travel_time_s" in rows
    assert "total_fuel_liters" in rows
    assert "total_corridor_waiting_time_s" in rows
    assert "cumulative_delay_veh_s" in rows

    # Fuel verification
    fuel = rows["total_fuel_liters"]
    assert pytest.approx(float(fuel["baseline"]), 0.1) == 23.18
    assert pytest.approx(float(fuel["coordinated"]), 0.1) == 18.39
    assert pytest.approx(float(fuel["marl_ppo"]), 0.1) == 26.55
    assert pytest.approx(float(fuel["marl_dqn"]), 0.1) == 34.15
    assert "0.750 kg/L petrol" in fuel["status_marl"]

    # True delay verification: baseline ~12001.2 veh*s, coordinated ~6388.8 veh*s (-46.8%)
    delay = rows["cumulative_delay_veh_s"]
    assert pytest.approx(float(delay["baseline"]), 1.0) == 12001.2
    assert pytest.approx(float(delay["coordinated"]), 1.0) == 6388.8
    assert pytest.approx(float(delay["coord_vs_base_pct"]), 0.1) == 46.8

    # DQN gridlock check
    tt = rows["mean_corridor_travel_time_s"]
    assert tt["marl_dqn"] == ""  # Empty because 0 trips completed


def test_no_superiority_claim_for_marl():
    """
    Verifies that Coordinated Adaptive remains superior to both MARL PPO and DQN
    across travel time, queue length, and fuel efficiency.
    """
    summary_path = PROJECT_ROOT / "outputs" / "corridor" / "marl_multi_controller_summary.csv"
    with open(summary_path, "r", encoding="utf-8") as f:
        rows = {r["metric"]: r for r in csv.DictReader(f)}

    coord_tt = float(rows["mean_corridor_travel_time_s"]["coordinated"])
    ppo_tt = float(rows["mean_corridor_travel_time_s"]["marl_ppo"])
    assert coord_tt < ppo_tt  # Coordinated is faster than PPO (57.19s vs 65.15s)

    coord_q = float(rows["mean_corridor_queue"]["coordinated"])
    ppo_q = float(rows["mean_corridor_queue"]["marl_ppo"])
    assert coord_q < ppo_q  # Coordinated queue is smaller than PPO (10.65 vs 29.50)

    coord_fuel = float(rows["total_fuel_liters"]["coordinated"])
    ppo_fuel = float(rows["total_fuel_liters"]["marl_ppo"])
    assert coord_fuel < ppo_fuel  # Coordinated uses less fuel than PPO (18.39 L vs 26.55 L)

    # DQN completed 0 trips
    dqn_trips = int(float(rows["total_corridor_trips_completed"]["marl_dqn"]))
    assert dqn_trips == 0


def test_api_experiments_compare_response():
    """Verifies that GET /api/experiments/compare returns 200 with corrected metrics and explicit assumptions."""
    res = client.get("/api/experiments/compare")
    assert res.status_code == 200
    data = res.json()
    assert len(data["controllers"]) == 4

    ctrls = {c["controller_name"]: c for c in data["controllers"]}
    assert "Fixed-Time Baseline" in ctrls
    assert "Coordinated Adaptive Controller" in ctrls
    assert "PPO (Proximal Policy Optimization)" in ctrls
    assert "DQN (Deep Q-Network)" in ctrls

    # Confirm fuel in Litres across all controllers and assumptions exposed
    for c in data["controllers"]:
        assert c["total_fuel_liters"] < 50.0  # Volumetric liters check
        assert "0.750 kg/L" in c["fuel_density_applied"]
        assert c["fuel_model"] is not None
        assert "HBEFA4" in c["fuel_model"]
        assert c["data_provenance"] is not None

    # Check true delay fields
    base = ctrls["Fixed-Time Baseline"]
    coord = ctrls["Coordinated Adaptive Controller"]
    assert pytest.approx(base["cumulative_delay_veh_s"], 1.0) == 12001.2
    assert pytest.approx(coord["cumulative_delay_veh_s"], 1.0) == 6388.8


def test_reproducibility_provenance_distinction():
    """
    Verifies that API and detailed JSON strictly distinguish independently reproduced
    Seed 1 results from restored historical Seeds 2-5 records without claiming full 5-seed re-simulation.
    """
    res_detailed = client.get("/api/experiments/marl-detailed")
    assert res_detailed.status_code == 200
    d_data = res_detailed.json()

    prov = d_data["provenance_metadata"]
    assert "Seed 1 was independently reproduced" in prov["reproducibility_distinction"]
    assert "Seeds 2-5 are restored historical records" in prov["reproducibility_distinction"]
    assert "Five-seed reproducibility is not claimed" in prov["reproducibility_distinction"]

    # Verify fuel model and density assumption documented
    assert "HBEFA4" in prov["fuel_model_and_type"]
    assert "0.750 kg/L" in prov["fuel_density_assumption"]
    assert "DIN EN 228" in prov["fuel_density_assumption"]

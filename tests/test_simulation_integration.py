"""
tests/test_simulation_integration.py

Integration tests running MultiIntersectionSimulation on the Silk Board corridor.
Verifies TraCI lifecycle, state extraction for J1/J2/J3, emissions, and clean teardown.
"""

from pathlib import Path
import pytest

from traffic_service.multi_intersection_simulation import MultiIntersectionSimulation

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SUMO_CONFIG = PROJECT_ROOT / "sumo" / "silk_board" / "silk_board.sumocfg"


def test_simulation_lifecycle_and_state_extraction():
    sim = MultiIntersectionSimulation(
        sumocfg_path=SUMO_CONFIG,
        mode="baseline",
        gui=False,
        step_length=1.0,
    )

    try:
        sim.start(seed=42)
        assert sim.sumo_manager.is_running

        # Step 15 seconds
        for _ in range(15):
            states, ok = sim.step()
            assert ok

        # Check J1, J2, J3 state integrity
        assert "J1" in states
        assert "J2" in states
        assert "J3" in states

        for j_id, state in states.items():
            assert state.junction_id == j_id
            assert state.current_phase in {0, 1, 2, 3}
            assert state.total_queue >= 0
            assert state.average_speed_kmh >= 0.0
            assert state.emissions.co2_mg_s >= 0.0
            assert state.emissions.fuel_ml_s >= 0.0

        # Verify AI Observation interface
        ai_obs = sim.get_ai_observations(states)
        assert set(ai_obs.keys()) == {"J1", "J2", "J3"}
        for j_id, obs in ai_obs.items():
            assert "phase" in obs
            assert "approach_queues" in obs
            assert "total_queue" in obs
            assert "upstream_expected_inflow" in obs
            assert "emergency_approaching" in obs

    finally:
        sim.close()
        assert not sim.sumo_manager.is_running


def test_coordinated_mode_stepping():
    sim = MultiIntersectionSimulation(
        sumocfg_path=SUMO_CONFIG,
        mode="coordinated",
        gui=False,
        step_length=1.0,
        enable_emergency=True,
    )

    try:
        sim.start(seed=42)
        assert sim.sumo_manager.is_running

        # Step 20 seconds
        for _ in range(20):
            states, ok = sim.step()
            assert ok

        summary = sim.metrics_collector.compute_summary()
        assert summary.simulation_duration >= 20.0
        assert summary.total_co2_kg >= 0.0
        assert summary.total_fuel_liters >= 0.0

    finally:
        sim.close()
        assert not sim.sumo_manager.is_running

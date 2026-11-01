"""
tests/test_simulation_service.py

Integration tests for SimulationService with the real SUMO Silk Board corridor.
Validates background stepping, pause/resume, manual override, and clean stop.
"""

import time
import pytest
from backend.simulation_service import sim_service


def setup_function():
    sim_service.reset_simulation()


def teardown_function():
    sim_service.stop_simulation()


def test_simulation_service_real_run_lifecycle():
    # Start coordinated simulation
    ok, msg = sim_service.start_simulation(
        mode="coordinated",
        duration=30,
        seed=42,
        step_length=1.0,
        decision_interval=5.0,
        enable_emergency=True,
        gui=False,
    )
    assert ok, f"Simulation failed to start: {msg}"
    assert sim_service.get_status().running is True

    # Allow simulation to step and wait for time > 0
    for _ in range(20):
        if sim_service.get_status().simulation_time > 0.0:
            break
        time.sleep(0.5)

    # Check that simulation has stepped forward
    st = sim_service.get_status()
    assert st.simulation_time > 0.0

    # Check live junctions state
    junctions = sim_service.get_live_junctions()
    assert "J1" in junctions
    assert "J2" in junctions
    assert "J3" in junctions

    # Test Pause
    p_ok, p_msg = sim_service.pause_simulation()
    assert p_ok
    assert sim_service.get_status().paused is True
    # Allow any in-flight step to settle
    time.sleep(0.2)
    time_paused = sim_service.get_status().simulation_time
    time.sleep(0.5)
    assert sim_service.get_status().simulation_time == time_paused

    # Test Resume
    r_ok, r_msg = sim_service.resume_simulation()
    assert r_ok
    assert sim_service.get_status().paused is False

    # Test Manual Override on J2
    # Ensure confirmation is required
    ov_fail, _ = sim_service.request_manual_override("J2", target_phase=0, confirmed=False)
    assert not ov_fail

    ov_ok, ov_msg = sim_service.request_manual_override("J2", target_phase=0, confirmed=True)
    assert ov_ok, f"Override failed: {ov_msg}"

    # Stop simulation
    stop_ok, stop_msg = sim_service.stop_simulation()
    assert stop_ok
    assert sim_service.get_status().running is False

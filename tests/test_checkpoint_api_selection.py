"""Focused API validation tests for approved P6 Stage A checkpoint selection."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import numpy as np
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.main import app
from backend.schemas import SimulationStartRequest
from backend.simulation_service import resolve_checkpoint_path, sim_service
from traffic_service.multi_intersection_simulation import MultiIntersectionSimulation
from traffic_service.signal_controller import SignalController


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SUMO_CONFIG = PROJECT_ROOT / "sumo" / "silk_board" / "silk_board.sumocfg"
client = TestClient(app)


@pytest.mark.parametrize(
    ("mode", "checkpoint_path"),
    [
        ("marl_ppo", "checkpoints/p6/ppo_stage_a_best.json"),
        ("marl_dqn", "checkpoints/p6/dqn_stage_a_best.json"),
    ],
)
def test_api_forwards_approved_checkpoint_path(monkeypatch, mode, checkpoint_path):
    calls = {}

    def fake_start_simulation(**kwargs):
        calls.update(kwargs)
        return True, "accepted"

    monkeypatch.setattr(sim_service, "start_simulation", fake_start_simulation)
    response = client.post(
        "/api/simulation/start",
        json={"mode": mode, "duration": 30, "checkpoint_path": checkpoint_path},
    )

    assert response.status_code == 200
    assert calls["checkpoint_path"] == checkpoint_path
    assert calls["mode"] == mode


def test_omitted_checkpoint_preserves_historical_default(monkeypatch):
    calls = {}

    def fake_start_simulation(**kwargs):
        calls.update(kwargs)
        return True, "accepted"

    monkeypatch.setattr(sim_service, "start_simulation", fake_start_simulation)
    response = client.post("/api/simulation/start", json={"mode": "marl_ppo", "duration": 30})

    assert response.status_code == 200
    assert calls["checkpoint_path"] is None


@pytest.mark.parametrize(
    ("mode", "algorithm"),
    [("marl_ppo", "ppo"), ("marl_dqn", "dqn")],
)
def test_simulation_omission_still_loads_historical_root_checkpoint(mode, algorithm):
    sim = MultiIntersectionSimulation(sumocfg_path=SUMO_CONFIG, mode=mode)
    try:
        checkpoint = PROJECT_ROOT / "checkpoints" / f"marl_{algorithm}_corridor.json"
        stored = json.loads(checkpoint.read_text(encoding="utf-8"))
        loaded = sim.marl_controller.agents["J1"].get_state_dict()
        key = "weights" if algorithm == "ppo" else "q_network_weights"
        assert all(
            np.array_equal(np.asarray(loaded[key][name]), np.asarray(stored["agents"]["J1"][key][name]))
            for name in stored["agents"]["J1"][key]
        )
    finally:
        sim.close()


@pytest.mark.parametrize(
    "checkpoint_path",
    [
        "checkpoints/p6/../marl_ppo_corridor.json",
        "../../checkpoints/p6/ppo_stage_a_best.json",
        "C:/checkpoints/p6/ppo_stage_a_best.json",
        "checkpoints/p6/unknown.json",
    ],
)
def test_schema_rejects_unapproved_or_traversal_path(checkpoint_path):
    with pytest.raises(ValidationError):
        SimulationStartRequest(mode="marl_ppo", checkpoint_path=checkpoint_path)


@pytest.mark.parametrize(
    ("mode", "checkpoint_path", "expected"),
    [
        ("marl_ppo", "checkpoints/p6/ppo_stage_a_best.json", "ppo_stage_a_best.json"),
        ("marl_dqn", "checkpoints/p6/dqn_stage_a_best.json", "dqn_stage_a_best.json"),
    ],
)
def test_service_resolves_existing_approved_checkpoint(mode, checkpoint_path, expected):
    resolved = resolve_checkpoint_path(mode, checkpoint_path)
    assert resolved == (PROJECT_ROOT / "checkpoints" / "p6" / expected).resolve()
    assert resolved.is_file()


@pytest.mark.parametrize(
    ("mode", "checkpoint_path"),
    [
        ("marl_dqn", "checkpoints/p6/ppo_stage_a_best.json"),
        ("marl_ppo", "checkpoints/p6/dqn_stage_a_best.json"),
        ("baseline", "checkpoints/p6/ppo_stage_a_best.json"),
        ("coordinated", "checkpoints/p6/dqn_stage_a_best.json"),
    ],
)
def test_service_rejects_algorithm_mismatch_or_non_marl_mode(mode, checkpoint_path):
    with pytest.raises(ValueError):
        resolve_checkpoint_path(mode, checkpoint_path)


@pytest.mark.parametrize(
    ("mode", "checkpoint_path"),
    [
        ("marl_dqn", "checkpoints/p6/ppo_stage_a_best.json"),
        ("marl_ppo", "checkpoints/p6/dqn_stage_a_best.json"),
    ],
)
def test_api_returns_bad_request_for_algorithm_checkpoint_mismatch(monkeypatch, mode, checkpoint_path):
    # Use the real service preflight but stop before simulation startup.
    def validate_then_stop(**kwargs):
        resolve_checkpoint_path(kwargs["mode"], kwargs["checkpoint_path"])
        pytest.fail("incompatible checkpoint unexpectedly passed validation")

    monkeypatch.setattr(sim_service, "start_simulation", validate_then_stop)
    response = client.post(
        "/api/simulation/start",
        json={"mode": mode, "checkpoint_path": checkpoint_path},
    )
    assert response.status_code == 400


def test_signal_controller_min_max_yellow_and_emergency_gates(monkeypatch):
    import traci

    trafficlight = MagicMock()
    trafficlight.getPhase.return_value = 0
    trafficlight.getNextSwitch.return_value = 45.0
    monkeypatch.setattr(traci, "trafficlight", trafficlight)
    controller = SignalController(
        "test_tls",
        green_phases={0, 2},
        yellow_transitions={0: 1, 2: 3},
        min_green=15.0,
        max_green=60.0,
        yellow_duration=4.0,
    )

    assert controller.get_green_elapsed(0.0) == 0.0
    assert controller.request_switch(target_green_phase=2, sim_time=14.0) is False
    assert controller.request_switch(target_green_phase=2, sim_time=15.0) is True
    trafficlight.setPhase.assert_called_once_with("test_tls", 1)
    trafficlight.setPhaseDuration.assert_called_once_with("test_tls", 4.0)

    trafficlight.getPhase.return_value = 1
    assert controller.request_switch(target_green_phase=2, sim_time=19.0) is False

    trafficlight.getPhase.return_value = 0
    controller._last_phase = 0
    controller._phase_start_time = 0.0
    assert controller.extend_current_green(sim_time=60.0) is False

    controller.emergency_locked = True
    assert controller.request_switch(target_green_phase=2, sim_time=61.0) is False
    assert controller.extend_current_green(sim_time=61.0) is False

"""
tests/test_marl_runtime_dispatch.py

Verification suite for Stage P3: MARL Runtime Dispatch Recovery.
Tests:
1. Checkpoint loading and junction validation for PPO and DQN.
2. Explicit failure on missing or corrupted checkpoint paths (FileNotFoundError / RuntimeError).
3. Action routing fidelity: ACTION_KEEP, ACTION_SWITCH, ACTION_EXTEND reaching SignalController.
4. Fallback execution safety on corrupted (NaN) observations without simulation crash.
5. Emergency lock bypass compatibility during active preemption.
6. Backend API validation and status reporting for marl_ppo and marl_dqn.
7. Live TraCI simulation stepping with SUMO in marl_ppo and marl_dqn modes.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock
import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from traffic_service.ai.env import ACTION_KEEP, ACTION_SWITCH, ACTION_EXTEND
from traffic_service.ai.marl_controller import MARLCorridorController
from traffic_service.multi_intersection_simulation import MultiIntersectionSimulation
from traffic_service.signal_controller import SignalController

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SUMO_CONFIG = PROJECT_ROOT / "sumo" / "silk_board" / "silk_board.sumocfg"
CHECKPOINTS_DIR = PROJECT_ROOT / "checkpoints"

client = TestClient(app)


# ==============================================================================
# 1. Checkpoint Loading & Explicit Failure Verification
# ==============================================================================

def test_checkpoint_junction_completeness():
    """Verifies that checkpoints contain weights for all corridor junctions (J1, J2, J3)."""
    for algo in ["ppo", "dqn"]:
        ckpt_path = CHECKPOINTS_DIR / f"marl_{algo}_corridor.json"
        assert ckpt_path.is_file(), f"Missing checkpoint: {ckpt_path}"

        ctrl = MARLCorridorController(algorithm=algo, junctions=["J1", "J2", "J3"])
        success = ctrl.load_checkpoint(ckpt_path)
        assert success is True, f"Failed to load checkpoint for {algo}"

        for j_id in ["J1", "J2", "J3"]:
            assert j_id in ctrl.agents
            state_dict = ctrl.agents[j_id].get_state_dict()
            assert "weights" in state_dict or "q_network_weights" in state_dict


def test_missing_checkpoint_raises_file_not_found(tmp_path):
    """Verifies that MultiIntersectionSimulation raises FileNotFoundError if checkpoint is missing."""
    non_existent = tmp_path / "non_existent_checkpoint.json"
    with pytest.raises(FileNotFoundError) as exc_info:
        MultiIntersectionSimulation(
            sumocfg_path=SUMO_CONFIG,
            mode="marl_ppo",
            checkpoint_path=non_existent,
        )
    assert "MARL checkpoint file not found" in str(exc_info.value)


def test_corrupted_checkpoint_raises_runtime_error(tmp_path):
    """Verifies that MultiIntersectionSimulation raises RuntimeError if checkpoint is corrupted or incomplete."""
    # Create invalid JSON syntax
    corrupt_json = tmp_path / "corrupt_syntax.json"
    corrupt_json.write_text("{invalid json", encoding="utf-8")

    with pytest.raises(RuntimeError) as exc_info:
        MultiIntersectionSimulation(
            sumocfg_path=SUMO_CONFIG,
            mode="marl_ppo",
            checkpoint_path=corrupt_json,
        )
    assert "Failed to load MARL checkpoint" in str(exc_info.value)

    # Create valid JSON missing one junction (e.g. missing J2)
    incomplete_json = tmp_path / "incomplete_agents.json"
    data = {
        "algorithm": "ppo",
        "junctions": ["J1", "J2", "J3"],
        "agents": {
            "J1": {"agent_id": "J1", "weights": [0.1, 0.2]},
            "J3": {"agent_id": "J3", "weights": [0.1, 0.2]},
            # J2 omitted intentionally
        },
    }
    incomplete_json.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(RuntimeError) as exc_info2:
        MultiIntersectionSimulation(
            sumocfg_path=SUMO_CONFIG,
            mode="marl_ppo",
            checkpoint_path=incomplete_json,
        )
    assert "Failed to load MARL checkpoint" in str(exc_info2.value)


# ==============================================================================
# 2. Action Routing Fidelity & SignalController Integration
# ==============================================================================

def test_action_routing_keep_switch_extend(monkeypatch):
    """Verifies that MARL decisions translate correctly to SignalController calls."""
    import traci

    mock_tl = MagicMock()
    mock_tl.getPhase.return_value = 0
    mock_tl.getNextSwitch.return_value = 35.0
    mock_tl.getPhaseDuration.return_value = 40.0
    monkeypatch.setattr(traci, "trafficlight", mock_tl)

    green_p = {0, 2}
    yellow_t = {0: 1, 2: 3}
    ctrl = SignalController("test_tls", green_phases=green_p, yellow_transitions=yellow_t, yellow_duration=4.0, min_green=15.0, max_green=60.0)

    # 1. ACTION_KEEP (0)
    marl = MARLCorridorController(algorithm="ppo", junctions=["J1"], controllers={"J1": ctrl})
    decisions_keep = {"J1": {"action": ACTION_KEEP, "action_name": "KEEP", "target_phase": 0, "current_phase": 0}}
    ops_keep = marl.apply_decisions(decisions_keep, sim_time=25.0)
    assert "KEEP_PHASE_0" in ops_keep["J1"]

    # 2. ACTION_SWITCH (1)
    ctrl._green_start_time = 0.0
    decisions_switch = {"J1": {"action": ACTION_SWITCH, "action_name": "SWITCH", "target_phase": 2, "current_phase": 0}}
    ops_switch = marl.apply_decisions(decisions_switch, sim_time=25.0)
    assert "REQUEST_SWITCH_TARGET_2_OK" in ops_switch["J1"]
    mock_tl.setPhase.assert_called_with("test_tls", 1)  # Yellow transition phase

    # 3. ACTION_EXTEND (2)
    mock_tl.reset_mock()
    mock_tl.getPhase.return_value = 0
    decisions_extend = {"J1": {"action": ACTION_EXTEND, "action_name": "EXTEND", "target_phase": 0, "current_phase": 0}}
    ops_extend = marl.apply_decisions(decisions_extend, sim_time=25.0)
    assert "EXTEND_GREEN_OK" in ops_extend["J1"]
    mock_tl.setPhaseDuration.assert_called_once()


def test_emergency_preemption_locks_out_marl_actions():
    """Verifies that an emergency-locked junction bypasses MARL policy decisions."""
    ctrl = MagicMock(spec=SignalController)
    ctrl.emergency_locked = True
    ctrl.emergency_priority_phase = 0
    ctrl.get_phase.return_value = 0

    marl = MARLCorridorController(algorithm="dqn", junctions=["J2"], controllers={"J2": ctrl})

    raw_obs = {
        "J2": {
            "phase": 0,
            "phase_elapsed": 20.0,
            "time_to_switch": 15.0,
            "approach_queues": {"corridor_hosur": 5},
            "total_queue": 15,
            "average_speed_kmh": 22.0,
            "total_waiting_time": 40.0,
            "vehicle_count": 20,
            "upstream_expected_inflow": 0.5,
            "approaching_platoons_count": 1,
            "co2_mg_s": 100.0,
            "emergency_approaching": True,
        }
    }

    decisions = marl.decide(raw_obs, sim_time=30.0, eval_mode=True)
    assert decisions["J2"]["action"] == ACTION_KEEP
    assert decisions["J2"]["is_emergency"] is True

    executed_ops = marl.apply_decisions(decisions, sim_time=30.0)
    assert executed_ops["J2"] == "EMERGENCY_LOCKED_BYPASS"
    ctrl.request_switch.assert_not_called()
    ctrl.extend_current_green.assert_not_called()


# ==============================================================================
# 3. Observation Safety & Fallback Handling
# ==============================================================================

def test_corrupted_observation_executes_fallback_without_crash():
    """Verifies that NaN observations trigger conservative fallback decisions."""
    ctrl = MagicMock(spec=SignalController)
    ctrl.emergency_locked = False
    ctrl.get_phase.return_value = 0
    ctrl.can_switch.return_value = False

    marl = MARLCorridorController(algorithm="ppo", junctions=["J1"], controllers={"J1": ctrl})

    # Pass corrupt observation with NaNs
    corrupt_obs = {
        "J1": {
            "phase": 0,
            "phase_elapsed": float("nan"),
            "time_to_switch": 10.0,
            "approach_queues": {"corridor_hosur": float("nan")},
            "total_queue": float("nan"),
            "average_speed_kmh": 0.0,
            "total_waiting_time": 0.0,
            "vehicle_count": 0,
            "upstream_expected_inflow": 0.0,
            "approaching_platoons_count": 0,
            "co2_mg_s": 0.0,
            "emergency_approaching": False,
        }
    }

    decisions = marl.decide(corrupt_obs, sim_time=20.0, eval_mode=True)
    assert "J1" in decisions
    assert decisions["J1"]["is_fallback"] is True
    assert "Corrupted observation" in decisions["J1"]["reason"]
    assert decisions["J1"]["action"] in {ACTION_KEEP, ACTION_SWITCH, ACTION_EXTEND}


# ==============================================================================
# 4. Backend API Endpoints Validation
# ==============================================================================

def test_api_simulation_start_accepts_marl_modes(monkeypatch):
    """Verifies that /api/simulation/start accepts 'marl_ppo' and 'marl_dqn' and rejects invalid modes."""
    # Bad mode -> 400
    res_bad = client.post("/api/simulation/start", json={"mode": "invalid_mode"})
    assert res_bad.status_code == 400
    assert "Supported modes" in res_bad.json()["detail"]

    # Mock start_simulation to isolate router validation
    from backend.routers import simulation as sim_router
    mock_start = MagicMock(return_value=(True, "Simulation started"))
    monkeypatch.setattr(sim_router.sim_service, "start_simulation", mock_start)

    for valid_mode in ["marl_ppo", "marl_dqn", "coordinated", "baseline"]:
        res = client.post("/api/simulation/start", json={"mode": valid_mode, "duration": 30})
        assert res.status_code == 200
        assert res.json()["success"] is True


def test_api_status_reports_correct_marl_controller_name():
    """Verifies that /api/simulation/status returns the explicit controller naming for MARL modes."""
    from backend.simulation_service import sim_service

    with sim_service._lock:
        sim_service._mode = "marl_ppo"
    res_ppo = client.get("/api/simulation/status")
    assert res_ppo.status_code == 200
    assert res_ppo.json()["controller"] == "MARL Proximal Policy Optimization (PPO Corridor)"

    with sim_service._lock:
        sim_service._mode = "marl_dqn"
    res_dqn = client.get("/api/simulation/status")
    assert res_dqn.status_code == 200
    assert res_dqn.json()["controller"] == "MARL Deep Q-Network (Double-DQN Corridor)"


# ==============================================================================
# 5. Live TraCI Stepping on SUMO in MARL Modes
# ==============================================================================

def test_live_marl_ppo_stepping_on_sumo():
    """Verifies live 15-second simulation run under MARL PPO control on SUMO."""
    sim = MultiIntersectionSimulation(
        sumocfg_path=SUMO_CONFIG,
        mode="marl_ppo",
        gui=False,
        step_length=1.0,
        decision_interval=5.0,
    )
    assert sim.marl_controller is not None
    assert sim.marl_controller.algorithm == "ppo"

    try:
        sim.start(seed=42)
        assert sim.sumo_manager.is_running

        for step_idx in range(15):
            states, ok = sim.step()
            assert ok
            assert "J1" in states
            assert "J2" in states
            assert "J3" in states

        # Verify summary metrics are recorded
        summary = sim.metrics_collector.compute_summary()
        assert summary.simulation_duration >= 15.0
        assert summary.total_fuel_liters >= 0.0

    finally:
        sim.close()
        assert not sim.sumo_manager.is_running


def test_live_marl_dqn_stepping_on_sumo():
    """Verifies live 15-second simulation run under MARL DQN control on SUMO."""
    sim = MultiIntersectionSimulation(
        sumocfg_path=SUMO_CONFIG,
        mode="marl_dqn",
        gui=False,
        step_length=1.0,
        decision_interval=5.0,
    )
    assert sim.marl_controller is not None
    assert sim.marl_controller.algorithm == "dqn"

    try:
        sim.start(seed=42)
        assert sim.sumo_manager.is_running

        for step_idx in range(15):
            states, ok = sim.step()
            assert ok
            assert "J1" in states
            assert "J2" in states
            assert "J3" in states

        summary = sim.metrics_collector.compute_summary()
        assert summary.simulation_duration >= 15.0
        assert summary.total_fuel_liters >= 0.0

    finally:
        sim.close()
        assert not sim.sumo_manager.is_running

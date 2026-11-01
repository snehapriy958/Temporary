"""
tests/test_p6_rewards_and_safety.py

Unit and integration tests for P6 Mixed Local-Global Rewards, Platoon Progression,
and Anti-Starvation Safety Constraints.
"""

from __future__ import annotations

import numpy as np
import pytest

from traffic_service.ai.env import (
    ACTION_KEEP,
    ACTION_SWITCH,
    ACTION_EXTEND,
    MultiIntersectionReward,
    RewardWeights,
    RewardBreakdown,
)
from traffic_service.ai.starvation_tracker import StarvationTracker, StarvationEvent
from traffic_service.communication import CorridorCommunicationHub
from traffic_service.ai.marl_controller import MARLCorridorController


class DummySignalController:
    """Mock SignalController for testing timing and starvation constraints."""

    def __init__(self, current_phase: int = 0, can_switch_val: bool = True, emergency_locked: bool = False) -> None:
        self.phase = current_phase
        self.can_switch_val = can_switch_val
        self.emergency_locked = emergency_locked
        self.emergency_priority_phase = 2

    def get_phase(self) -> int:
        return self.phase

    def can_switch(self, sim_time: float) -> bool:
        return self.can_switch_val

    def request_switch(self, target_green_phase: int, sim_time: float) -> bool:
        if self.can_switch_val:
            self.phase = target_green_phase
            return True
        return False

    def extend_current_green(self, sim_time: float) -> bool:
        return True


# =====================================================================
# 1. Anti-Starvation Safety Constraint Tests
# =====================================================================

def test_starvation_tracker_accumulates_red_time():
    tracker = StarvationTracker(max_red_threshold_s=60.0)

    # Initially all red timers are zero
    assert tracker.red_elapsed["J1"]["corridor_hosur"] == 0.0
    assert tracker.red_elapsed["J1"]["side_cross"] == 0.0

    # Step 1: J1 is in Phase 0 (side_cross is green, corridor_hosur is red)
    tracker.update(
        current_phases={"J1": 0, "J2": 0, "J3": 0},
        approach_queues={"J1": {"corridor_hosur": 10, "side_cross": 2}},
        step_length=1.0,
        sim_time=1.0,
    )

    # corridor_hosur (green is phase 2) was red: elapsed = 1.0s
    assert tracker.red_elapsed["J1"]["corridor_hosur"] == 1.0
    # side_cross (green is phase 0) was green: elapsed = 0.0s
    assert tracker.red_elapsed["J1"]["side_cross"] == 0.0


def test_starvation_tracker_triggers_forced_switch_at_threshold():
    tracker = StarvationTracker(max_red_threshold_s=60.0)

    # Simulate 60 seconds of red for J1 corridor_hosur
    for t in range(1, 61):
        tracker.update(
            current_phases={"J1": 0, "J2": 0, "J3": 0},
            approach_queues={"J1": {"corridor_hosur": 15, "side_cross": 1}},
            step_length=1.0,
            sim_time=float(t),
        )

    # Approach should now be detected as starved
    starved = tracker.get_starved_approaches("J1")
    assert len(starved) == 1
    assert starved[0]["approach"] == "corridor_hosur"
    assert starved[0]["red_duration_s"] == 60.0
    assert starved[0]["target_green_phase"] == 2

    # Action mask when can_switch is True: KEEP and EXTEND must be masked out, SWITCH enforced
    mask, reason = tracker.get_action_mask(
        j_id="J1",
        current_phase=0,
        can_switch=True,
        emergency_locked=False,
        sim_time=60.0,
    )

    np.testing.assert_array_equal(mask, [0.0, 1.0, 0.0])
    assert "STARVATION_PREVENTION" in reason
    assert len(tracker.events) == 1
    assert tracker.events[0].starved_approach == "corridor_hosur"


def test_starvation_tracker_masks_extend_when_min_green_not_elapsed():
    tracker = StarvationTracker(max_red_threshold_s=60.0)

    # Simulate 65s of red
    for t in range(1, 66):
        tracker.update(
            current_phases={"J1": 0},
            approach_queues={"J1": {"corridor_hosur": 10}},
            step_length=1.0,
            sim_time=float(t),
        )

    # If can_switch is False (e.g. min green not reached on current phase), EXTEND must be prohibited
    mask, reason = tracker.get_action_mask(
        j_id="J1",
        current_phase=0,
        can_switch=False,
        emergency_locked=False,
        sim_time=65.0,
    )

    np.testing.assert_array_equal(mask, [1.0, 0.0, 0.0])
    assert "STARVATION_PENDING_MIN_GREEN" in reason


def test_emergency_preemption_overrides_starvation():
    tracker = StarvationTracker(max_red_threshold_s=60.0)
    for t in range(1, 70):
        tracker.update(
            current_phases={"J1": 0},
            approach_queues={"J1": {"corridor_hosur": 25}},
            step_length=1.0,
            sim_time=float(t),
        )

    # When emergency lock is active, emergency override takes strict priority
    mask, reason = tracker.get_action_mask(
        j_id="J1",
        current_phase=0,
        can_switch=True,
        emergency_locked=True,
        sim_time=70.0,
    )

    np.testing.assert_array_equal(mask, [1.0, 0.0, 0.0])
    assert "EMERGENCY_LOCK_ACTIVE" in reason


# =====================================================================
# 2. Mixed Local-Global Reward Tests
# =====================================================================

def test_mixed_reward_alpha_convex_combination():
    weights = RewardWeights(alpha=0.5)
    reward_fn = MultiIntersectionReward(weights=weights)

    states = {
        "J1": {"total_queue": 10, "total_waiting_time": 50.0, "average_speed_kmh": 25.0, "co2_mg_s": 1000.0, "phase": 2},
        "J2": {"total_queue": 15, "total_waiting_time": 80.0, "average_speed_kmh": 20.0, "co2_mg_s": 1500.0, "phase": 0},
        "J3": {"total_queue": 5, "total_waiting_time": 20.0, "average_speed_kmh": 30.0, "co2_mg_s": 800.0, "phase": 2},
    }
    actions = {"J1": ACTION_KEEP, "J2": ACTION_KEEP, "J3": ACTION_KEEP}

    rewards_50, breakdowns_50 = reward_fn.compute_mixed_rewards(
        states=states,
        actions=actions,
        completed_trips=2,
    )

    for j_id in ["J1", "J2", "J3"]:
        b = breakdowns_50[j_id]
        expected_mixed = 0.5 * b.local_reward + 0.5 * b.corridor_reward
        assert pytest.approx(b.mixed_reward, abs=1e-4) == expected_mixed
        assert pytest.approx(rewards_50[j_id], abs=1e-4) == expected_mixed

    # Pure local test (alpha = 0.0)
    reward_fn.weights.alpha = 0.0
    rewards_0, breakdowns_0 = reward_fn.compute_mixed_rewards(states=states, actions=actions, completed_trips=2)
    for j_id in ["J1", "J2", "J3"]:
        assert pytest.approx(rewards_0[j_id], abs=1e-4) == breakdowns_0[j_id].local_reward

    # Pure global test (alpha = 1.0)
    reward_fn.weights.alpha = 1.0
    rewards_1, breakdowns_1 = reward_fn.compute_mixed_rewards(states=states, actions=actions, completed_trips=2)
    for j_id in ["J1", "J2", "J3"]:
        assert pytest.approx(rewards_1[j_id], abs=1e-4) == breakdowns_1[j_id].corridor_reward


def test_platoon_progression_reward_and_anti_double_counting():
    hub = CorridorCommunicationHub(corridor_sequence=["J1", "J2", "J3"])
    reward_fn = MultiIntersectionReward(weights=RewardWeights(alpha=0.5, weight_progression=0.25))

    # J1 announces an approaching platoon arriving at J2 in 10s (window 15s to 25s)
    hub.announce_platoon(sender_id="J1", vehicle_count=10, speed_mps=11.0, eta_seconds=10.0, timestamp=10.0)

    # At t=20.0s, platoon is arriving at J2. J2 is in Arterial Green (Phase 0)
    states = {
        "J1": {"total_queue": 2, "total_waiting_time": 10.0, "average_speed_kmh": 35.0, "co2_mg_s": 500.0, "phase": 2},
        "J2": {"total_queue": 5, "total_waiting_time": 15.0, "average_speed_kmh": 30.0, "co2_mg_s": 800.0, "phase": 0},
        "J3": {"total_queue": 1, "total_waiting_time": 5.0, "average_speed_kmh": 40.0, "co2_mg_s": 400.0, "phase": 2},
    }
    actions = {"J1": ACTION_KEEP, "J2": ACTION_KEEP, "J3": ACTION_KEEP}

    _, breakdowns_step1 = reward_fn.compute_mixed_rewards(
        states=states,
        actions=actions,
        comm_hub=hub,
        current_time=20.0,
    )

    # J2 received progression reward (+0.25)
    assert breakdowns_step1["J2"].r_progression == pytest.approx(0.25, abs=1e-4)

    # Step 2: At t=21.0s, during the same platoon window, bonus must NOT be double-counted!
    _, breakdowns_step2 = reward_fn.compute_mixed_rewards(
        states=states,
        actions=actions,
        comm_hub=hub,
        current_time=21.0,
    )
    assert breakdowns_step2["J2"].r_progression == 0.0


def test_upstream_flow_integrity_penalty():
    reward_fn = MultiIntersectionReward(weights=RewardWeights(alpha=0.5, weight_flow_integrity=0.30))

    # J1 has 12 queued vehicles on corridor_hosur but holds Phase 0 (side cross green) without releasing trips
    states = {
        "J1": {
            "total_queue": 15,
            "total_waiting_time": 100.0,
            "average_speed_kmh": 10.0,
            "co2_mg_s": 2000.0,
            "phase": 0,
            "approach_queues": {"corridor_hosur": 12, "side_cross": 3},
        },
        "J2": {"total_queue": 0, "total_waiting_time": 0.0, "average_speed_kmh": 40.0, "co2_mg_s": 200.0, "phase": 0},
        "J3": {"total_queue": 0, "total_waiting_time": 0.0, "average_speed_kmh": 40.0, "co2_mg_s": 200.0, "phase": 2},
    }
    actions = {"J1": ACTION_KEEP, "J2": ACTION_KEEP, "J3": ACTION_KEEP}

    _, breakdowns = reward_fn.compute_mixed_rewards(
        states=states,
        actions=actions,
        completed_trips=0,
    )

    assert breakdowns["J1"].R_flow_integrity == pytest.approx(-0.30, abs=1e-4)


# =====================================================================
# 3. MARL Controller Starvation Integration Tests
# =====================================================================

def test_marl_controller_enforces_anti_starvation_switch():
    ctrl_j1 = DummySignalController(current_phase=0, can_switch_val=True)
    ctrl_j2 = DummySignalController(current_phase=0, can_switch_val=True)
    ctrl_j3 = DummySignalController(current_phase=2, can_switch_val=True)

    controllers = {"J1": ctrl_j1, "J2": ctrl_j2, "J3": ctrl_j3}
    marl = MARLCorridorController(
        algorithm="mappo",
        junctions=["J1", "J2", "J3"],
        controllers=controllers,
        max_red_threshold_s=60.0,
    )

    # Pre-starve J1 corridor_hosur by advancing red timer past 60s
    for t in range(1, 62):
        marl.starvation_tracker.update(
            current_phases={"J1": 0, "J2": 0, "J3": 2},
            approach_queues={"J1": {"corridor_hosur": 14, "side_cross": 2}},
            step_length=1.0,
            sim_time=float(t),
        )

    raw_obs = {
        "J1": {
            "phase": 0,
            "phase_elapsed": 61.0,
            "total_queue": 16,
            "approach_queues": {"corridor_hosur": 14, "side_cross": 2},
            "average_speed_kmh": 15.0,
            "total_waiting_time": 300.0,
        },
        "J2": {"phase": 0, "phase_elapsed": 30.0, "total_queue": 5, "approach_queues": {"corridor_hosur": 5}},
        "J3": {"phase": 2, "phase_elapsed": 20.0, "total_queue": 2, "approach_queues": {"corridor_hosur": 2}},
    }

    decisions = marl.decide(raw_obs, sim_time=61.0, eval_mode=True)

    # J1 MUST be forced to SWITCH to arterial green (Phase 2)
    assert decisions["J1"]["action"] == ACTION_SWITCH
    assert decisions["J1"]["target_phase"] == 2
    assert decisions["J1"]["is_starvation_prevention"] is True
    assert "Anti-Starvation Overrule" in decisions["J1"]["reason"]

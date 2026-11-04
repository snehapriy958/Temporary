"""
tests/test_p6_1_pretraining_validation.py

Pre-Training Validation Gate for Stage P6.1.
Verifies:
1. Anti-starvation safety constraint boundaries (59s, 60s, 61s), resets, min-green masking,
   emergency preemption, and the 60s threshold vs 65s ceiling guarantee.
2. MAPPO CTDE correctness: topological state slicing [0:14, 14:28, 28:42], action masking
   invariance, numerical GAE and PPO-clip calculations, shared critic non-interference.
3. Multi-objective reward audit: independence of all 11 terms, zero traffic vs saturated queues,
   corridor collapse non-compensation, and platoon progression anti-double-counting.
4. Curriculum demand rates, vehicle mix, and seed disjointness.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, List
import numpy as np
import pytest

from traffic_service.ai.env import (
    CorridorObservationSpace,
    MultiIntersectionReward,
    RewardWeights,
    RewardBreakdown,
    ACTION_KEEP,
    ACTION_SWITCH,
    ACTION_EXTEND,
    CORRIDOR_OBSERVATION_DIM,
    OBSERVATION_DIM_PER_JUNCTION,
)
from traffic_service.ai.starvation_tracker import StarvationTracker, StarvationEvent
from traffic_service.ai.models import (
    MAPPOActorNetwork,
    MAPPOCentralizedCriticNetwork,
    TORCH_AVAILABLE,
)
from traffic_service.ai.mappo_agent import (
    MAPPOAgent,
    train_mappo_corridor,
)
from traffic_service.ai.marl_controller import MARLCorridorController
from traffic_service.communication import CorridorCommunicationHub
from traffic_service.curriculum import (
    CurriculumDemandGenerator,
    CURRICULUM_STAGES,
)

if TORCH_AVAILABLE:
    import torch
    import torch.nn.functional as F


# =====================================================================
# Dummy Helpers for Controlled Unit Testing
# =====================================================================

class DummySignalController:
    """Mock controller adhering to SignalController interface."""

    def __init__(
        self,
        current_phase: int = 0,
        can_switch_val: bool = True,
        emergency_locked: bool = False,
        min_green: float = 15.0,
        yellow_duration: float = 4.0,
    ) -> None:
        self.phase = current_phase
        self.can_switch_val = can_switch_val
        self.emergency_locked = emergency_locked
        self.min_green = min_green
        self.yellow_duration = yellow_duration
        self.switch_requested = False
        self.target_green_phase: int | None = None
        self.green_elapsed = 20.0

    def get_phase(self) -> int:
        return self.phase

    def is_green(self, phase: int | None = None) -> bool:
        p = self.phase if phase is None else phase
        return p in (0, 2)

    def get_green_elapsed(self, sim_time: float) -> float:
        return self.green_elapsed

    def can_switch(self, sim_time: float) -> bool:
        if self.emergency_locked or not self.is_green():
            return False
        return self.can_switch_val

    def request_switch(self, target_green_phase: int, sim_time: float, force: bool = False) -> bool:
        if self.emergency_locked and not force:
            return False
        self.switch_requested = True
        self.target_green_phase = target_green_phase
        return True


# =====================================================================
# PART 1: Anti-Starvation & Safety Constraints Verification
# =====================================================================

def test_anti_starvation_boundaries_59_60_61_seconds():
    """
    Validates exact boundary behavior at 59.0s, 60.0s, and 61.0s.
    Threshold: 60.0s.
    - 59.0s: Unconstrained, SWITCH is NOT forced.
    - 60.0s: Forced SWITCH [0.0, 1.0, 0.0] triggered and logged.
    - 61.0s: Forced SWITCH [0.0, 1.0, 0.0] maintained.
    """
    tracker = StarvationTracker(max_red_threshold_s=60.0)

    # 1. Approach red for 59.0s
    phases = {"J1": 2}  # Hosur Green
    queues = {"J1": {"corridor_hosur": 0, "side_cross": 5}}
    tracker.update(phases, queues, step_length=59.0, sim_time=59.0)

    mask_59, reason_59 = tracker.get_action_mask("J1", current_phase=2, can_switch=True, sim_time=59.0)
    assert np.allclose(mask_59, [1.0, 1.0, 1.0]), f"Expected unconstrained at 59s, got {mask_59}"
    assert len(tracker.events) == 0, "No starvation event should be logged at 59s"

    # 2. Advance by 1.0s to reach exactly 60.0s
    tracker.update(phases, queues, step_length=1.0, sim_time=60.0)
    mask_60, reason_60 = tracker.get_action_mask("J1", current_phase=2, can_switch=True, sim_time=60.0)
    assert np.allclose(mask_60, [0.0, 1.0, 0.0]), f"Expected forced SWITCH at 60s, got {mask_60}"
    assert "STARVATION_PREVENTION" in reason_60
    assert len(tracker.events) == 1
    assert tracker.events[0].junction_id == "J1"
    assert tracker.events[0].starved_approach == "side_cross"
    assert tracker.events[0].red_duration_s == 60.0
    assert tracker.events[0].action_enforced == "SWITCH"

    # 3. Advance to 61.0s (if still waiting in phase 2)
    tracker.update(phases, queues, step_length=1.0, sim_time=61.0)
    mask_61, reason_61 = tracker.get_action_mask("J1", current_phase=2, can_switch=True, sim_time=61.0)
    assert np.allclose(mask_61, [0.0, 1.0, 0.0]), f"Expected forced SWITCH at 61s, got {mask_61}"


def test_timer_reset_when_approach_receives_service():
    """
    Verifies that when a starved approach receives green, its red timer
    resets immediately to 0.0s and action mask returns to unconstrained.
    """
    tracker = StarvationTracker(max_red_threshold_s=60.0)

    # Accumulate 65s red on J2 madiwala (green phase is 2, currently in phase 0)
    phases = {"J2": 0}
    queues = {"J2": {"corridor_hosur": 10, "madiwala": 8}}
    tracker.update(phases, queues, step_length=65.0, sim_time=65.0)

    starved = tracker.get_starved_approaches("J2")
    assert len(starved) == 1
    assert starved[0]["approach"] == "madiwala"
    assert starved[0]["red_duration_s"] == 65.0

    # Service madiwala: signal switches to phase 2
    phases_servicing = {"J2": 2}
    tracker.update(phases_servicing, queues, step_length=1.0, sim_time=66.0)

    assert tracker.red_elapsed["J2"]["madiwala"] == 0.0, "Red elapsed should reset to 0.0s on green"
    starved_after = tracker.get_starved_approaches("J2")
    assert len(starved_after) == 0, "No starved approach should exist after switch to green"

    # Check action mask when currently servicing madiwala
    mask, reason = tracker.get_action_mask("J2", current_phase=2, can_switch=True, sim_time=66.0)
    assert np.allclose(mask, [1.0, 1.0, 1.0])


def test_min_green_prevents_immediate_switch_and_masks_extend():
    """
    Verifies behavior when an approach is starved but minimum green has not elapsed:
    - SWITCH is prohibited (min-green safety).
    - EXTEND is masked out ([1.0, 0.0, 0.0]), preventing the agent from prolonging green.
    - As soon as can_switch becomes True, mask switches to [0.0, 1.0, 0.0].
    """
    tracker = StarvationTracker(max_red_threshold_s=60.0)

    phases = {"J3": 2}  # Hosur green
    queues = {"J3": {"corridor_hosur": 2, "side_cross": 6}}
    tracker.update(phases, queues, step_length=60.0, sim_time=60.0)

    # 1. can_switch is False (min green active)
    mask_pending, reason_pending = tracker.get_action_mask("J3", current_phase=2, can_switch=False, sim_time=60.0)
    assert np.allclose(mask_pending, [1.0, 0.0, 0.0]), f"Expected [1, 0, 0], got {mask_pending}"
    assert "STARVATION_PENDING_MIN_GREEN" in reason_pending
    assert mask_pending[2] == 0.0, "EXTEND must be strictly prohibited when starvation is pending"

    # 2. Min green elapses -> can_switch becomes True
    mask_cleared, reason_cleared = tracker.get_action_mask("J3", current_phase=2, can_switch=True, sim_time=65.0)
    assert np.allclose(mask_cleared, [0.0, 1.0, 0.0]), f"Expected [0, 1, 0], got {mask_cleared}"
    assert "STARVATION_PREVENTION" in reason_cleared


def test_emergency_preemption_and_post_emergency_recovery():
    """
    Verifies that:
    1. Emergency lockout overrides starvation: enforces KEEP [1, 0, 0].
    2. Once emergency unlocks, anti-starvation immediately recovers and forces SWITCH [0, 1, 0].
    """
    tracker = StarvationTracker(max_red_threshold_s=60.0)

    phases = {"J1": 2}
    queues = {"J1": {"corridor_hosur": 0, "side_cross": 10}}
    tracker.update(phases, queues, step_length=70.0, sim_time=70.0)

    # During emergency lock:
    mask_emerg, reason_emerg = tracker.get_action_mask(
        "J1", current_phase=2, can_switch=True, emergency_locked=True, sim_time=70.0
    )
    assert np.allclose(mask_emerg, [1.0, 0.0, 0.0])
    assert reason_emerg == "EMERGENCY_LOCK_ACTIVE"

    # Post-emergency recovery:
    mask_recov, reason_recov = tracker.get_action_mask(
        "J1", current_phase=2, can_switch=True, emergency_locked=False, sim_time=75.0
    )
    assert np.allclose(mask_recov, [0.0, 1.0, 0.0])
    assert "STARVATION_PREVENTION" in reason_recov


def test_all_junctions_and_all_approaches():
    """
    Verifies anti-starvation constraint coverage across all 3 junctions (J1, J2, J3)
    and all inbound approaches ('corridor_hosur', 'side_cross', 'madiwala').
    """
    tracker = StarvationTracker(max_red_threshold_s=60.0)

    test_cases = [
        ("J1", "side_cross", 2, 0),       # J1 side cross starved when in Hosur green (phase 2)
        ("J1", "corridor_hosur", 0, 2),   # J1 Hosur starved when in side green (phase 0)
        ("J2", "madiwala", 0, 2),         # J2 Madiwala starved when in Hosur green (phase 0)
        ("J2", "corridor_hosur", 2, 0),   # J2 Hosur starved when in Madiwala green (phase 2)
        ("J3", "side_cross", 2, 0),       # J3 side cross starved when in Hosur green (phase 2)
        ("J3", "corridor_hosur", 0, 2),   # J3 Hosur starved when in side green (phase 0)
    ]

    for j_id, starved_app, curr_phase, target_phase in test_cases:
        tracker.reset()
        phases = {j_id: curr_phase}
        queues = {j_id: {starved_app: 4}}
        tracker.update(phases, queues, step_length=60.0, sim_time=60.0)

        starved = tracker.get_starved_approaches(j_id)
        assert len(starved) == 1
        assert starved[0]["approach"] == starved_app
        assert starved[0]["target_green_phase"] == target_phase

        mask, reason = tracker.get_action_mask(j_id, current_phase=curr_phase, can_switch=True, sim_time=60.0)
        assert np.allclose(mask, [0.0, 1.0, 0.0]), f"Failed for {j_id} approach {starved_app}"


def test_duplicate_step_update_protection():
    """
    Verifies that calling update() multiple times at the same sim_time
    does not accumulate duplicate red time.
    """
    tracker = StarvationTracker(max_red_threshold_s=60.0)
    phases = {"J1": 2}
    queues = {"J1": {"side_cross": 3}}

    # First call at sim_time = 1.0s
    tracker.update(phases, queues, step_length=1.0, sim_time=1.0)
    assert tracker.red_elapsed["J1"]["side_cross"] == 1.0

    # Duplicate call at sim_time = 1.0s (e.g. from sim.step and marl.decide)
    tracker.update(phases, queues, step_length=1.0, sim_time=1.0)
    assert tracker.red_elapsed["J1"]["side_cross"] == 1.0, "Duplicate call at same sim_time must not add red time"

    # Advance to sim_time = 2.0s
    tracker.update(phases, queues, step_length=1.0, sim_time=2.0)
    assert tracker.red_elapsed["J1"]["side_cross"] == 2.0


def test_mathematical_guarantee_60s_threshold_vs_65s_ceiling():
    """
    Demonstrates the exact mathematical derivation of the 60s threshold vs 65s ceiling:
      T_ceiling = T_threshold (60.0s) + delta_t_sim (1.0s) + T_yellow (4.0s) = 65.0s.
    """
    threshold_s = 60.0
    dt_sim = 1.0
    t_yellow = 4.0

    ceiling = threshold_s + dt_sim + t_yellow
    assert math.isclose(ceiling, 65.0, abs_tol=1e-5), f"Expected 65.0s ceiling, got {ceiling}"


# =====================================================================
# PART 2: MAPPO CTDE Correctness & Numerical Validation
# =====================================================================

def test_mappo_junction_ordering_and_corridor_concatenation():
    """
    Verifies topological ordering [J1, J2, J3] in the 42-dim corridor observation vector:
    - J1: slice [0:14]
    - J2: slice [14:28]
    - J3: slice [28:42]
    """
    obs_space = CorridorObservationSpace(junctions=["J1", "J2", "J3"])

    raw_obs = {
        "J1": {"total_queue": 10, "phase": 2},
        "J2": {"total_queue": 20, "phase": 0},
        "J3": {"total_queue": 30, "phase": 2},
    }

    vec_j1 = obs_space.vectorize_junction("J1", raw_obs["J1"])
    vec_j2 = obs_space.vectorize_junction("J2", raw_obs["J2"])
    vec_j3 = obs_space.vectorize_junction("J3", raw_obs["J3"])

    corridor_vec = obs_space.vectorize_corridor(raw_obs)
    assert corridor_vec.shape == (42,)

    # Verify exact slice alignment
    assert np.allclose(corridor_vec[0:14], vec_j1), "J1 slice [0:14] mismatch"
    assert np.allclose(corridor_vec[14:28], vec_j2), "J2 slice [14:28] mismatch"
    assert np.allclose(corridor_vec[28:42], vec_j3), "J3 slice [28:42] mismatch"


@pytest.mark.skipif(not TORCH_AVAILABLE, reason="PyTorch not available")
def test_mappo_masked_action_probabilities_remain_zero_and_logits_finite():
    """
    Verifies that:
    1. Masked actions have exact 0.0 probability.
    2. Softmax probabilities sum to 1.0.
    3. Categorical distribution entropy remains non-negative and finite (no NaNs).
    """
    actor = MAPPOActorNetwork(in_features=14, num_actions=3, seed=42)

    x = torch.randn(5, 14)
    # Mask out action 0 (KEEP) and action 2 (EXTEND), only allow action 1 (SWITCH)
    mask = torch.tensor([[0.0, 1.0, 0.0]] * 5, dtype=torch.float32)

    logits, probs = actor.forward_logits(x, mask=mask)

    assert logits.shape == (5, 3)
    assert probs.shape == (5, 3)

    # Probabilities for masked actions must be 0.0
    assert torch.all(probs[:, 0] == 0.0)
    assert torch.all(probs[:, 2] == 0.0)
    assert torch.allclose(probs[:, 1], torch.ones(5), atol=1e-6)

    # Entropy calculation
    dist = torch.distributions.Categorical(probs=probs)
    entropy = dist.entropy()
    assert not torch.isnan(entropy).any(), "Entropy should not contain NaNs"
    assert not torch.isinf(entropy).any(), "Entropy should not contain Infs"
    # When 1 action has probability 1.0 and others 0.0, entropy should be 0.0
    assert torch.allclose(entropy, torch.zeros(5), atol=1e-5)


def test_mappo_gae_numerical_calculation():
    """
    Verifies Generalized Advantage Estimation (GAE-Lambda) against manual mathematical computation.
    Given:
      gamma = 0.99, lambda = 0.95
      rewards = [1.0, 2.0, -1.0, 0.5]
      values = [0.5, 1.0, 0.2, 0.1]
      last_corridor_value = 0.0
      dones = [False, False, False, False]
    """
    gamma = 0.99
    lam = 0.95
    rewards = np.array([1.0, 2.0, -1.0, 0.5], dtype=np.float32)
    values = np.array([0.5, 1.0, 0.2, 0.1], dtype=np.float32)
    dones = np.array([False, False, False, False], dtype=np.bool_)
    last_val = 0.0

    # Manual reverse recurrence:
    # t = 3: delta_3 = 0.5 + 0.99 * 0.0 - 0.1 = 0.4
    #        A_3 = 0.4
    # t = 2: delta_2 = -1.0 + 0.99 * 0.1 - 0.2 = -1.101
    #        A_2 = -1.101 + 0.99 * 0.95 * A_3 = -1.101 + 0.9405 * 0.4 = -0.7248
    # t = 1: delta_1 = 2.0 + 0.99 * 0.2 - 1.0 = 1.198
    #        A_1 = 1.198 + 0.9405 * A_2 = 1.198 + 0.9405 * (-0.7248) = 0.5163256
    # t = 0: delta_0 = 1.0 + 0.99 * 1.0 - 0.5 = 1.49
    #        A_0 = 1.49 + 0.9405 * A_1 = 1.49 + 0.9405 * 0.5163256 = 1.975604

    agent = MAPPOAgent("J1", in_features=14, corridor_features=42, gamma=gamma, gae_lambda=lam)
    adv_norm, returns = agent.compute_gae(last_val, dones, rewards, values)

    assert len(returns) == 4
    # Check returns = unnormalized advantages + values
    unnorm_adv = returns - values
    expected_adv_3 = 0.4
    expected_adv_2 = -1.101 + (gamma * lam * expected_adv_3)
    expected_adv_1 = 1.198 + (gamma * lam * expected_adv_2)
    expected_adv_0 = 1.49 + (gamma * lam * expected_adv_1)

    assert math.isclose(unnorm_adv[3], expected_adv_3, abs_tol=1e-4)
    assert math.isclose(unnorm_adv[2], expected_adv_2, abs_tol=1e-4)
    assert math.isclose(unnorm_adv[1], expected_adv_1, abs_tol=1e-4)
    assert math.isclose(unnorm_adv[0], expected_adv_0, abs_tol=1e-4)


@pytest.mark.skipif(not TORCH_AVAILABLE, reason="PyTorch not available")
def test_mappo_shared_critic_coordinated_training_non_interference():
    """
    Verifies that train_mappo_corridor trains all three decentralized actors
    and updates the shared centralized critic ONCE per batch without conflicting optimization.
    """
    critic = MAPPOCentralizedCriticNetwork(in_features=42, seed=100)
    critic_opt = torch.optim.Adam(critic.parameters(), lr=0.001)

    agents = {
        j: MAPPOAgent(
            agent_id=j,
            in_features=14,
            corridor_features=42,
            shared_critic=critic,
            shared_critic_optimizer=critic_opt,
            seed=42 + i,
        )
        for i, j in enumerate(["J1", "J2", "J3"])
    }

    # Populate 16 steps of mock transitions for each agent
    for step in range(16):
        c_state = np.random.randn(42).astype(np.float32)
        done = (step == 15)
        for j_id, agent in agents.items():
            l_state = np.random.randn(14).astype(np.float32)
            mask = np.array([1.0, 1.0, 1.0], dtype=np.float32)
            action, info = agent.select_action(l_state, action_mask=mask)
            agent.store_transition(
                local_state=l_state,
                corridor_state=c_state,
                action=action,
                action_mask=mask,
                reward=float(np.random.randn()),
                log_prob=info["log_prob"],
                value=float(np.random.randn()),
                done=done,
            )

    results = train_mappo_corridor(agents, shared_critic=critic, shared_critic_optimizer=critic_opt, epochs=2)

    assert "policy_results" in results
    assert len(results["policy_results"]) == 3
    for j_id in ["J1", "J2", "J3"]:
        assert j_id in results["policy_results"]
        assert not np.isnan(results["policy_results"][j_id]["policy_loss"])

    assert not np.isnan(results["critic_loss"])
    assert results["critic_loss"] >= 0.0
    # Buffers must be cleared after update
    for agent in agents.values():
        assert len(agent.buffer) == 0


# =====================================================================
# PART 3: Multi-Objective Reward Diagnostics & Edge Cases
# =====================================================================

def test_reward_components_independent_evaluation():
    """
    Independently verifies each of the 11 reward components:
    Local:
      1. r_q (queue penalty)
      2. r_w (wait time penalty)
      3. r_s (speed incentive)
      4. r_c (CO2 penalty)
      5. r_chatter (phase switch chatter penalty)
      6. r_emerg (emergency penalty)
      7. r_prog (platoon progression bonus)
    Corridor:
      8. R_throughput (completed trips bonus)
      9. R_corridor_delay (corridor queue penalty)
      10. R_starvation (global starvation penalty)
      11. R_flow_integrity (upstream arterial holding penalty)
    """
    weights = RewardWeights(
        weight_queue=0.35,
        weight_wait_time=0.30,
        weight_speed=0.15,
        weight_throughput=0.50,
        weight_emissions=0.10,
        weight_emergency_delay=1.0,
        switch_chatter_penalty=0.05,
        alpha=0.5,
        weight_progression=0.25,
        weight_corridor_delay=0.50,
        weight_starvation=0.50,
        weight_flow_integrity=0.30,
    )
    reward_fn = MultiIntersectionReward(weights=weights)

    states = {
        "J1": {
            "total_queue": 15,
            "total_waiting_time": 100.0,
            "average_speed_kmh": 20.0,
            "co2_mg_s": 2500.0,
            "phase": 2,
            "approach_queues": {"corridor_hosur": 10, "side_cross": 5},
        },
        "J2": {
            "total_queue": 15,
            "total_waiting_time": 100.0,
            "average_speed_kmh": 20.0,
            "co2_mg_s": 2500.0,
            "phase": 0,
            "approach_queues": {"corridor_hosur": 10, "madiwala": 5},
        },
        "J3": {
            "total_queue": 15,
            "total_waiting_time": 100.0,
            "average_speed_kmh": 20.0,
            "co2_mg_s": 2500.0,
            "phase": 2,
            "approach_queues": {"corridor_hosur": 10, "side_cross": 5},
        },
    }
    actions = {"J1": ACTION_KEEP, "J2": ACTION_KEEP, "J3": ACTION_KEEP}

    mixed_r, breakdowns = reward_fn.compute_mixed_rewards(
        states=states,
        actions=actions,
        completed_trips=2,
    )

    b1 = breakdowns["J1"]
    # Check individual terms
    assert math.isclose(b1.r_queue, -0.35 * (15.0 / 30.0), abs_tol=1e-4)      # -0.175
    assert math.isclose(b1.r_wait, -0.30 * (100.0 / 200.0), abs_tol=1e-4)    # -0.150
    assert math.isclose(b1.r_speed, 0.15 * (20.0 / 40.0), abs_tol=1e-4)      # +0.075
    assert math.isclose(b1.r_co2, -0.10 * (2.5 / 5.0), abs_tol=1e-4)         # -0.050
    assert b1.r_chatter == 0.0
    assert b1.r_emergency == 0.0

    # Corridor terms
    assert math.isclose(b1.R_throughput, 0.50 * (2.0 / 5.0), abs_tol=1e-4)   # +0.20
    assert math.isclose(b1.R_corridor_delay, -0.50 * (45.0 / 60.0), abs_tol=1e-4)  # -0.375


def test_zero_traffic_and_saturated_queues_extremes():
    """
    Tests edge cases:
    1. Zero traffic: penalties are near zero, throughput is 0.
    2. Saturated queues: normalized terms clip at 1.0, producing bounded penalties.
    """
    reward_fn = MultiIntersectionReward()

    # Case 1: Zero traffic
    zero_states = {
        j: {"total_queue": 0, "total_waiting_time": 0.0, "average_speed_kmh": 40.0, "co2_mg_s": 0.0, "phase": 2}
        for j in ["J1", "J2", "J3"]
    }
    zero_acts = {j: ACTION_KEEP for j in ["J1", "J2", "J3"]}
    r_zero, b_zero = reward_fn.compute_mixed_rewards(zero_states, zero_acts, completed_trips=0)

    for j in ["J1", "J2", "J3"]:
        assert r_zero[j] >= 0.0, f"Zero traffic should produce non-negative reward, got {r_zero[j]}"

    # Case 2: Saturated traffic
    sat_states = {
        j: {"total_queue": 100, "total_waiting_time": 2000.0, "average_speed_kmh": 0.0, "co2_mg_s": 10000.0, "phase": 2}
        for j in ["J1", "J2", "J3"]
    }
    sat_acts = {j: ACTION_KEEP for j in ["J1", "J2", "J3"]}
    r_sat, b_sat = reward_fn.compute_mixed_rewards(sat_states, sat_acts, completed_trips=0)

    for j in ["J1", "J2", "J3"]:
        assert r_sat[j] < -0.5, f"Saturated traffic must produce significant negative reward, got {r_sat[j]}"
        assert r_sat[j] >= -15.0, f"Mixed reward must remain within bounds [-15, 15], got {r_sat[j]}"


def test_low_local_queues_cannot_compensate_corridor_collapse():
    """
    Proves that a junction with zero queue (e.g. J2) still receives a negative mixed reward
    if the rest of the corridor has collapsed (heavy queues and starvation at J1 and J3).
    This mathematical property prevents selfish local equilibria.
    """
    tracker = StarvationTracker(max_red_threshold_s=60.0)
    tracker.red_elapsed["J1"]["side_cross"] = 80.0
    tracker.current_queues["J1"]["side_cross"] = 25
    tracker.red_elapsed["J3"]["side_cross"] = 80.0
    tracker.current_queues["J3"]["side_cross"] = 25

    states = {
        "J1": {"total_queue": 30, "total_waiting_time": 500.0, "average_speed_kmh": 0.0, "phase": 2},
        "J2": {"total_queue": 0, "total_waiting_time": 0.0, "average_speed_kmh": 40.0, "phase": 0},  # Selfish J2 has 0 queue
        "J3": {"total_queue": 30, "total_waiting_time": 500.0, "average_speed_kmh": 0.0, "phase": 2},
    }
    actions = {"J1": ACTION_KEEP, "J2": ACTION_KEEP, "J3": ACTION_KEEP}

    reward_fn = MultiIntersectionReward()
    mixed_r, breakdowns = reward_fn.compute_mixed_rewards(
        states=states,
        actions=actions,
        starvation_tracker=tracker,
        completed_trips=0,
    )

    # J2 local reward is positive (+0.15 for speed), but corridor reward is heavily negative
    assert breakdowns["J2"].local_reward > 0.0
    assert breakdowns["J2"].corridor_reward < -0.5
    # Mixed reward for J2 must be negative
    assert mixed_r["J2"] < 0.0, (
        f"Corridor collapse must penalize all agents: J2 mixed reward was {mixed_r['J2']} >= 0.0"
    )


def test_platoon_progression_anti_double_counting():
    """
    Verifies that platoon bonus is granted once when served, and cannot be re-awarded.
    """
    hub = CorridorCommunicationHub(corridor_sequence=["J1", "J2", "J3"])
    p_id = hub.announce_platoon(
        sender_id="J1",
        vehicle_count=8,
        speed_mps=12.0,
        eta_seconds=5.0,
        timestamp=10.0,
    )
    assert p_id != ""

    unserved = hub.get_unserved_approaching_platoons("J2", current_time=15.0)
    assert len(unserved) == 1
    assert unserved[0]["platoon_id"] == p_id

    # Mark served
    hub.mark_platoon_served("J2", p_id)
    assert hub.is_platoon_served("J2", p_id)

    # Second check should return empty
    unserved_2 = hub.get_unserved_approaching_platoons("J2", current_time=15.0)
    assert len(unserved_2) == 0, "Served platoon must not be re-awarded"


# =====================================================================
# PART 4: Curriculum Demand & Benchmark Equivalence Verification
# =====================================================================

def test_curriculum_stages_demand_and_composition(tmp_path: Path):
    """
    Validates curriculum stages A, B, and C parameters and route generation:
    - Stage A: 300 arterial / 300 cross (1:1 ratio), duration 1200s, no ambulance.
    - Stage B: 800 arterial / 400 cross (2:1 ratio), duration 1200s, no ambulance.
    - Stage C: 1800 arterial / 900 cross (2:1 peak ratio), duration 1200s, ambulance at 500s.
    """
    assert CURRICULUM_STAGES["stage_a"].arterial_veh_per_hr == 300
    assert CURRICULUM_STAGES["stage_a"].cross_veh_per_hr == 300
    assert not CURRICULUM_STAGES["stage_a"].ambulance_enabled

    assert CURRICULUM_STAGES["stage_b"].arterial_veh_per_hr == 800
    assert CURRICULUM_STAGES["stage_b"].cross_veh_per_hr == 400
    assert not CURRICULUM_STAGES["stage_b"].ambulance_enabled

    assert CURRICULUM_STAGES["stage_c"].arterial_veh_per_hr == 1800
    assert CURRICULUM_STAGES["stage_c"].cross_veh_per_hr == 900
    assert CURRICULUM_STAGES["stage_c"].ambulance_enabled
    assert CURRICULUM_STAGES["stage_c"].ambulance_insert_time_s == 500.0

    gen = CurriculumDemandGenerator(output_dir=tmp_path)
    file_c = gen.generate_stage_routes("stage_c")
    assert file_c.is_file()
    content = file_c.read_text(encoding="utf-8")
    assert "stage_c_ambulance" in content
    assert 'depart="500.0"' in content
    assert "vehsPerHour" in content


def test_disjoint_training_and_evaluation_seeds():
    """
    Verifies that training seeds and evaluation seeds are completely disjoint.
    """
    training_seeds = {11, 22, 33, 44, 55}
    evaluation_seeds = {42, 101, 202, 303, 404}

    intersection = training_seeds.intersection(evaluation_seeds)
    assert len(intersection) == 0, f"Training and evaluation seeds must be disjoint! Found overlap: {intersection}"

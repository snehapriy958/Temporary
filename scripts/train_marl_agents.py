"""
scripts/train_marl_agents.py

Controlled Multi-Episode Training Harness for Stage P4 Validation.
Trains Coordinated Double-DQN and Actor-Critic PPO agents on the
Bengaluru Silk Board SUMO corridor with full autograd backpropagation.

Outputs:
- checkpoints/marl_dqn_corridor_v2.json
- checkpoints/marl_ppo_corridor_v2.json
- checkpoints/marl_training_validation_p4.json
"""

from __future__ import annotations

import json
import logging
import random
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

# Ensure project root is in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import numpy as np
import torch

from traffic_service.ai.env import (
    ACTION_NAMES,
    CorridorObservationSpace,
    MultiIntersectionReward,
    RewardWeights,
)
from traffic_service.ai.marl_controller import MARLCorridorController
from traffic_service.multi_intersection_simulation import MultiIntersectionSimulation

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("TrainMARL")

SUMO_CONFIG = BASE_DIR / "sumo" / "silk_board" / "silk_board.sumocfg"
CHECKPOINTS_DIR = BASE_DIR / "checkpoints"
CHECKPOINTS_DIR.mkdir(parents=True, exist_ok=True)


def train_dqn_corridor(
    num_episodes: int = 5,
    episode_duration: float = 60.0,
    decision_interval: float = 5.0,
    base_seed: int = 42,
) -> Dict[str, Any]:
    """Runs controlled multi-episode training for Double-DQN agents across J1, J2, J3."""
    logger.info("=" * 70)
    logger.info(f"STARTING CONTROLLED DOUBLE-DQN TRAINING ({num_episodes} EPISODES, SEED={base_seed})")
    logger.info("=" * 70)

    # Set deterministic seeds
    random.seed(base_seed)
    np.random.seed(base_seed)
    torch.manual_seed(base_seed)

    # Initialize un-checkpointed MARL controller for training
    marl = MARLCorridorController(
        algorithm="dqn",
        junctions=["J1", "J2", "J3"],
        seed=base_seed,
    )
    # Set learning rates & exploration parameters
    for j_id, agent in marl.agents.items():
        agent.lr = 0.001
        agent.epsilon = 0.8
        agent.epsilon_decay = 0.95
        agent.epsilon_min = 0.05
        agent.target_update_interval = 10

    reward_fn = MultiIntersectionReward(RewardWeights())
    obs_space = CorridorObservationSpace()

    episode_records: List[Dict[str, Any]] = []

    for ep in range(1, num_episodes + 1):
        ep_seed = base_seed + ep * 10
        reward_fn.reset()
        ep_rewards = {j: 0.0 for j in ["J1", "J2", "J3"]}
        ep_td_losses = []
        ep_grad_norms = []

        sim = MultiIntersectionSimulation(
            sumocfg_path=SUMO_CONFIG,
            mode="coordinated",
            gui=False,
            step_length=1.0,
            decision_interval=decision_interval,
        )
        # Wire controllers to MARL
        marl.controllers = sim.controllers
        marl.hub = sim.hub

        sim.start(seed=ep_seed)
        sim_time = 0.0
        step_idx = 0

        # Initial observation
        raw_obs = sim.get_ai_observations(sim.get_states(sim_time))
        prev_vecs = {j: obs_space.vectorize_junction(j, raw_obs[j]) for j in ["J1", "J2", "J3"]}

        try:
            while sim_time < episode_duration:
                # 1. Decide actions with exploration (eval_mode=False)
                decisions = marl.decide(raw_obs, sim_time=sim_time, eval_mode=False)
                # Apply decisions
                marl.apply_decisions(decisions, sim_time)

                # 2. Advance simulation by decision_interval seconds
                for _ in range(int(decision_interval)):
                    states, ok = sim.step()
                    if not ok:
                        break
                sim_time = sim.sumo_manager.get_time()
                step_idx += 1

                # 3. New observations & rewards
                raw_obs_next = sim.get_ai_observations(states)
                next_vecs = {j: obs_space.vectorize_junction(j, raw_obs_next[j]) for j in ["J1", "J2", "J3"]}

                is_done = (sim_time >= episode_duration)

                # 4. Store transitions & update DQN for each junction
                for j_id, agent in marl.agents.items():
                    act = decisions[j_id]["action"]
                    r_j = reward_fn.compute_junction_reward(
                        j_id=j_id,
                        state=raw_obs_next[j_id],
                        action=act,
                        emergency_stopped=False,
                    )
                    ep_rewards[j_id] += r_j

                    agent.replay_buffer.push(
                        state=prev_vecs[j_id],
                        action=act,
                        reward=r_j,
                        next_state=next_vecs[j_id],
                        done=is_done,
                    )

                    # Train step if enough samples
                    if len(agent.replay_buffer) >= 16:
                        td_loss = agent.train_step(batch_size=16)
                        ep_td_losses.append(td_loss)

                        # Capture maximum gradient norm across layers
                        max_gn = max(
                            param.grad.norm().item()
                            for param in agent.q_network.parameters()
                            if param.grad is not None
                        )
                        ep_grad_norms.append(max_gn)

                prev_vecs = next_vecs
                raw_obs = raw_obs_next

            # Episode summary
            summary = sim.metrics_collector.compute_summary()
            ep_rec = {
                "episode": ep,
                "seed": ep_seed,
                "duration_s": summary.simulation_duration,
                "mean_reward": float(np.mean(list(ep_rewards.values()))),
                "rewards_by_junction": {j: float(r) for j, r in ep_rewards.items()},
                "mean_td_loss": float(np.mean(ep_td_losses)) if ep_td_losses else 0.0,
                "mean_max_grad_norm": float(np.mean(ep_grad_norms)) if ep_grad_norms else 0.0,
                "epsilon": float(marl.agents["J2"].epsilon),
                "completed_trips": summary.total_corridor_trips_completed,
                "average_queue": summary.mean_corridor_queue,
                "cumulative_delay_veh_s": summary.cumulative_delay_veh_s,
                "average_travel_time_s": summary.mean_corridor_travel_time_s,
                "total_fuel_liters": summary.total_fuel_liters,
                "total_co2_kg": summary.total_co2_kg,
            }
            episode_records.append(ep_rec)
            logger.info(
                f"[DQN EP {ep}/{num_episodes}] Seed={ep_seed} | MeanReward={ep_rec['mean_reward']:.2f} | "
                f"TDLoss={ep_rec['mean_td_loss']:.4f} | GradNorm={ep_rec['mean_max_grad_norm']:.4f} | "
                f"Eps={ep_rec['epsilon']:.3f} | Trips={ep_rec['completed_trips']} | "
                f"AvgQueue={ep_rec['average_queue']:.1f} | Fuel={ep_rec['total_fuel_liters']:.3f}L"
            )

        finally:
            sim.close()

    # Save v2 checkpoint
    v2_ckpt_path = CHECKPOINTS_DIR / "marl_dqn_corridor_v2.json"
    marl.save_checkpoint(v2_ckpt_path, version="2.0-autograd")
    logger.info(f"Saved v2 DQN checkpoint to: {v2_ckpt_path}")

    return {
        "algorithm": "dqn",
        "checkpoint": str(v2_ckpt_path),
        "episodes": episode_records,
    }


def train_ppo_corridor(
    num_episodes: int = 5,
    episode_duration: float = 60.0,
    decision_interval: float = 5.0,
    base_seed: int = 43,
) -> Dict[str, Any]:
    """Runs controlled multi-episode training for Actor-Critic PPO agents across J1, J2, J3."""
    logger.info("=" * 70)
    logger.info(f"STARTING CONTROLLED ACTOR-CRITIC PPO TRAINING ({num_episodes} EPISODES, SEED={base_seed})")
    logger.info("=" * 70)

    random.seed(base_seed)
    np.random.seed(base_seed)
    torch.manual_seed(base_seed)

    marl = MARLCorridorController(
        algorithm="ppo",
        junctions=["J1", "J2", "J3"],
        seed=base_seed,
    )
    for j_id, agent in marl.agents.items():
        agent.lr = 0.0005
        agent.clip_ratio = 0.2
        agent.entropy_coef = 0.02
        agent.value_loss_coef = 0.5

    reward_fn = MultiIntersectionReward(RewardWeights())
    obs_space = CorridorObservationSpace()

    episode_records: List[Dict[str, Any]] = []

    for ep in range(1, num_episodes + 1):
        ep_seed = base_seed + ep * 10
        reward_fn.reset()
        ep_rewards = {j: 0.0 for j in ["J1", "J2", "J3"]}
        ep_policy_losses = []
        ep_value_losses = []
        ep_entropies = []
        ep_grad_norms = []

        sim = MultiIntersectionSimulation(
            sumocfg_path=SUMO_CONFIG,
            mode="coordinated",
            gui=False,
            step_length=1.0,
            decision_interval=decision_interval,
        )
        marl.controllers = sim.controllers
        marl.hub = sim.hub

        sim.start(seed=ep_seed)
        sim_time = 0.0
        step_idx = 0

        raw_obs = sim.get_ai_observations(sim.get_states(sim_time))
        prev_vecs = {j: obs_space.vectorize_junction(j, raw_obs[j]) for j in ["J1", "J2", "J3"]}

        try:
            while sim_time < episode_duration:
                # 1. Decide actions with stochastic sampling (eval_mode=False)
                decisions = marl.decide(raw_obs, sim_time=sim_time, eval_mode=False)
                marl.apply_decisions(decisions, sim_time)

                # 2. Advance simulation
                for _ in range(int(decision_interval)):
                    states, ok = sim.step()
                    if not ok:
                        break
                sim_time = sim.sumo_manager.get_time()
                step_idx += 1

                # 3. New observations & rewards
                raw_obs_next = sim.get_ai_observations(states)
                next_vecs = {j: obs_space.vectorize_junction(j, raw_obs_next[j]) for j in ["J1", "J2", "J3"]}
                is_done = (sim_time >= episode_duration)

                # 4. Store transitions in PPO buffer
                for j_id, agent in marl.agents.items():
                    act = decisions[j_id]["action"]
                    val = decisions[j_id].get("value", 0.0)
                    lp = decisions[j_id].get("log_prob", 0.0)

                    r_j = reward_fn.compute_junction_reward(
                        j_id=j_id,
                        state=raw_obs_next[j_id],
                        action=act,
                        emergency_stopped=False,
                    )
                    ep_rewards[j_id] += r_j

                    agent.store_transition(
                        state=prev_vecs[j_id],
                        action=act,
                        reward=r_j,
                        value=val,
                        log_prob=lp,
                        done=is_done,
                    )

                prev_vecs = next_vecs
                raw_obs = raw_obs_next

            # 5. PPO Update at end of episode trajectory rollout
            for j_id, agent in marl.agents.items():
                last_v = agent.get_value(next_vecs[j_id])
                p_metrics = agent.train_step(last_value=last_v, epochs=4, minibatch_size=16)
                ep_policy_losses.append(p_metrics.get("policy_loss", 0.0))
                ep_value_losses.append(p_metrics.get("value_loss", 0.0))
                ep_entropies.append(p_metrics.get("entropy", 0.0))

                max_gn = max(
                    param.grad.norm().item()
                    for param in agent.ac_network.parameters()
                    if param.grad is not None
                )
                ep_grad_norms.append(max_gn)

            summary = sim.metrics_collector.compute_summary()
            ep_rec = {
                "episode": ep,
                "seed": ep_seed,
                "duration_s": summary.simulation_duration,
                "mean_reward": float(np.mean(list(ep_rewards.values()))),
                "rewards_by_junction": {j: float(r) for j, r in ep_rewards.items()},
                "mean_policy_loss": float(np.mean(ep_policy_losses)),
                "mean_value_loss": float(np.mean(ep_value_losses)),
                "mean_entropy": float(np.mean(ep_entropies)),
                "mean_max_grad_norm": float(np.mean(ep_grad_norms)),
                "completed_trips": summary.total_corridor_trips_completed,
                "average_queue": summary.mean_corridor_queue,
                "cumulative_delay_veh_s": summary.cumulative_delay_veh_s,
                "average_travel_time_s": summary.mean_corridor_travel_time_s,
                "total_fuel_liters": summary.total_fuel_liters,
                "total_co2_kg": summary.total_co2_kg,
            }
            episode_records.append(ep_rec)
            logger.info(
                f"[PPO EP {ep}/{num_episodes}] Seed={ep_seed} | MeanReward={ep_rec['mean_reward']:.2f} | "
                f"PolLoss={ep_rec['mean_policy_loss']:.4f} | ValLoss={ep_rec['mean_value_loss']:.4f} | "
                f"Entropy={ep_rec['mean_entropy']:.4f} | GradNorm={ep_rec['mean_max_grad_norm']:.4f} | "
                f"Trips={ep_rec['completed_trips']} | AvgQueue={ep_rec['average_queue']:.1f} | "
                f"Fuel={ep_rec['total_fuel_liters']:.3f}L"
            )

        finally:
            sim.close()

    v2_ckpt_path = CHECKPOINTS_DIR / "marl_ppo_corridor_v2.json"
    marl.save_checkpoint(v2_ckpt_path, version="2.0-autograd")
    logger.info(f"Saved v2 PPO checkpoint to: {v2_ckpt_path}")

    return {
        "algorithm": "ppo",
        "checkpoint": str(v2_ckpt_path),
        "episodes": episode_records,
    }


def validate_checkpoints() -> Dict[str, Any]:
    """Validates newly generated v2 checkpoints against fresh agent instances."""
    logger.info("=" * 70)
    logger.info("VALIDATING CHECKPOINTS V2 (FRESH INSTANTIATION & INFERENCE)")
    logger.info("=" * 70)

    val_results = {}

    for algo in ["dqn", "ppo"]:
        ckpt_path = CHECKPOINTS_DIR / f"marl_{algo}_corridor_v2.json"
        assert ckpt_path.is_file(), f"Expected checkpoint file does not exist: {ckpt_path}"

        with open(ckpt_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert data["algorithm"] == algo
        assert data["algorithm_version"] == "2.0-autograd"
        assert set(data["junctions"]) == {"J1", "J2", "J3"}

        # Fresh controller instantiation
        ctrl = MARLCorridorController(algorithm=algo)
        loaded = ctrl.load_checkpoint(ckpt_path)
        assert loaded, f"Failed to load checkpoint into fresh controller for {algo}"

        # Verify all 3 agents loaded
        assert set(ctrl.agents.keys()) == {"J1", "J2", "J3"}

        # Test forward inference on synthetic observation
        test_obs = {
            j_id: {
                "phase": 0,
                "phase_elapsed": 20.0,
                "time_to_switch": 15.0,
                "approach_queues": {"corridor_hosur": 5},
                "total_queue": 10,
                "average_speed_kmh": 25.0,
                "total_waiting_time": 30.0,
                "vehicle_count": 12,
                "upstream_expected_inflow": 0.4,
                "approaching_platoons_count": 1,
                "co2_mg_s": 80.0,
                "emergency_approaching": False,
            }
            for j_id in ["J1", "J2", "J3"]
        }
        decisions = ctrl.decide(test_obs, sim_time=20.0, eval_mode=True)
        assert len(decisions) == 3
        for j_id in ["J1", "J2", "J3"]:
            assert decisions[j_id]["action"] in (0, 1, 2)
            assert not decisions[j_id]["is_fallback"]

        logger.info(f"[VALIDATION] {algo.upper()} v2 Checkpoint passed fresh load & inference check.")
        val_results[algo] = {
            "checkpoint": str(ckpt_path),
            "version": data["algorithm_version"],
            "saved_at": data["saved_at"],
            "junctions_verified": list(ctrl.agents.keys()),
            "decisions": {j: decisions[j]["action_name"] for j in ["J1", "J2", "J3"]},
        }

    return val_results


def main():
    start_time = time.time()
    dqn_results = train_dqn_corridor(num_episodes=5, episode_duration=60.0, base_seed=42)
    ppo_results = train_ppo_corridor(num_episodes=5, episode_duration=60.0, base_seed=43)
    val_results = validate_checkpoints()

    full_log = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_duration_s": time.time() - start_time,
        "dqn_training": dqn_results,
        "ppo_training": ppo_results,
        "checkpoint_validation": val_results,
    }

    log_path = CHECKPOINTS_DIR / "marl_training_validation_p4.json"
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(full_log, f, indent=2)

    logger.info("=" * 70)
    logger.info(f"STAGE P4 TRAINING & VALIDATION COMPLETE. Log saved to: {log_path}")
    logger.info("=" * 70)


if __name__ == "__main__":
    main()

"""
scripts/train_marl_p5_multiseed.py

Stage P5 Multi-Seed Training Harness for Double-DQN and Actor-Critic PPO.
Trains on Bengaluru Silk Board SUMO corridor across multiple deterministic seeds.

Outputs:
- checkpoints/p5_training/dqn_seed{seed}_final.json
- checkpoints/p5_training/ppo_seed{seed}_final.json
- checkpoints/marl_dqn_corridor_p5.json
- checkpoints/marl_ppo_corridor_p5.json
- results/p5/p5_training_curves.json
- results/p5/p5_training_curves.csv
"""

from __future__ import annotations

import csv
import json
import logging
import random
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import numpy as np
import torch

from traffic_service.ai.env import CorridorObservationSpace, MultiIntersectionReward, RewardWeights
from traffic_service.ai.marl_controller import MARLCorridorController
from traffic_service.multi_intersection_simulation import MultiIntersectionSimulation

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("TrainP5MultiSeed")

SUMO_CONFIG = BASE_DIR / "sumo" / "silk_board" / "silk_board.sumocfg"
P5_CKPT_DIR = BASE_DIR / "checkpoints" / "p5_training"
P5_CKPT_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR = BASE_DIR / "results" / "p5"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# Training configurations: 3 disjoint seeds, 15 episodes each, 120s duration
TRAIN_SEEDS = [42, 84, 126]
EPISODES_PER_SEED = 15
EPISODE_DURATION_S = 120.0
DECISION_INTERVAL_S = 5.0


def train_dqn_multiseed() -> Dict[str, Any]:
    logger.info("=" * 75)
    logger.info("STAGE P5: COMMENCING MULTI-SEED DOUBLE-DQN TRAINING")
    logger.info(f"Seeds: {TRAIN_SEEDS} | Episodes/seed: {EPISODES_PER_SEED} | Horizon: {EPISODE_DURATION_S}s")
    logger.info("=" * 75)

    all_seed_results = []
    all_flat_rows = []
    final_controller = None

    obs_space = CorridorObservationSpace()
    reward_fn = MultiIntersectionReward(RewardWeights())

    for s_idx, base_seed in enumerate(TRAIN_SEEDS, 1):
        logger.info(f"--- Starting DQN Training Run {s_idx}/{len(TRAIN_SEEDS)} [Base Seed={base_seed}] ---")
        random.seed(base_seed)
        np.random.seed(base_seed)
        torch.manual_seed(base_seed)

        marl = MARLCorridorController(
            algorithm="dqn",
            junctions=["J1", "J2", "J3"],
            seed=base_seed,
        )
        for j_id, agent in marl.agents.items():
            agent.lr = 0.001
            agent.epsilon = 0.8
            agent.epsilon_decay = 0.95
            agent.epsilon_min = 0.05
            agent.target_update_interval = 12

        seed_episodes = []

        for ep in range(1, EPISODES_PER_SEED + 1):
            ep_sim_seed = base_seed * 1000 + ep * 7
            reward_fn.reset()
            ep_rewards = {j: 0.0 for j in ["J1", "J2", "J3"]}
            ep_td_losses = []
            ep_grad_norms = []

            sim = MultiIntersectionSimulation(
                sumocfg_path=SUMO_CONFIG,
                mode="coordinated",
                gui=False,
                step_length=1.0,
                decision_interval=DECISION_INTERVAL_S,
            )
            marl.controllers = sim.controllers
            marl.hub = sim.hub

            sim.start(seed=ep_sim_seed)
            sim_time = 0.0

            raw_obs = sim.get_ai_observations(sim.get_states(sim_time))
            prev_vecs = {j: obs_space.vectorize_junction(j, raw_obs[j]) for j in ["J1", "J2", "J3"]}

            try:
                while sim_time < EPISODE_DURATION_S:
                    decisions = marl.decide(raw_obs, sim_time=sim_time, eval_mode=False)
                    marl.apply_decisions(decisions, sim_time)

                    for _ in range(int(DECISION_INTERVAL_S)):
                        states, ok = sim.step()
                        if not ok:
                            break
                    sim_time = sim.sumo_manager.get_time()

                    raw_obs_next = sim.get_ai_observations(states)
                    next_vecs = {j: obs_space.vectorize_junction(j, raw_obs_next[j]) for j in ["J1", "J2", "J3"]}
                    is_done = (sim_time >= EPISODE_DURATION_S)

                    for j_id, agent in marl.agents.items():
                        act = decisions[j_id]["action"]
                        r_j = reward_fn.compute_junction_reward(
                            j_id=j_id, state=raw_obs_next[j_id], action=act, emergency_stopped=False
                        )
                        ep_rewards[j_id] += r_j

                        agent.replay_buffer.push(prev_vecs[j_id], act, r_j, next_vecs[j_id], is_done)

                        if len(agent.replay_buffer) >= 16:
                            td_loss = agent.train_step(batch_size=16)
                            ep_td_losses.append(td_loss)
                            max_gn = max(p.grad.norm().item() for p in agent.q_network.parameters() if p.grad is not None)
                            ep_grad_norms.append(max_gn)

                    prev_vecs = next_vecs
                    raw_obs = raw_obs_next

                summary = sim.metrics_collector.compute_summary()
                rec = {
                    "algorithm": "dqn",
                    "train_seed": base_seed,
                    "episode": ep,
                    "sim_seed": ep_sim_seed,
                    "mean_reward": float(np.mean(list(ep_rewards.values()))),
                    "td_loss": float(np.mean(ep_td_losses)) if ep_td_losses else 0.0,
                    "policy_loss": 0.0,
                    "value_loss": 0.0,
                    "entropy": 0.0,
                    "epsilon": float(marl.agents["J2"].epsilon),
                    "max_grad_norm": float(np.mean(ep_grad_norms)) if ep_grad_norms else 0.0,
                    "completed_trips": summary.total_corridor_trips_completed,
                    "average_queue": summary.mean_corridor_queue,
                    "cumulative_delay_veh_s": summary.cumulative_delay_veh_s,
                    "average_travel_time_s": summary.mean_corridor_travel_time_s,
                    "total_fuel_liters": summary.total_fuel_liters,
                    "total_co2_kg": summary.total_co2_kg,
                }
                seed_episodes.append(rec)
                all_flat_rows.append(rec)

                logger.info(
                    f"[DQN Seed {base_seed} | Ep {ep}/{EPISODES_PER_SEED}] Reward={rec['mean_reward']:.2f} | "
                    f"TDLoss={rec['td_loss']:.4f} | Eps={rec['epsilon']:.3f} | "
                    f"GradNorm={rec['max_grad_norm']:.4f} | Queue={rec['average_queue']:.1f} | "
                    f"Delay={rec['cumulative_delay_veh_s']:.0f}s | Fuel={rec['total_fuel_liters']:.3f}L"
                )

            finally:
                sim.close()

        # Save per-seed checkpoint
        seed_ckpt_path = P5_CKPT_DIR / f"dqn_seed{base_seed}_final.json"
        marl.save_checkpoint(seed_ckpt_path, version="5.0-multiseed")
        logger.info(f"Saved seed checkpoint: {seed_ckpt_path}")

        all_seed_results.append({
            "train_seed": base_seed,
            "episodes": seed_episodes,
            "checkpoint": str(seed_ckpt_path),
        })
        final_controller = marl

    # Save canonical P5 DQN checkpoint
    canonical_ckpt = BASE_DIR / "checkpoints" / "marl_dqn_corridor_p5.json"
    final_controller.save_checkpoint(canonical_ckpt, version="5.0-autograd-multiseed")
    logger.info(f"Saved canonical P5 DQN checkpoint: {canonical_ckpt}")

    return {
        "algorithm": "dqn",
        "canonical_checkpoint": str(canonical_ckpt),
        "seed_results": all_seed_results,
        "flat_rows": all_flat_rows,
    }


def train_ppo_multiseed() -> Dict[str, Any]:
    logger.info("=" * 75)
    logger.info("STAGE P5: COMMENCING MULTI-SEED ACTOR-CRITIC PPO TRAINING")
    logger.info(f"Seeds: {TRAIN_SEEDS} | Episodes/seed: {EPISODES_PER_SEED} | Horizon: {EPISODE_DURATION_S}s")
    logger.info("=" * 75)

    all_seed_results = []
    all_flat_rows = []
    final_controller = None

    obs_space = CorridorObservationSpace()
    reward_fn = MultiIntersectionReward(RewardWeights())

    for s_idx, base_seed in enumerate(TRAIN_SEEDS, 1):
        logger.info(f"--- Starting PPO Training Run {s_idx}/{len(TRAIN_SEEDS)} [Base Seed={base_seed}] ---")
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

        seed_episodes = []

        for ep in range(1, EPISODES_PER_SEED + 1):
            ep_sim_seed = base_seed * 1000 + ep * 7
            reward_fn.reset()
            ep_rewards = {j: 0.0 for j in ["J1", "J2", "J3"]}
            ep_pol_losses = []
            ep_val_losses = []
            ep_entropies = []
            ep_grad_norms = []

            sim = MultiIntersectionSimulation(
                sumocfg_path=SUMO_CONFIG,
                mode="coordinated",
                gui=False,
                step_length=1.0,
                decision_interval=DECISION_INTERVAL_S,
            )
            marl.controllers = sim.controllers
            marl.hub = sim.hub

            sim.start(seed=ep_sim_seed)
            sim_time = 0.0

            raw_obs = sim.get_ai_observations(sim.get_states(sim_time))
            prev_vecs = {j: obs_space.vectorize_junction(j, raw_obs[j]) for j in ["J1", "J2", "J3"]}

            try:
                while sim_time < EPISODE_DURATION_S:
                    decisions = marl.decide(raw_obs, sim_time=sim_time, eval_mode=False)
                    marl.apply_decisions(decisions, sim_time)

                    for _ in range(int(DECISION_INTERVAL_S)):
                        states, ok = sim.step()
                        if not ok:
                            break
                    sim_time = sim.sumo_manager.get_time()

                    raw_obs_next = sim.get_ai_observations(states)
                    next_vecs = {j: obs_space.vectorize_junction(j, raw_obs_next[j]) for j in ["J1", "J2", "J3"]}
                    is_done = (sim_time >= EPISODE_DURATION_S)

                    for j_id, agent in marl.agents.items():
                        act = decisions[j_id]["action"]
                        val = decisions[j_id].get("value", 0.0)
                        lp = decisions[j_id].get("log_prob", 0.0)

                        r_j = reward_fn.compute_junction_reward(
                            j_id=j_id, state=raw_obs_next[j_id], action=act, emergency_stopped=False
                        )
                        ep_rewards[j_id] += r_j

                        agent.store_transition(prev_vecs[j_id], act, r_j, val, lp, is_done)

                    prev_vecs = next_vecs
                    raw_obs = raw_obs_next

                # End of episode trajectory update
                for j_id, agent in marl.agents.items():
                    last_v = agent.get_value(next_vecs[j_id])
                    p_metrics = agent.train_step(last_value=last_v, epochs=4, minibatch_size=16)
                    ep_pol_losses.append(p_metrics.get("policy_loss", 0.0))
                    ep_val_losses.append(p_metrics.get("value_loss", 0.0))
                    ep_entropies.append(p_metrics.get("entropy", 0.0))

                    max_gn = max(p.grad.norm().item() for p in agent.ac_network.parameters() if p.grad is not None)
                    ep_grad_norms.append(max_gn)

                summary = sim.metrics_collector.compute_summary()
                rec = {
                    "algorithm": "ppo",
                    "train_seed": base_seed,
                    "episode": ep,
                    "sim_seed": ep_sim_seed,
                    "mean_reward": float(np.mean(list(ep_rewards.values()))),
                    "td_loss": 0.0,
                    "policy_loss": float(np.mean(ep_pol_losses)),
                    "value_loss": float(np.mean(ep_val_losses)),
                    "entropy": float(np.mean(ep_entropies)),
                    "epsilon": 0.0,
                    "max_grad_norm": float(np.mean(ep_grad_norms)),
                    "completed_trips": summary.total_corridor_trips_completed,
                    "average_queue": summary.mean_corridor_queue,
                    "cumulative_delay_veh_s": summary.cumulative_delay_veh_s,
                    "average_travel_time_s": summary.mean_corridor_travel_time_s,
                    "total_fuel_liters": summary.total_fuel_liters,
                    "total_co2_kg": summary.total_co2_kg,
                }
                seed_episodes.append(rec)
                all_flat_rows.append(rec)

                logger.info(
                    f"[PPO Seed {base_seed} | Ep {ep}/{EPISODES_PER_SEED}] Reward={rec['mean_reward']:.2f} | "
                    f"PolLoss={rec['policy_loss']:.4f} | ValLoss={rec['value_loss']:.4f} | "
                    f"Entropy={rec['entropy']:.4f} | GradNorm={rec['max_grad_norm']:.4f} | "
                    f"Queue={rec['average_queue']:.1f} | Delay={rec['cumulative_delay_veh_s']:.0f}s | "
                    f"Fuel={rec['total_fuel_liters']:.3f}L"
                )

            finally:
                sim.close()

        seed_ckpt_path = P5_CKPT_DIR / f"ppo_seed{base_seed}_final.json"
        marl.save_checkpoint(seed_ckpt_path, version="5.0-multiseed")
        logger.info(f"Saved seed checkpoint: {seed_ckpt_path}")

        all_seed_results.append({
            "train_seed": base_seed,
            "episodes": seed_episodes,
            "checkpoint": str(seed_ckpt_path),
        })
        final_controller = marl

    canonical_ckpt = BASE_DIR / "checkpoints" / "marl_ppo_corridor_p5.json"
    final_controller.save_checkpoint(canonical_ckpt, version="5.0-autograd-multiseed")
    logger.info(f"Saved canonical P5 PPO checkpoint: {canonical_ckpt}")

    return {
        "algorithm": "ppo",
        "canonical_checkpoint": str(canonical_ckpt),
        "seed_results": all_seed_results,
        "flat_rows": all_flat_rows,
    }


def main():
    start_time = time.time()
    dqn_res = train_dqn_multiseed()
    ppo_res = train_ppo_multiseed()
    elapsed = time.time() - start_time

    # Save complete JSON training curves
    training_data = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_training_wall_time_s": elapsed,
        "train_seeds": TRAIN_SEEDS,
        "episodes_per_seed": EPISODES_PER_SEED,
        "episode_duration_s": EPISODE_DURATION_S,
        "decision_interval_s": DECISION_INTERVAL_S,
        "dqn": dqn_res,
        "ppo": ppo_res,
    }
    json_path = RESULTS_DIR / "p5_training_curves.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(training_data, f, indent=2)
    logger.info(f"Saved training curves JSON: {json_path}")

    # Save flat CSV for tabular reporting and curve generation
    csv_path = RESULTS_DIR / "p5_training_curves.csv"
    flat_rows = dqn_res["flat_rows"] + ppo_res["flat_rows"]
    if flat_rows:
        fieldnames = list(flat_rows[0].keys())
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(flat_rows)
        logger.info(f"Saved training curves CSV: {csv_path}")

    logger.info("=" * 75)
    logger.info(f"P5 MULTI-SEED TRAINING COMPLETE in {elapsed:.2f}s (~{elapsed/60:.1f} mins)")
    logger.info("=" * 75)


if __name__ == "__main__":
    main()

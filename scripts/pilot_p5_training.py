"""
scripts/pilot_p5_training.py

Stage P5 Pilot: Fast 3-episode stability check for Double-DQN and Actor-Critic PPO
to verify TraCI lifecycle, gradient tracking, metric recording, and timing before scaling.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import numpy as np
import torch

from traffic_service.ai.env import CorridorObservationSpace, MultiIntersectionReward, RewardWeights
from traffic_service.ai.marl_controller import MARLCorridorController
from traffic_service.multi_intersection_simulation import MultiIntersectionSimulation

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("PilotP5")

SUMO_CONFIG = BASE_DIR / "sumo" / "silk_board" / "silk_board.sumocfg"
PILOT_DIR = BASE_DIR / "checkpoints" / "p5_pilot"
PILOT_DIR.mkdir(parents=True, exist_ok=True)


def run_pilot(algorithm: str, seed: int = 42, num_episodes: int = 3, ep_duration: float = 120.0) -> dict:
    logger.info(f"--- Running Pilot for {algorithm.upper()} (Seed={seed}, Episodes={num_episodes}, Duration={ep_duration}s) ---")
    start_t = time.time()

    torch.manual_seed(seed)
    np.random.seed(seed)

    marl = MARLCorridorController(algorithm=algorithm, junctions=["J1", "J2", "J3"], seed=seed)
    obs_space = CorridorObservationSpace()
    reward_fn = MultiIntersectionReward(RewardWeights())

    ep_logs = []

    for ep in range(1, num_episodes + 1):
        ep_seed = seed + ep * 10
        reward_fn.reset()
        ep_rewards = {j: 0.0 for j in ["J1", "J2", "J3"]}
        ep_losses = []
        ep_grad_norms = []

        sim = MultiIntersectionSimulation(
            sumocfg_path=SUMO_CONFIG,
            mode="coordinated",
            gui=False,
            step_length=1.0,
            decision_interval=5.0,
        )
        marl.controllers = sim.controllers
        marl.hub = sim.hub

        sim.start(seed=ep_seed)
        sim_time = 0.0

        raw_obs = sim.get_ai_observations(sim.get_states(sim_time))
        prev_vecs = {j: obs_space.vectorize_junction(j, raw_obs[j]) for j in ["J1", "J2", "J3"]}

        try:
            while sim_time < ep_duration:
                decisions = marl.decide(raw_obs, sim_time=sim_time, eval_mode=False)
                marl.apply_decisions(decisions, sim_time)

                for _ in range(5):
                    states, ok = sim.step()
                    if not ok:
                        break
                sim_time = sim.sumo_manager.get_time()

                raw_obs_next = sim.get_ai_observations(states)
                next_vecs = {j: obs_space.vectorize_junction(j, raw_obs_next[j]) for j in ["J1", "J2", "J3"]}
                is_done = (sim_time >= ep_duration)

                for j_id, agent in marl.agents.items():
                    act = decisions[j_id]["action"]
                    r_j = reward_fn.compute_junction_reward(
                        j_id=j_id, state=raw_obs_next[j_id], action=act, emergency_stopped=False
                    )
                    ep_rewards[j_id] += r_j

                    if algorithm == "dqn":
                        agent.replay_buffer.push(prev_vecs[j_id], act, r_j, next_vecs[j_id], is_done)
                        if len(agent.replay_buffer) >= 16:
                            td_loss = agent.train_step(batch_size=16)
                            ep_losses.append(td_loss)
                            max_gn = max(p.grad.norm().item() for p in agent.q_network.parameters() if p.grad is not None)
                            ep_grad_norms.append(max_gn)
                    else:  # ppo
                        val = decisions[j_id].get("value", 0.0)
                        lp = decisions[j_id].get("log_prob", 0.0)
                        agent.store_transition(prev_vecs[j_id], act, r_j, val, lp, is_done)

                prev_vecs = next_vecs
                raw_obs = raw_obs_next

            if algorithm == "ppo":
                for j_id, agent in marl.agents.items():
                    last_v = agent.get_value(next_vecs[j_id])
                    p_metrics = agent.train_step(last_value=last_v, epochs=4, minibatch_size=16)
                    ep_losses.append(p_metrics.get("value_loss", 0.0))
                    max_gn = max(p.grad.norm().item() for p in agent.ac_network.parameters() if p.grad is not None)
                    ep_grad_norms.append(max_gn)

            summary = sim.metrics_collector.compute_summary()
            ep_logs.append({
                "episode": ep,
                "seed": ep_seed,
                "mean_reward": float(np.mean(list(ep_rewards.values()))),
                "mean_loss": float(np.mean(ep_losses)) if ep_losses else 0.0,
                "mean_grad_norm": float(np.mean(ep_grad_norms)) if ep_grad_norms else 0.0,
                "completed_trips": summary.total_corridor_trips_completed,
                "average_queue": summary.mean_corridor_queue,
                "cumulative_delay_veh_s": summary.cumulative_delay_veh_s,
                "total_fuel_liters": summary.total_fuel_liters,
            })
            logger.info(
                f"[{algorithm.upper()} Pilot Ep {ep}/{num_episodes}] Reward={ep_logs[-1]['mean_reward']:.2f} | "
                f"Loss={ep_logs[-1]['mean_loss']:.4f} | GradNorm={ep_logs[-1]['mean_grad_norm']:.4f} | "
                f"Queue={ep_logs[-1]['average_queue']:.1f} | Fuel={ep_logs[-1]['total_fuel_liters']:.3f}L"
            )
        finally:
            sim.close()

    ckpt_path = PILOT_DIR / f"pilot_{algorithm}_checkpoint.json"
    marl.save_checkpoint(ckpt_path, version="5.0-pilot")

    total_wall_time = time.time() - start_t
    logger.info(f"[{algorithm.upper()} Pilot] Completed in {total_wall_time:.2f}s ({total_wall_time/num_episodes:.2f}s/episode)")

    return {
        "algorithm": algorithm,
        "wall_time_s": total_wall_time,
        "per_episode_wall_time_s": total_wall_time / num_episodes,
        "episodes": ep_logs,
        "checkpoint": str(ckpt_path),
    }


def main():
    dqn_res = run_pilot("dqn", seed=42, num_episodes=3, ep_duration=120.0)
    ppo_res = run_pilot("ppo", seed=43, num_episodes=3, ep_duration=120.0)

    pilot_summary = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "dqn_pilot": dqn_res,
        "ppo_pilot": ppo_res,
    }
    with open(PILOT_DIR / "pilot_summary.json", "w", encoding="utf-8") as f:
        json.dump(pilot_summary, f, indent=2)

    logger.info(f"Pilot complete. Results saved to {PILOT_DIR / 'pilot_summary.json'}")


if __name__ == "__main__":
    main()

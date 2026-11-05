"""
scripts/train_curriculum_p6.py

Stage P6.2 Controlled Curriculum Training Harness.
Executes multi-agent curriculum training across three sequential stages:
- Stage A: Balanced demand (1:1, 300 veh/h, 1200s, no ambulance)
- Stage B: Moderate asymmetry (2:1, 800 veh/h arterial / 400 veh/h cross, 1200s, no ambulance)
- Stage C: Full Silk Board demand (1800 veh/h arterial / 900 veh/h cross, 1200s, ambulance at 500s)

Supports:
- MAPPO (primary CTDE architecture)
- PPO (independent actor-critic baseline)
- Double-DQN (independent dueling double-DQN baseline)
- Coordinated Adaptive (non-learning reference benchmark)

Enforces strict execution gates, numerical stability checks, safety boundary audits,
and versioned checkpointing under checkpoints/p6/ and results/p6/.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import math
from pathlib import Path
import random
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# Ensure project root in python path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from traffic_service.ai.env import (
    CorridorObservationSpace,
    MultiIntersectionReward,
    RewardWeights,
    ACTION_KEEP,
    ACTION_SWITCH,
    ACTION_EXTEND,
    CORRIDOR_OBSERVATION_DIM,
    OBSERVATION_DIM_PER_JUNCTION,
)
from traffic_service.ai.starvation_tracker import StarvationTracker
from traffic_service.ai.models import TORCH_AVAILABLE
from traffic_service.ai.marl_controller import MARLCorridorController
from traffic_service.ai.mappo_agent import MAPPOAgent, train_mappo_corridor
from traffic_service.ai.ppo_agent import PPOAgent
from traffic_service.ai.dqn_agent import DQNAgent
from traffic_service.multi_intersection_simulation import MultiIntersectionSimulation
from traffic_service.curriculum import CurriculumDemandGenerator, CURRICULUM_STAGES

if TORCH_AVAILABLE:
    import torch

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("CurriculumTrainer")

# Directory paths
SUMO_CONFIG = BASE_DIR / "sumo" / "silk_board" / "silk_board.sumocfg"
CHECKPOINT_DIR = BASE_DIR / "checkpoints" / "p6"
RESULTS_DIR = BASE_DIR / "results" / "p6"
DEMAND_DIR = BASE_DIR / "data" / "curriculum"

CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
DEMAND_DIR.mkdir(parents=True, exist_ok=True)

# Experimental constants
TRAINING_SEEDS = [11, 22, 33, 44, 55]
STAGE_DURATION_S = 1200.0
DECISION_INTERVAL_S = 5.0
SIM_STEP_LENGTH = 1.0


class TrainingGateError(RuntimeError):
    """Raised when an execution gate condition is breached."""
    pass


def verify_gate_health(record: Dict[str, Any], stage_id: str, episode: int, seed: int) -> None:
    """
    Validates numerical health, safety compliance, and physical boundaries.
    Raises TrainingGateError if any condition is violated.
    """
    # 1. NaN / Inf Checks
    for k in ["mean_reward", "policy_loss", "critic_loss", "td_loss", "max_grad_norm"]:
        val = record.get(k, 0.0)
        if math.isnan(val) or math.isinf(val):
            raise TrainingGateError(f"Gate Failed: NaN or Inf detected in {k} ({val}) at {stage_id} Ep {episode} Seed {seed}")

    # 2. Maximum Red Duration Ceiling Check on Queued Vehicles
    max_queued_red = record.get("max_queued_red_duration_s", 0.0)
    # Physical ceiling: 60s threshold + 1s step + 4s yellow = 65.0s (allow 0.1s float margin)
    if max_queued_red > 65.1:
        raise TrainingGateError(
            f"Gate Failed: Anti-starvation ceiling exceeded! Queued vehicles waited {max_queued_red:.1f}s > 65.0s at {stage_id} Ep {episode}"
        )

    # 3. Trips Integrity Check (must not deadlock into 0 trips on non-pilot episodes)
    if episode > 1 and record.get("completed_trips", 0) == 0:
        logger.warning(
            f"Gate Warning: 0 trips completed at {stage_id} Ep {episode} Seed {seed}. Checking queue buildup: {record.get('average_queue')}"
        )


def run_episode(
    marl_controller: Optional[MARLCorridorController],
    algorithm: str,
    stage_id: str,
    route_file: Path,
    seed: int,
    episode: int,
    eval_mode: bool = False,
    duration_s: float = STAGE_DURATION_S,
) -> Dict[str, Any]:
    """
    Executes a single simulation episode under the specified curriculum stage.
    Collects complete step-level diagnostics, trains agent networks if in training mode,
    and returns comprehensive episode telemetry.
    """
    random.seed(seed + episode * 17)
    np.random.seed(seed + episode * 17)
    if TORCH_AVAILABLE:
        torch.manual_seed(seed + episode * 17)

    mode = "coordinated" if marl_controller is None else "baseline"

    sim = MultiIntersectionSimulation(
        sumocfg_path=SUMO_CONFIG,
        mode=mode,
        gui=False,
        step_length=SIM_STEP_LENGTH,
        decision_interval=DECISION_INTERVAL_S,
        enable_emergency=(stage_id == "stage_c"),
    )

    if marl_controller is not None:
        marl_controller.controllers = sim.controllers
        marl_controller.hub = sim.hub
        marl_controller.starvation_tracker.reset()
        sim.marl_controller = marl_controller

    obs_space = CorridorObservationSpace()
    reward_fn = MultiIntersectionReward()
    reward_fn.reset()

    sim_seed = seed * 1000 + episode * 13
    route_abs_path = str(route_file.resolve())
    sim.start(seed=sim_seed, additional_args=["--route-files", route_abs_path])

    sim_time = 0.0
    ep_rewards = {j: 0.0 for j in ["J1", "J2", "J3"]}
    ep_breakdowns: Dict[str, List[RewardBreakdown]] = {j: [] for j in ["J1", "J2", "J3"]}

    policy_losses = []
    critic_losses = []
    td_losses = []
    entropies = []
    grad_norms = []
    starvation_events_count = 0
    max_queued_red_seen = 0.0
    max_raw_red_seen = 0.0

    prev_vecs = {}
    prev_corridor_vec = None
    prev_actions = {}
    prev_decisions = {}

    try:
        raw_states = sim.get_states(sim_time)
        raw_obs = sim.get_ai_observations(raw_states)
        prev_vecs = {j: obs_space.vectorize_junction(j, raw_obs.get(j, {})) for j in ["J1", "J2", "J3"]}
        prev_corridor_vec = obs_space.vectorize_corridor(raw_obs)

        while sim_time < duration_s:
            # 1. Action selection
            if marl_controller is not None:
                decisions = marl_controller.decide(raw_obs, sim_time=sim_time, eval_mode=eval_mode)
                marl_controller.apply_decisions(decisions, sim_time)
            else:
                # Coordinated Adaptive Reference
                sim._run_coordinated_control(raw_states, sim_time)
                decisions = {
                    j: {
                        "action": ACTION_KEEP,
                        "action_name": "COORDINATED",
                        "action_mask": [1.0, 1.0, 1.0],
                        "log_prob": 0.0,
                        "value": 0.0,
                    }
                    for j in ["J1", "J2", "J3"]
                }

            # 2. Advance simulation by decision interval
            for _ in range(int(DECISION_INTERVAL_S)):
                states, ok = sim.step()
                if not ok:
                    break

            sim_time = sim.sumo_manager.get_time()
            raw_states = states
            raw_obs_next = sim.get_ai_observations(raw_states)
            next_vecs = {j: obs_space.vectorize_junction(j, raw_obs_next.get(j, {})) for j in ["J1", "J2", "J3"]}
            next_corridor_vec = obs_space.vectorize_corridor(raw_obs_next)
            is_done = (sim_time >= duration_s)

            # 3. Track maximum red duration across all approaches
            if marl_controller is not None:
                for j_id, apps in marl_controller.starvation_tracker.queued_red_elapsed.items():
                    for app, dur in apps.items():
                        if dur > max_queued_red_seen:
                            max_queued_red_seen = dur
                for j_id, apps in marl_controller.starvation_tracker.red_elapsed.items():
                    for app, dur in apps.items():
                        if dur > max_raw_red_seen:
                            max_raw_red_seen = dur
                starvation_events_count = len(marl_controller.starvation_tracker.events)

            # 4. Compute mixed rewards
            actions_dict = {j: decisions[j]["action"] for j in ["J1", "J2", "J3"]}
            completed_now = len(sim.metrics_collector._completed_travel_times)
            emergency_halted = (
                sim.emergency_coordinator.active
                and not sim.emergency_coordinator.metrics.completed
            ) if sim.enable_emergency else False

            mixed_r, b_downs = reward_fn.compute_mixed_rewards(
                states=raw_obs_next,
                actions=actions_dict,
                comm_hub=sim.hub,
                starvation_tracker=marl_controller.starvation_tracker if marl_controller else None,
                completed_trips=completed_now,
                active_emergency_stopped=emergency_halted,
                current_time=sim_time,
            )

            for j in ["J1", "J2", "J3"]:
                ep_rewards[j] += mixed_r[j]
                ep_breakdowns[j].append(b_downs[j])

            # 5. Store transitions & train if not eval_mode
            if not eval_mode and marl_controller is not None:
                if algorithm == "mappo":
                    for j_id, agent in marl_controller.agents.items():
                        assert isinstance(agent, MAPPOAgent)
                        dec = decisions[j_id]
                        agent.store_transition(
                            local_state=prev_vecs[j_id],
                            corridor_state=prev_corridor_vec,
                            action=dec["action"],
                            action_mask=np.array(dec["action_mask"], dtype=np.float32),
                            reward=mixed_r[j_id],
                            log_prob=dec["log_prob"],
                            value=dec["value"],
                            done=is_done,
                        )

                    # Update MAPPO every batch interval (e.g. 16 steps) or at end of episode
                    first_agent = marl_controller.agents["J1"]
                    if len(first_agent.buffer) >= 16 or is_done:
                        last_c_val = first_agent.get_corridor_value(next_corridor_vec) if not is_done else 0.0
                        train_res = train_mappo_corridor(
                            agents=marl_controller.agents,
                            shared_critic=marl_controller.shared_critic,
                            shared_critic_optimizer=marl_controller.shared_critic_optimizer,
                            last_corridor_value=last_c_val,
                            epochs=2,
                        )
                        policy_losses.append(train_res.get("mean_policy_loss", 0.0))
                        critic_losses.append(train_res.get("critic_loss", 0.0))
                        for j_res in train_res.get("policy_results", {}).values():
                            entropies.append(j_res.get("entropy", 0.0))
                        if TORCH_AVAILABLE and marl_controller.shared_critic:
                            gn = max(
                                p.grad.norm().item()
                                for p in marl_controller.shared_critic.parameters()
                                if p.grad is not None
                            ) if list(marl_controller.shared_critic.parameters()) else 0.0
                            grad_norms.append(gn)

                elif algorithm == "ppo":
                    for j_id, agent in marl_controller.agents.items():
                        assert isinstance(agent, PPOAgent)
                        dec = decisions[j_id]
                        agent.store_transition(
                            state=prev_vecs[j_id],
                            action=dec["action"],
                            reward=mixed_r[j_id],
                            log_prob=dec["log_prob"],
                            value=dec["value"],
                            done=is_done,
                        )
                    first_agent = marl_controller.agents["J1"]
                    if len(first_agent.buffer) >= 16 or is_done:
                        for j_id, agent in marl_controller.agents.items():
                            last_v = agent.get_value(next_vecs[j_id]) if not is_done else 0.0
                            t_res = agent.train_step(last_value=last_v, epochs=2)
                            policy_losses.append(t_res.get("policy_loss", 0.0))
                            critic_losses.append(t_res.get("value_loss", 0.0))
                            entropies.append(t_res.get("entropy", 0.0))
                            if TORCH_AVAILABLE:
                                gn = max(
                                    p.grad.norm().item()
                                    for p in agent.ac_network.parameters()
                                    if p.grad is not None
                                )
                                grad_norms.append(gn)

                elif algorithm == "dqn":
                    for j_id, agent in marl_controller.agents.items():
                        assert isinstance(agent, DQNAgent)
                        act = decisions[j_id]["action"]
                        agent.replay_buffer.push(prev_vecs[j_id], act, mixed_r[j_id], next_vecs[j_id], is_done)
                        if len(agent.replay_buffer) >= 16:
                            td_l = agent.train_step(batch_size=16)
                            td_losses.append(td_l)
                            if TORCH_AVAILABLE:
                                gn = max(
                                    p.grad.norm().item()
                                    for p in agent.q_network.parameters()
                                    if p.grad is not None
                                )
                                grad_norms.append(gn)

            prev_vecs = next_vecs
            prev_corridor_vec = next_corridor_vec
            raw_obs = raw_obs_next

        # Episode summary
        summary = sim.metrics_collector.compute_summary()
        mean_rew = float(np.mean(list(ep_rewards.values())))

        # Aggregate breakdown averages across steps and junctions
        all_b = [b for j in ep_breakdowns for b in ep_breakdowns[j]]
        avg_r_queue = float(np.mean([b.r_queue for b in all_b])) if all_b else 0.0
        avg_r_wait = float(np.mean([b.r_wait for b in all_b])) if all_b else 0.0
        avg_r_speed = float(np.mean([b.r_speed for b in all_b])) if all_b else 0.0
        avg_r_prog = float(np.mean([b.r_progression for b in all_b])) if all_b else 0.0
        avg_R_tp = float(np.mean([b.R_throughput for b in all_b])) if all_b else 0.0
        avg_R_cdelay = float(np.mean([b.R_corridor_delay for b in all_b])) if all_b else 0.0
        avg_R_starve = float(np.mean([b.R_starvation for b in all_b])) if all_b else 0.0
        avg_R_flow = float(np.mean([b.R_flow_integrity for b in all_b])) if all_b else 0.0

        rec = {
            "algorithm": algorithm,
            "stage": stage_id,
            "train_seed": seed,
            "episode": episode,
            "sim_seed": sim_seed,
            "mean_reward": mean_rew,
            "reward_j1": float(ep_rewards["J1"]),
            "reward_j2": float(ep_rewards["J2"]),
            "reward_j3": float(ep_rewards["J3"]),
            "policy_loss": float(np.mean(policy_losses)) if policy_losses else 0.0,
            "critic_loss": float(np.mean(critic_losses)) if critic_losses else 0.0,
            "td_loss": float(np.mean(td_losses)) if td_losses else 0.0,
            "entropy": float(np.mean(entropies)) if entropies else 0.0,
            "epsilon": float(marl_controller.agents["J2"].epsilon) if algorithm == "dqn" and marl_controller else 0.0,
            "max_grad_norm": float(np.mean(grad_norms)) if grad_norms else 0.0,
            "completed_trips": summary.total_corridor_trips_completed,
            "average_queue": summary.mean_corridor_queue,
            "cumulative_delay_veh_s": summary.cumulative_delay_veh_s,
            "average_travel_time_s": summary.mean_corridor_travel_time_s,
            "total_fuel_liters": summary.total_fuel_liters,
            "total_co2_kg": summary.total_co2_kg,
            "max_queued_red_duration_s": max_queued_red_seen,
            "max_red_duration_s": max_raw_red_seen,
            "starvation_events": starvation_events_count,
            "emergency_completed": sim.emergency_coordinator.metrics.completed if sim.enable_emergency else True,
            # Component diagnostics
            "r_queue": avg_r_queue,
            "r_wait": avg_r_wait,
            "r_speed": avg_r_speed,
            "r_progression": avg_r_prog,
            "R_throughput": avg_R_tp,
            "R_corridor_delay": avg_R_cdelay,
            "R_starvation": avg_R_starve,
            "R_flow_integrity": avg_R_flow,
        }

        # Gate verification
        verify_gate_health(rec, stage_id, episode, seed)

        return rec

    finally:
        sim.close()


def train_stage(
    stage_id: str,
    algorithms: List[str] = ["mappo", "ppo", "dqn", "coordinated"],
    seeds: List[int] = TRAINING_SEEDS,
    episodes_per_seed: int = 5,
    is_pilot: bool = False,
) -> Dict[str, Any]:
    """
    Executes curriculum training for a single stage across the requested algorithms and seeds.
    """
    logger.info("=" * 80)
    mode_str = "PILOT EXECUTION GATE" if is_pilot else "FULL CURRICULUM TRAINING"
    logger.info(f"STARTING {mode_str} FOR STAGE: {stage_id.upper()}")
    logger.info(f"Algorithms: {algorithms} | Seeds: {seeds} | Episodes/seed: {episodes_per_seed}")
    logger.info("=" * 80)

    # 1. Generate clean route XML for this stage
    demand_gen = CurriculumDemandGenerator(output_dir=DEMAND_DIR)
    route_file = demand_gen.generate_stage_routes(stage_id, include_vtypes=False)
    logger.info(f"Generated and verified curriculum route file: {route_file}")

    stage_summary: Dict[str, Any] = {
        "stage_id": stage_id,
        "is_pilot": is_pilot,
        "algorithms": {},
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    for algo in algorithms:
        logger.info(f"\n--- COMMENCING {algo.upper()} ON {stage_id.upper()} ---")
        algo_records = []
        best_reward = -float("inf")
        best_controller = None
        last_controller = None

        for s_idx, seed in enumerate(seeds, 1):
            logger.info(f"> Seed {seed} ({s_idx}/{len(seeds)})")
            marl_ctrl = None
            if algo != "coordinated":
                marl_ctrl = MARLCorridorController(
                    algorithm=algo,
                    junctions=["J1", "J2", "J3"],
                    seed=seed,
                )
                # If prior stage checkpoint exists, load warm weights
                prior_stage = "stage_a" if stage_id == "stage_b" else ("stage_b" if stage_id == "stage_c" else None)
                if prior_stage and not is_pilot:
                    prior_ckpt = CHECKPOINT_DIR / f"{algo}_{prior_stage}_best.json"
                    if prior_ckpt.is_file():
                        loaded = marl_ctrl.load_checkpoint(prior_ckpt)
                        if loaded:
                            logger.info(f"Successfully warm-started {algo} from {prior_ckpt.name}")

            n_ep = 1 if (algo == "coordinated" and not is_pilot) else episodes_per_seed
            for ep in range(1, n_ep + 1):
                rec = run_episode(
                    marl_controller=marl_ctrl,
                    algorithm=algo,
                    stage_id=stage_id,
                    route_file=route_file,
                    seed=seed,
                    episode=ep,
                    eval_mode=(algo == "coordinated"),
                )
                algo_records.append(rec)

                logger.info(
                    f"[{algo.upper()} | {stage_id} | S{seed} Ep{ep}/{n_ep}] "
                    f"Rew={rec['mean_reward']:.2f} | PolL={rec['policy_loss']:.4f} | "
                    f"CritL={rec['critic_loss']:.4f} | TDL={rec['td_loss']:.4f} | "
                    f"Trips={rec['completed_trips']} | Queue={rec['average_queue']:.1f} | "
                    f"MaxQueuedRed={rec['max_queued_red_duration_s']:.1f}s | MaxRed={rec['max_red_duration_s']:.1f}s | StarveEvents={rec['starvation_events']}"
                )

                if rec["mean_reward"] > best_reward and marl_ctrl is not None and not is_pilot:
                    best_reward = rec["mean_reward"]
                    best_ckpt = CHECKPOINT_DIR / f"{algo}_{stage_id}_best.json"
                    meta = {
                        "algorithm": algo,
                        "curriculum_stage": stage_id,
                        "seed": seed,
                        "episode": ep,
                        "best_mean_reward": best_reward,
                        "source_commit": "1d55856",
                        "metrics": rec,
                    }
                    marl_ctrl.save_checkpoint(best_ckpt, version=f"6.2-{algo}-{stage_id}-best", metadata=meta)
                    logger.info(f"Saved new best checkpoint: {best_ckpt} (Reward: {best_reward:.2f})")

            # Save per-seed checkpoint
            if marl_ctrl is not None and not is_pilot:
                seed_ckpt = CHECKPOINT_DIR / f"{algo}_{stage_id}_seed{seed}.json"
                meta = {
                    "algorithm": algo,
                    "curriculum_stage": stage_id,
                    "seed": seed,
                    "episodes": episodes_per_seed,
                    "source_commit": "1d55856",
                }
                marl_ctrl.save_checkpoint(seed_ckpt, version=f"6.2-{algo}-{stage_id}-seed{seed}", metadata=meta)
                logger.info(f"Saved seed checkpoint: {seed_ckpt}")

        # Checkpoints for learning algorithms
        if marl_ctrl is not None and not is_pilot:
            final_ckpt = CHECKPOINT_DIR / f"{algo}_{stage_id}_final.json"
            meta = {
                "algorithm": algo,
                "curriculum_stage": stage_id,
                "training_seeds": seeds,
                "episodes_per_seed": episodes_per_seed,
                "total_episodes": len(algo_records),
                "best_mean_reward": best_reward,
                "source_commit": "1d55856",
            }
            marl_ctrl.save_checkpoint(final_ckpt, version=f"6.2-{algo}-{stage_id}-final", metadata=meta)
            logger.info(f"Saved final checkpoint: {final_ckpt}")

        # Save CSV and JSON curve files
        curves_csv = RESULTS_DIR / f"{algo}_{stage_id}_{'pilot' if is_pilot else 'curves'}.csv"
        curves_json = RESULTS_DIR / f"{algo}_{stage_id}_{'pilot' if is_pilot else 'curves'}.json"

        if algo_records:
            fieldnames = list(algo_records[0].keys())
            with open(curves_csv, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(algo_records)

            with open(curves_json, "w", encoding="utf-8") as f:
                json.dump(algo_records, f, indent=2)

        stage_summary["algorithms"][algo] = {
            "record_count": len(algo_records),
            "mean_reward": float(np.mean([r["mean_reward"] for r in algo_records])) if algo_records else 0.0,
            "mean_trips": float(np.mean([r["completed_trips"] for r in algo_records])) if algo_records else 0.0,
            "mean_queue": float(np.mean([r["average_queue"] for r in algo_records])) if algo_records else 0.0,
            "mean_delay_s": float(np.mean([r["cumulative_delay_veh_s"] for r in algo_records])) if algo_records else 0.0,
            "max_red_seen": float(np.max([r["max_red_duration_s"] for r in algo_records])) if algo_records else 0.0,
            "starvation_events_total": int(np.sum([r["starvation_events"] for r in algo_records])) if algo_records else 0,
        }

    # Save summary
    summary_path = RESULTS_DIR / f"{stage_id}_{'pilot_summary' if is_pilot else 'stage_summary'}.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(stage_summary, f, indent=2)
    logger.info(f"Saved stage summary to: {summary_path}")

    return stage_summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="P6.2 Curriculum Training Runner")
    parser.add_argument("--stage", choices=["stage_a", "stage_b", "stage_c"], default="stage_a", help="Curriculum stage")
    parser.add_argument("--pilot", action="store_true", help="Execute short 1-episode pilot gate")
    parser.add_argument("--algorithms", nargs="+", default=["mappo", "ppo", "dqn", "coordinated"], help="Algorithms to train")
    parser.add_argument("--seeds", nargs="+", type=int, default=TRAINING_SEEDS, help="Random training seeds")
    parser.add_argument("--episodes", type=int, default=5, help="Episodes per seed")

    args = parser.parse_args()

    active_seeds = [args.seeds[0]] if args.pilot else args.seeds
    active_episodes = 1 if args.pilot else args.episodes

    summary = train_stage(
        stage_id=args.stage,
        algorithms=args.algorithms,
        seeds=active_seeds,
        episodes_per_seed=active_episodes,
        is_pilot=args.pilot,
    )
    logger.info(f"Stage {args.stage} complete.")

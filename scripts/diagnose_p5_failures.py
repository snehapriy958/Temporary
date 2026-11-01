"""
scripts/diagnose_p5_failures.py

Stage P5.1 Diagnostic Script:
Inspects J1 PPO starvation, J2 DQN gridlock, action distributions,
phase residency, Q-values, and reward structure.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import numpy as np
import torch

from traffic_service.ai.env import ACTION_NAMES, CorridorObservationSpace, MultiIntersectionReward, RewardWeights
from traffic_service.ai.marl_controller import MARLCorridorController
from traffic_service.multi_intersection_simulation import MultiIntersectionSimulation

logging.basicConfig(level=logging.WARNING)

SUMO_CONFIG = BASE_DIR / "sumo" / "silk_board" / "silk_board.sumocfg"
P5_PPO_CKPT = BASE_DIR / "checkpoints" / "marl_ppo_corridor_p5.json"
P5_DQN_CKPT = BASE_DIR / "checkpoints" / "marl_dqn_corridor_p5.json"


def diagnose_ppo_run(seed: int = 1, duration: int = 300):
    print("=" * 80)
    print(f"DIAGNOSING PPO RUN ON SEED {seed} ({duration}s)")
    print("=" * 80)

    sim = MultiIntersectionSimulation(
        sumocfg_path=SUMO_CONFIG,
        mode="marl_ppo",
        checkpoint_path=P5_PPO_CKPT,
        step_length=1.0,
        decision_interval=5.0,
        enable_emergency=False,
        gui=False,
    )
    sim.start(seed=seed)

    # Track phase distribution, action counts, queues
    j_stats = {
        j: {
            "actions": {0: 0, 1: 0, 2: 0},
            "phase_time": {},
            "queues_corridor": [],
            "queues_side": [],
            "switch_attempts": 0,
            "switch_success": 0,
            "extend_attempts": 0,
        }
        for j in ["J1", "J2", "J3"]
    }

    try:
        while sim.sumo_manager.get_time() < duration:
            sim_time = sim.sumo_manager.get_time()

            # Record phase occupancy
            for j in ["J1", "J2", "J3"]:
                p = sim.controllers[j].get_phase()
                j_stats[j]["phase_time"][p] = j_stats[j]["phase_time"].get(p, 0) + 1

            # When decision happens
            if sim_time >= sim._next_decision_time:
                states = sim.get_states(sim_time)
                ai_obs = sim.get_ai_observations(states)
                decisions = sim.marl_controller.decide(ai_obs, sim_time, eval_mode=True)
                ops = sim.marl_controller.apply_decisions(decisions, sim_time)

                for j in ["J1", "J2", "J3"]:
                    act = decisions[j]["action"]
                    j_stats[j]["actions"][act] += 1
                    j_stats[j]["queues_corridor"].append(states[j].approach_queues.get("corridor_hosur", 0))
                    j_stats[j]["queues_side"].append(
                        states[j].approach_queues.get("side_cross", states[j].approach_queues.get("madiwala", 0))
                    )
                    if act == 1:
                        j_stats[j]["switch_attempts"] += 1
                        if "OK" in ops.get(j, ""):
                            j_stats[j]["switch_success"] += 1
                    elif act == 2:
                        j_stats[j]["extend_attempts"] += 1

            sim.step()

        summary = sim.metrics_collector.compute_summary()
        print(f"Completed Trips: {summary.total_corridor_trips_completed}")
        print(f"Cumulative Delay: {summary.cumulative_delay_veh_s:.0f} veh-s")
        print(f"Mean Corridor Queue: {summary.mean_corridor_queue:.1f}")

        for j in ["J1", "J2", "J3"]:
            print(f"\n--- Junction {j} ---")
            print(f"Action Counts: KEEP={j_stats[j]['actions'][0]}, SWITCH={j_stats[j]['actions'][1]}, EXTEND={j_stats[j]['actions'][2]}")
            print(f"Switch Success Rate: {j_stats[j]['switch_success']}/{j_stats[j]['switch_attempts']}")
            print(f"Phase Time Occupancy (seconds): {j_stats[j]['phase_time']}")
            print(f"Mean Corridor Approach Queue: {np.mean(j_stats[j]['queues_corridor']):.1f} (Max: {np.max(j_stats[j]['queues_corridor'])})")
            print(f"Mean Side Approach Queue: {np.mean(j_stats[j]['queues_side']):.1f} (Max: {np.max(j_stats[j]['queues_side'])})")

    finally:
        sim.close()


def diagnose_dqn_run(seed: int = 1, duration: int = 300):
    print("\n" + "=" * 80)
    print(f"DIAGNOSING DQN RUN ON SEED {seed} ({duration}s)")
    print("=" * 80)

    sim = MultiIntersectionSimulation(
        sumocfg_path=SUMO_CONFIG,
        mode="marl_dqn",
        checkpoint_path=P5_DQN_CKPT,
        step_length=1.0,
        decision_interval=5.0,
        enable_emergency=False,
        gui=False,
    )
    sim.start(seed=seed)

    j_stats = {
        j: {
            "actions": {0: 0, 1: 0, 2: 0},
            "phase_time": {},
            "queues_corridor": [],
            "queues_side": [],
            "switch_attempts": 0,
            "switch_success": 0,
            "extend_attempts": 0,
        }
        for j in ["J1", "J2", "J3"]
    }

    try:
        while sim.sumo_manager.get_time() < duration:
            sim_time = sim.sumo_manager.get_time()

            for j in ["J1", "J2", "J3"]:
                p = sim.controllers[j].get_phase()
                j_stats[j]["phase_time"][p] = j_stats[j]["phase_time"].get(p, 0) + 1

            if sim_time >= sim._next_decision_time:
                states = sim.get_states(sim_time)
                ai_obs = sim.get_ai_observations(states)
                decisions = sim.marl_controller.decide(ai_obs, sim_time, eval_mode=True)
                ops = sim.marl_controller.apply_decisions(decisions, sim_time)

                for j in ["J1", "J2", "J3"]:
                    act = decisions[j]["action"]
                    j_stats[j]["actions"][act] += 1
                    j_stats[j]["queues_corridor"].append(states[j].approach_queues.get("corridor_hosur", 0))
                    j_stats[j]["queues_side"].append(
                        states[j].approach_queues.get("side_cross", states[j].approach_queues.get("madiwala", 0))
                    )
                    if act == 1:
                        j_stats[j]["switch_attempts"] += 1
                        if "OK" in ops.get(j, ""):
                            j_stats[j]["switch_success"] += 1
                    elif act == 2:
                        j_stats[j]["extend_attempts"] += 1

            sim.step()

        summary = sim.metrics_collector.compute_summary()
        print(f"Completed Trips: {summary.total_corridor_trips_completed}")
        print(f"Cumulative Delay: {summary.cumulative_delay_veh_s:.0f} veh-s")
        print(f"Mean Corridor Queue: {summary.mean_corridor_queue:.1f}")

        for j in ["J1", "J2", "J3"]:
            print(f"\n--- Junction {j} ---")
            print(f"Action Counts: KEEP={j_stats[j]['actions'][0]}, SWITCH={j_stats[j]['actions'][1]}, EXTEND={j_stats[j]['actions'][2]}")
            print(f"Switch Success Rate: {j_stats[j]['switch_success']}/{j_stats[j]['switch_attempts']}")
            print(f"Phase Time Occupancy (seconds): {j_stats[j]['phase_time']}")
            print(f"Mean Corridor Approach Queue: {np.mean(j_stats[j]['queues_corridor']):.1f} (Max: {np.max(j_stats[j]['queues_corridor'])})")
            print(f"Mean Side Approach Queue: {np.mean(j_stats[j]['queues_side']):.1f} (Max: {np.max(j_stats[j]['queues_side'])})")

    finally:
        sim.close()


def main():
    diagnose_ppo_run(seed=1, duration=300)
    diagnose_dqn_run(seed=1, duration=300)


if __name__ == "__main__":
    main()

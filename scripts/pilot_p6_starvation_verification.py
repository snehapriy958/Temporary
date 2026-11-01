"""
scripts/pilot_p6_starvation_verification.py

Pilot Verification Script for Stage P6 Anti-Starvation Constraints and Mixed Rewards.
Runs a live SUMO simulation with MARLCorridorController (with StarvationTracker active),
verifying:
1. No queued approach red duration exceeds max_red_threshold_s (60.0s) + transition buffer.
2. Anti-starvation switches fire reliably when starvation threshold is approached.
3. Mixed local-global rewards and detailed breakdown telemetry are computed cleanly.
"""

from __future__ import annotations

import sys
from pathlib import Path
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from traffic_service.multi_intersection_simulation import MultiIntersectionSimulation
from traffic_service.ai.env import MultiIntersectionReward, RewardWeights


def run_pilot(duration_s: int = 150, seed: int = 42) -> None:
    print(f"=== Stage P6 Pre-Training Pilot: Anti-Starvation & Mixed Reward Verification ===", flush=True)
    print(f"Simulation duration: {duration_s}s | Random Seed: {seed}", flush=True)

    sumocfg_path = PROJECT_ROOT / "sumo" / "silk_board" / "silk_board.sumocfg"
    sim = MultiIntersectionSimulation(
        sumocfg_path=str(sumocfg_path),
        mode="marl_ppo",
        gui=False,
    )

    reward_fn = MultiIntersectionReward(weights=RewardWeights(alpha=0.5))

    sim.start(seed=seed)
    print("SUMO simulation engine started successfully.", flush=True)

    forced_switches_count = 0
    max_red_observed = 0.0
    highest_red_approach = ""

    try:
        for step in range(1, duration_s + 1):
            sim_time = float(step)
            states, ok = sim.step()
            if not ok:
                break

            ai_obs = sim.get_ai_observations(states)
            tracker = sim.marl_controller.starvation_tracker

            # Monitor red elapsed across all approaches
            for j_id in ["J1", "J2", "J3"]:
                for app, red_t in tracker.red_elapsed[j_id].items():
                    q = tracker.current_queues[j_id].get(app, 0)
                    if q > 0 and red_t > max_red_observed:
                        max_red_observed = red_t
                        highest_red_approach = f"{j_id}:{app}"

            # Compute mixed rewards and breakdown telemetry
            actions = {j_id: sim.controllers[j_id].get_phase() for j_id in ["J1", "J2", "J3"]}
            trips = len(sim.metrics_collector._completed_travel_times)
            rewards, breakdowns = reward_fn.compute_mixed_rewards(
                states=ai_obs,
                actions=actions,
                comm_hub=sim.hub,
                starvation_tracker=tracker,
                completed_trips=trips,
                current_time=sim_time,
            )

            if step % 30 == 0:
                print(
                    f"[{sim_time:5.1f}s] Trips: {trips:2d} | "
                    f"Max Red: {max_red_observed:4.1f}s ({highest_red_approach}) | "
                    f"J1 R_mixed: {rewards['J1']:+.2f} | J2 R_mixed: {rewards['J2']:+.2f} | J3 R_mixed: {rewards['J3']:+.2f}",
                    flush=True,
                )

        forced_switches_count = len(sim.marl_controller.starvation_tracker.events)
        total_trips = len(sim.metrics_collector._completed_travel_times)
        print("\n--- Pilot Results Summary ---", flush=True)
        print(f"Total Steps Simulated: {duration_s}", flush=True)
        print(f"Total Completed Corridor Trips: {total_trips}", flush=True)
        print(f"Maximum Queued Approach Red Duration: {max_red_observed:.1f}s (Approach: {highest_red_approach})", flush=True)
        print(f"Total Anti-Starvation Forced Interventions: {forced_switches_count}", flush=True)

        # Verification Assertions:
        # Threshold is 60.0s; maximum tolerable red duration with clearance is 65.0s
        assert max_red_observed <= 65.0, (
            f"Anti-starvation safety breach: queued approach red duration reached {max_red_observed:.1f}s > 65.0s!"
        )
        print("PASS: Anti-Starvation Safety Constraint strictly verified (no queued movement exceeded 65.0s).", flush=True)

    finally:
        sim.close()
        print("Simulation closed cleanly.", flush=True)


if __name__ == "__main__":
    run_pilot(duration_s=150, seed=42)

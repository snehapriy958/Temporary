"""
scripts/verify_four_controllers.py

Stage P3: End-to-End Verification of All 4 Controllers on SUMO
Executes a 30-second simulation episode on the Bengaluru Silk Board corridor
for each supported controller mode:
1. 'baseline' (Fixed-time uncoordinated)
2. 'coordinated' (Coordinated Adaptive with inflow anticipation and green wave)
3. 'marl_ppo' (Multi-Agent PPO policy from marl_ppo_corridor.json)
4. 'marl_dqn' (Multi-Agent Double-DQN policy from marl_dqn_corridor.json)
"""

import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Setup logging to capture structured runtime traces
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("verify_four_controllers")

from traffic_service.multi_intersection_simulation import MultiIntersectionSimulation

SUMO_CONFIG = PROJECT_ROOT / "sumo" / "silk_board" / "silk_board.sumocfg"

MODES = ["baseline", "coordinated", "marl_ppo", "marl_dqn"]
SIMULATION_SECONDS = 30


def run_controller_verification():
    results = {}

    for mode in MODES:
        logger.info(f"\n{'='*70}\nSTARTING VERIFICATION RUN: Mode = '{mode}'\n{'='*70}")
        sim = MultiIntersectionSimulation(
            sumocfg_path=SUMO_CONFIG,
            mode=mode,
            gui=False,
            step_length=1.0,
            decision_interval=5.0,
            enable_emergency=True,
        )

        try:
            sim.start(seed=42)
            assert sim.sumo_manager.is_running, f"SUMO failed to start for mode '{mode}'"

            step_count = 0
            for step_idx in range(SIMULATION_SECONDS):
                states, ok = sim.step()
                assert ok, f"sim.step() returned False at step {step_idx} in mode '{mode}'"
                step_count += 1

            summary = sim.metrics_collector.compute_summary()
            results[mode] = {
                "mode": mode,
                "simulated_seconds": summary.simulation_duration,
                "steps_completed": step_count,
                "mean_corridor_speed_kmh": round(summary.mean_corridor_speed_kmh, 2),
                "mean_corridor_queue": round(summary.mean_corridor_queue, 2),
                "total_fuel_liters": round(summary.total_fuel_liters, 3),
                "total_co2_kg": round(summary.total_co2_kg, 3),
                "cumulative_delay_veh_s": round(summary.cumulative_delay_veh_s, 1),
                "trips_completed": summary.total_corridor_trips_completed,
            }
            logger.info(f"COMPLETED RUN: Mode = '{mode}' -> Summary: {results[mode]}")

        finally:
            sim.close()
            assert not sim.sumo_manager.is_running

    logger.info(f"\n{'='*70}\nALL 4 CONTROLLER RUNS VERIFIED SUCCESSFULLY\n{'='*70}")
    for mode, res in results.items():
        logger.info(
            f"Mode {mode:12s}: duration={res['simulated_seconds']}s, "
            f"speed={res['mean_corridor_speed_kmh']} km/h, "
            f"queue={res['mean_corridor_queue']} veh, "
            f"delay={res['cumulative_delay_veh_s']} veh*s, "
            f"fuel={res['total_fuel_liters']} L, "
            f"CO2={res['total_co2_kg']} kg, "
            f"trips={res['trips_completed']}"
        )

    return results


if __name__ == "__main__":
    run_controller_verification()

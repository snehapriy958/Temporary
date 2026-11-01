"""
scripts/evaluate_p5_controllers.py

Stage P5 Independent Evaluation of Four Signal Controllers on SUMO Corridor:
1. Fixed-time baseline ('baseline')
2. Coordinated adaptive ('coordinated')
3. Trained MARL PPO ('marl_ppo') using checkpoints/marl_ppo_corridor_p5.json
4. Trained MARL DQN ('marl_dqn') using checkpoints/marl_dqn_corridor_p5.json

Requirements:
- Identical network (silk_board.net.xml)
- Identical traffic demand (silk_board.rou.xml)
- Identical horizon (600 seconds)
- Identical evaluation seeds: [1, 2, 3, 4, 5] (disjoint from training seeds)
- Deterministic inference (eval_mode=True, zero exploration)
- Metrics: travel time, cumulative delay, queue, throughput, fuel (0.750 kg/L), CO2, ambulance traversal

Outputs:
- results/p5/p5_per_seed_evaluation.csv
- results/p5/p5_aggregate_evaluation.csv
- results/p5/p5_evaluation_results.json
"""

from __future__ import annotations

import csv
import json
import logging
import math
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import numpy as np
from scipy import stats

from traffic_service.multi_intersection_simulation import MultiIntersectionSimulation

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("EvalP5Controllers")

SUMO_CONFIG = BASE_DIR / "sumo" / "silk_board" / "silk_board.sumocfg"
RESULTS_DIR = BASE_DIR / "results" / "p5"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
PER_RUN_DIR = RESULTS_DIR / "per_run_csvs"
PER_RUN_DIR.mkdir(parents=True, exist_ok=True)

EVAL_SEEDS = [1, 2, 3, 4, 5]
DURATION_S = 600
DECISION_INTERVAL_S = 5.0

P5_CHECKPOINTS = {
    "marl_ppo": BASE_DIR / "checkpoints" / "marl_ppo_corridor_p5.json",
    "marl_dqn": BASE_DIR / "checkpoints" / "marl_dqn_corridor_p5.json",
}

CONTROLLER_MODES = ["baseline", "coordinated", "marl_ppo", "marl_dqn"]
CONTROLLER_DISPLAY_NAMES = {
    "baseline": "Fixed-Time Baseline",
    "coordinated": "Coordinated Adaptive",
    "marl_ppo": "Trained MARL PPO (P5)",
    "marl_dqn": "Trained MARL DQN (P5)",
}


def run_single_evaluation(mode: str, seed: int) -> Dict[str, Any]:
    """Runs a single 600s evaluation for a controller mode and seed."""
    logger.info(f"==> Evaluating [{mode.upper()}] on Seed {seed} for {DURATION_S}s...")

    ckpt_path = P5_CHECKPOINTS.get(mode)
    if ckpt_path is not None and not ckpt_path.is_file():
        raise FileNotFoundError(f"Required trained checkpoint not found: {ckpt_path}")

    sim = MultiIntersectionSimulation(
        sumocfg_path=SUMO_CONFIG,
        mode=mode,
        checkpoint_path=ckpt_path,
        step_length=1.0,
        decision_interval=DECISION_INTERVAL_S,
        enable_emergency=True,
        gui=False,
    )

    t0 = time.time()
    try:
        summary = sim.run_full_simulation(duration_seconds=DURATION_S, seed=seed)
        wall_time = time.time() - t0

        # Export step-by-step trace
        trace_path = PER_RUN_DIR / f"{mode}_seed_{seed}.csv"
        sim.metrics_collector.export_csv(trace_path)

        result = {
            "mode": mode,
            "display_name": CONTROLLER_DISPLAY_NAMES[mode],
            "seed": seed,
            "duration_simulated_s": summary.simulation_duration,
            "wall_time_s": wall_time,
            "mean_corridor_travel_time_s": summary.mean_corridor_travel_time_s,
            "cumulative_delay_veh_s": summary.cumulative_delay_veh_s,
            "mean_corridor_queue": summary.mean_corridor_queue,
            "total_corridor_trips_completed": summary.total_corridor_trips_completed,
            "mean_corridor_speed_kmh": summary.mean_corridor_speed_kmh,
            "total_fuel_liters": summary.total_fuel_liters,
            "total_co2_kg": summary.total_co2_kg,
            "emergency_traversal_duration_s": summary.emergency_traversal_duration_s,
            "j1_mean_queue": summary.j1_mean_queue,
            "j2_mean_queue": summary.j2_mean_queue,
            "j3_mean_queue": summary.j3_mean_queue,
            "status": "COMPLETED",
        }
        logger.info(
            f"    [{mode} Seed {seed}] Done in {wall_time:.1f}s | TravelTime={result['mean_corridor_travel_time_s']:.1f}s | "
            f"Delay={result['cumulative_delay_veh_s']:.0f}s | Trips={result['total_corridor_trips_completed']} | "
            f"Queue={result['mean_corridor_queue']:.1f} | Fuel={result['total_fuel_liters']:.2f}L | "
            f"Ambulance={result['emergency_traversal_duration_s']:.1f}s"
        )
        return result

    except Exception as exc:
        logger.error(f"    [{mode} Seed {seed}] FAILED: {exc}")
        return {
            "mode": mode,
            "display_name": CONTROLLER_DISPLAY_NAMES[mode],
            "seed": seed,
            "status": f"FAILED: {exc}",
            "mean_corridor_travel_time_s": None,
            "cumulative_delay_veh_s": None,
            "mean_corridor_queue": None,
            "total_corridor_trips_completed": None,
            "mean_corridor_speed_kmh": None,
            "total_fuel_liters": None,
            "total_co2_kg": None,
            "emergency_traversal_duration_s": None,
        }


def compute_metrics_statistics(
    per_seed_results: List[Dict[str, Any]]
) -> Dict[str, Dict[str, Any]]:
    """Computes mean, std, and 95% CI across evaluation seeds for each controller."""
    stats_dict: Dict[str, Dict[str, Any]] = {}

    metric_keys = [
        "mean_corridor_travel_time_s",
        "cumulative_delay_veh_s",
        "mean_corridor_queue",
        "total_corridor_trips_completed",
        "mean_corridor_speed_kmh",
        "total_fuel_liters",
        "total_co2_kg",
        "emergency_traversal_duration_s",
    ]

    for mode in CONTROLLER_MODES:
        mode_runs = [r for r in per_seed_results if r["mode"] == mode and r["status"] == "COMPLETED"]
        stats_dict[mode] = {
            "display_name": CONTROLLER_DISPLAY_NAMES[mode],
            "completed_runs": len(mode_runs),
            "total_runs": len(EVAL_SEEDS),
            "metrics": {},
        }

        for m_key in metric_keys:
            vals = [float(r[m_key]) for r in mode_runs if r.get(m_key) is not None]
            if vals:
                mean_val = float(np.mean(vals))
                std_val = float(np.std(vals, ddof=1)) if len(vals) > 1 else 0.0
                # 95% confidence interval
                if len(vals) > 1 and std_val > 0.0:
                    ci = float(stats.t.ppf(0.975, df=len(vals) - 1) * (std_val / math.sqrt(len(vals))))
                else:
                    ci = 0.0
                stats_dict[mode]["metrics"][m_key] = {
                    "mean": mean_val,
                    "std": std_val,
                    "ci95": ci,
                    "min": float(np.min(vals)),
                    "max": float(np.max(vals)),
                    "values_by_seed": {r["seed"]: float(r[m_key]) for r in mode_runs},
                }
            else:
                stats_dict[mode]["metrics"][m_key] = {"mean": 0.0, "std": 0.0, "ci95": 0.0}

    return stats_dict


def compute_comparisons(
    stats_dict: Dict[str, Dict[str, Any]],
    per_seed_results: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Computes relative percentage changes and paired t-tests vs baseline and coordinated."""
    comparisons: Dict[str, Any] = {}

    # Helper for relative change:
    # Lower is better for: travel_time, cumulative_delay, queue, fuel, co2, emergency
    # Higher is better for: trips, speed
    lower_is_better = {
        "mean_corridor_travel_time_s": True,
        "cumulative_delay_veh_s": True,
        "mean_corridor_queue": True,
        "total_corridor_trips_completed": False,
        "mean_corridor_speed_kmh": False,
        "total_fuel_liters": True,
        "total_co2_kg": True,
        "emergency_traversal_duration_s": True,
    }

    baseline_metrics = stats_dict["baseline"]["metrics"]
    coord_metrics = stats_dict["coordinated"]["metrics"]

    for mode in ["coordinated", "marl_ppo", "marl_dqn"]:
        mode_comp = {
            "display_name": CONTROLLER_DISPLAY_NAMES[mode],
            "vs_baseline": {},
            "vs_coordinated": {},
        }
        for m_key, is_lower in lower_is_better.items():
            base_m = baseline_metrics[m_key]["mean"]
            mode_m = stats_dict[mode]["metrics"][m_key]["mean"]
            coord_m = coord_metrics[m_key]["mean"]

            # Comparison vs Baseline (% improvement: positive means better)
            if base_m > 0:
                rel_base = ((base_m - mode_m) / base_m * 100.0) if is_lower else ((mode_m - base_m) / base_m * 100.0)
            else:
                rel_base = 0.0

            # Comparison vs Coordinated (% improvement relative to coordinated)
            if coord_m > 0:
                rel_coord = ((coord_m - mode_m) / coord_m * 100.0) if is_lower else ((mode_m - coord_m) / coord_m * 100.0)
            else:
                rel_coord = 0.0

            # Paired t-test vs baseline
            mode_vals = [stats_dict[mode]["metrics"][m_key]["values_by_seed"][s] for s in EVAL_SEEDS]
            base_vals = [baseline_metrics[m_key]["values_by_seed"][s] for s in EVAL_SEEDS]
            coord_vals = [coord_metrics[m_key]["values_by_seed"][s] for s in EVAL_SEEDS]

            p_val_base = 1.0
            if len(set(mode_vals)) > 1 or len(set(base_vals)) > 1:
                try:
                    _, p_val_base = stats.ttest_rel(mode_vals, base_vals)
                except Exception:
                    p_val_base = 1.0

            p_val_coord = 1.0
            if len(set(mode_vals)) > 1 or len(set(coord_vals)) > 1:
                try:
                    _, p_val_coord = stats.ttest_rel(mode_vals, coord_vals)
                except Exception:
                    p_val_coord = 1.0

            mode_comp["vs_baseline"][m_key] = {
                "rel_improvement_pct": float(rel_base),
                "p_value": float(p_val_base) if not math.isnan(p_val_base) else 1.0,
                "is_significant_p05": bool(p_val_base < 0.05),
            }
            mode_comp["vs_coordinated"][m_key] = {
                "rel_improvement_pct": float(rel_coord),
                "p_value": float(p_val_coord) if not math.isnan(p_val_coord) else 1.0,
                "is_significant_p05": bool(p_val_coord < 0.05),
            }

        comparisons[mode] = mode_comp

    return comparisons


def main():
    logger.info("=" * 80)
    logger.info("STARTING STAGE P5 INDEPENDENT MULTI-SEED CONTROLLER EVALUATION")
    logger.info(f"Controllers: {CONTROLLER_MODES}")
    logger.info(f"Evaluation Seeds: {EVAL_SEEDS} | Horizon: {DURATION_S}s | Mode: Deterministic")
    logger.info("=" * 80)

    start_all = time.time()
    per_seed_results: List[Dict[str, Any]] = []

    # Run evaluations in order: baseline -> coordinated -> marl_ppo -> marl_dqn
    for mode in CONTROLLER_MODES:
        logger.info(f"\n--- COMMENCING SUITE: {CONTROLLER_DISPLAY_NAMES[mode]} ---")
        for seed in EVAL_SEEDS:
            res = run_single_evaluation(mode=mode, seed=seed)
            per_seed_results.append(res)

    total_time = time.time() - start_all
    logger.info("=" * 80)
    logger.info(f"ALL 20 EVALUATION RUNS COMPLETED IN {total_time:.1f}s (~{total_time/60:.1f} mins)")
    logger.info("=" * 80)

    # 1. Compute aggregate statistics
    stats_dict = compute_metrics_statistics(per_seed_results)

    # 2. Compute paired comparisons
    comparisons = compute_comparisons(stats_dict, per_seed_results)

    # 3. Export per-seed CSV
    per_seed_csv = RESULTS_DIR / "p5_per_seed_evaluation.csv"
    if per_seed_results:
        fieldnames = list(per_seed_results[0].keys())
        with open(per_seed_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(per_seed_results)
        logger.info(f"Saved per-seed CSV: {per_seed_csv}")

    # 4. Export aggregate CSV
    aggregate_csv = RESULTS_DIR / "p5_aggregate_evaluation.csv"
    agg_rows = []
    for mode in CONTROLLER_MODES:
        m_dict = stats_dict[mode]["metrics"]
        row = {
            "mode": mode,
            "display_name": CONTROLLER_DISPLAY_NAMES[mode],
            "travel_time_mean_s": m_dict["mean_corridor_travel_time_s"]["mean"],
            "travel_time_std_s": m_dict["mean_corridor_travel_time_s"]["std"],
            "cumulative_delay_mean_s": m_dict["cumulative_delay_veh_s"]["mean"],
            "cumulative_delay_std_s": m_dict["cumulative_delay_veh_s"]["std"],
            "mean_queue_veh": m_dict["mean_corridor_queue"]["mean"],
            "mean_queue_std": m_dict["mean_corridor_queue"]["std"],
            "trips_completed_mean": m_dict["total_corridor_trips_completed"]["mean"],
            "trips_completed_std": m_dict["total_corridor_trips_completed"]["std"],
            "mean_speed_kmh": m_dict["mean_corridor_speed_kmh"]["mean"],
            "fuel_liters_mean": m_dict["total_fuel_liters"]["mean"],
            "co2_kg_mean": m_dict["total_co2_kg"]["mean"],
            "emergency_clearance_mean_s": m_dict["emergency_traversal_duration_s"]["mean"],
        }
        agg_rows.append(row)

    if agg_rows:
        with open(aggregate_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(agg_rows[0].keys()))
            writer.writeheader()
            writer.writerows(agg_rows)
        logger.info(f"Saved aggregate CSV: {aggregate_csv}")

    # 5. Export comprehensive machine-readable JSON
    full_json_path = RESULTS_DIR / "p5_evaluation_results.json"
    full_output = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_evaluation_wall_time_s": total_time,
        "evaluation_seeds": EVAL_SEEDS,
        "duration_seconds": DURATION_S,
        "fuel_density_assumption": "0.750 kg/L (petrol reference density)",
        "controllers": CONTROLLER_MODES,
        "per_seed_results": per_seed_results,
        "aggregate_statistics": stats_dict,
        "comparisons": comparisons,
    }
    with open(full_json_path, "w", encoding="utf-8") as f:
        json.dump(full_output, f, indent=2)
    logger.info(f"Saved evaluation results JSON: {full_json_path}")

    # Print summary table
    print("\n" + "=" * 90)
    print("STAGE P5 EVALUATION SUMMARY (MEAN +/- STD OVER 5 SEEDS)")
    print("=" * 90)
    print(f"{'Controller':<26} | {'Travel Time (s)':<16} | {'Delay (veh-s)':<16} | {'Queue (veh)':<12} | {'Trips':<8} | {'Ambulance':<10}")
    print("-" * 90)
    for row in agg_rows:
        tt = f"{row['travel_time_mean_s']:.1f} +/- {row['travel_time_std_s']:.1f}"
        delay = f"{row['cumulative_delay_mean_s']:.0f} +/- {row['cumulative_delay_std_s']:.0f}"
        q = f"{row['mean_queue_veh']:.1f} +/- {row['mean_queue_std']:.1f}"
        trips = f"{row['trips_completed_mean']:.0f}"
        amb = f"{row['emergency_clearance_mean_s']:.1f}s"
        print(f"{row['display_name']:<26} | {tt:<16} | {delay:<16} | {q:<12} | {trips:<8} | {amb:<10}")
    print("=" * 90)


if __name__ == "__main__":
    main()

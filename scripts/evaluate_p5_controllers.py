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
- Robust missing data semantics: travel time is null/N/A when completed trips == 0;
  ambulance traversal is null/TIMEOUT when not cleared within the simulation horizon.

Outputs:
- results/p5/p5_per_seed_evaluation.csv
- results/p5/p5_aggregate_evaluation.csv
- results/p5/p5_evaluation_results.json
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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

METRIC_KEYS = [
    "mean_corridor_travel_time_s",
    "cumulative_delay_veh_s",
    "mean_corridor_queue",
    "total_corridor_trips_completed",
    "mean_corridor_speed_kmh",
    "total_fuel_liters",
    "total_co2_kg",
    "emergency_traversal_duration_s",
]

LOWER_IS_BETTER = {
    "mean_corridor_travel_time_s": True,
    "cumulative_delay_veh_s": True,
    "mean_corridor_queue": True,
    "total_corridor_trips_completed": False,
    "mean_corridor_speed_kmh": False,
    "total_fuel_liters": True,
    "total_co2_kg": True,
    "emergency_traversal_duration_s": True,
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

        trips = summary.total_corridor_trips_completed
        # Corrected reporting semantics:
        # None for travel time if 0 trips completed
        travel_time = summary.mean_corridor_travel_time_s if trips > 0 else None
        # None for emergency if not completed
        emergency_dur = summary.emergency_traversal_duration_s if summary.emergency_cleared else None

        result = {
            "mode": mode,
            "display_name": CONTROLLER_DISPLAY_NAMES[mode],
            "seed": seed,
            "duration_simulated_s": summary.simulation_duration,
            "wall_time_s": wall_time,
            "mean_corridor_travel_time_s": travel_time,
            "cumulative_delay_veh_s": summary.cumulative_delay_veh_s,
            "mean_corridor_queue": summary.mean_corridor_queue,
            "total_corridor_trips_completed": trips,
            "mean_corridor_speed_kmh": summary.mean_corridor_speed_kmh,
            "total_fuel_liters": summary.total_fuel_liters,
            "total_co2_kg": summary.total_co2_kg,
            "emergency_traversal_duration_s": emergency_dur,
            "emergency_clearance_status": "CLEARED" if emergency_dur is not None else "TIMEOUT (>600s)",
            "j1_mean_queue": summary.j1_mean_queue,
            "j2_mean_queue": summary.j2_mean_queue,
            "j3_mean_queue": summary.j3_mean_queue,
            "status": "COMPLETED",
        }
        tt_disp = f"{travel_time:.1f}s" if travel_time is not None else "N/A (0 trips)"
        amb_disp = f"{emergency_dur:.1f}s" if emergency_dur is not None else "TIMEOUT (>600s)"
        logger.info(
            f"    [{mode} Seed {seed}] Done in {wall_time:.1f}s | TravelTime={tt_disp} | "
            f"Delay={result['cumulative_delay_veh_s']:.0f}s | Trips={trips} | "
            f"Queue={result['mean_corridor_queue']:.1f} | Fuel={result['total_fuel_liters']:.2f}L | "
            f"Ambulance={amb_disp}"
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
            "emergency_clearance_status": "FAILED",
        }


def compute_metrics_statistics(
    per_seed_results: List[Dict[str, Any]]
) -> Dict[str, Dict[str, Any]]:
    """Computes mean, std, and 95% CI across evaluation seeds for each controller."""
    stats_dict: Dict[str, Dict[str, Any]] = {}

    for mode in CONTROLLER_MODES:
        mode_runs = [r for r in per_seed_results if r["mode"] == mode and r.get("status") == "COMPLETED"]
        stats_dict[mode] = {
            "display_name": CONTROLLER_DISPLAY_NAMES[mode],
            "completed_runs": len(mode_runs),
            "total_runs": len(EVAL_SEEDS),
            "metrics": {},
        }

        for m_key in METRIC_KEYS:
            vals = [float(r[m_key]) for r in mode_runs if r.get(m_key) is not None]
            val_map = {r["seed"]: r.get(m_key) for r in mode_runs}
            if vals:
                mean_val = float(np.mean(vals))
                std_val = float(np.std(vals, ddof=1)) if len(vals) > 1 else 0.0
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
                    "n_valid": len(vals),
                    "values_by_seed": val_map,
                }
            else:
                stats_dict[mode]["metrics"][m_key] = {
                    "mean": None,
                    "std": None,
                    "ci95": None,
                    "min": None,
                    "max": None,
                    "n_valid": 0,
                    "values_by_seed": val_map,
                }

    return stats_dict


def compute_comparisons(
    stats_dict: Dict[str, Dict[str, Any]],
    per_seed_results: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Computes relative percentage changes, paired t-tests, Wilcoxon signed-rank tests, and Cohen's d_z."""
    comparisons: Dict[str, Any] = {}

    base_m_dict = stats_dict["baseline"]["metrics"]
    coord_m_dict = stats_dict["coordinated"]["metrics"]

    for mode in ["coordinated", "marl_ppo", "marl_dqn"]:
        mode_comp = {
            "display_name": CONTROLLER_DISPLAY_NAMES[mode],
            "vs_baseline": {},
            "vs_coordinated": {},
        }

        for k, lower_better in LOWER_IS_BETTER.items():
            mode_metric = stats_dict[mode]["metrics"][k]

            for comp_name, comp_dict in [("vs_baseline", base_m_dict), ("vs_coordinated", coord_m_dict)]:
                comp_metric = comp_dict[k]

                mode_vals = [mode_metric["values_by_seed"][s] for s in EVAL_SEEDS]
                comp_vals = [comp_metric["values_by_seed"][s] for s in EVAL_SEEDS]

                has_none = any(v is None for v in mode_vals) or any(v is None for v in comp_vals)

                if has_none or mode_metric["mean"] is None or comp_metric["mean"] is None:
                    mode_comp[comp_name][k] = {
                        "rel_improvement_pct": None,
                        "mean_difference": None,
                        "ci95_difference": None,
                        "p_value_paired_t": None,
                        "t_statistic": None,
                        "is_significant_p05": False,
                        "wilcoxon_statistic": None,
                        "wilcoxon_p_value": None,
                        "cohens_d_z": None,
                        "status": "UNDEFINED: Missing valid completed measurements (zero trips or timeout)",
                    }
                else:
                    m_m = mode_metric["mean"]
                    c_m = comp_metric["mean"]

                    rel_pct = ((c_m - m_m) / c_m * 100.0) if lower_better else ((m_m - c_m) / c_m * 100.0)

                    m_arr = np.array(mode_vals, dtype=float)
                    c_arr = np.array(comp_vals, dtype=float)

                    diffs = m_arr - c_arr
                    mean_diff = float(np.mean(diffs))
                    std_diff = float(np.std(diffs, ddof=1)) if len(diffs) > 1 else 0.0
                    ci95_diff = float(stats.t.ppf(0.975, df=len(diffs) - 1) * (std_diff / math.sqrt(len(diffs)))) if std_diff > 0 else 0.0

                    if std_diff > 0:
                        t_res = stats.ttest_rel(m_arr, c_arr)
                        t_stat = float(t_res.statistic)
                        p_val = float(t_res.pvalue)
                    else:
                        t_stat = 0.0
                        p_val = 1.0

                    try:
                        w_res = stats.wilcoxon(m_arr, c_arr)
                        w_stat = float(w_res.statistic)
                        w_p = float(w_res.pvalue)
                    except Exception:
                        w_stat = None
                        w_p = None

                    cohen_d = float(abs(mean_diff) / std_diff) if std_diff > 0 else None

                    mode_comp[comp_name][k] = {
                        "rel_improvement_pct": float(rel_pct),
                        "mean_difference": mean_diff,
                        "ci95_difference": ci95_diff,
                        "t_statistic": t_stat,
                        "p_value_paired_t": p_val,
                        "is_significant_p05": bool(p_val < 0.05),
                        "wilcoxon_statistic": w_stat,
                        "wilcoxon_p_value": w_p,
                        "cohens_d_z": cohen_d,
                        "status": "VALID",
                    }

        comparisons[mode] = mode_comp

    return comparisons


def export_results(per_seed_results: List[Dict[str, Any]], stats_dict: Dict[str, Any], comparisons: Dict[str, Any], total_time: float) -> None:
    """Exports CSV and JSON artifacts with robust formatting for nulls/timeouts."""
    # 1. Per-seed CSV
    per_seed_csv = RESULTS_DIR / "p5_per_seed_evaluation.csv"
    with open(per_seed_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "mode", "display_name", "seed", "duration_simulated_s", "wall_time_s",
            "mean_corridor_travel_time_s", "cumulative_delay_veh_s", "mean_corridor_queue",
            "total_corridor_trips_completed", "mean_corridor_speed_kmh", "total_fuel_liters",
            "total_co2_kg", "emergency_traversal_duration_s", "emergency_clearance_status",
            "j1_mean_queue", "j2_mean_queue", "j3_mean_queue", "status"
        ])
        for r in per_seed_results:
            tt_str = f"{r['mean_corridor_travel_time_s']:.2f}" if r["mean_corridor_travel_time_s"] is not None else "N/A"
            amb_str = f"{r['emergency_traversal_duration_s']:.1f}" if r["emergency_traversal_duration_s"] is not None else "TIMEOUT"
            writer.writerow([
                r["mode"], r["display_name"], r["seed"], f"{r['duration_simulated_s']:.1f}",
                f"{r['wall_time_s']:.2f}", tt_str, f"{r['cumulative_delay_veh_s']:.1f}",
                f"{r['mean_corridor_queue']:.3f}", r["total_corridor_trips_completed"],
                f"{r['mean_corridor_speed_kmh']:.2f}", f"{r['total_fuel_liters']:.4f}",
                f"{r['total_co2_kg']:.4f}", amb_str, r.get("emergency_clearance_status", "UNKNOWN"),
                f"{r.get('j1_mean_queue', 0.0):.2f}", f"{r.get('j2_mean_queue', 0.0):.2f}",
                f"{r.get('j3_mean_queue', 0.0):.2f}", r["status"]
            ])
    logger.info(f"Saved per-seed CSV: {per_seed_csv}")

    # 2. Aggregate CSV
    aggregate_csv = RESULTS_DIR / "p5_aggregate_evaluation.csv"
    with open(aggregate_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "mode", "display_name",
            "travel_time_mean_s", "travel_time_std_s", "travel_time_ci95_s",
            "cumulative_delay_mean_s", "cumulative_delay_std_s", "cumulative_delay_ci95_s",
            "mean_queue_veh", "mean_queue_std", "mean_queue_ci95",
            "trips_completed_mean", "trips_completed_std",
            "mean_speed_kmh", "fuel_liters_mean", "co2_kg_mean",
            "emergency_clearance_mean_s", "emergency_status"
        ])
        for mode in CONTROLLER_MODES:
            m_dict = stats_dict[mode]["metrics"]
            tt_m = f"{m_dict['mean_corridor_travel_time_s']['mean']:.2f}" if m_dict['mean_corridor_travel_time_s']['mean'] is not None else "N/A"
            tt_s = f"{m_dict['mean_corridor_travel_time_s']['std']:.2f}" if m_dict['mean_corridor_travel_time_s']['std'] is not None else "N/A"
            tt_ci = f"{m_dict['mean_corridor_travel_time_s']['ci95']:.2f}" if m_dict['mean_corridor_travel_time_s']['ci95'] is not None else "N/A"

            del_m = f"{m_dict['cumulative_delay_veh_s']['mean']:.1f}"
            del_s = f"{m_dict['cumulative_delay_veh_s']['std']:.1f}"
            del_ci = f"{m_dict['cumulative_delay_veh_s']['ci95']:.1f}"

            q_m = f"{m_dict['mean_corridor_queue']['mean']:.2f}"
            q_s = f"{m_dict['mean_corridor_queue']['std']:.2f}"
            q_ci = f"{m_dict['mean_corridor_queue']['ci95']:.2f}"

            trips_m = f"{m_dict['total_corridor_trips_completed']['mean']:.1f}"
            trips_s = f"{m_dict['total_corridor_trips_completed']['std']:.1f}"

            spd_m = f"{m_dict['mean_corridor_speed_kmh']['mean']:.2f}"
            fuel_m = f"{m_dict['total_fuel_liters']['mean']:.2f}"
            co2_m = f"{m_dict['total_co2_kg']['mean']:.2f}"

            amb_m = f"{m_dict['emergency_traversal_duration_s']['mean']:.1f}" if m_dict['emergency_traversal_duration_s']['mean'] is not None else "TIMEOUT"
            amb_status = "CLEARED" if m_dict['emergency_traversal_duration_s']['mean'] is not None else "TIMEOUT (>600s)"

            writer.writerow([
                mode, CONTROLLER_DISPLAY_NAMES[mode],
                tt_m, tt_s, tt_ci,
                del_m, del_s, del_ci,
                q_m, q_s, q_ci,
                trips_m, trips_s,
                spd_m, fuel_m, co2_m,
                amb_m, amb_status
            ])
    logger.info(f"Saved aggregate CSV: {aggregate_csv}")

    # 3. Comprehensive machine-readable JSON
    full_json_path = RESULTS_DIR / "p5_evaluation_results.json"
    full_output = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_evaluation_wall_time_s": total_time,
        "evaluation_seeds": EVAL_SEEDS,
        "duration_seconds": DURATION_S,
        "fuel_density_assumption": "0.750 kg/L (petrol reference density: DIN EN 228 / HBEFA 4.2)",
        "statistical_limitations": {
            "evaluation_seeds_count": len(EVAL_SEEDS),
            "degrees_of_freedom": len(EVAL_SEEDS) - 1,
            "sample_size_note": "N=5 evaluation seeds provide pilot statistical power. Paired t-tests assume normality of pairwise differences. Non-parametric Wilcoxon signed-rank tests and Cohen's d_z effect sizes are provided alongside standard t-tests.",
            "missing_data_semantics": {
                "travel_time": "Reported as null (JSON) / 'N/A' (CSV) when total_corridor_trips_completed == 0.",
                "emergency_traversal": "Reported as null (JSON) / 'TIMEOUT' (CSV) when the emergency vehicle did not clear the corridor within the 600s horizon."
            }
        },
        "controllers": CONTROLLER_MODES,
        "per_seed_results": per_seed_results,
        "aggregate_statistics": stats_dict,
        "comparisons": comparisons,
    }
    with open(full_json_path, "w", encoding="utf-8") as f:
        json.dump(full_output, f, indent=2)
    logger.info(f"Saved evaluation results JSON: {full_json_path}")


def main():
    parser = argparse.ArgumentParser(description="Evaluate P5 controllers or recompute statistics")
    parser.add_argument("--recompute-only", action="store_true", help="Recompute statistics from existing per-run artifacts")
    args = parser.parse_args()

    start_all = time.time()

    if args.recompute_only:
        logger.info("Recomputing statistics from existing per-seed evaluation results...")
        per_seed_csv = RESULTS_DIR / "p5_per_seed_evaluation.csv"
        with open(per_seed_csv, "r", encoding="utf-8") as f:
            raw_rows = list(csv.DictReader(f))

        per_seed_results = []
        for r in raw_rows:
            mode = r["mode"]
            seed = int(r["seed"])
            trips = int(float(r["total_corridor_trips_completed"]))
            raw_tt = r.get("mean_corridor_travel_time_s")
            raw_amb = r.get("emergency_traversal_duration_s")

            tt_val = None
            if trips > 0 and raw_tt is not None and raw_tt not in ("N/A", ""):
                val = float(raw_tt)
                if val > 0.0:
                    tt_val = val

            amb_val = None
            if raw_amb is not None and raw_amb not in ("TIMEOUT", "N/A", ""):
                val = float(raw_amb)
                if val > 0.0:
                    amb_val = val

            per_seed_results.append({
                "mode": mode,
                "display_name": CONTROLLER_DISPLAY_NAMES[mode],
                "seed": seed,
                "duration_simulated_s": float(r.get("duration_simulated_s", 600.0)),
                "wall_time_s": float(r.get("wall_time_s", 0.0)),
                "mean_corridor_travel_time_s": tt_val,
                "cumulative_delay_veh_s": float(r["cumulative_delay_veh_s"]),
                "mean_corridor_queue": float(r["mean_corridor_queue"]),
                "total_corridor_trips_completed": trips,
                "mean_corridor_speed_kmh": float(r["mean_corridor_speed_kmh"]),
                "total_fuel_liters": float(r["total_fuel_liters"]),
                "total_co2_kg": float(r["total_co2_kg"]),
                "emergency_traversal_duration_s": amb_val,
                "emergency_clearance_status": "CLEARED" if amb_val is not None else "TIMEOUT (>600s)",
                "j1_mean_queue": float(r.get("j1_mean_queue", 0.0)),
                "j2_mean_queue": float(r.get("j2_mean_queue", 0.0)),
                "j3_mean_queue": float(r.get("j3_mean_queue", 0.0)),
                "status": r.get("status", "COMPLETED"),
            })
    else:
        logger.info("=" * 80)
        logger.info("STARTING STAGE P5 INDEPENDENT MULTI-SEED CONTROLLER EVALUATION")
        logger.info(f"Controllers: {CONTROLLER_MODES}")
        logger.info(f"Evaluation Seeds: {EVAL_SEEDS} | Horizon: {DURATION_S}s | Mode: Deterministic")
        logger.info("=" * 80)

        per_seed_results = []
        for mode in CONTROLLER_MODES:
            logger.info(f"\n--- COMMENCING SUITE: {CONTROLLER_DISPLAY_NAMES[mode]} ---")
            for seed in EVAL_SEEDS:
                res = run_single_evaluation(mode=mode, seed=seed)
                per_seed_results.append(res)

    total_time = time.time() - start_all

    stats_dict = compute_metrics_statistics(per_seed_results)
    comparisons = compute_comparisons(stats_dict, per_seed_results)
    export_results(per_seed_results, stats_dict, comparisons, total_time)

    # Print summary table
    print("\n" + "=" * 100)
    print("STAGE P5 EVALUATION SUMMARY (MEAN +/- STD OVER 5 SEEDS — CORRECTED SEMANTICS)")
    print("=" * 100)
    print(f"{'Controller':<26} | {'Travel Time (s)':<18} | {'Delay (veh-s)':<18} | {'Queue (veh)':<14} | {'Trips':<8} | {'Ambulance':<12}")
    print("-" * 100)
    for mode in CONTROLLER_MODES:
        m = stats_dict[mode]["metrics"]
        tt = f"{m['mean_corridor_travel_time_s']['mean']:.1f} +/- {m['mean_corridor_travel_time_s']['std']:.1f}" if m['mean_corridor_travel_time_s']['mean'] is not None else "N/A (0 trips)"
        delay = f"{m['cumulative_delay_veh_s']['mean']:.0f} +/- {m['cumulative_delay_veh_s']['std']:.0f}"
        q = f"{m['mean_corridor_queue']['mean']:.1f} +/- {m['mean_corridor_queue']['std']:.1f}"
        trips = f"{m['total_corridor_trips_completed']['mean']:.0f}"
        amb = f"{m['emergency_traversal_duration_s']['mean']:.1f}s" if m['emergency_traversal_duration_s']['mean'] is not None else "TIMEOUT"
        print(f"{CONTROLLER_DISPLAY_NAMES[mode]:<26} | {tt:<18} | {delay:<18} | {q:<14} | {trips:<8} | {amb:<12}")
    print("=" * 100)


if __name__ == "__main__":
    main()

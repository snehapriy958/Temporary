"""
scripts/evaluate_corridor.py

Full multi-seed evaluation comparing:
1. Baseline (Uncoordinated Fixed-Time signals at J1, J2, J3)
2. Coordinated (Adaptive corridor control + inter-intersection communication + emergency green wave)

Evaluates corridor travel time, speeds, queues, waiting times, CO2 emissions, fuel,
and emergency vehicle response times across multiple random seeds.
"""

from __future__ import annotations

import csv
from pathlib import Path
import statistics
import sys

# Ensure repository root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from traffic_service.multi_intersection_simulation import MultiIntersectionSimulation


SUMO_CONFIG = PROJECT_ROOT / "sumo" / "silk_board" / "silk_board.sumocfg"
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "corridor"
SEEDS = [1, 2, 3, 4, 5]
DURATION = 600  # seconds


def run_experiment(mode: str, seed: int) -> dict:
    """Runs a single simulation episode in the given mode with the given seed."""
    print(f"--> Running {mode.upper()} [Seed {seed}]...")
    sim = MultiIntersectionSimulation(
        sumocfg_path=SUMO_CONFIG,
        mode=mode,
        step_length=1.0,
        decision_interval=5.0,
        enable_emergency=True,
    )
    summary = sim.run_full_simulation(duration_seconds=DURATION, seed=seed)

    # Save detailed per-step metrics
    run_csv = OUTPUT_DIR / mode / f"seed_{seed}.csv"
    sim.metrics_collector.export_csv(run_csv)

    return {
        "seed": seed,
        "mode": mode,
        "mean_corridor_travel_time_s": summary.mean_corridor_travel_time_s,
        "total_corridor_trips_completed": summary.total_corridor_trips_completed,
        "mean_corridor_speed_kmh": summary.mean_corridor_speed_kmh,
        "total_corridor_waiting_time_s": summary.total_corridor_waiting_time_s,
        "mean_corridor_queue": summary.mean_corridor_queue,
        "max_corridor_queue": summary.max_corridor_queue,
        "total_co2_kg": summary.total_co2_kg,
        "total_fuel_liters": summary.total_fuel_liters,
        "emergency_traversal_duration_s": summary.emergency_traversal_duration_s,
        "j1_mean_queue": summary.j1_mean_queue,
        "j2_mean_queue": summary.j2_mean_queue,
        "j3_mean_queue": summary.j3_mean_queue,
    }


def compute_stats(values: list[float]) -> tuple[float, float]:
    """Returns (mean, standard_deviation)."""
    if not values:
        return 0.0, 0.0
    m = statistics.mean(values)
    s = statistics.stdev(values) if len(values) > 1 else 0.0
    return m, s


def calculate_improvement(baseline: float, coordinated: float, higher_is_better: bool = False) -> float:
    """Calculates percentage improvement."""
    if baseline == 0.0:
        return 0.0
    if higher_is_better:
        return ((coordinated - baseline) / baseline) * 100.0
    return ((baseline - coordinated) / baseline) * 100.0


def main() -> None:
    print("=" * 80)
    print("CORRIDOR-LEVEL TRAFFIC & EMISSION EVALUATION (J1 -> J2 -> J3)")
    print("Baseline (Uncoordinated) vs. Coordinated Control")
    print(f"Seeds: {SEEDS} | Episode Duration: {DURATION}s")
    print("=" * 80)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "baseline").mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "coordinated").mkdir(parents=True, exist_ok=True)

    baseline_results = []
    coordinated_results = []

    for seed in SEEDS:
        baseline_results.append(run_experiment("baseline", seed))
        coordinated_results.append(run_experiment("coordinated", seed))

    # Compile metric comparison
    metrics_to_compare = [
        ("mean_corridor_queue", "Average Corridor Queue (veh)", False),
        ("max_corridor_queue", "Max Corridor Queue (veh)", False),
        ("mean_corridor_travel_time_s", "Corridor Travel Time (s)", False),
        ("total_corridor_waiting_time_s", "Total Waiting Time (s)", False),
        ("mean_corridor_speed_kmh", "Average Speed (km/h)", True),
        ("total_corridor_trips_completed", "Completed Corridor Trips", True),
        ("total_co2_kg", "Total CO2 Emissions (kg)", False),
        ("total_fuel_liters", "Total Fuel Consumed (L)", False),
        ("emergency_traversal_duration_s", "Ambulance Traversal Time (s)", False),
    ]

    summary_rows = []
    print("\n" + "=" * 90)
    print(f"{'METRIC':<35} | {'BASELINE (Mean ± Std)':<22} | {'COORDINATED (Mean ± Std)':<22} | {'IMPROVEMENT':<12}")
    print("-" * 90)

    for key, label, higher_is_better in metrics_to_compare:
        b_vals = [r[key] for r in baseline_results]
        c_vals = [r[key] for r in coordinated_results]

        b_mean, b_std = compute_stats(b_vals)
        c_mean, c_std = compute_stats(c_vals)

        imp = calculate_improvement(b_mean, c_mean, higher_is_better=higher_is_better)
        direction_sign = "+" if imp >= 0 else ""

        print(
            f"{label:<35} | {b_mean:8.2f} ± {b_std:<8.2f} | {c_mean:8.2f} ± {c_std:<8.2f} | {direction_sign}{imp:6.2f}%"
        )

        summary_rows.append({
            "metric": key,
            "label": label,
            "baseline_mean": b_mean,
            "baseline_std": b_std,
            "coordinated_mean": c_mean,
            "coordinated_std": c_std,
            "improvement_percent": imp,
        })

    print("=" * 90)

    # Save summary CSV
    summary_file = OUTPUT_DIR / "corridor_multi_seed_summary.csv"
    with summary_file.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "metric",
                "label",
                "baseline_mean",
                "baseline_std",
                "coordinated_mean",
                "coordinated_std",
                "improvement_percent",
            ],
        )
        writer.writeheader()
        writer.writerows(summary_rows)

    print(f"\nFinal summary written to: {summary_file}")


if __name__ == "__main__":
    main()

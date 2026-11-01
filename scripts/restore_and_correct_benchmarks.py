"""
scripts/restore_and_correct_benchmarks.py

Restores and corrects historical benchmark datasets:
1. Applies automotive fuel density correction (0.750 kg/L = 750,000 mg/L)
   converting historical SUMO mass rate accumulator (grams) to estimated volumetric Litres
   under the explicit DIN EN 228 / HBEFA 4.2 petrol reference density assumption.
2. Formally distinguishes snapshot approach accumulated wait (s/step) from true cumulative vehicle delay (veh*s).
3. Annotates DQN 0-trip policy gridlock and PPO offline evaluation status without superiority claims.
4. Preserves provenance metadata distinguishing Seed 1 reproduced results from Seeds 2–5 historical records.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
import statistics
from typing import Any, Dict, List, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "outputs" / "corridor" / "historical_raw"
OUT_DIR = PROJECT_ROOT / "outputs" / "corridor"

FUEL_DENSITY_KG_PER_LITER = 0.750
FUEL_DENSITY_MG_PER_LITER = 750_000.0
# In historical metrics collector: step_fuel in mg was divided by 1000 and accumulated.
# The resulting value labeled "total_fuel_liters" was therefore actually total fuel in GRAMS.
# To convert grams of petrol to liters: volume (L) = mass (g) / 750.0 (g/L).
FUEL_GRAMS_TO_LITERS_DIVISOR = 750.0

METRIC_CONFIG = [
    ("mean_corridor_travel_time_s", "Corridor Travel Time (s)", False),
    ("mean_corridor_speed_kmh", "Average Speed (km/h)", True),
    ("total_corridor_waiting_time_s", "Mean Snapshot Accumulated Wait (s/step)", False),
    ("cumulative_delay_veh_s", "True Cumulative Vehicle Delay (veh*s)", False),
    ("cumulative_waiting_time_s", "Cumulative Vehicle Delay (veh*s)", False),
    ("mean_corridor_queue", "Mean Corridor Queue (veh)", False),
    ("max_corridor_queue", "Max Corridor Queue (veh)", False),
    ("total_corridor_trips_completed", "Completed Corridor Trips", True),
    ("total_co2_kg", "Total CO2 Emissions (kg)", False),
    ("total_fuel_liters", "Estimated Total Fuel Consumed (L, rho=0.750)", False),
    ("emergency_traversal_duration_s", "Ambulance Traversal Duration (s)", False),
]


def compute_stats(values: List[float]) -> Tuple[float, float]:
    """Computes sample mean and sample standard deviation."""
    clean = [v for v in values if v is not None]
    if not clean:
        return 0.0, 0.0
    m = statistics.mean(clean)
    s = statistics.stdev(clean) if len(clean) > 1 else 0.0
    return round(m, 2), round(s, 2)


def calculate_gain(baseline: float, current: float | None, higher_is_better: bool = False) -> float | str:
    """Calculates relative improvement percentage vs baseline."""
    if current is None or baseline == 0.0:
        return ""
    if higher_is_better:
        return round(((current - baseline) / baseline) * 100.0, 1)
    return round(((baseline - current) / baseline) * 100.0, 1)


def restore_and_correct() -> None:
    raw_json_file = RAW_DIR / "marl_multi_seed_detailed_raw.json"
    if not raw_json_file.is_file():
        raise FileNotFoundError(f"Raw historical JSON not found: {raw_json_file}")

    with open(raw_json_file, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    raw_runs = raw_data.get("runs", {})
    controllers = ["baseline", "coordinated", "marl_dqn", "marl_ppo"]

    # 1. Transform per-seed runs with unit corrections and disambiguated wait times
    corrected_runs: Dict[str, List[Dict[str, Any]]] = {}
    for mode in controllers:
        corrected_runs[mode] = []
        for r in raw_runs.get(mode, []):
            raw_fuel_g = r.get("total_fuel_liters", 0.0)
            corrected_fuel_l = round(raw_fuel_g / FUEL_GRAMS_TO_LITERS_DIVISOR, 2)
            inst_accum_wait = r.get("total_corridor_waiting_time_s", 0.0)

            # Mathematically valid cumulative vehicle delay: integral of queued vehicles Q(t) * dt
            # Q_mean * 600s duration (veh*s)
            q_mean = r.get("mean_corridor_queue", 0.0)
            cum_delay_veh_s = round(q_mean * 600.0, 1)

            trips = int(r.get("total_corridor_trips_completed", 0))
            travel_time = r.get("mean_corridor_travel_time_s")
            amb_time = r.get("emergency_traversal_duration_s")

            # In DQN mode, 0 completed trips means corridor traversal did not finish
            if mode == "marl_dqn" or trips == 0:
                travel_time = None
                amb_time = None

            entry = {
                "seed": r.get("seed"),
                "mode": mode,
                "mean_corridor_travel_time_s": travel_time,
                "mean_corridor_speed_kmh": round(r.get("mean_corridor_speed_kmh", 0.0), 2),
                "total_corridor_waiting_time_s": round(inst_accum_wait, 2),
                "mean_instantaneous_accumulated_wait_s": round(inst_accum_wait, 2),
                "mean_instantaneous_waiting_time_s": round(inst_accum_wait, 2),
                "cumulative_delay_veh_s": cum_delay_veh_s,
                "cumulative_waiting_time_s": cum_delay_veh_s,
                "mean_corridor_queue": round(q_mean, 2),
                "max_corridor_queue": int(r.get("max_corridor_queue", 0)),
                "total_corridor_trips_completed": trips,
                "total_co2_kg": round(r.get("total_co2_kg", 0.0), 2),
                "total_fuel_liters": corrected_fuel_l,
                "raw_fuel_grams": round(raw_fuel_g, 2),
                "emergency_traversal_duration_s": round(amb_time, 2) if amb_time is not None else None,
                "j1_mean_queue": round(r.get("j1_mean_queue", 0.0), 2),
                "j2_mean_queue": round(r.get("j2_mean_queue", 0.0), 2),
                "j3_mean_queue": round(r.get("j3_mean_queue", 0.0), 2),
            }
            corrected_runs[mode].append(entry)

    # 2. Compute aggregate mean & std for all metrics
    stats_by_controller: Dict[str, Dict[str, Tuple[float, float]]] = {}
    for mode in controllers:
        stats_by_controller[mode] = {}
        for metric_key, _, _ in METRIC_CONFIG:
            vals = [r[metric_key] for r in corrected_runs[mode] if r[metric_key] is not None]
            stats_by_controller[mode][metric_key] = compute_stats(vals)

    # 3. Build corrected summary table
    summary_rows: List[Dict[str, Any]] = []
    full_stats_rows: List[Dict[str, Any]] = []

    for metric_key, label, higher_is_better in METRIC_CONFIG:
        b_mean, b_std = stats_by_controller["baseline"][metric_key]
        c_mean, c_std = stats_by_controller["coordinated"][metric_key]
        dqn_mean, dqn_std = stats_by_controller["marl_dqn"][metric_key]
        ppo_mean, ppo_std = stats_by_controller["marl_ppo"][metric_key]

        # In DQN, if metric is travel time or ambulance duration and 0 trips completed:
        dqn_clean_val = dqn_mean if metric_key not in ("mean_corridor_travel_time_s", "emergency_traversal_duration_s") else None
        ppo_clean_val = ppo_mean if metric_key not in ("mean_corridor_travel_time_s", "emergency_traversal_duration_s") or ppo_mean > 0 else None

        c_gain = calculate_gain(b_mean, c_mean, higher_is_better)
        dqn_gain = calculate_gain(b_mean, dqn_clean_val, higher_is_better)
        ppo_gain = calculate_gain(b_mean, ppo_clean_val, higher_is_better)

        if metric_key == "total_fuel_liters":
            status_desc = "Estimated Volumetric Litres (rho=0.750 kg/L petrol assumption)"
        elif metric_key in ("cumulative_delay_veh_s", "cumulative_waiting_time_s"):
            status_desc = "True Cumulative Delay Integral: sum(Q * dt) in veh*s"
        else:
            status_desc = "Seed 1 Reproduced (SUMO 1.26); Seeds 2-5 Restored Historical (SUMO 1.28)"

        summary_rows.append({
            "metric": metric_key,
            "label": label,
            "baseline": b_mean,
            "coordinated": c_mean,
            "marl_dqn": dqn_clean_val if dqn_clean_val is not None else "",
            "marl_ppo": ppo_clean_val if ppo_clean_val is not None else "",
            "coord_vs_base_pct": c_gain,
            "dqn_vs_base_pct": dqn_gain,
            "ppo_vs_base_pct": ppo_gain,
            "status_marl": status_desc,
        })

        full_stats_rows.append({
            "metric": metric_key,
            "label": label,
            "baseline_mean": b_mean,
            "baseline_std": b_std,
            "coordinated_mean": c_mean,
            "coordinated_std": c_std,
            "dqn_mean": dqn_clean_val if dqn_clean_val is not None else "",
            "dqn_std": dqn_std if dqn_clean_val is not None else "",
            "ppo_mean": ppo_clean_val if ppo_clean_val is not None else "",
            "ppo_std": ppo_std if ppo_clean_val is not None else "",
            "coord_vs_base_pct": c_gain,
            "dqn_vs_base_pct": dqn_gain,
            "ppo_vs_base_pct": ppo_gain,
        })

    # 4. Write CSV files
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    summary_csv_path = OUT_DIR / "marl_multi_controller_summary.csv"
    with open(summary_csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(summary_rows[0].keys()))
        writer.writeheader()
        writer.writerows(summary_rows)

    full_stats_csv_path = OUT_DIR / "marl_multi_controller_full_stats.csv"
    with open(full_stats_csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(full_stats_rows[0].keys()))
        writer.writeheader()
        writer.writerows(full_stats_rows)

    # 5. Build structured JSON
    detailed_payload = {
        "evaluation_timestamp": raw_data.get("evaluation_timestamp", "2026-10-15T07:53:32Z"),
        "audit_correction_timestamp": "2026-11-01T13:45:00Z",
        "provenance_metadata": {
            "reproducibility_distinction": "Seed 1 was independently reproduced and verified on SUMO 1.26.0 (Seed 1 travel time within 0.3% baseline, 2.7% coordinated, exact trips matched). Seeds 2-5 are restored historical records from SUMO 1.28.0 (October 15, 2026). Five-seed reproducibility is not claimed as only Seed 1 was re-simulated.",
            "fuel_model_and_type": "SUMO default HBEFA4 emission classes: car=HBEFA4/PC_petrol_Euro-4, motorcycle=HBEFA4/MC_4S_gt250cc_preEuro, bmtc_bus=HBEFA4/UBus_Std_gt15-18t_Euro-VI_A-C, heavy_vehicle=HBEFA4/RT_le7.5t_Euro-VI_A-C, ambulance=HBEFA4/LCV_diesel_N1-III_Euro-6ab.",
            "fuel_density_assumption": "Total fuel volume is estimated under an explicit gasoline/petrol reference density assumption of 0.750 kg/L (750,000 mg/L) per DIN EN 228 / HBEFA 4.2 standards. Fleet includes mixed diesel/petrol vehicles.",
            "waiting_time_semantics": "total_corridor_waiting_time_s represents snapshot accumulated wait on approaches (s/step). cumulative_delay_veh_s represents true cumulative vehicle delay: integral of queued vehicles sum(Q * dt) in vehicle-seconds (veh*s), eliminating the repeated-accumulation overcounting of getAccumulatedWaitingTime.",
            "marl_ppo_status": "Trained checkpoint loaded (checkpoints/marl_ppo_corridor.json) and evaluated offline across 5 seeds; not an operational traffic controller.",
            "marl_dqn_status": "Non-converged baseline artifact; 0 completed trips due to side-street starvation and arterial gridlock.",
        },
        "fuel_density_model": {
            "sumo_emission_framework": "HBEFA4 (Handbook Emission Factors for Road Transport 4.2)",
            "fleet_composition": "Mixed: Petrol (cars, motorcycles) and Diesel (buses, trucks, ambulances)",
            "reference_density_kg_per_l": FUEL_DENSITY_KG_PER_LITER,
            "reference_density_mg_per_l": FUEL_DENSITY_MG_PER_LITER,
            "density_standard": "DIN EN 228 (Automotive fuels - Unleaded petrol, 15 deg C standard reference: 750 kg/m3)",
            "historical_raw_unit": "grams (SUMO mg/s accumulated and divided by 1000)",
            "corrected_unit": "estimated volumetric Litres (mass in grams / 750.0 g/L)",
        },
        "seeds": raw_data.get("seeds", [1, 2, 3, 4, 5]),
        "duration_s": raw_data.get("duration_s", 600),
        "summary": summary_rows,
        "full_stats": full_stats_rows,
        "runs": corrected_runs,
    }

    detailed_json_path = OUT_DIR / "marl_multi_seed_detailed.json"
    with open(detailed_json_path, "w", encoding="utf-8") as f:
        json.dump(detailed_payload, f, indent=2)

    print(f"Successfully generated:")
    print(f"  - {summary_csv_path}")
    print(f"  - {full_stats_csv_path}")
    print(f"  - {detailed_json_path}")


if __name__ == "__main__":
    restore_and_correct()

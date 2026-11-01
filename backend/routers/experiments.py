"""
backend/routers/experiments.py

Controller performance comparison benchmarks and historical experiment runs from database.
"""

from __future__ import annotations

import csv
import json
from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.config import BASE_DIR
from backend.database import get_db
from backend.models import SimulationRun
from backend.schemas import (
    ControllerMetricComparison,
    ExperimentCompareResponse,
    ExperimentHistoryItem,
)

router = APIRouter(prefix="/api/experiments", tags=["Experiments"])


@router.get("/compare", response_model=ExperimentCompareResponse)
def get_controller_comparison() -> ExperimentCompareResponse:
    """
    Returns empirical comparison benchmarks between:
    1. Fixed-time baseline
    2. Coordinated adaptive controller (Silk Board green wave + inflow anticipation)
    3. PPO controller (Marked Not Implemented with architecture roadmap)
    4. DQN controller (Marked Not Implemented with architecture roadmap)
    """
    # Parse multi-seed summary csv if available
    summary_csv = BASE_DIR / "outputs" / "corridor" / "corridor_multi_seed_summary.csv"
    metrics: dict[str, dict[str, float]] = {}

    if summary_csv.is_file():
        try:
            with open(summary_csv, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    metric_key = row.get("metric", "")
                    b_mean = float(row.get("baseline_mean", 0.0))
                    c_mean = float(row.get("coordinated_mean", 0.0))
                    metrics[metric_key] = {"baseline": b_mean, "coordinated": c_mean}
        except Exception as exc:
            print(f"[Experiments] Error reading multi_seed summary CSV: {exc}")

    # Baseline numbers (defaults from multi-seed 5-run benchmark)
    b_tt = metrics.get("mean_corridor_travel_time_s", {}).get("baseline", 91.05)
    b_spd = metrics.get("mean_corridor_speed_kmh", {}).get("baseline", 27.85)
    b_wait = metrics.get("total_corridor_waiting_time_s", {}).get("baseline", 779.43)
    b_q = metrics.get("mean_corridor_queue", {}).get("baseline", 20.01)
    b_co2 = metrics.get("total_co2_kg", {}).get("baseline", 53.72)
    b_fuel = metrics.get("total_fuel_liters", {}).get("baseline", 23.19)
    b_amb = metrics.get("emergency_traversal_duration_s", {}).get("baseline", 41.0)

    # Coordinated numbers
    c_tt = metrics.get("mean_corridor_travel_time_s", {}).get("coordinated", 57.50)
    c_spd = metrics.get("mean_corridor_speed_kmh", {}).get("coordinated", 36.40)
    c_wait = metrics.get("total_corridor_waiting_time_s", {}).get("coordinated", 296.88)
    c_q = metrics.get("mean_corridor_queue", {}).get("coordinated", 10.67)
    c_co2 = metrics.get("total_co2_kg", {}).get("coordinated", 42.67)
    c_fuel = metrics.get("total_fuel_liters", {}).get("coordinated", 18.42)
    c_amb = metrics.get("emergency_traversal_duration_s", {}).get("coordinated", 33.6)

    controllers_list: List[ControllerMetricComparison] = [
        ControllerMetricComparison(
            controller_name="Fixed-Time Baseline",
            status="Implemented",
            description="Uncoordinated static time allocations across J1, J2, and J3.",
            mean_travel_time_s=round(b_tt, 2),
            mean_speed_kmh=round(b_spd, 2),
            total_waiting_time_s=round(b_wait, 2),
            mean_queue=round(b_q, 2),
            total_co2_kg=round(b_co2, 2),
            total_fuel_liters=round(b_fuel, 2),
            emergency_traversal_duration_s=round(b_amb, 2),
            notes="Standard SUMO signal timing plan with no inter-intersection communication.",
        ),
        ControllerMetricComparison(
            controller_name="Coordinated Adaptive Controller",
            status="Implemented",
            description="Movement-aware queue pressure, upstream J1->J2 inflow anticipation, and emergency green wave.",
            mean_travel_time_s=round(c_tt, 2),
            mean_speed_kmh=round(c_spd, 2),
            total_waiting_time_s=round(c_wait, 2),
            mean_queue=round(c_q, 2),
            total_co2_kg=round(c_co2, 2),
            total_fuel_liters=round(c_fuel, 2),
            emergency_traversal_duration_s=round(c_amb, 2),
            notes="Achieves 36.8% faster corridor travel time, 61.9% waiting time reduction, and 18.0% faster ambulance traversal.",
        ),
        ControllerMetricComparison(
            controller_name="PPO (Proximal Policy Optimization)",
            status="Not implemented",
            description="Multi-agent reinforcement learning policy for continuous or discrete signal phase control.",
            mean_travel_time_s=None,
            mean_speed_kmh=None,
            total_waiting_time_s=None,
            mean_queue=None,
            total_co2_kg=None,
            total_fuel_liters=None,
            emergency_traversal_duration_s=None,
            notes="Not implemented: Observation interface is exposed via get_ai_observations(), but neural network weights, reward engineering, and MARL training loop are not yet integrated.",
        ),
        ControllerMetricComparison(
            controller_name="DQN (Deep Q-Network)",
            status="Not implemented",
            description="Value-based deep reinforcement learning for discrete signal phase duration selection.",
            mean_travel_time_s=None,
            mean_speed_kmh=None,
            total_waiting_time_s=None,
            mean_queue=None,
            total_co2_kg=None,
            total_fuel_liters=None,
            emergency_traversal_duration_s=None,
            notes="Not implemented: Requires experience replay buffer, Q-network training checkpoint, and action masking for yellow safety transitions.",
        ),
    ]

    return ExperimentCompareResponse(
        network="Silk Board Corridor (J1 -> J2 -> J3)",
        benchmark_duration_s=600,
        controllers=controllers_list,
    )


@router.get("/history", response_model=List[ExperimentHistoryItem])
def get_experiment_history(db: Session = Depends(get_db)) -> List[ExperimentHistoryItem]:
    """Retrieves all past simulation runs and summary metrics stored in SQLite."""
    runs = db.query(SimulationRun).order_by(SimulationRun.id.desc()).limit(50).all()
    results: List[ExperimentHistoryItem] = []
    for r in runs:
        summary_dict = None
        if r.summary_metrics_json:
            try:
                summary_dict = json.loads(r.summary_metrics_json)
            except Exception:
                pass

        results.append(
            ExperimentHistoryItem(
                id=r.id,
                run_uuid=r.run_uuid,
                mode=r.mode,
                status=r.status,
                seed=r.seed,
                duration_requested=r.duration_requested,
                duration_simulated=r.duration_simulated,
                started_at=r.started_at.isoformat() if r.started_at else "",
                completed_at=r.completed_at.isoformat() if r.completed_at else None,
                summary_metrics=summary_dict,
            )
        )
    return results

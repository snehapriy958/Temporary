"""
traffic_service/ai/starvation_tracker.py

Anti-Starvation Safety Constraint Engine for Multi-Intersection Corridor.
Tracks red phase residency per incoming approach, detects phase starvation,
enforces strict action masking to force phase switches when thresholds are breached,
and records auditable starvation logs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

logger = logging.getLogger("starvation_tracker")

# Default phase mappings: approach -> green phase index
DEFAULT_APPROACH_GREEN_PHASES = {
    "J1": {
        "corridor_hosur": 2,
        "side_cross": 0,
    },
    "J2": {
        "corridor_hosur": 0,
        "madiwala": 2,
    },
    "J3": {
        "corridor_hosur": 2,
        "side_cross": 0,
    },
}

DEFAULT_MAX_RED_THRESHOLD_S = 60.0


@dataclass
class StarvationEvent:
    """Audit record for a forced signal switch caused by approach starvation."""
    timestamp: float
    junction_id: str
    starved_approach: str
    red_duration_s: float
    threshold_s: float
    queue_count: int
    current_phase: int
    target_phase: int
    action_enforced: str = "SWITCH"


class StarvationTracker:
    """
    Monitors red duration on all junction approaches and enforces anti-starvation constraints.
    Guarantees no queued movement is starved beyond max_red_threshold_s.
    """

    def __init__(
        self,
        approach_green_phases: Optional[Dict[str, Dict[str, int]]] = None,
        max_red_threshold_s: float = DEFAULT_MAX_RED_THRESHOLD_S,
        min_queue_to_starve: int = 1,
    ) -> None:
        self.approach_green_phases = approach_green_phases or DEFAULT_APPROACH_GREEN_PHASES
        self.max_red_threshold_s = float(max_red_threshold_s)
        self.min_queue_to_starve = int(min_queue_to_starve)

        # Elapsed red time: junction_id -> {approach: seconds}
        self.red_elapsed: Dict[str, Dict[str, float]] = {
            j_id: {app: 0.0 for app in apps}
            for j_id, apps in self.approach_green_phases.items()
        }

        # Elapsed queued red time: junction_id -> {approach: seconds} while queue >= min_queue_to_starve
        self.queued_red_elapsed: Dict[str, Dict[str, float]] = {
            j_id: {app: 0.0 for app in apps}
            for j_id, apps in self.approach_green_phases.items()
        }

        # Current approach queues cache: junction_id -> {approach: count}
        self.current_queues: Dict[str, Dict[str, int]] = {
            j_id: {app: 0 for app in apps}
            for j_id, apps in self.approach_green_phases.items()
        }

        # Audit log of starvation interventions
        self.events: List[StarvationEvent] = []
        self._last_update_time: Optional[float] = None

    def reset(self) -> None:
        """Resets all red timers, queue caches, and events."""
        for j_id in self.red_elapsed:
            for app in self.red_elapsed[j_id]:
                self.red_elapsed[j_id][app] = 0.0
                self.queued_red_elapsed[j_id][app] = 0.0
                self.current_queues[j_id][app] = 0
        self.events.clear()
        self._last_update_time = None

    def update(
        self,
        current_phases: Dict[str, int],
        approach_queues: Dict[str, Dict[str, int]],
        step_length: float = 1.0,
        sim_time: float = 0.0,
    ) -> None:
        """
        Updates red duration timers across all monitored approaches.
        Called at every simulation step (typically 1.0s).
        Guards against double-accumulation if invoked multiple times at the same sim_time.
        """
        is_duplicate_step = (
            self._last_update_time is not None
            and np.isclose(sim_time, self._last_update_time, atol=1e-3)
        )

        for j_id, apps in self.approach_green_phases.items():
            raw_curr_p = current_phases.get(j_id, 0)
            try:
                curr_p = int(raw_curr_p) if not (isinstance(raw_curr_p, float) and np.isnan(raw_curr_p)) else 0
            except (ValueError, TypeError):
                curr_p = 0
            q_map = approach_queues.get(j_id, {})

            for app, green_p in apps.items():
                raw_q = q_map.get(app, 0)
                try:
                    q = int(raw_q) if not (isinstance(raw_q, float) and np.isnan(raw_q)) else 0
                except (ValueError, TypeError):
                    q = 0
                self.current_queues[j_id][app] = q

                if curr_p == green_p:
                    # Approach is currently receiving green: reset red duration
                    self.red_elapsed[j_id][app] = 0.0
                    self.queued_red_elapsed[j_id][app] = 0.0
                else:
                    # Approach is facing red: accumulate red time unless duplicate call in same second
                    if not is_duplicate_step:
                        self.red_elapsed[j_id][app] += step_length
                        if q >= self.min_queue_to_starve:
                            self.queued_red_elapsed[j_id][app] += step_length
                        else:
                            self.queued_red_elapsed[j_id][app] = 0.0

        if not is_duplicate_step:
            self._last_update_time = sim_time

    def get_starved_approaches(self, j_id: str) -> List[Dict[str, Any]]:
        """
        Identifies any approach at j_id exceeding max_red_threshold_s with queued vehicles.
        """
        starved: List[Dict[str, Any]] = []
        apps = self.approach_green_phases.get(j_id, {})
        for app, green_p in apps.items():
            red_dur = self.red_elapsed[j_id].get(app, 0.0)
            q = self.current_queues[j_id].get(app, 0)
            if red_dur >= self.max_red_threshold_s and q >= self.min_queue_to_starve:
                starved.append({
                    "approach": app,
                    "target_green_phase": green_p,
                    "red_duration_s": red_dur,
                    "queue": q,
                })
        return starved

    def get_action_mask(
        self,
        j_id: str,
        current_phase: int,
        can_switch: bool,
        emergency_locked: bool = False,
        sim_time: float = 0.0,
    ) -> Tuple[np.ndarray, str]:
        """
        Returns a 3-element float32 mask [mask_keep, mask_switch, mask_extend]
        where 1.0 = valid action, 0.0 = prohibited action.

        Guarantees:
        - Emergency lock overrides all and enforces KEEP [1, 0, 0].
        - If starved approach exists and can_switch is True, forces SWITCH [0, 1, 0].
        - If starved approach exists and can_switch is False, prevents EXTEND [1, 0, 0].
        - If no starvation, respects standard can_switch constraints.
        """
        # 1. Emergency Preemption Lockout Priority
        if emergency_locked:
            return np.array([1.0, 0.0, 0.0], dtype=np.float32), "EMERGENCY_LOCK_ACTIVE"

        # 2. Check for Starved Approaches
        starved = self.get_starved_approaches(j_id)
        if starved:
            # Check if current phase is already the green phase for the starved approach
            target_p = starved[0]["target_green_phase"]
            starved_app = starved[0]["approach"]
            red_dur = starved[0]["red_duration_s"]
            q = starved[0]["queue"]

            if current_phase == target_p:
                # Already serving the approach, can maintain or extend
                return np.array([1.0, 0.0, 1.0], dtype=np.float32), f"SERVING_STARVED_APPROACH_{starved_app}"

            if can_switch:
                # Minimum green satisfied: FORCE SWITCH to starved approach
                reason = (
                    f"STARVATION_PREVENTION: Forced SWITCH at {j_id}. "
                    f"Approach '{starved_app}' red for {red_dur:.1f}s >= {self.max_red_threshold_s:.1f}s "
                    f"(Queue={q})"
                )
                logger.warning(f"[{sim_time:.1f}s] {reason}")

                # Record event
                event = StarvationEvent(
                    timestamp=sim_time,
                    junction_id=j_id,
                    starved_approach=starved_app,
                    red_duration_s=red_dur,
                    threshold_s=self.max_red_threshold_s,
                    queue_count=q,
                    current_phase=current_phase,
                    target_phase=target_p,
                    action_enforced="SWITCH",
                )
                self.events.append(event)
                return np.array([0.0, 1.0, 0.0], dtype=np.float32), reason
            else:
                # Min green not yet satisfied: Mask out EXTEND so green expires naturally at min_green
                reason = (
                    f"STARVATION_PENDING_MIN_GREEN: Approach '{starved_app}' red for {red_dur:.1f}s. "
                    f"EXTEND masked out."
                )
                return np.array([1.0, 0.0, 0.0], dtype=np.float32), reason

        # 3. Standard Non-Starved Constraints
        if can_switch:
            # All actions (KEEP, SWITCH, EXTEND) valid
            return np.array([1.0, 1.0, 1.0], dtype=np.float32), "UNCONSTRAINED"
        else:
            # Min-green active: SWITCH prohibited, KEEP and EXTEND valid
            return np.array([1.0, 0.0, 1.0], dtype=np.float32), "MIN_GREEN_ACTIVE"

    def get_starvation_penalty(self, j_id: str) -> float:
        """
        Computes a continuous penalty for approaches exceeding the threshold.
        Normalized to [-1.0, 0.0].
        """
        apps = self.approach_green_phases.get(j_id, {})
        penalty = 0.0
        for app in apps:
            red_dur = self.red_elapsed[j_id].get(app, 0.0)
            q = self.current_queues[j_id].get(app, 0)
            if red_dur > self.max_red_threshold_s and q > 0:
                excess = (red_dur - self.max_red_threshold_s) / 30.0
                penalty += min(excess, 1.0) * min(float(q) / 10.0, 1.0)
        return float(np.clip(penalty, 0.0, 1.0))

"""
traffic_service/ai/env.py

Multi-Agent Environment definitions for Corridor Signal Coordination.
Provides normalized observation vectorization, action space mappings,
and multi-objective reward function incorporating queue lengths, waiting times,
throughput, emissions, and emergency vehicle delays.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union
import numpy as np

# Discrete Action Space
ACTION_KEEP = 0    # Hold current phase
ACTION_SWITCH = 1  # Request switch to conflicting green (via yellow clearance)
ACTION_EXTEND = 2  # Extend current green up to max_green

ACTION_NAMES = {
    ACTION_KEEP: "KEEP",
    ACTION_SWITCH: "SWITCH",
    ACTION_EXTEND: "EXTEND",
}

DEFAULT_JUNCTIONS = ["J1", "J2", "J3"]
OBSERVATION_DIM_PER_JUNCTION = 14
CORRIDOR_OBSERVATION_DIM = OBSERVATION_DIM_PER_JUNCTION * len(DEFAULT_JUNCTIONS)  # 42


@dataclass
class RewardWeights:
    """Configurable weights for the multi-objective reward function."""
    weight_queue: float = 0.35          # Penalty for queue buildup
    weight_wait_time: float = 0.30      # Penalty for accumulated waiting time
    weight_speed: float = 0.15          # Incentive for maintaining free-flow speed
    weight_throughput: float = 0.50     # Bonus for completed corridor trips
    weight_emissions: float = 0.10      # Penalty for CO2 emissions
    weight_emergency_delay: float = 1.0 # High penalty if emergency vehicle is halted
    switch_chatter_penalty: float = 0.05# Small penalty for rapid phase transitions
    # P6 Coordination extensions:
    alpha: float = 0.5                  # Mixed local-global weighting coefficient
    weight_progression: float = 0.25    # Incentive for serving arriving platoons on green
    weight_corridor_delay: float = 0.50 # Penalty for total corridor queue accumulation
    weight_starvation: float = 0.50     # Global penalty when any approach exceeds max red threshold
    weight_flow_integrity: float = 0.30 # Penalty if upstream arterial holds queue without releasing trips
    max_red_threshold_s: float = 60.0   # Maximum tolerable red duration per queued approach


@dataclass
class RewardBreakdown:
    """Detailed telemetry breakdown of local, global, and mixed reward components."""
    junction_id: str
    local_reward: float
    corridor_reward: float
    mixed_reward: float
    r_queue: float = 0.0
    r_wait: float = 0.0
    r_speed: float = 0.0
    r_co2: float = 0.0
    r_chatter: float = 0.0
    r_progression: float = 0.0
    r_emergency: float = 0.0
    R_throughput: float = 0.0
    R_corridor_delay: float = 0.0
    R_starvation: float = 0.0
    R_flow_integrity: float = 0.0


class CorridorObservationSpace:
    """
    Transforms raw simulation telemetry into normalized, clean feature vectors
    for neural policy and Q-network ingestion.
    """

    def __init__(
        self,
        junctions: Optional[List[str]] = None,
        max_queue: float = 50.0,
        max_speed_kmh: float = 60.0,
        max_wait_time_s: float = 500.0,
        max_green: float = 60.0,
        min_green: float = 15.0,
        max_co2_mg_s: float = 10000.0,
        max_inflow_rate: float = 10.0,
    ) -> None:
        self.junctions = junctions or list(DEFAULT_JUNCTIONS)
        self.max_queue = max_queue
        self.max_speed_kmh = max_speed_kmh
        self.max_wait_time_s = max_wait_time_s
        self.max_green = max_green
        self.min_green = min_green
        self.max_co2_mg_s = max_co2_mg_s
        self.max_inflow_rate = max_inflow_rate

    def vectorize_junction(self, j_id: str, raw_obs: Dict[str, Any]) -> np.ndarray:
        """
        Transforms a single junction's observation dictionary into a 14-dim normalized vector:
          [0]: current_phase_norm (phase / 3.0)
          [1]: phase_elapsed_norm (min(elapsed / max_green, 1.0))
          [2]: time_to_switch_norm (min(switch / max_green, 1.0))
          [3]: can_switch_flag (1.0 if elapsed >= min_green else 0.0)
          [4]: corridor_queue_norm (q_corridor / max_queue)
          [5]: side_queue_norm (q_side / max_queue)
          [6]: total_queue_norm (total_q / (2 * max_queue))
          [7]: average_speed_norm (avg_speed / max_speed)
          [8]: waiting_time_norm (min(wait / max_wait, 1.0))
          [9]: vehicle_count_norm (min(count / (2 * max_queue), 1.0))
          [10]: co2_emissions_norm (min(co2 / max_co2, 1.0))
          [11]: upstream_inflow_norm (min(inflow / max_inflow, 1.0))
          [12]: approaching_platoons_norm (min(platoons / 5.0, 1.0))
          [13]: emergency_approaching_flag (1.0 if emergency else 0.0)
        """
        vec = np.zeros(OBSERVATION_DIM_PER_JUNCTION, dtype=np.float32)
        if not raw_obs:
            return vec

        try:
            phase = float(raw_obs.get("phase", 0))
            elapsed = float(raw_obs.get("phase_elapsed", 0.0))
            time_to_switch = float(raw_obs.get("time_to_switch", 0.0))
            total_q = float(raw_obs.get("total_queue", 0))
            avg_speed = float(raw_obs.get("average_speed_kmh", 0.0))
            total_wait = float(raw_obs.get("total_waiting_time", 0.0))
            veh_count = float(raw_obs.get("vehicle_count", 0))
            inflow = float(raw_obs.get("upstream_expected_inflow", 0.0))
            platoons = float(raw_obs.get("approaching_platoons_count", 0))
            co2 = float(raw_obs.get("co2_mg_s", 0.0))
            emergency = 1.0 if raw_obs.get("emergency_approaching", False) else 0.0

            # Approach queues breakdown
            app_queues = raw_obs.get("approach_queues", {})
            q_corridor = float(app_queues.get("corridor_hosur", 0))
            # side queue can be madiwala (J2) or side_cross (J1, J3)
            q_side = float(app_queues.get("madiwala", app_queues.get("side_cross", 0)))

            can_switch = 1.0 if elapsed >= self.min_green else 0.0

            vec[0] = np.clip(phase / 3.0, 0.0, 1.0)
            vec[1] = np.clip(elapsed / self.max_green, 0.0, 1.0)
            vec[2] = np.clip(time_to_switch / self.max_green, 0.0, 1.0)
            vec[3] = can_switch
            vec[4] = np.clip(q_corridor / self.max_queue, 0.0, 1.0)
            vec[5] = np.clip(q_side / self.max_queue, 0.0, 1.0)
            vec[6] = np.clip(total_q / (2.0 * self.max_queue), 0.0, 1.0)
            vec[7] = np.clip(avg_speed / self.max_speed_kmh, 0.0, 1.0)
            vec[8] = np.clip(total_wait / self.max_wait_time_s, 0.0, 1.0)
            vec[9] = np.clip(veh_count / (2.0 * self.max_queue), 0.0, 1.0)
            vec[10] = np.clip(co2 / self.max_co2_mg_s, 0.0, 1.0)
            vec[11] = np.clip(inflow / self.max_inflow_rate, 0.0, 1.0)
            vec[12] = np.clip(platoons / 5.0, 0.0, 1.0)
            vec[13] = emergency
        except Exception:
            # Safe zero-fallback for malformed data
            vec.fill(0.0)

        # Replace any residual NaNs / Infs
        np.nan_to_num(vec, copy=False, nan=0.0, posinf=1.0, neginf=0.0)
        return vec

    def vectorize_corridor(self, raw_observations: Dict[str, Dict[str, Any]]) -> np.ndarray:
        """
        Concatenates all junction vectors in topological order [J1, J2, J3]
        into a unified corridor state vector (dim = 42).
        """
        sub_vecs = [
            self.vectorize_junction(j_id, raw_observations.get(j_id, {}))
            for j_id in self.junctions
        ]
        return np.concatenate(sub_vecs, axis=0).astype(np.float32)

    def vectorize_multi_agent(
        self, raw_observations: Dict[str, Dict[str, Any]]
    ) -> Dict[str, np.ndarray]:
        """
        Produces independent observation vectors per agent:
        {"J1": vec1, "J2": vec2, "J3": vec3}.
        """
        return {
            j_id: self.vectorize_junction(j_id, raw_observations.get(j_id, {}))
            for j_id in self.junctions
        }


class MultiIntersectionReward:
    """
    Computes local and global multi-objective reward signals for reinforcement learning.
    Balances queue minimization, delay reduction, throughput maximization,
    emission abatement, and emergency green-wave facilitation.
    """

    def __init__(self, weights: Optional[RewardWeights] = None) -> None:
        self.weights = weights or RewardWeights()
        self._prev_phases: Dict[str, int] = {}
        self._prev_completed_trips: int = 0

    def reset(self) -> None:
        self._prev_phases.clear()
        self._prev_completed_trips = 0

    def compute_junction_reward(
        self,
        j_id: str,
        state: Dict[str, Any],
        action: int,
        emergency_stopped: bool = False,
        comm_hub: Optional[Any] = None,
        current_time: float = 0.0,
    ) -> float:
        """
        Computes the reward for an individual junction agent.
        """
        q = float(state.get("total_queue", 0))
        wait = float(state.get("total_waiting_time", 0.0))
        speed = float(state.get("average_speed_kmh", 0.0))
        co2_g = float(state.get("co2_mg_s", 0.0)) / 1000.0  # mg -> g

        # Normalized component penalties
        r_queue = -self.weights.weight_queue * (q / 30.0)
        r_wait = -self.weights.weight_wait_time * (wait / 200.0)
        r_speed = self.weights.weight_speed * (speed / 40.0)
        r_co2 = -self.weights.weight_emissions * (co2_g / 5.0)

        # Chatter penalty if agent frequently switches
        prev_p = self._prev_phases.get(j_id)
        curr_p = int(state.get("phase", 0))
        self._prev_phases[j_id] = curr_p
        r_chatter = 0.0
        if prev_p is not None and prev_p != curr_p and action == ACTION_SWITCH:
            r_chatter = -self.weights.switch_chatter_penalty

        # Emergency penalty if an ambulance is approaching but halted
        r_emergency = 0.0
        if emergency_stopped:
            r_emergency = -self.weights.weight_emergency_delay

        # Platoon progression incentive
        r_prog = 0.0
        if comm_hub is not None and hasattr(comm_hub, "get_unserved_approaching_platoons"):
            corridor_phase = 2 if j_id in ("J1", "J3") else 0
            unserved = comm_hub.get_unserved_approaching_platoons(j_id, current_time)
            if unserved:
                if curr_p == corridor_phase:
                    for plt in unserved:
                        cnt = float(plt.get("vehicle_count", plt.get("count", 5.0)))
                        r_prog += self.weights.weight_progression * min(cnt / 10.0, 1.0)
                        comm_hub.mark_platoon_served(plt.get("platoon_id", ""), j_id)
                elif action == ACTION_KEEP:
                    r_prog -= 0.15
        r_prog = float(np.clip(r_prog, -0.5, 0.5))

        total = r_queue + r_wait + r_speed + r_co2 + r_chatter + r_emergency + r_prog
        return float(np.clip(total, -10.0, 10.0))

    def compute_corridor_reward(
        self,
        states: Dict[str, Dict[str, Any]],
        actions: Dict[str, int],
        completed_trips: int = 0,
        active_emergency_stopped: bool = False,
    ) -> float:
        """
        Computes global coordinated corridor reward (sum of junction rewards + throughput bonus).
        """
        total_r = 0.0
        for j_id, st in states.items():
            act = actions.get(j_id, ACTION_KEEP)
            total_r += self.compute_junction_reward(
                j_id=j_id,
                state=st,
                action=act,
                emergency_stopped=active_emergency_stopped,
            )

        # Throughput bonus for newly completed corridor trips
        new_trips = max(0, completed_trips - self._prev_completed_trips)
        self._prev_completed_trips = completed_trips
        r_throughput = self.weights.weight_throughput * new_trips

        corridor_reward = total_r + r_throughput
        return float(np.clip(corridor_reward, -30.0, 30.0))

    def compute_mixed_rewards(
        self,
        states: Dict[str, Dict[str, Any]],
        actions: Dict[str, int],
        comm_hub: Optional[Any] = None,
        starvation_tracker: Optional[Any] = None,
        completed_trips: int = 0,
        active_emergency_stopped: bool = False,
        current_time: float = 0.0,
    ) -> Tuple[Dict[str, float], Dict[str, RewardBreakdown]]:
        """
        Computes mixed local-global rewards for MARL agents:
          R_j(t) = (1 - alpha) * r_j(t) + alpha * R_corridor(t)

        Balances localized queuing and delay with corridor-wide throughput,
        anti-starvation penalties, and upstream flow integrity.
        """
        # 1. Global Corridor Terms
        new_trips = max(0, completed_trips - self._prev_completed_trips)
        self._prev_completed_trips = completed_trips
        r_throughput = self.weights.weight_throughput * min(float(new_trips) / 5.0, 1.0)

        tot_q = sum(float(st.get("total_queue", 0)) for st in states.values())
        r_cdelay = -self.weights.weight_corridor_delay * min(tot_q / 60.0, 1.0)

        r_starve = 0.0
        if starvation_tracker is not None and hasattr(starvation_tracker, "get_starvation_penalty"):
            sum_pen = sum(starvation_tracker.get_starvation_penalty(j) for j in states)
            r_starve = -self.weights.weight_starvation * min(sum_pen, 2.0)

        # Upstream flow integrity: penalize if J1 holds arterial queue without releasing trips
        r_flow = 0.0
        j1_st = states.get("J1", {})
        if j1_st:
            j1_app_q = j1_st.get("approach_queues", {})
            j1_corridor_q = float(j1_app_q.get("corridor_hosur", 0))
            j1_phase = int(j1_st.get("phase", 0))
            if j1_corridor_q >= 5.0 and j1_phase != 2 and new_trips == 0:
                r_flow = -self.weights.weight_flow_integrity

        global_corridor_reward = float(np.clip(r_throughput + r_cdelay + r_starve + r_flow, -10.0, 10.0))

        # 2. Local Rewards and Mixed Combination
        mixed_rewards: Dict[str, float] = {}
        breakdowns: Dict[str, RewardBreakdown] = {}

        for j_id, st in states.items():
            act = actions.get(j_id, ACTION_KEEP)
            q = float(st.get("total_queue", 0))
            wait = float(st.get("total_waiting_time", 0.0))
            speed = float(st.get("average_speed_kmh", 0.0))
            co2_g = float(st.get("co2_mg_s", 0.0)) / 1000.0

            r_q = -self.weights.weight_queue * min(q / 30.0, 1.0)
            r_w = -self.weights.weight_wait_time * min(wait / 200.0, 1.0)
            r_s = self.weights.weight_speed * min(speed / 40.0, 1.0)
            r_c = -self.weights.weight_emissions * min(co2_g / 5.0, 1.0)

            prev_p = self._prev_phases.get(j_id)
            curr_p = int(st.get("phase", 0))
            self._prev_phases[j_id] = curr_p
            r_chatter = 0.0
            if prev_p is not None and prev_p != curr_p and act == ACTION_SWITCH:
                r_chatter = -self.weights.switch_chatter_penalty

            r_emerg = -self.weights.weight_emergency_delay if active_emergency_stopped else 0.0

            # Platoon progression incentive
            r_prog = 0.0
            if comm_hub is not None and hasattr(comm_hub, "get_unserved_approaching_platoons"):
                corridor_phase = 2 if j_id in ("J1", "J3") else 0
                unserved = comm_hub.get_unserved_approaching_platoons(j_id, current_time)
                if unserved:
                    if curr_p == corridor_phase:
                        for plt in unserved:
                            cnt = float(plt.get("vehicle_count", plt.get("count", 5.0)))
                            r_prog += self.weights.weight_progression * min(cnt / 10.0, 1.0)
                            comm_hub.mark_platoon_served(plt.get("platoon_id", ""), j_id)
                    elif act == ACTION_KEEP:
                        r_prog -= 0.15
            r_prog = float(np.clip(r_prog, -0.5, 0.5))

            local_r = float(np.clip(r_q + r_w + r_s + r_c + r_chatter + r_emerg + r_prog, -10.0, 10.0))
            mixed_r = float(np.clip(
                (1.0 - self.weights.alpha) * local_r + self.weights.alpha * global_corridor_reward,
                -15.0,
                15.0,
            ))

            mixed_rewards[j_id] = mixed_r
            breakdowns[j_id] = RewardBreakdown(
                junction_id=j_id,
                local_reward=local_r,
                corridor_reward=global_corridor_reward,
                mixed_reward=mixed_r,
                r_queue=r_q,
                r_wait=r_w,
                r_speed=r_s,
                r_co2=r_c,
                r_chatter=r_chatter,
                r_progression=r_prog,
                r_emergency=r_emerg,
                R_throughput=r_throughput,
                R_corridor_delay=r_cdelay,
                R_starvation=r_starve,
                R_flow_integrity=r_flow,
            )

        return mixed_rewards, breakdowns

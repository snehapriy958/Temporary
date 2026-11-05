"""
traffic_service/ai/marl_controller.py

Coordinated Multi-Agent Reinforcement Learning (MARL) Corridor Controller.
Orchestrates autonomous agents across J1, J2, and J3 along Bengaluru's Silk Board corridor.
Features:
- Neighbor state exchange via CorridorCommunicationHub
- Support for both DQN and PPO agents
- Failsafe fallback logic for anomalous observations and emergency overrides
- Enforces min/max green times, yellow clearance transitions, and conflicting movement constraints
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

from .env import (
    CorridorObservationSpace,
    MultiIntersectionReward,
    ACTION_KEEP,
    ACTION_SWITCH,
    ACTION_EXTEND,
    ACTION_NAMES,
    DEFAULT_JUNCTIONS,
    CORRIDOR_OBSERVATION_DIM,
    OBSERVATION_DIM_PER_JUNCTION,
)
from .dqn_agent import DQNAgent
from .ppo_agent import PPOAgent
from .mappo_agent import MAPPOAgent
from .models import MAPPOCentralizedCriticNetwork, TORCH_AVAILABLE
from .starvation_tracker import StarvationTracker
from traffic_service.communication import CorridorCommunicationHub
from traffic_service.signal_controller import SignalController
from traffic_service.state_extractor import IntersectionState

logger = logging.getLogger("marl_controller")


class MARLCorridorController:
    """
    Coordinates multi-intersection signal control for J1, J2, and J3 using MARL.
    Supports DQN, PPO, and MAPPO (Multi-Agent PPO with CTDE) algorithms with
    anti-starvation action masking and platoon communication.
    """

    def __init__(
        self,
        algorithm: str = "dqn",  # 'dqn', 'ppo', or 'mappo'
        junctions: Optional[List[str]] = None,
        controllers: Optional[Dict[str, SignalController]] = None,
        communication_hub: Optional[CorridorCommunicationHub] = None,
        starvation_tracker: Optional[StarvationTracker] = None,
        max_red_threshold_s: float = 60.0,
        seed: int = 42,
    ) -> None:
        self.algorithm = algorithm.lower()
        self.junctions = junctions or list(DEFAULT_JUNCTIONS)
        self.controllers = controllers or {}
        self.hub = communication_hub or CorridorCommunicationHub(corridor_sequence=self.junctions)
        self.starvation_tracker = starvation_tracker or StarvationTracker(max_red_threshold_s=max_red_threshold_s)
        self.seed = seed

        self.obs_space = CorridorObservationSpace(junctions=self.junctions)
        self.reward_fn = MultiIntersectionReward()

        # Phase mappings per junction
        self.corridor_green_phases = {"J1": 2, "J2": 0, "J3": 2}
        self.conflicting_green_phases = {"J1": 0, "J2": 2, "J3": 0}

        # Initialize shared centralized critic for MAPPO
        self.shared_critic = None
        self.shared_critic_optimizer = None
        if self.algorithm == "mappo":
            self.shared_critic = MAPPOCentralizedCriticNetwork(
                in_features=CORRIDOR_OBSERVATION_DIM, seed=seed + 100
            )
            if TORCH_AVAILABLE:
                import torch
                self.shared_critic_optimizer = torch.optim.Adam(
                    self.shared_critic.parameters(), lr=0.001, eps=1e-5
                )

        # Initialize agents per junction
        self.agents: Dict[str, DQNAgent | PPOAgent | MAPPOAgent] = {}
        for idx, j_id in enumerate(self.junctions):
            agent_seed = seed + (idx * 37)
            if self.algorithm == "mappo":
                self.agents[j_id] = MAPPOAgent(
                    agent_id=j_id,
                    in_features=OBSERVATION_DIM_PER_JUNCTION,
                    corridor_features=CORRIDOR_OBSERVATION_DIM,
                    num_actions=3,
                    shared_critic=self.shared_critic,
                    shared_critic_optimizer=self.shared_critic_optimizer,
                    seed=agent_seed,
                )
            elif self.algorithm == "ppo":
                self.agents[j_id] = PPOAgent(
                    agent_id=j_id,
                    in_features=self.obs_space.vectorize_junction(j_id, {}).shape[0],
                    num_actions=3,
                    seed=agent_seed,
                )
            else:
                self.agents[j_id] = DQNAgent(
                    agent_id=j_id,
                    in_features=self.obs_space.vectorize_junction(j_id, {}).shape[0],
                    num_actions=3,
                    seed=agent_seed,
                )

        self._initialize_domain_prior_weights()

    def _initialize_domain_prior_weights(self) -> None:
        """
        Initializes agents with domain-informed corridor priors:
        - Penalizes switching before arterial queues clear.
        - Favors extending when upstream inflow / platoon alerts are active.
        """
        for j_id, agent in self.agents.items():
            if isinstance(agent, DQNAgent):
                w = agent.q_network.get_weights()
                # Bias adv_out for EXTEND on corridor pressure
                w["adv_out_b"][ACTION_KEEP] += 0.2
                w["adv_out_b"][ACTION_EXTEND] += 0.3
                agent.q_network.set_weights(w)
                agent.update_target_network()

    def set_controllers(self, controllers: Dict[str, SignalController]) -> None:
        self.controllers = controllers

    def set_communication_hub(self, hub: CorridorCommunicationHub) -> None:
        self.hub = hub

    def decide(
        self,
        raw_observations: Dict[str, Dict[str, Any]],
        sim_time: float,
        eval_mode: bool = True,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Main decision function called at each decision timestep.
        Returns decisions per junction:
        {
          "J1": {"action": 0, "target_phase": 2, "reason": "..."},
          "J2": {"action": 2, "target_phase": 0, "reason": "..."},
          "J3": {"action": 0, "target_phase": 2, "reason": "..."}
        }
        """
        decisions: Dict[str, Dict[str, Any]] = {}

        # 1. Coordinate Inter-Intersection Communication Bus
        self._exchange_inter_intersection_messages(raw_observations, sim_time)

        # 2. Update Starvation Tracker with latest approach queues and phases
        curr_phases = {}
        app_queues = {}
        for j in self.junctions:
            obs = raw_observations.get(j, {})
            raw_p = obs.get("phase", 0)
            try:
                curr_phases[j] = int(raw_p) if not (isinstance(raw_p, float) and np.isnan(raw_p)) else 0
            except (ValueError, TypeError):
                curr_phases[j] = 0
            app_queues[j] = obs.get("approach_queues", {})
        self.starvation_tracker.update(curr_phases, app_queues, step_length=1.0, sim_time=sim_time)

        # 3. Compute Agent Decisions
        for j_id in self.junctions:
            obs_dict = raw_observations.get(j_id, {})
            ctrl = self.controllers.get(j_id)

            # Check emergency lockout
            if ctrl and ctrl.emergency_locked:
                decisions[j_id] = {
                    "action": ACTION_KEEP,
                    "action_name": ACTION_NAMES.get(ACTION_KEEP, "KEEP"),
                    "target_phase": ctrl.emergency_priority_phase,
                    "current_phase": ctrl.get_phase(),
                    "observation_shape": (14,),
                    "reason": f"Emergency Priority Lock active at {j_id}. MARL actions bypassed.",
                    "confidence": 1.0,
                    "is_fallback": False,
                    "is_emergency": True,
                }
                continue

            # Check validity of observation
            if not obs_dict or "phase" not in obs_dict:
                decisions[j_id] = self._fallback_decision(j_id, obs_dict, sim_time, "Missing observation data")
                continue

            # Check if any raw observation field is NaN
            has_raw_nan = False
            for v in obs_dict.values():
                if isinstance(v, float) and np.isnan(v):
                    has_raw_nan = True
                    break
                elif isinstance(v, dict):
                    for sub_v in v.values():
                        if isinstance(sub_v, float) and np.isnan(sub_v):
                            has_raw_nan = True
                            break
            if has_raw_nan:
                decisions[j_id] = self._fallback_decision(j_id, obs_dict, sim_time, "Corrupted observation (NaNs)")
                continue

            # Vectorize
            vec = self.obs_space.vectorize_junction(j_id, obs_dict)
            if np.isnan(vec).any():
                decisions[j_id] = self._fallback_decision(j_id, obs_dict, sim_time, "Corrupted observation (NaNs)")
                continue

            # Check signal timing constraints
            can_switch = True
            if ctrl:
                can_switch = ctrl.can_switch(sim_time)
            else:
                elapsed = float(obs_dict.get("phase_elapsed", 0.0))
                can_switch = (elapsed >= 15.0)

            # Anti-Starvation Action Masking
            emergency_locked = bool(ctrl and ctrl.emergency_locked)
            action_mask, mask_reason = self.starvation_tracker.get_action_mask(
                j_id=j_id,
                current_phase=int(obs_dict.get("phase", 0)),
                can_switch=can_switch,
                emergency_locked=emergency_locked,
                sim_time=sim_time,
            )

            # Select agent action
            agent = self.agents[j_id]
            try:
                action, info = agent.select_action(
                    vec,
                    eval_mode=eval_mode,
                    can_switch=can_switch,
                    action_mask=action_mask,
                )
            except Exception as exc:
                logger.warning(f"Agent {j_id} inference failed: {exc}. Using fallback.")
                decisions[j_id] = self._fallback_decision(j_id, obs_dict, sim_time, f"Inference exception: {exc}")
                continue

            curr_phase = int(obs_dict.get("phase", 0))
            corridor_phase = self.corridor_green_phases.get(j_id, 0)
            conflicting_phase = self.conflicting_green_phases.get(j_id, 2)

            # Determine target phase
            target_phase = curr_phase
            if action == ACTION_SWITCH:
                target_phase = conflicting_phase if curr_phase == corridor_phase else corridor_phase

            is_starve_switch = ("STARVATION_PREVENTION" in mask_reason)
            reason_str = f"MARL [{self.algorithm.upper()}] Agent {j_id}: {info.get('reason')}"
            if is_starve_switch:
                reason_str = f"MARL [{self.algorithm.upper()}] Agent {j_id}: Anti-Starvation Overrule ({mask_reason})"

            decisions[j_id] = {
                "action": action,
                "action_name": ACTION_NAMES.get(action, "UNKNOWN"),
                "target_phase": target_phase,
                "current_phase": curr_phase,
                "observation_shape": tuple(vec.shape),
                "reason": reason_str,
                "q_values" if self.algorithm == "dqn" else "probabilities": info.get("q_values") or info.get("probabilities"),
                "action_mask": action_mask.tolist(),
                "mask_reason": mask_reason,
                "is_starvation_prevention": is_starve_switch,
                "confidence": float(info.get("confidence", 1.0)),
                "value": float(info.get("value", 0.0)),
                "log_prob": float(info.get("log_prob", 0.0)),
                "is_fallback": False,
                "is_emergency": False,
            }

        return decisions

    def apply_decisions(
        self,
        decisions: Dict[str, Dict[str, Any]],
        sim_time: float,
    ) -> Dict[str, str]:
        """
        Safely applies MARL decisions to traffic signal controllers.
        Respects safety transitions through yellow phases and min/max green times.
        Returns a dictionary mapping junction ID to executed operation status.
        """
        executed_ops: Dict[str, str] = {}
        for j_id, dec in decisions.items():
            ctrl = self.controllers.get(j_id)
            if not ctrl:
                executed_ops[j_id] = "NO_CONTROLLER"
                continue
            if ctrl.emergency_locked:
                executed_ops[j_id] = "EMERGENCY_LOCKED_BYPASS"
                continue

            action = dec.get("action", ACTION_KEEP)
            target_phase = dec.get("target_phase")

            if action == ACTION_SWITCH and target_phase is not None:
                switched = ctrl.request_switch(target_green_phase=target_phase, sim_time=sim_time)
                executed_ops[j_id] = f"REQUEST_SWITCH_TARGET_{target_phase}_{'OK' if switched else 'REJECTED'}"
            elif action == ACTION_EXTEND:
                extended = ctrl.extend_current_green(sim_time)
                executed_ops[j_id] = f"EXTEND_GREEN_{'OK' if extended else 'REJECTED'}"
            else:
                executed_ops[j_id] = f"KEEP_PHASE_{dec.get('current_phase', ctrl.get_phase())}"

        return executed_ops

    def _exchange_inter_intersection_messages(
        self, raw_observations: Dict[str, Dict[str, Any]], sim_time: float
    ) -> None:
        """
        Publishes anticipated outflow and departing platoons across neighboring junctions:
        J1 (Feeder) -> J2 (Silk Board) -> J3 (Feeder).
        """
        # J1 -> J2 communication
        j1_obs = raw_observations.get("J1", {})
        if j1_obs:
            q_hosur = j1_obs.get("approach_queues", {}).get("corridor_hosur", 0)
            if not isinstance(q_hosur, (int, float)) or np.isnan(q_hosur):
                q_hosur = 0.0
            phase = j1_obs.get("phase", 0)
            # If J1 is green on Hosur corridor, predict platoon departure
            if phase == self.corridor_green_phases["J1"]:
                outflow_rate = min(3.0, float(q_hosur) * 0.15 + 0.5)
                self.hub.publish_upstream_inflow("J1", outflow_rate_veh_s=outflow_rate, timestamp=sim_time)
                if q_hosur >= 5:
                    self.hub.announce_platoon(
                        sender_id="J1",
                        vehicle_count=int(q_hosur),
                        speed_mps=11.0,
                        eta_seconds=16.0,
                        timestamp=sim_time,
                    )

        # J2 -> J3 communication
        j2_obs = raw_observations.get("J2", {})
        if j2_obs:
            q_hosur = j2_obs.get("approach_queues", {}).get("corridor_hosur", 0)
            if not isinstance(q_hosur, (int, float)) or np.isnan(q_hosur):
                q_hosur = 0.0
            phase = j2_obs.get("phase", 0)
            if phase == self.corridor_green_phases["J2"]:
                outflow_rate = min(3.5, float(q_hosur) * 0.15 + 0.5)
                self.hub.publish_upstream_inflow("J2", outflow_rate_veh_s=outflow_rate, timestamp=sim_time)

    def _fallback_decision(
        self,
        j_id: str,
        obs_dict: Dict[str, Any],
        sim_time: float,
        reason_detail: str,
    ) -> Dict[str, Any]:
        """
        Conservative fallback controller adhering to signal timing constraints.
        """
        ctrl = self.controllers.get(j_id)
        curr_phase = ctrl.get_phase() if ctrl else int(obs_dict.get("phase", 0))
        can_switch = ctrl.can_switch(sim_time) if ctrl else False

        app_queues = obs_dict.get("approach_queues", {})
        q_corridor = app_queues.get("corridor_hosur", 0)
        q_side = app_queues.get("madiwala", app_queues.get("side_cross", 0))

        corridor_phase = self.corridor_green_phases.get(j_id, 0)
        conflicting_phase = self.conflicting_green_phases.get(j_id, 2)

        action = ACTION_KEEP
        target_p = curr_phase

        if can_switch:
            if curr_phase == corridor_phase and q_side > q_corridor + 3:
                action = ACTION_SWITCH
                target_p = conflicting_phase
            elif curr_phase == conflicting_phase and q_corridor > q_side:
                action = ACTION_SWITCH
                target_p = corridor_phase
        elif curr_phase == corridor_phase and q_corridor > 0:
            action = ACTION_EXTEND

        return {
            "action": action,
            "action_name": ACTION_NAMES.get(action, "UNKNOWN"),
            "target_phase": target_p,
            "current_phase": curr_phase,
            "observation_shape": (14,),
            "reason": f"Fallback Controller triggered for {j_id} ({reason_detail})",
            "confidence": 0.0,
            "is_fallback": True,
            "is_emergency": False,
        }

    def save_checkpoint(
        self,
        filepath: Path | str,
        version: str = "2.0-autograd",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Saves current agent weights and hyperparameters to a JSON checkpoint file."""
        from datetime import datetime, timezone
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        checkpoint_data = {
            "algorithm": self.algorithm,
            "algorithm_version": version,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "seed": self.seed,
            "junctions": self.junctions,
            "agents": {
                j_id: agent.get_state_dict() for j_id, agent in self.agents.items()
            },
        }
        if metadata:
            checkpoint_data["metadata"] = metadata
        if self.algorithm == "mappo" and self.shared_critic is not None:
            critic_w = self.shared_critic.get_weights()
            checkpoint_data["shared_critic_weights"] = {
                k: v.tolist() if hasattr(v, "tolist") else v for k, v in critic_w.items()
            }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(checkpoint_data, f, indent=2)
        logger.info(f"Saved MARL checkpoint (version: {version}) to: {path}")

    def load_checkpoint(self, filepath: Path | str) -> bool:
        """Loads agent weights from a checkpoint file. Returns True if successfully loaded."""
        path = Path(filepath)
        if not path.is_file():
            logger.warning(f"Checkpoint file not found: {path}")
            return False
        try:
            with open(path, "r", encoding="utf-8") as f:
                checkpoint_data = json.load(f)
            if not isinstance(checkpoint_data, dict):
                logger.error(f"Checkpoint data in {path} is not a valid JSON dictionary")
                return False
            agents_dict = checkpoint_data.get("agents", {})
            for j_id in self.junctions:
                if j_id not in agents_dict:
                    logger.error(f"Checkpoint {path} missing weights for junction '{j_id}'")
                    return False
            for j_id, agent_state in agents_dict.items():
                if j_id in self.agents:
                    self.agents[j_id].load_state_dict(agent_state)
            if (
                self.algorithm == "mappo"
                and "shared_critic_weights" in checkpoint_data
                and self.shared_critic is not None
            ):
                raw_cw = checkpoint_data["shared_critic_weights"]
                converted_cw = {
                    k: np.array(v, dtype=np.float32) if not isinstance(v, np.ndarray) else v
                    for k, v in raw_cw.items()
                }
                self.shared_critic.set_weights(converted_cw)
            version = checkpoint_data.get("algorithm_version", "1.0-historical")
            logger.info(f"Loaded MARL checkpoint (version: {version}) from: {path}")
            return True
        except Exception as exc:
            logger.error(f"Failed to load MARL checkpoint: {exc}")
            return False


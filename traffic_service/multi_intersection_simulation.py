"""
traffic_service/multi_intersection_simulation.py

Multi-intersection simulation orchestrator for J1, J2, and J3.
Coordinates simulation stepping, state extraction, inter-intersection communication,
corridor traffic metrics, and emergency green wave.
Provides clean observation/action hooks for external AI agents to attach later.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, TYPE_CHECKING
if TYPE_CHECKING:
    import subprocess

logger = logging.getLogger("simulation")

from .communication import CorridorCommunicationHub
from .corridor_metrics import CorridorMetricsCollector, CorridorMetricsSummary
from .emergency_wave import EmergencyWaveCoordinator
from .signal_controller import SignalController
from .state_extractor import IntersectionState, IntersectionStateExtractor
from .sumo_manager import SumoManager


class MultiIntersectionSimulation:
    """
    Simulation coordinator managing the J1 -> J2 -> J3 corridor.
    Supports:
      - 'baseline': Uncoordinated fixed-time control across all junctions
      - 'coordinated': Adaptive coordinated control with communication and emergency wave
    """

    def __init__(
        self,
        sumocfg_path: Path | str,
        mode: str = "coordinated",  # 'baseline', 'coordinated', 'marl_ppo', or 'marl_dqn'
        gui: bool = False,
        step_length: float = 1.0,
        decision_interval: float = 5.0,
        enable_emergency: bool = True,
        label: str = "default",
        on_process_spawned: Optional[Callable[[subprocess.Popen, Optional[int]], None]] = None,
        checkpoint_path: Optional[Path | str] = None,
    ) -> None:
        self.sumocfg_path = Path(sumocfg_path)
        self.mode = mode.lower()
        self.step_length = step_length
        self.decision_interval = decision_interval
        self.enable_emergency = enable_emergency
        self.label = label
        self.on_process_spawned = on_process_spawned

        self.sumo_manager = SumoManager(
            sumocfg_path=self.sumocfg_path,
            gui=gui,
            step_length=step_length,
            label=label,
            on_process_spawned=on_process_spawned,
        )

        # ----------------------------------------------------
        # Junction Lane & TLS Definitions
        # ----------------------------------------------------
        self.tls_ids = {
            "J1": "1617743335",
            "J2": "GS_cluster_10282769895_10775075568_11964440742_11964440743",
            "J3": "6970466614",
        }

        self.approach_lanes = {
            "J1": {
                "corridor_hosur": ["172853382#2_0", "172853382#2_1"],
                "side_cross": ["-148697299_0"],
            },
            "J2": {
                "corridor_hosur": [
                    "172853382#3_0",
                    "172853382#3_1",
                    "464465165#0_0",
                    "464465165#0_1",
                    "464465165#0_2",
                ],
                "madiwala": ["92196679#0_0", "92196679#0_1"],
            },
            "J3": {
                "corridor_hosur": ["1148717038#0_0", "1148717038#0_1"],
                "side_cross": ["-744783934_0"],
            },
        }

        # Green and Yellow phases per TLS
        self.green_phases = {
            "J1": {0, 2},
            "J2": {0, 2},
            "J3": {0, 2},
        }
        self.yellow_transitions = {
            "J1": {0: 1, 2: 3},
            "J2": {0: 1, 2: 3},
            "J3": {0: 1, 2: 3},
        }
        self.corridor_priority_phases = {
            "J1": 2,
            "J2": 0,
            "J3": 2,
        }

        # Communication bus
        self.hub = CorridorCommunicationHub(corridor_sequence=["J1", "J2", "J3"])

        # State Extractors & Controllers
        self.extractors: Dict[str, IntersectionStateExtractor] = {
            j_id: IntersectionStateExtractor(
                junction_id=j_id,
                tls_id=self.tls_ids[j_id],
                approach_lanes=self.approach_lanes[j_id],
            )
            for j_id in ["J1", "J2", "J3"]
        }

        self.controllers: Dict[str, SignalController] = {
            j_id: SignalController(
                tls_id=self.tls_ids[j_id],
                green_phases=self.green_phases[j_id],
                yellow_transitions=self.yellow_transitions[j_id],
                min_green=15.0,
                max_green=60.0,
            )
            for j_id in ["J1", "J2", "J3"]
        }

        # Emergency Coordinator
        self.emergency_coordinator = EmergencyWaveCoordinator(
            controllers=self.controllers,
            communication_hub=self.hub,
            corridor_phases=self.corridor_priority_phases,
        )

        # Corridor Metrics
        self.metrics_collector = CorridorMetricsCollector(
            entry_edge="172853382#2",
            exit_edge="40696223#1",
            step_length=step_length,
        )

        # MARL Decision Controller for 'marl_dqn' and 'marl_ppo'
        if self.mode in ("marl_dqn", "marl_ppo"):
            from .ai.marl_controller import MARLCorridorController
            algo = "ppo" if self.mode == "marl_ppo" else "dqn"
            self.marl_controller: Optional[MARLCorridorController] = MARLCorridorController(
                algorithm=algo,
                junctions=["J1", "J2", "J3"],
                controllers=self.controllers,
                communication_hub=self.hub,
            )
            ckpt_file = (
                Path(checkpoint_path)
                if checkpoint_path is not None
                else Path(__file__).resolve().parent.parent / "checkpoints" / f"marl_{algo}_corridor.json"
            )
            if not ckpt_file.is_file():
                raise FileNotFoundError(
                    f"MARL checkpoint file not found for mode '{self.mode}': {ckpt_file}"
                )
            loaded = self.marl_controller.load_checkpoint(ckpt_file)
            if not loaded:
                raise RuntimeError(
                    f"Failed to load MARL checkpoint for mode '{self.mode}' from {ckpt_file}: invalid or corrupted checkpoint."
                )
            for j_id in ["J1", "J2", "J3"]:
                if j_id not in self.marl_controller.agents:
                    raise RuntimeError(
                        f"Missing agent for junction '{j_id}' in MARL controller for mode '{self.mode}'"
                    )
            logger.info(
                f"Successfully initialized MARL {algo.upper()} controller with checkpoint: {ckpt_file}"
            )
        else:
            self.marl_controller = None

        self._next_decision_time: float = 0.0

    @property
    def process(self):
        """Returns the subprocess.Popen handle from SumoManager if available."""
        return self.sumo_manager.process

    @property
    def pid(self) -> Optional[int]:
        """Returns the OS PID from SumoManager if available."""
        return self.sumo_manager.pid

    def start(self, seed: int = 42) -> None:
        """Starts the SUMO process."""
        self.sumo_manager.start(seed=seed)
        self._next_decision_time = 0.0

    def close(self) -> None:
        """Closes the simulation."""
        self.sumo_manager.stop()

    def get_states(self, sim_time: float) -> Dict[str, IntersectionState]:
        """Extracts current state for all three intersections."""
        return {
            j_id: self.extractors[j_id].extract(sim_time, step_length=self.step_length)
            for j_id in ["J1", "J2", "J3"]
        }

    # ========================================================
    # CLEAN INTERFACE FOR FUTURE AI AGENTS (PPO / DQN / MARL)
    # ========================================================

    def get_ai_observations(self, states: Dict[str, IntersectionState]) -> Dict[str, Dict[str, Any]]:
        """
        Structured, normalized observations prepared for future AI models.
        AI team can ingest this dictionary directly into Gym observation spaces.
        """
        obs = {}
        for j_id, state in states.items():
            expected_inflow = self.hub.get_expected_inflow(j_id)
            approaching_platoons = len(self.hub.get_approaching_platoons(j_id, state.simulation_time))

            obs[j_id] = {
                "phase": state.current_phase,
                "phase_elapsed": state.phase_elapsed,
                "time_to_switch": state.time_to_switch,
                "approach_queues": state.approach_queues,
                "total_queue": state.total_queue,
                "average_speed_kmh": state.average_speed_kmh,
                "total_waiting_time": state.total_waiting_time,
                "vehicle_count": state.vehicle_count,
                "upstream_expected_inflow": expected_inflow,
                "approaching_platoons_count": approaching_platoons,
                "co2_mg_s": state.emissions.co2_mg_s,
                "emergency_approaching": len(state.approaching_emergency_vehicles) > 0,
            }
        return obs

    def step(self, actions: Optional[Dict[str, int]] = None) -> Tuple[Dict[str, IntersectionState], bool]:
        """
        Advances the simulation by 1 second.
        If actions are supplied (e.g. from an external AI agent):
          actions: {"J2": action_int} where 0=KEEP, 1=SWITCH, 2=EXTEND
        Otherwise, runs internal control mode ('baseline' or 'coordinated').
        """
        sim_time = self.sumo_manager.step()
        states = self.get_states(sim_time)

        # 1. Update Emergency Wave Coordinator if enabled
        if self.enable_emergency:
            self.emergency_coordinator.update(sim_time)

        # 2. Inter-intersection state communication update
        # J1 informs J2 of outflow on corridor
        j1_corridor_q = states["J1"].approach_queues.get("corridor_hosur", 0)
        self.hub.publish_upstream_inflow("J1", outflow_rate_veh_s=j1_corridor_q * 0.1, timestamp=sim_time)

        # J2 informs J3 of outflow on corridor
        j2_corridor_q = states["J2"].approach_queues.get("corridor_hosur", 0)
        self.hub.publish_upstream_inflow("J2", outflow_rate_veh_s=j2_corridor_q * 0.1, timestamp=sim_time)

        # 3. Decision Control (every decision_interval seconds)
        if sim_time >= self._next_decision_time:
            self._next_decision_time += self.decision_interval

            if actions is not None:
                # External AI Agent Action Execution
                self._apply_ai_actions(actions, sim_time)
            elif self.mode in ("marl_dqn", "marl_ppo") and self.marl_controller is not None:
                # MARL Coordinated Decision Execution
                ai_obs = self.get_ai_observations(states)
                decisions = self.marl_controller.decide(ai_obs, sim_time, eval_mode=True)
                executed_ops = self.marl_controller.apply_decisions(decisions, sim_time)
                for j_id, dec in decisions.items():
                    op_str = executed_ops.get(j_id, "NONE")
                    logger.info(
                        f"[MARL RUNTIME] SimTime={sim_time:.1f}s | Mode={self.mode} | Junction={j_id} | "
                        f"Agent={self.marl_controller.algorithm.upper()} | "
                        f"ObsShape={dec.get('observation_shape', (14,))} | "
                        f"Action={dec.get('action_name')} ({dec.get('action')}) | "
                        f"TargetPhase={dec.get('target_phase')} | ExecutedOp={op_str} | "
                        f"Fallback={dec.get('is_fallback')}"
                    )
            elif self.mode == "coordinated":
                # Built-in Coordinated Adaptive Strategy
                self._run_coordinated_control(states, sim_time)
            elif self.mode == "baseline":
                # Fixed-time: SUMO internal timing handles phase switches
                pass

        # 4. Metrics Recording
        emergency_duration = (
            self.emergency_coordinator.metrics.total_traversal_duration
            if self.emergency_coordinator.metrics.completed
            else 0.0
        )
        self.metrics_collector.record_step(sim_time, states, emergency_duration=emergency_duration)

        return states, True

    def _apply_ai_actions(self, actions: Dict[str, int], sim_time: float) -> None:
        """Executes actions supplied by an AI agent (0=KEEP, 1=SWITCH, 2=EXTEND)."""
        for j_id, action in actions.items():
            ctrl = self.controllers.get(j_id)
            if not ctrl or ctrl.emergency_locked:
                continue

            curr_phase = ctrl.get_phase()
            if action == 1:  # SWITCH
                target_phase = 2 if curr_phase == 0 else 0
                ctrl.request_switch(target_green_phase=target_phase, sim_time=sim_time)
            elif action == 2:  # EXTEND
                ctrl.extend_current_green(sim_time)

    def _run_coordinated_control(self, states: Dict[str, IntersectionState], sim_time: float) -> None:
        """
        Coordinated multi-intersection control logic:
        - J1 & J3: Coordinate progression along Hosur Road.
        - J2: Movement-aware queue pressure + anticipation of upstream J1 arrivals.
        """
        # --- J2 Adaptive Controller with Upstream Inflow Anticipation ---
        j2_ctrl = self.controllers["J2"]
        if not j2_ctrl.emergency_locked and j2_ctrl.is_green():
            j2_state = states["J2"]
            curr_phase = j2_ctrl.get_phase()
            hosur_q = j2_state.approach_queues.get("corridor_hosur", 0)
            madiwala_q = j2_state.approach_queues.get("madiwala", 0)

            # Upstream bonus: incoming traffic released from J1
            upstream_inflow_bonus = int(self.hub.get_expected_inflow("J2") * 5)
            effective_hosur_q = hosur_q + upstream_inflow_bonus

            elapsed = j2_ctrl.get_green_elapsed(sim_time)

            if curr_phase == 0:  # Hosur Green
                if elapsed >= j2_ctrl.min_green and madiwala_q > effective_hosur_q + 2:
                    j2_ctrl.request_switch(target_green_phase=2, sim_time=sim_time)
                elif effective_hosur_q > 0 and effective_hosur_q >= madiwala_q:
                    j2_ctrl.extend_current_green(sim_time)
            elif curr_phase == 2:  # Madiwala Green
                if elapsed >= j2_ctrl.min_green and effective_hosur_q > madiwala_q + 2:
                    j2_ctrl.request_switch(target_green_phase=0, sim_time=sim_time)
                elif madiwala_q > 0 and madiwala_q >= effective_hosur_q:
                    j2_ctrl.extend_current_green(sim_time)

        # --- J1 & J3 Progression Alignment ---
        for j_id, target_corridor_phase in [("J1", 2), ("J3", 2)]:
            ctrl = self.controllers[j_id]
            if not ctrl.emergency_locked and ctrl.is_green():
                q_corridor = states[j_id].approach_queues.get("corridor_hosur", 0)
                q_cross = states[j_id].approach_queues.get("side_cross", 0)
                curr_p = ctrl.get_phase()
                elapsed = ctrl.get_green_elapsed(sim_time)

                if curr_p == target_corridor_phase:
                    if q_corridor > 0 and elapsed < ctrl.max_green:
                        ctrl.extend_current_green(sim_time)
                    elif elapsed >= ctrl.min_green and q_cross > q_corridor + 2:
                        ctrl.request_switch(target_green_phase=0, sim_time=sim_time)
                else:
                    if elapsed >= ctrl.min_green and q_corridor > q_cross:
                        ctrl.request_switch(target_green_phase=target_corridor_phase, sim_time=sim_time)

    def run_full_simulation(self, duration_seconds: int = 600, seed: int = 42) -> CorridorMetricsSummary:
        """Executes a complete simulation run for duration_seconds and returns the summary."""
        self.start(seed=seed)
        try:
            while self.sumo_manager.get_time() < duration_seconds:
                self.step()
            emergency_completed = self.emergency_coordinator.metrics.completed
            emergency_dur = (
                self.emergency_coordinator.metrics.total_traversal_duration
                if emergency_completed
                else None
            )
            return self.metrics_collector.compute_summary(
                emergency_duration=emergency_dur,
                emergency_cleared=emergency_completed,
            )
        finally:
            self.close()

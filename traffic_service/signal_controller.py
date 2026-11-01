"""
traffic_service/signal_controller.py

Safe, constraint-respecting signal phase controller for individual traffic lights.
Enforces min_green, max_green, yellow clearance transitions, green extensions,
and priority locks for emergency vehicles.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set
import traci


class SignalController:
    """
    Manages phase switching and timing constraints for a single traffic light signal.
    Guarantees no unsafe green-to-green transitions.
    """

    def __init__(
        self,
        tls_id: str,
        green_phases: Set[int],
        yellow_transitions: Dict[int, int],  # from_green -> yellow_phase
        min_green: float = 15.0,
        max_green: float = 60.0,
        yellow_duration: float = 4.0,
        green_extension: float = 10.0,
    ) -> None:
        self.tls_id = tls_id
        self.green_phases = green_phases
        self.yellow_transitions = yellow_transitions
        self.min_green = min_green
        self.max_green = max_green
        self.yellow_duration = yellow_duration
        self.green_extension = green_extension

        self.emergency_locked: bool = False
        self.emergency_priority_phase: Optional[int] = None

    def get_phase(self) -> int:
        """Returns the current active phase."""
        try:
            return traci.trafficlight.getPhase(self.tls_id)
        except traci.TraCIException:
            return 0

    def is_green(self, phase: Optional[int] = None) -> bool:
        """Checks if current (or specified) phase is a green phase."""
        p = self.get_phase() if phase is None else phase
        return p in self.green_phases

    def is_yellow(self, phase: Optional[int] = None) -> bool:
        """Checks if current (or specified) phase is a yellow transition phase."""
        p = self.get_phase() if phase is None else phase
        return p in self.yellow_transitions.values()

    def get_green_elapsed(self, sim_time: float) -> float:
        """Calculates elapsed seconds in current phase."""
        try:
            next_switch = traci.trafficlight.getNextSwitch(self.tls_id)
            phase_duration = traci.trafficlight.getPhaseDuration(self.tls_id)
            remaining = max(0.0, next_switch - sim_time)
            return max(0.0, phase_duration - remaining)
        except traci.TraCIException:
            return 0.0

    def can_switch(self, sim_time: float) -> bool:
        """Returns True if the current phase is green and has met min_green."""
        if self.emergency_locked:
            return False
        if not self.is_green():
            return False
        return self.get_green_elapsed(sim_time) >= self.min_green

    def request_switch(self, target_green_phase: int, sim_time: float, force: bool = False) -> bool:
        """
        Safely initiates a phase switch to target_green_phase.
        If current phase differs, transitions through the mandatory yellow phase.
        """
        if self.emergency_locked and not force:
            return False

        current_phase = self.get_phase()
        if current_phase == target_green_phase:
            return True  # already in target phase

        # If currently in green, must go to corresponding yellow first
        if current_phase in self.green_phases:
            if not force and self.get_green_elapsed(sim_time) < self.min_green:
                return False  # Min green not satisfied

            yellow_phase = self.yellow_transitions.get(current_phase)
            if yellow_phase is not None:
                traci.trafficlight.setPhase(self.tls_id, yellow_phase)
                traci.trafficlight.setPhaseDuration(self.tls_id, self.yellow_duration)
                return True

        # If already in yellow, let SUMO complete the natural yellow transition
        return False

    def extend_current_green(self, sim_time: float) -> bool:
        """Extends current green duration up to max_green."""
        if self.emergency_locked:
            return False
        if not self.is_green():
            return False

        elapsed = self.get_green_elapsed(sim_time)
        if elapsed >= self.max_green:
            return False

        try:
            next_switch = traci.trafficlight.getNextSwitch(self.tls_id)
            remaining = max(0.0, next_switch - sim_time)
            new_remaining = min(remaining + self.green_extension, self.max_green - elapsed)

            if new_remaining > remaining:
                traci.trafficlight.setPhaseDuration(self.tls_id, new_remaining)
                return True
        except traci.TraCIException:
            pass
        return False

    def lock_emergency_priority(self, corridor_green_phase: int, sim_time: float) -> str:
        """
        Enforces emergency priority green for corridor.
        Safely sequences yellow if currently serving a conflicting phase.
        Returns the action taken ('ALREADY_GREEN', 'SWITCHING_YELLOW', 'HELD_PRIORITY').
        """
        current_phase = self.get_phase()

        if current_phase == corridor_green_phase:
            self.emergency_locked = True
            self.emergency_priority_phase = corridor_green_phase
            # Extend green safely while locked
            try:
                traci.trafficlight.setPhaseDuration(self.tls_id, 30.0)
            except traci.TraCIException:
                pass
            return "ALREADY_GREEN"

        # Conflicting green: force yellow transition
        if current_phase in self.green_phases:
            yellow_phase = self.yellow_transitions.get(current_phase)
            if yellow_phase is not None:
                traci.trafficlight.setPhase(self.tls_id, yellow_phase)
                traci.trafficlight.setPhaseDuration(self.tls_id, self.yellow_duration)
                return "SWITCHING_YELLOW"

        # Already in yellow: wait for transition to target green
        if self.is_yellow(current_phase):
            return "CLEARING_YELLOW"

        return "HOLD"

    def release_emergency_priority(self) -> None:
        """Releases the emergency lock, restoring normal/adaptive control."""
        self.emergency_locked = False
        self.emergency_priority_phase = None

"""
traffic_service/communication.py

Inter-intersection communication layer for corridor coordination (J1 <-> J2 <-> J3).
Exchanges upstream inflow rates, platoon release predictions, and emergency alerts.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional


@dataclass
class IntersectionMessage:
    """Inter-intersection message packet."""
    sender_id: str
    receiver_id: str
    timestamp: float
    message_type: str  # 'PLATOON_RELEASE', 'UPSTREAM_INFLOW', 'EMERGENCY_ALERT', 'CONGESTION_WARNING'
    payload: Dict[str, Any] = field(default_factory=dict)


class CorridorCommunicationHub:
    """
    Message bus enabling coordinated traffic management across multiple intersections.
    Maintains topological sequence: J1 -> J2 -> J3.
    """

    def __init__(self, corridor_sequence: Optional[List[str]] = None) -> None:
        self.corridor_sequence: List[str] = corridor_sequence or ["J1", "J2", "J3"]
        self._inbox: Dict[str, Deque[IntersectionMessage]] = defaultdict(deque)
        self._latest_inflow: Dict[str, float] = defaultdict(float)
        self._active_platoons: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self._emergency_broadcast: Optional[Dict[str, Any]] = None

    def send(self, msg: IntersectionMessage) -> None:
        """Sends a point-to-point message to a specific intersection."""
        self._inbox[msg.receiver_id].append(msg)

    def broadcast(self, sender_id: str, msg_type: str, timestamp: float, payload: Dict[str, Any]) -> None:
        """Broadcasts a message to all other intersections along the corridor."""
        for j_id in self.corridor_sequence:
            if j_id != sender_id:
                msg = IntersectionMessage(
                    sender_id=sender_id,
                    receiver_id=j_id,
                    timestamp=timestamp,
                    message_type=msg_type,
                    payload=payload,
                )
                self.send(msg)

    def get_messages(self, receiver_id: str, clear: bool = True) -> List[IntersectionMessage]:
        """Retrieves messages received by an intersection."""
        msgs = list(self._inbox[receiver_id])
        if clear:
            self._inbox[receiver_id].clear()
        return msgs

    def publish_upstream_inflow(self, sender_id: str, outflow_rate_veh_s: float, timestamp: float) -> None:
        """
        Notifies the next downstream intersection of current outflow rate
        destined for the downstream corridor.
        """
        if sender_id not in self.corridor_sequence:
            return

        idx = self.corridor_sequence.index(sender_id)
        if idx + 1 < len(self.corridor_sequence):
            downstream_id = self.corridor_sequence[idx + 1]
            self._latest_inflow[downstream_id] = outflow_rate_veh_s
            msg = IntersectionMessage(
                sender_id=sender_id,
                receiver_id=downstream_id,
                timestamp=timestamp,
                message_type="UPSTREAM_INFLOW",
                payload={"inflow_rate_veh_s": outflow_rate_veh_s},
            )
            self.send(msg)

    def get_expected_inflow(self, receiver_id: str) -> float:
        """Returns the most recent anticipated inflow rate from the upstream intersection."""
        return self._latest_inflow.get(receiver_id, 0.0)

    def announce_platoon(
        self,
        sender_id: str,
        vehicle_count: int,
        speed_mps: float,
        eta_seconds: float,
        timestamp: float,
    ) -> None:
        """
        Notifies the immediate downstream intersection of a departing vehicle platoon
        so it can prepare green-wave alignment.
        """
        if sender_id not in self.corridor_sequence:
            return

        idx = self.corridor_sequence.index(sender_id)
        if idx + 1 < len(self.corridor_sequence):
            downstream_id = self.corridor_sequence[idx + 1]
            platoon_info = {
                "origin": sender_id,
                "count": vehicle_count,
                "speed_mps": speed_mps,
                "arrival_time": timestamp + eta_seconds,
            }
            self._active_platoons[downstream_id].append(platoon_info)
            msg = IntersectionMessage(
                sender_id=sender_id,
                receiver_id=downstream_id,
                timestamp=timestamp,
                message_type="PLATOON_RELEASE",
                payload=platoon_info,
            )
            self.send(msg)

    def get_approaching_platoons(self, junction_id: str, current_time: float) -> List[Dict[str, Any]]:
        """Returns platoons expected to arrive within the next 30 seconds."""
        platoons = self._active_platoons.get(junction_id, [])
        valid = [p for p in platoons if p["arrival_time"] >= current_time]
        self._active_platoons[junction_id] = valid
        return valid

    def broadcast_emergency(
        self,
        ambulance_id: str,
        current_location: str,
        etas: Dict[str, float],
        timestamp: float,
    ) -> None:
        """Broadcasts corridor-wide emergency vehicle tracking data."""
        self._emergency_broadcast = {
            "ambulance_id": ambulance_id,
            "current_location": current_location,
            "etas": etas,
            "timestamp": timestamp,
        }
        self.broadcast(
            sender_id="EMERGENCY_SERVICE",
            msg_type="EMERGENCY_ALERT",
            timestamp=timestamp,
            payload=self._emergency_broadcast,
        )

    def get_emergency_status(self) -> Optional[Dict[str, Any]]:
        """Returns the latest corridor emergency alert."""
        return self._emergency_broadcast

    def clear_emergency(self, timestamp: float) -> None:
        """Clears the corridor emergency alert."""
        self._emergency_broadcast = None
        self.broadcast(
            sender_id="EMERGENCY_SERVICE",
            msg_type="EMERGENCY_CLEARED",
            timestamp=timestamp,
            payload={},
        )

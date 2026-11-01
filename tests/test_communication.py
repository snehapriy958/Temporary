"""
tests/test_communication.py

Unit tests for inter-intersection communication bus and message routing.
"""

import pytest
from traffic_service.communication import CorridorCommunicationHub, IntersectionMessage


def test_hub_initialization():
    hub = CorridorCommunicationHub(corridor_sequence=["J1", "J2", "J3"])
    assert hub.corridor_sequence == ["J1", "J2", "J3"]
    assert hub.get_expected_inflow("J2") == 0.0


def test_point_to_point_messaging():
    hub = CorridorCommunicationHub(corridor_sequence=["J1", "J2", "J3"])
    msg = IntersectionMessage(
        sender_id="J1",
        receiver_id="J2",
        timestamp=10.0,
        message_type="QUEUE_ALERT",
        payload={"queue": 15},
    )
    hub.send(msg)

    # J3 inbox should be empty
    assert len(hub.get_messages("J3")) == 0

    # J2 inbox should have the message
    j2_inbox = hub.get_messages("J2")
    assert len(j2_inbox) == 1
    assert j2_inbox[0].payload["queue"] == 15

    # Inbox should clear after read
    assert len(hub.get_messages("J2")) == 0


def test_upstream_inflow_propagation():
    hub = CorridorCommunicationHub(corridor_sequence=["J1", "J2", "J3"])
    hub.publish_upstream_inflow(sender_id="J1", outflow_rate_veh_s=2.5, timestamp=20.0)

    # J2 should record expected inflow from J1
    assert hub.get_expected_inflow("J2") == 2.5
    # J3 should not yet receive inflow directly from J1
    assert hub.get_expected_inflow("J3") == 0.0

    # J1 messages should be delivered to J2
    msgs = hub.get_messages("J2")
    assert len(msgs) == 1
    assert msgs[0].message_type == "UPSTREAM_INFLOW"
    assert msgs[0].payload["inflow_rate_veh_s"] == 2.5


def test_platoon_announcement():
    hub = CorridorCommunicationHub(corridor_sequence=["J1", "J2", "J3"])
    hub.announce_platoon(
        sender_id="J2",
        vehicle_count=8,
        speed_mps=12.0,
        eta_seconds=15.0,
        timestamp=50.0,
    )

    # J3 should see approaching platoon arriving at t=65.0
    platoons = hub.get_approaching_platoons("J3", current_time=55.0)
    assert len(platoons) == 1
    assert platoons[0]["count"] == 8
    assert platoons[0]["arrival_time"] == 65.0

    # If queried past arrival time, expired platoons are filtered
    expired = hub.get_approaching_platoons("J3", current_time=70.0)
    assert len(expired) == 0


def test_emergency_broadcast():
    hub = CorridorCommunicationHub(corridor_sequence=["J1", "J2", "J3"])
    hub.broadcast_emergency(
        ambulance_id="ambulance_0",
        current_location="172853382#2",
        etas={"J1": 5.0, "J2": 25.0, "J3": 45.0},
        timestamp=100.0,
    )

    status = hub.get_emergency_status()
    assert status is not None
    assert status["ambulance_id"] == "ambulance_0"
    assert status["etas"]["J1"] == 5.0

    hub.clear_emergency(timestamp=110.0)
    assert hub.get_emergency_status() is None

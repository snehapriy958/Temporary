"""
tests/test_websocket.py

Unit tests for real-time WebSocket telemetry endpoint.
"""

import json
import pytest
from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def test_websocket_traffic_stream():
    """Tests WebSocket connection and initial telemetry payload structure."""
    with client.websocket_connect("/ws/traffic") as websocket:
        data = websocket.receive_json()
        assert data is not None
        assert data.get("type") == "INITIAL_STATE"
        assert "simulation_time" in data
        assert "status" in data
        assert "junctions" in data
        assert "metrics" in data
        assert "signals" in data
        assert "emergencies" in data
        assert "decisions" in data

        # Send ping to verify bidirectional heartbeat
        websocket.send_text("ping")
        pong = websocket.receive_json()
        assert pong.get("type") == "PONG"

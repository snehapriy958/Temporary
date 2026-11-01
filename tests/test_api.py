"""
tests/test_api.py

Unit and integration tests for FastAPI REST API endpoints.
Tests health, simulation controls, input validation, signals, traffic metrics,
emergencies, risk zones, decisions, and comparisons.
"""

import pytest
from fastapi.testclient import TestClient

from backend.database import init_db
from backend.main import app
from backend.simulation_service import sim_service

client = TestClient(app)


def setup_module():
    """Initialize DB tables."""
    init_db()


def setup_function():
    """Ensure clean simulation state before each test."""
    sim_service.reset_simulation()


def teardown_function():
    """Clean up after test."""
    sim_service.stop_simulation()


def test_health_endpoint():
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "sumo_available" in data
    assert "sumo_version" in data
    assert "active_simulation" in data


def test_simulation_status():
    response = client.get("/api/simulation/status")
    assert response.status_code == 200
    data = response.json()
    assert data["running"] is False
    assert data["paused"] is False
    assert data["simulation_time"] == 0.0
    assert "junctions" in data
    assert set(data["junctions"]) == {"J1", "J2", "J3"}


def test_simulation_start_validation():
    # Test invalid mode
    res_bad = client.post("/api/simulation/start", json={"mode": "invalid_mode"})
    assert res_bad.status_code == 400

    # Test invalid duration (< 10)
    res_short = client.post("/api/simulation/start", json={"duration": 5})
    assert res_short.status_code == 422  # Pydantic validation error


def test_traffic_live():
    response = client.get("/api/traffic/live")
    assert response.status_code == 200
    data = response.json()
    assert "simulation_time" in data
    assert "status" in data
    assert "junctions" in data
    assert "J1" in data["junctions"]
    assert "J2" in data["junctions"]
    assert "J3" in data["junctions"]


def test_traffic_metrics():
    response = client.get("/api/traffic/metrics")
    assert response.status_code == 200
    data = response.json()
    assert "total_vehicles" in data
    assert "throughput_vehicles" in data
    assert "mean_speed_kmh" in data
    assert "total_co2_kg" in data
    assert "total_fuel_liters" in data


def test_signals_endpoint():
    response = client.get("/api/signals")
    assert response.status_code == 200
    data = response.json()
    assert "signals" in data
    assert "J1" in data["signals"]
    assert "J2" in data["signals"]
    assert "J3" in data["signals"]


def test_signal_override_validation():
    # Unconfirmed override should fail
    res_unconf = client.post(
        "/api/signals/override",
        json={"junction_id": "J2", "target_phase": 0, "confirmed": False},
    )
    assert res_unconf.status_code == 400
    assert "confirmation" in res_unconf.json()["detail"].lower()

    # Confirmed override when simulation is not running
    res_not_run = client.post(
        "/api/signals/override",
        json={"junction_id": "J2", "target_phase": 0, "confirmed": True},
    )
    assert res_not_run.status_code == 400
    assert "not currently running" in res_not_run.json()["detail"].lower()


def test_emergencies_endpoint():
    response = client.get("/api/emergencies")
    assert response.status_code == 200
    data = response.json()
    assert "active_emergency" in data
    assert "emergency_locked_junctions" in data
    assert "events" in data


def test_risks_endpoint():
    response = client.get("/api/risks")
    assert response.status_code == 200
    data = response.json()
    assert "total_zones" in data
    assert "risk_zones" in data
    assert "hotspots" in data
    assert len(data["risk_zones"]) >= 1


def test_decisions_endpoint():
    response = client.get("/api/decisions")
    assert response.status_code == 200
    data = response.json()
    assert "total_decisions" in data
    assert "decisions" in data
    assert len(data["decisions"]) >= 1


def test_experiments_compare():
    response = client.get("/api/experiments/compare")
    assert response.status_code == 200
    data = response.json()
    assert "controllers" in data
    names = [c["controller_name"] for c in data["controllers"]]
    assert "Fixed-Time Baseline" in names
    assert "Coordinated Adaptive Controller" in names
    assert "PPO (Proximal Policy Optimization)" in names
    assert "DQN (Deep Q-Network)" in names

    # Verify PPO and DQN are explicitly marked Not implemented
    for c in data["controllers"]:
        if "PPO" in c["controller_name"] or "DQN" in c["controller_name"]:
            assert c["status"] == "Not implemented"


def test_experiments_history():
    response = client.get("/api/experiments/history")
    assert response.status_code == 200
    assert isinstance(response.json(), list)

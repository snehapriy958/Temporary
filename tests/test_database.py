"""
tests/test_database.py

Unit tests for database initialization, models, and metric persistence.
"""

from datetime import datetime
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.models import (
    Base,
    EmergencyEventRecord,
    RiskZoneRecord,
    SignalDecisionRecord,
    SimulationRun,
    TrafficMetricRecord,
)

TEST_DB_URL = "sqlite:///:memory:"


@pytest.fixture
def test_db():
    engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_simulation_run_persistence(test_db):
    run = SimulationRun(
        run_uuid="test_uuid_123",
        mode="coordinated",
        status="RUNNING",
        seed=42,
        duration_requested=600,
        started_at=datetime.utcnow(),
    )
    test_db.add(run)
    test_db.commit()
    test_db.refresh(run)

    assert run.id is not None
    assert run.run_uuid == "test_uuid_123"

    # Add associated metrics
    metric = TrafficMetricRecord(
        run_id=run.id,
        simulation_time=15.0,
        total_vehicles=25,
        throughput_vehicles=5,
        mean_speed_kmh=34.2,
        co2_kg=1.45,
    )
    test_db.add(metric)
    test_db.commit()

    saved_run = test_db.query(SimulationRun).filter_by(run_uuid="test_uuid_123").first()
    assert len(saved_run.metrics) == 1
    assert saved_run.metrics[0].total_vehicles == 25


def test_risk_zone_persistence(test_db):
    zone = RiskZoneRecord(
        zone_id="RZ_SILK_BOARD",
        zone_name="Silk Board Junction Core",
        risk_level="CRITICAL",
        composite_risk_score=92.5,
        total_crashes=34,
        fatal_crashes=8,
        center_latitude=12.9172,
        center_longitude=77.6228,
        associated_junction="J2",
        safety_advisory="Enforce dedicated yellow clearance transitions and high-speed corridor caution.",
    )
    test_db.add(zone)
    test_db.commit()

    saved = test_db.query(RiskZoneRecord).filter_by(zone_id="RZ_SILK_BOARD").first()
    assert saved is not None
    assert saved.risk_level == "CRITICAL"
    assert saved.composite_risk_score == 92.5

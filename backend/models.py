"""
backend/models.py

SQLAlchemy database models for Smart Traffic Coordination dashboard.
"""

from __future__ import annotations

from datetime import datetime
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class SimulationRun(Base):
    """Stores records of completed and running traffic simulation sessions."""
    __tablename__ = "simulation_runs"

    id = Column(Integer, primary_key=True, index=True)
    run_uuid = Column(String(64), unique=True, index=True, nullable=False)
    mode = Column(String(32), nullable=False)  # 'baseline' or 'coordinated'
    status = Column(String(32), default="INITIALIZING")  # RUNNING, PAUSED, COMPLETED, STOPPED, ERROR
    seed = Column(Integer, default=42)
    duration_requested = Column(Integer, default=600)
    duration_simulated = Column(Float, default=0.0)
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    summary_metrics_json = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)

    metrics = relationship("TrafficMetricRecord", back_populates="run", cascade="all, delete-orphan")
    decisions = relationship("SignalDecisionRecord", back_populates="run", cascade="all, delete-orphan")
    emergencies = relationship("EmergencyEventRecord", back_populates="run", cascade="all, delete-orphan")


class TrafficMetricRecord(Base):
    """Periodic snapshots of corridor performance during a simulation run."""
    __tablename__ = "traffic_metrics"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("simulation_runs.id"), nullable=False, index=True)
    simulation_time = Column(Float, nullable=False, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    total_vehicles = Column(Integer, default=0)
    throughput_vehicles = Column(Integer, default=0)
    mean_speed_kmh = Column(Float, default=0.0)
    mean_queue = Column(Float, default=0.0)
    max_queue = Column(Integer, default=0)
    total_waiting_time = Column(Float, default=0.0)
    co2_kg = Column(Float, default=0.0)
    nox_g = Column(Float, default=0.0)
    fuel_liters = Column(Float, default=0.0)

    run = relationship("SimulationRun", back_populates="metrics")


class SignalDecisionRecord(Base):
    """Log of adaptive and manual signal control actions."""
    __tablename__ = "signal_decisions"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("simulation_runs.id"), nullable=True, index=True)
    simulation_time = Column(Float, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    junction_id = Column(String(16), nullable=False, index=True)  # J1, J2, J3
    current_phase = Column(Integer, nullable=False)
    target_phase = Column(Integer, nullable=True)
    action = Column(String(32), nullable=False)  # SWITCH, EXTEND, KEEP, EMERGENCY_PREEMPTION, MANUAL_OVERRIDE
    reason = Column(Text, nullable=False)
    is_override = Column(Boolean, default=False)

    run = relationship("SimulationRun", back_populates="decisions")


class EmergencyEventRecord(Base):
    """History of emergency vehicle preemption events."""
    __tablename__ = "emergency_events"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("simulation_runs.id"), nullable=True, index=True)
    simulation_time = Column(Float, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    vehicle_id = Column(String(64), nullable=False)
    affected_corridor = Column(String(64), default="J1 -> J2 -> J3")
    preemption_active = Column(Boolean, default=False)
    arrival_time = Column(Float, default=0.0)
    clearance_time = Column(Float, default=0.0)
    traversal_duration = Column(Float, default=0.0)
    completed = Column(Boolean, default=False)

    run = relationship("SimulationRun", back_populates="emergencies")


class RiskZoneRecord(Base):
    """Documented accident blackspots and MoRTH/IRC risk zones."""
    __tablename__ = "risk_zones"

    id = Column(Integer, primary_key=True, index=True)
    zone_id = Column(String(32), unique=True, index=True, nullable=False)
    zone_name = Column(String(128), nullable=False)
    risk_level = Column(String(16), nullable=False)  # CRITICAL, HIGH, MEDIUM, LOW
    composite_risk_score = Column(Float, default=0.0)
    total_crashes = Column(Integer, default=0)
    fatal_crashes = Column(Integer, default=0)
    center_latitude = Column(Float, nullable=False)
    center_longitude = Column(Float, nullable=False)
    associated_junction = Column(String(16), nullable=True)
    affected_edges = Column(Text, nullable=True)
    safety_advisory = Column(Text, nullable=True)

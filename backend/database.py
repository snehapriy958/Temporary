"""
backend/database.py

Database session setup, engine creation, and schema initialization logic.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.config import BASE_DIR, DATABASE_URL
from backend.models import Base, RiskZoneRecord

# SQLite connect args
connect_args = {"check_same_thread": False} if "sqlite" in DATABASE_URL else {}

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency for obtaining a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Creates database tables and pre-populates historical risk zones if empty."""
    Base.metadata.create_all(bind=engine)

    # Seed risk zones from outputs/risk/risk_zones.json if available and table is empty
    db = SessionLocal()
    try:
        count = db.query(RiskZoneRecord).count()
        if count == 0:
            json_file = BASE_DIR / "outputs" / "risk" / "risk_zones.json"
            if json_file.is_file():
                try:
                    with open(json_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    items = data.get("risk_zones", []) if isinstance(data, dict) else data
                    for z in items:
                        edges_str = json.dumps(z.get("affected_edges", []))
                        rec = RiskZoneRecord(
                            zone_id=z.get("zone_id", ""),
                            zone_name=z.get("zone_name", ""),
                            risk_level=z.get("risk_level", "LOW"),
                            composite_risk_score=float(z.get("composite_risk_score", 0.0)),
                            total_crashes=int(z.get("total_crashes", 0)),
                            fatal_crashes=int(z.get("fatal_crashes", 0)),
                            center_latitude=float(z.get("center_latitude", 0.0)),
                            center_longitude=float(z.get("center_longitude", 0.0)),
                            associated_junction=z.get("associated_junction"),
                            affected_edges=edges_str,
                            safety_advisory=z.get("safety_advisory", ""),
                        )
                        db.add(rec)
                    db.commit()
                except Exception as exc:
                    db.rollback()
                    print(f"[Database] Warning: Failed to seed risk zones: {exc}")
    finally:
        db.close()

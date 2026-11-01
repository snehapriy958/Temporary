"""
backend/risk_service.py

Service layer for reading documented accident blackspots, IRC/MoRTH risk zones,
and spatial hotspot clusters.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, List

from backend.config import BASE_DIR
from backend.schemas import HotspotItemSchema, RiskZoneItemSchema, RisksResponse


def get_risk_zones() -> List[RiskZoneItemSchema]:
    """Reads risk zones from outputs/risk/risk_zones.json."""
    json_path = BASE_DIR / "outputs" / "risk" / "risk_zones.json"
    zones: List[RiskZoneItemSchema] = []
    if json_path.is_file():
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            items = data.get("risk_zones", []) if isinstance(data, dict) else data
            for item in items:
                zones.append(
                    RiskZoneItemSchema(
                        zone_id=item.get("zone_id", ""),
                        zone_name=item.get("zone_name", ""),
                        risk_level=item.get("risk_level", "LOW"),
                        composite_risk_score=float(item.get("composite_risk_score", 0.0)),
                        total_crashes=int(item.get("total_crashes", 0)),
                        fatal_crashes=int(item.get("fatal_crashes", 0)),
                        center_latitude=float(item.get("center_latitude", 0.0)),
                        center_longitude=float(item.get("center_longitude", 0.0)),
                        associated_junction=item.get("associated_junction"),
                        affected_edges=item.get("affected_edges", []),
                        safety_advisory=item.get("safety_advisory", ""),
                    )
                )
        except Exception as exc:
            print(f"[RiskService] Failed reading risk_zones.json: {exc}")
    return zones


def get_hotspots() -> List[HotspotItemSchema]:
    """Reads accident hotspot clusters from outputs/hotspots/hotspots.csv."""
    csv_path = BASE_DIR / "outputs" / "hotspots" / "hotspots.csv"
    hotspots: List[HotspotItemSchema] = []
    if csv_path.is_file():
        try:
            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    hotspots.append(
                        HotspotItemSchema(
                            hotspot_id=row.get("hotspot_id", ""),
                            blackspot_count=int(row.get("blackspot_count", 0)),
                            total_crashes=int(row.get("total_crashes", 0)),
                            fatal_crashes=int(row.get("fatal_crashes", 0)),
                            severity_score=float(row.get("severity_score", 0.0)),
                            center_latitude=float(row.get("center_latitude", 0.0)),
                            center_longitude=float(row.get("center_longitude", 0.0)),
                            corridor_relevance=row.get("corridor_relevance", "UNKNOWN"),
                        )
                    )
        except Exception as exc:
            print(f"[RiskService] Failed reading hotspots.csv: {exc}")
    return hotspots


def get_full_risk_assessment() -> RisksResponse:
    """Aggregates all risk zones and hotspots."""
    zones = get_risk_zones()
    hotspots = get_hotspots()
    critical_count = sum(1 for z in zones if z.risk_level.upper() == "CRITICAL")
    high_count = sum(1 for z in zones if z.risk_level.upper() == "HIGH")

    return RisksResponse(
        total_zones=len(zones),
        critical_zones=critical_count,
        high_zones=high_count,
        risk_zones=zones,
        hotspots=hotspots,
    )

"""
traffic_service/risk_mapper.py

Risk-zone mapping module translating hotspot clusters and documented blackspots
into standardized operational risk tiers (CRITICAL, HIGH, MEDIUM, LOW) for the
road network and signalized intersections (J1, J2, J3).
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .hotspot_analyzer import Hotspot


@dataclass
class RiskZone:
    """Designated spatial risk zone with classification and traffic control advice."""
    zone_id: str
    zone_name: str
    risk_level: str  # "CRITICAL", "HIGH", "MEDIUM", "LOW"
    composite_risk_score: float
    total_crashes: int
    fatal_crashes: int
    center_latitude: float
    center_longitude: float
    center_x: float
    center_y: float
    associated_junction: Optional[str]  # e.g. "J1", "J2", "J3", or None
    affected_edges: List[str]
    safety_advisory: str


class RiskMapper:
    """
    Evaluates observed accident frequency, fatality counts, and network infrastructure
    proximity to generate operational risk classifications for traffic management.
    """

    # Defensible threshold boundaries for Composite Risk Index (CRI)
    THRESHOLD_CRITICAL = 60.0
    THRESHOLD_HIGH = 35.0
    THRESHOLD_MEDIUM = 15.0

    def __init__(self) -> None:
        self.risk_zones: List[RiskZone] = []

    def compute_composite_risk(
        self,
        severity_score: float,
        is_corridor: bool,
        has_junction: bool,
    ) -> float:
        """
        Calculates Composite Risk Index (CRI).
        Base is the MoRTH-weighted severity score, with project-specific engineering
        multiplier bonuses for arterial corridor transit (+50%) and signalized
        intersection conflict zones (+30%).
        """
        corridor_multiplier = 0.5 if is_corridor else 0.0
        junction_multiplier = 0.3 if has_junction else 0.0
        cri = severity_score * (1.0 + corridor_multiplier + junction_multiplier)
        return round(cri, 2)

    def classify_risk_tier(self, score: float) -> str:
        """Classifies a composite risk score into standard operational tiers."""
        if score >= self.THRESHOLD_CRITICAL:
            return "CRITICAL"
        if score >= self.THRESHOLD_HIGH:
            return "HIGH"
        if score >= self.THRESHOLD_MEDIUM:
            return "MEDIUM"
        return "LOW"

    def generate_advisory(self, risk_level: str, assoc_j: Optional[str]) -> str:
        """Generates domain safety and signal timing advisory."""
        if risk_level == "CRITICAL":
            return (
                f"Severe collision hazard at {assoc_j or 'corridor node'}. "
                "Enforce mandatory all-red clearance transitions, strict maximum green limits, "
                "and prioritize uninterrupted emergency preemption."
            )
        if risk_level == "HIGH":
            return (
                f"Elevated collision density near {assoc_j or 'approach edge'}. "
                "Recommend dilemma-zone green extensions and pedestrian protection phases."
            )
        if risk_level == "MEDIUM":
            return "Moderate incident history. Standard adaptive signal queue management applicable."
        return "Low incident history. Maintain default coordinated progression."

    def map_hotspots_to_risk_zones(self, hotspots: List[Hotspot]) -> List[RiskZone]:
        """Translates detected hotspots into formal risk zones."""
        self.risk_zones = []

        for h in hotspots:
            is_corridor = h.corridor_relevance == "CORRIDOR"
            has_junction = len(h.affected_junctions) > 0

            # Match associated corridor junction
            assoc_j = None
            for j in ["J1", "J2", "J3"]:
                if j in h.affected_junctions or any(j in item for item in h.affected_junctions):
                    assoc_j = j
                    break

            if not assoc_j and math_dist_close(h.center_latitude, h.center_longitude, 12.9172, 77.6228, 0.003):
                assoc_j = "J2"
            elif not assoc_j and math_dist_close(h.center_latitude, h.center_longitude, 12.9210, 77.6205, 0.003):
                assoc_j = "J1"
            elif not assoc_j and math_dist_close(h.center_latitude, h.center_longitude, 12.9125, 77.6240, 0.003):
                assoc_j = "J3"

            score = self.compute_composite_risk(
                severity_score=h.severity_score,
                is_corridor=is_corridor or (assoc_j is not None),
                has_junction=has_junction or (assoc_j is not None),
            )
            tier = self.classify_risk_tier(score)
            advisory = self.generate_advisory(tier, assoc_j)

            zone_name = f"Silk Board Zone {h.hotspot_id}"
            if assoc_j:
                zone_name += f" ({assoc_j} Focus)"

            self.risk_zones.append(
                RiskZone(
                    zone_id=f"RZ_{h.hotspot_id}",
                    zone_name=zone_name,
                    risk_level=tier,
                    composite_risk_score=score,
                    total_crashes=h.total_crashes,
                    fatal_crashes=h.fatal_crashes,
                    center_latitude=h.center_latitude,
                    center_longitude=h.center_longitude,
                    center_x=h.center_x,
                    center_y=h.center_y,
                    associated_junction=assoc_j,
                    affected_edges=h.affected_edges,
                    safety_advisory=advisory,
                )
            )

        self.risk_zones.sort(key=lambda z: z.composite_risk_score, reverse=True)
        return self.risk_zones

    def export_json(self, output_path: Path | str) -> None:
        """Exports risk zones to JSON."""
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "metadata": {
                "system": "Hybrid AI Traffic Control — Silk Board Corridor",
                "risk_model": "Documented Blackspot Severity & Infrastructure Proximity Index (CRI)",
                "note": "Corridor risk analysis uses documented georeferenced blackspots as weighted spatial observations rather than individual historical crash records.",
                "thresholds": {
                    "CRITICAL": f">= {self.THRESHOLD_CRITICAL}",
                    "HIGH": f"{self.THRESHOLD_HIGH} - {self.THRESHOLD_CRITICAL}",
                    "MEDIUM": f"{self.THRESHOLD_MEDIUM} - {self.THRESHOLD_HIGH}",
                    "LOW": f"< {self.THRESHOLD_MEDIUM}",
                },
            },
            "risk_zones": [asdict(z) for z in self.risk_zones],
        }
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def export_csv(self, output_path: Path | str) -> None:
        """Exports risk summary table to CSV."""
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not self.risk_zones:
            return

        with path.open("w", newline="", encoding="utf-8") as f:
            fieldnames = [
                "zone_id",
                "zone_name",
                "risk_level",
                "composite_risk_score",
                "total_crashes",
                "fatal_crashes",
                "center_latitude",
                "center_longitude",
                "associated_junction",
                "affected_edges",
                "safety_advisory",
            ]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for z in self.risk_zones:
                row = asdict(z)
                row["affected_edges"] = ";".join(z.affected_edges)
                del row["center_x"]
                del row["center_y"]
                writer.writerow(row)


def math_dist_close(lat1: float, lon1: float, lat2: float, lon2: float, tol: float = 0.003) -> bool:
    """Checks coordinate closeness within simple degree tolerance."""
    return abs(lat1 - lat2) <= tol and abs(lon1 - lon2) <= tol

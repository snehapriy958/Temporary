"""
traffic_service/hotspot_analyzer.py

Hotspot analysis module identifying high-risk crash clusters along the road network.
Operates directly on georeferenced blackspot observations using spatial clustering
and IRC/MoRTH severity-weighted scoring without artificial incident unrolling.
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
import math
from pathlib import Path
from typing import Dict, List, Optional
import numpy as np
from sklearn.cluster import DBSCAN

from .spatial_mapper import MappedBlackspot


# MoRTH / IRC Road Safety Audit Severity Weights
SEVERITY_WEIGHT_FATAL = 5.0
SEVERITY_WEIGHT_NON_FATAL = 2.0


@dataclass
class Hotspot:
    """Accident hotspot cluster with aggregated crash metrics and severity score."""
    hotspot_id: str
    blackspot_count: int
    total_crashes: int
    fatal_crashes: int
    non_fatal_crashes: int
    severity_score: float
    center_x: float
    center_y: float
    center_latitude: float
    center_longitude: float
    affected_edges: List[str]
    affected_junctions: List[str]
    radius_m: float
    corridor_relevance: str  # "CORRIDOR", "CORRIDOR_APPROACH", "OFF_CORRIDOR"


class HotspotAnalyzer:
    """
    Identifies geographic clusters of blackspots and ranks them by incident frequency
    and weighted severity score directly from aggregate observations.
    """

    def __init__(
        self,
        eps_meters: float = 200.0,
        min_samples: int = 1,
        weight_fatal: float = SEVERITY_WEIGHT_FATAL,
        weight_non_fatal: float = SEVERITY_WEIGHT_NON_FATAL,
    ) -> None:
        self.eps_meters = eps_meters
        self.min_samples = min_samples
        self.weight_fatal = weight_fatal
        self.weight_non_fatal = weight_non_fatal
        self.hotspots: List[Hotspot] = []

    def compute_severity_score(self, fatal: int, non_fatal: int) -> float:
        """Calculates IRC/MoRTH severity-weighted score."""
        return round((fatal * self.weight_fatal) + (non_fatal * self.weight_non_fatal), 1)

    def analyze(self, mapped_blackspots: List[MappedBlackspot]) -> List[Hotspot]:
        """Runs spatial clustering across blackspots and computes aggregate hotspot metrics."""
        self.hotspots = []
        if not mapped_blackspots:
            return []

        coords = np.array([[b.sumo_x, b.sumo_y] for b in mapped_blackspots])

        # Cluster using metric DBSCAN (Euclidean distance on UTM coordinates in meters)
        clustering = DBSCAN(eps=self.eps_meters, min_samples=self.min_samples, metric="euclidean")
        labels = clustering.fit_predict(coords)

        unique_labels = sorted(set(labels))
        hotspot_idx = 1

        for label in unique_labels:
            if label == -1 and len(unique_labels) > 1:
                # Handle unclustered noise points individually
                cluster_indices = [i for i, l in enumerate(labels) if l == -1]
            else:
                cluster_indices = [i for i, l in enumerate(labels) if l == label]

            # If noise points grouped together, process each individually
            if label == -1 and len(unique_labels) > 1:
                sub_groups = [[idx] for idx in cluster_indices]
            else:
                sub_groups = [cluster_indices]

            for group in sub_groups:
                spots = [mapped_blackspots[i] for i in group]
                group_coords = coords[group]

                center_x = float(np.mean(group_coords[:, 0]))
                center_y = float(np.mean(group_coords[:, 1]))
                center_lat = float(np.mean([s.latitude for s in spots]))
                center_lon = float(np.mean([s.longitude for s in spots]))

                total_c = sum(s.annual_crashes for s in spots)
                fatal_c = sum(s.fatal_crashes for s in spots)
                non_fatal_c = max(0, total_c - fatal_c)

                score = self.compute_severity_score(fatal_c, non_fatal_c)

                distances = [math.hypot(x - center_x, y - center_y) for x, y in group_coords]
                radius = max(distances) if distances else 0.0

                edges = sorted(list({s.nearest_edge_id for s in spots if s.nearest_edge_id}))
                junctions = sorted(list({s.corridor_junction or s.nearest_junction_id for s in spots if s.nearest_junction_id or s.corridor_junction}))

                is_corridor = any(s.is_corridor for s in spots)
                relevance = "CORRIDOR" if is_corridor else "OFF_CORRIDOR"

                self.hotspots.append(
                    Hotspot(
                        hotspot_id=f"HS_{hotspot_idx:02d}",
                        blackspot_count=len(spots),
                        total_crashes=total_c,
                        fatal_crashes=fatal_c,
                        non_fatal_crashes=non_fatal_c,
                        severity_score=score,
                        center_x=round(center_x, 2),
                        center_y=round(center_y, 2),
                        center_latitude=round(center_lat, 6),
                        center_longitude=round(center_lon, 6),
                        affected_edges=edges,
                        affected_junctions=junctions,
                        radius_m=round(radius, 2),
                        corridor_relevance=relevance,
                    )
                )
                hotspot_idx += 1

        self.hotspots.sort(key=lambda h: h.severity_score, reverse=True)
        return self.hotspots

    def export_csv(self, output_path: Path | str) -> None:
        """Exports detected hotspots to CSV."""
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not self.hotspots:
            return

        with path.open("w", newline="", encoding="utf-8") as f:
            fieldnames = [
                "hotspot_id",
                "blackspot_count",
                "total_crashes",
                "fatal_crashes",
                "non_fatal_crashes",
                "severity_score",
                "center_x",
                "center_y",
                "center_latitude",
                "center_longitude",
                "affected_edges",
                "affected_junctions",
                "radius_m",
                "corridor_relevance",
            ]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for h in self.hotspots:
                row = asdict(h)
                row["affected_edges"] = ";".join(h.affected_edges)
                row["affected_junctions"] = ";".join(h.affected_junctions)
                writer.writerow(row)

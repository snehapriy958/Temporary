"""
traffic_service/spatial_mapper.py

Spatial mapping module linking georeferenced blackspot observations (WGS84 lat/lon)
to the SUMO road network (silk_board.net.xml) and the J1/J2/J3 corridor.
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import sumolib

from .accident_dataset import BlackspotRecord


@dataclass
class MappedBlackspot:
    """Blackspot observation mapped to SUMO road infrastructure."""
    spot_id: str
    location_name: str
    police_station: str
    latitude: float
    longitude: float
    sumo_x: float
    sumo_y: float
    annual_crashes: int
    fatal_crashes: int
    primary_collision_type: str
    documented_risk_category: str
    nearest_edge_id: Optional[str]
    nearest_edge_name: str
    edge_distance_m: Optional[float]
    nearest_junction_id: Optional[str]
    junction_distance_m: Optional[float]
    corridor_junction: Optional[str]  # "J1", "J2", "J3", or None
    is_corridor: bool
    is_matched: bool
    unmatched_reason: Optional[str] = None


class SpatialMapper:
    """
    Projects GPS coordinates to SUMO 2D Cartesian coordinates and snaps blackspots
    to nearest edges and intersections using spatial proximity queries.
    """

    def __init__(
        self,
        net_path: Path | str,
        junction_mapping_path: Optional[Path | str] = None,
        max_edge_distance_m: float = 60.0,
        max_junction_distance_m: float = 120.0,
    ) -> None:
        self.net_path = Path(net_path)
        if not self.net_path.exists():
            raise FileNotFoundError(f"SUMO network file not found: {self.net_path}")

        self.net = sumolib.net.readNet(str(self.net_path))
        self.max_edge_distance_m = max_edge_distance_m
        self.max_junction_distance_m = max_junction_distance_m

        # Load corridor junction definitions
        self.corridor_junction_ids: Dict[str, str] = {}
        self.corridor_edge_ids: set[str] = {
            "172853382#2", "172853382#3", "1148717038#0", "40696223#1",
            "464465165#0", "92196679#0", "-148697299", "-744783934",
        }

        if junction_mapping_path:
            j_path = Path(junction_mapping_path)
            if j_path.exists():
                with j_path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                    for j_key in ["J1", "J2", "J3"]:
                        if j_key in data:
                            self.corridor_junction_ids[j_key] = data[j_key].get("junction_id", "")

        self.boundary = self.net.getBoundary()  # (min_x, min_y, max_x, max_y)
        self.net_offset = self.net.getLocationOffset()  # (offset_x, offset_y)

    def wgs84_to_sumo_xy(self, lon: float, lat: float) -> Tuple[float, float]:
        """
        Converts WGS84 (lon, lat) to SUMO 2D coordinates (x, y) using
        built-in UTM Zone 43N projection + network offset translation.
        """
        try:
            x, y = self.net.convertLonLat2XY(lon, lat)
            return float(x), float(y)
        except Exception:
            pass

        # Standalone deterministic UTM Zone 43N projection
        a = 6378137.0
        f = 1 / 298.257223563
        e2 = 2 * f - f ** 2
        e_prime2 = e2 / (1 - e2)
        lon0 = 75.0  # Central meridian for Zone 43 (72E to 78E)
        k0 = 0.9996

        lat_rad = math.radians(lat)
        lon_rad = math.radians(lon)
        lon0_rad = math.radians(lon0)

        sin_lat = math.sin(lat_rad)
        cos_lat = math.cos(lat_rad)
        tan_lat = math.tan(lat_rad)

        N = a / math.sqrt(1 - e2 * sin_lat ** 2)
        T = tan_lat ** 2
        C = e_prime2 * cos_lat ** 2
        A = (lon_rad - lon0_rad) * cos_lat

        M = a * (
            (1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256) * lat_rad
            - (3 * e2 / 8 + 3 * e2 ** 2 / 32 + 45 * e2 ** 3 / 1024) * math.sin(2 * lat_rad)
            + (15 * e2 ** 2 / 256 + 45 * e2 ** 3 / 1024) * math.sin(4 * lat_rad)
            - (35 * e2 ** 3 / 3072) * math.sin(6 * lat_rad)
        )

        easting = k0 * N * (
            A + (1 - T + C) * A ** 3 / 6 + (5 - 18 * T + T ** 2 + 72 * C - 58 * e_prime2) * A ** 5 / 120
        ) + 500000.0

        northing = k0 * (
            M + N * tan_lat * (
                A ** 2 / 2 + (5 - T + 9 * C + 4 * C ** 2) * A ** 4 / 24
                + (61 - 58 * T + T ** 2 + 600 * C - 330 * e_prime2) * A ** 6 / 720
            )
        )

        x = easting + self.net_offset[0]
        y = northing + self.net_offset[1]
        return x, y

    def map_point(
        self,
        spot_id: str,
        lat: float,
        lon: float,
        location_name: str = "",
        police_station: str = "",
        annual_crashes: int = 0,
        fatal_crashes: int = 0,
        primary_collision_type: str = "OTHER",
        documented_risk_category: str = "MEDIUM",
    ) -> MappedBlackspot:
        """Projects a blackspot coordinate and identifies nearest edge and junction."""
        x, y = self.wgs84_to_sumo_xy(lon, lat)

        min_x, min_y, max_x, max_y = self.boundary
        if not (min_x <= x <= max_x and min_y <= y <= max_y):
            return MappedBlackspot(
                spot_id=spot_id,
                location_name=location_name,
                police_station=police_station,
                latitude=lat,
                longitude=lon,
                sumo_x=round(x, 2),
                sumo_y=round(y, 2),
                annual_crashes=annual_crashes,
                fatal_crashes=fatal_crashes,
                primary_collision_type=primary_collision_type,
                documented_risk_category=documented_risk_category,
                nearest_edge_id=None,
                nearest_edge_name="",
                edge_distance_m=None,
                nearest_junction_id=None,
                junction_distance_m=None,
                corridor_junction=None,
                is_corridor=False,
                is_matched=False,
                unmatched_reason="outside_network_boundary",
            )

        neighbor_edges = self.net.getNeighboringEdges(x, y, r=self.max_edge_distance_m)
        if not neighbor_edges:
            return MappedBlackspot(
                spot_id=spot_id,
                location_name=location_name,
                police_station=police_station,
                latitude=lat,
                longitude=lon,
                sumo_x=round(x, 2),
                sumo_y=round(y, 2),
                annual_crashes=annual_crashes,
                fatal_crashes=fatal_crashes,
                primary_collision_type=primary_collision_type,
                documented_risk_category=documented_risk_category,
                nearest_edge_id=None,
                nearest_edge_name="",
                edge_distance_m=None,
                nearest_junction_id=None,
                junction_distance_m=None,
                corridor_junction=None,
                is_corridor=False,
                is_matched=False,
                unmatched_reason=f"no_edge_within_{self.max_edge_distance_m:.0f}m",
            )

        best_edge, edge_dist = neighbor_edges[0]
        best_edge_id = best_edge.getID()
        edge_name = best_edge.getName() or ""

        # Query neighboring junctions from candidate edge endpoints
        best_node_id: Optional[str] = None
        min_node_dist: float = float("inf")
        corridor_junction: Optional[str] = None

        candidate_nodes = [best_edge.getFromNode(), best_edge.getToNode()]
        for c_edge, _ in neighbor_edges[:3]:
            candidate_nodes.extend([c_edge.getFromNode(), c_edge.getToNode()])

        for node in candidate_nodes:
            if node is None:
                continue
            nx, ny = node.getCoord()
            d = math.hypot(nx - x, ny - y)
            if d < min_node_dist:
                min_node_dist = d
                best_node_id = node.getID()

        node_dist = min_node_dist if min_node_dist <= self.max_junction_distance_m else None
        if node_dist is None:
            best_node_id = None

        # Check proximity to known corridor junctions (J1, J2, J3)
        for j_label, j_id in self.corridor_junction_ids.items():
            if not j_id:
                continue
            try:
                j_node = self.net.getNode(j_id)
                if j_node is not None:
                    jx, jy = j_node.getCoord()
                    j_dist = math.hypot(jx - x, jy - y)
                    if j_dist <= self.max_junction_distance_m:
                        corridor_junction = j_label
                        best_node_id = j_id
                        node_dist = j_dist
                        break
            except Exception:
                pass

        is_corridor = (
            corridor_junction is not None
            or best_edge_id in self.corridor_edge_ids
            or any(part in edge_name.lower() for part in ["hosur", "silk board", "madiwala"])
        )

        return MappedBlackspot(
            spot_id=spot_id,
            location_name=location_name,
            police_station=police_station,
            latitude=lat,
            longitude=lon,
            sumo_x=round(x, 2),
            sumo_y=round(y, 2),
            annual_crashes=annual_crashes,
            fatal_crashes=fatal_crashes,
            primary_collision_type=primary_collision_type,
            documented_risk_category=documented_risk_category,
            nearest_edge_id=best_edge_id,
            nearest_edge_name=edge_name,
            edge_distance_m=round(edge_dist, 2),
            nearest_junction_id=best_node_id,
            junction_distance_m=round(node_dist, 2) if node_dist is not None else None,
            corridor_junction=corridor_junction,
            is_corridor=is_corridor,
            is_matched=True,
            unmatched_reason=None,
        )

    def map_records(
        self, records: List[BlackspotRecord]
    ) -> Tuple[List[MappedBlackspot], List[MappedBlackspot]]:
        """Maps an entire list of BlackspotRecord objects."""
        matched: List[MappedBlackspot] = []
        unmatched: List[MappedBlackspot] = []

        for rec in records:
            res = self.map_point(
                spot_id=rec.spot_id,
                lat=rec.latitude,
                lon=rec.longitude,
                location_name=rec.location_name,
                police_station=rec.police_station,
                annual_crashes=rec.annual_crashes,
                fatal_crashes=rec.fatal_crashes,
                primary_collision_type=rec.primary_collision_type,
                documented_risk_category=rec.documented_risk_category,
            )
            if res.is_matched:
                matched.append(res)
            else:
                unmatched.append(res)

        return matched, unmatched

    def export_summary(
        self,
        mapped_records: List[MappedBlackspot],
        output_csv: Path | str,
    ) -> None:
        """Exports mapped blackspot records to CSV."""
        path = Path(output_csv)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not mapped_records:
            return

        with path.open("w", newline="", encoding="utf-8") as f:
            fieldnames = [
                "spot_id",
                "location_name",
                "police_station",
                "latitude",
                "longitude",
                "sumo_x",
                "sumo_y",
                "annual_crashes",
                "fatal_crashes",
                "primary_collision_type",
                "nearest_edge_id",
                "nearest_edge_name",
                "edge_distance_m",
                "nearest_junction_id",
                "junction_distance_m",
                "corridor_junction",
                "is_corridor",
                "is_matched",
                "unmatched_reason",
            ]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in mapped_records:
                row = asdict(r)
                del row["documented_risk_category"]
                writer.writerow(row)

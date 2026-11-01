"""
traffic_service/accident_dataset.py

Accident and blackspot dataset ingestion, cleaning, and standardization pipeline.
Processes official Bengaluru Traffic Police (BTP) crash statistics, police station
geolocations, and documented corridor blackspots as weighted spatial observations.
Does NOT create synthetic timestamps or artificial unrolled incident records.
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
import xml.etree.ElementTree as ET


BENGALURU_BBOX = {
    "min_lat": 12.80,
    "max_lat": 13.15,
    "min_lon": 77.50,
    "max_lon": 77.80,
}

VALID_COLLISION_TYPES = {
    "REAR_END",
    "SIDE_IMPACT",
    "PEDESTRIAN",
    "HEAD_ON",
    "SKIDDING",
    "OTHER",
}


@dataclass
class BlackspotRecord:
    """Documented accident blackspot represented as a weighted spatial observation."""
    spot_id: str
    location_name: str
    police_station: str
    latitude: float
    longitude: float
    road_name: str
    annual_crashes: int
    fatal_crashes: int
    primary_collision_type: str
    documented_risk_category: str


class AccidentDataPipeline:
    """
    Ingests documented corridor blackspot data and BTP police station metadata,
    validates geospatial coordinates, cleans records, and standardizes them as
    weighted spatial observations.
    """

    def __init__(
        self,
        raw_dir: Path | str,
        processed_dir: Path | str,
    ) -> None:
        self.raw_dir = Path(raw_dir)
        self.processed_dir = Path(processed_dir)
        self.processed_dir.mkdir(parents=True, exist_ok=True)
        self.cleaned_records: List[BlackspotRecord] = []
        self.rejected_records: List[Dict[str, Any]] = []

    def validate_coordinate(self, lat: float, lon: float) -> bool:
        """Validates that coordinates are non-null numbers within Bengaluru bounds."""
        if lat is None or lon is None:
            return False
        try:
            lat_f = float(lat)
            lon_f = float(lon)
        except (ValueError, TypeError):
            return False

        return (
            BENGALURU_BBOX["min_lat"] <= lat_f <= BENGALURU_BBOX["max_lat"]
            and BENGALURU_BBOX["min_lon"] <= lon_f <= BENGALURU_BBOX["max_lon"]
        )

    def normalize_collision_type(self, raw_type: str) -> str:
        """Normalizes collision types."""
        t = (raw_type or "").strip().upper()
        if "REAR" in t:
            return "REAR_END"
        if "SIDE" in t or "SWIPE" in t or "ANGLE" in t:
            return "SIDE_IMPACT"
        if "PED" in t:
            return "PEDESTRIAN"
        if "HEAD" in t:
            return "HEAD_ON"
        if "SKID" in t:
            return "SKIDDING"
        return "OTHER"

    def load_police_stations_kml(
        self, kml_filename: str = "bengaluru_traffic_police_stations.kml"
    ) -> Dict[str, tuple[float, float]]:
        """Parses KML file returning mapping of station name -> (lat, lon)."""
        kml_path = self.raw_dir / kml_filename
        stations: Dict[str, tuple[float, float]] = {}
        if not kml_path.exists():
            return stations

        try:
            tree = ET.parse(kml_path)
            root = tree.getroot()
            for pm in root.findall(".//{http://www.opengis.net/kml/2.2}Placemark"):
                coords_el = pm.find(".//{http://www.opengis.net/kml/2.2}coordinates")
                if coords_el is None or not coords_el.text:
                    continue
                coords_parts = coords_el.text.strip().split(",")
                if len(coords_parts) < 2:
                    continue
                try:
                    lon = float(coords_parts[0])
                    lat = float(coords_parts[1])
                except ValueError:
                    continue

                for sd in pm.findall(".//{http://www.opengis.net/kml/2.2}SimpleData"):
                    if sd.attrib.get("name") == "TRF_POL_STAName" and sd.text:
                        raw_name = sd.text.replace("Traffic Police Station,", "").strip()
                        stations[raw_name.lower()] = (lat, lon)
        except Exception:
            pass

        return stations

    def process_blackspots(
        self, filename: str = "btp_corridor_blackspots_raw.csv"
    ) -> List[BlackspotRecord]:
        """
        Loads documented corridor blackspots directly as weighted spatial observations.
        Preserves original annual crash and fatality counts without synthetic unrolling.
        """
        path = self.raw_dir / filename
        records: List[BlackspotRecord] = []
        if not path.exists():
            return records

        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                spot_id = row.get("spot_id", "").strip()
                try:
                    lat = float(row.get("latitude", 0.0))
                    lon = float(row.get("longitude", 0.0))
                except (ValueError, TypeError):
                    self.rejected_records.append({"row": row, "reason": "invalid_coordinates"})
                    continue

                if not self.validate_coordinate(lat, lon):
                    self.rejected_records.append({"row": row, "reason": "out_of_bounds_coordinates"})
                    continue

                annual_crashes = int(float(row.get("annual_crashes_avg", 0)))
                fatal_crashes = int(float(row.get("fatal_crashes_avg", 0)))

                records.append(
                    BlackspotRecord(
                        spot_id=spot_id,
                        location_name=row.get("location_name", "").strip(),
                        police_station=row.get("police_station", "").strip(),
                        latitude=lat,
                        longitude=lon,
                        road_name=row.get("road_name", "").strip(),
                        annual_crashes=annual_crashes,
                        fatal_crashes=fatal_crashes,
                        primary_collision_type=self.normalize_collision_type(
                            row.get("primary_collision_type", "")
                        ),
                        documented_risk_category=row.get("risk_category", "MEDIUM").strip().upper(),
                    )
                )

        return records

    def run_pipeline(self) -> List[BlackspotRecord]:
        """Runs the complete ingestion and standardization pipeline."""
        self.cleaned_records = []
        self.rejected_records = []

        # Process blackspot records as weighted spatial observations
        self.cleaned_records = self.process_blackspots()

        # Export standardized CSV
        out_csv = self.processed_dir / "cleaned_accidents.csv"
        self.export_csv(out_csv)

        return self.cleaned_records

    def export_csv(self, output_path: Path | str) -> None:
        """Exports standardized blackspot records to CSV."""
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not self.cleaned_records:
            return

        with path.open("w", newline="", encoding="utf-8") as f:
            fieldnames = [
                "spot_id",
                "location_name",
                "police_station",
                "latitude",
                "longitude",
                "road_name",
                "annual_crashes",
                "fatal_crashes",
                "primary_collision_type",
                "documented_risk_category",
            ]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in self.cleaned_records:
                writer.writerow(asdict(r))

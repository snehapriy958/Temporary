"""
traffic_service/scenario_generator.py

Traffic scenario generation supporting parameterized demand regimes:
1. NORMAL: Standard multi-class urban traffic flow
2. PEAK_RUSH / HIGH_DEMAND: Scaled traffic volumes representing heavy congestion
3. CORRIDOR_EMERGENCY: Background traffic with priority ambulance insertion
4. RISK_INCIDENT: Elevated demand pressure near high-risk conflict zones
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional
import xml.etree.ElementTree as ET


@dataclass
class ScenarioConfig:
    name: str
    description: str
    demand_scale: float  # Multiplier on default flows (1.0 = normal, 1.4 = peak)
    emergency_enabled: bool
    emergency_depart_s: int = 420
    duration_s: int = 600


SCENARIO_PRESETS: Dict[str, ScenarioConfig] = {
    "NORMAL": ScenarioConfig(
        name="NORMAL",
        description="Standard calibrated multi-class traffic flow along Silk Board corridor",
        demand_scale=1.0,
        emergency_enabled=True,
        emergency_depart_s=420,
    ),
    "HIGH_DEMAND": ScenarioConfig(
        name="HIGH_DEMAND",
        description="Peak rush hour conditions with 40% increased approach volume",
        demand_scale=1.4,
        emergency_enabled=True,
        emergency_depart_s=360,
    ),
    "CORRIDOR_EMERGENCY": ScenarioConfig(
        name="CORRIDOR_EMERGENCY",
        description="Continuous corridor arterial demand with critical ambulance preemption",
        demand_scale=1.1,
        emergency_enabled=True,
        emergency_depart_s=300,
    ),
    "INCIDENT_CONGESTION": ScenarioConfig(
        name="INCIDENT_CONGESTION",
        description="Spillback conditions reflecting bottlenecking near critical risk zones",
        demand_scale=1.5,
        emergency_enabled=True,
        emergency_depart_s=400,
    ),
}


class ScenarioGenerator:
    """
    Generates customized SUMO route and demand XML files for specified traffic regimes.
    """

    def __init__(self, output_dir: Optional[Path | str] = None) -> None:
        if output_dir:
            self.output_dir = Path(output_dir)
        else:
            self.output_dir = (
                Path(__file__).resolve().parent.parent
                / "sumo"
                / "silk_board"
                / "demand"
                / "scenarios"
            )
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_scenario_rou_xml(
        self,
        scenario: str | ScenarioConfig,
        output_file: Optional[Path | str] = None,
    ) -> Path:
        """Builds a validated SUMO .rou.xml file for the given scenario."""
        if isinstance(scenario, str):
            cfg = SCENARIO_PRESETS.get(scenario.upper(), SCENARIO_PRESETS["NORMAL"])
        else:
            cfg = scenario

        if output_file is None:
            dest_path = self.output_dir / f"scenario_{cfg.name.lower()}.rou.xml"
        else:
            dest_path = Path(output_file)

        dest_path.parent.mkdir(parents=True, exist_ok=True)

        root = ET.Element(
            "routes",
            {
                "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
                "xsi:noNamespaceSchemaLocation": "http://sumo.dlr.de/xsd/routes_file.xsd",
            },
        )

        # Vehicle Type Definitions (standard multi-class mix)
        vtypes = [
            ("motorcycle", "motorcycle", "0.9", "12.0", "4.0", "2.2", "45", "1.0", "0.5"),
            ("car", "passenger", "2.0", "15.0", "2.6", "4.5", "50", "2.5", "0.5"),
            ("bus", "bus", "2.5", "12.0", "1.5", "12.0", "40", "3.0", "0.5"),
            ("truck", "truck", "2.5", "10.0", "1.2", "8.0", "35", "3.0", "0.5"),
            ("ambulance", "emergency", "1.0", "22.0", "5.0", "6.5", "70", "2.5", "0.1"),
        ]
        for tid, vclass, mingap, maxspeed, accel, length, shape, tau, jm in vtypes:
            ET.SubElement(
                root,
                "vType",
                {
                    "id": tid,
                    "vClass": vclass,
                    "minGap": mingap,
                    "maxSpeed": maxspeed,
                    "accel": accel,
                    "decel": "4.5",
                    "emergencyDecel": "7.0",
                    "length": length,
                    "guiShape": shape,
                    "tau": tau,
                    "jmDriveAfterYellowTime": jm,
                },
            )

        # Base Corridor Routes
        routes = [
            ("corridor_j1_j2_j3", ["172853382#2", "172853382#3", "1148717038#0", "40696223#1"]),
            ("hosur_to_hosur", ["172853382#3", "1148717038#0"]),
            ("madiwala_to_hosur", ["92196679#0", "1148717038#0"]),
            ("hosur_to_madiwala", ["464465165#0", "239438610#0"]),
        ]
        for rid, edges in routes:
            ET.SubElement(root, "route", {"id": rid, "edges": " ".join(edges)})

        scale = cfg.demand_scale

        # Chronologically ordered flows (SUMO incremental parse requirement)
        # Period 1: 0 - 300s
        self._add_flow(root, "c_mc_p1", "motorcycle", "corridor_j1_j2_j3", 0, 300, int(350 * scale))
        self._add_flow(root, "c_car_p1", "car", "corridor_j1_j2_j3", 0, 300, int(150 * scale))
        self._add_flow(root, "c_bus_p1", "bus", "corridor_j1_j2_j3", 0, 300, int(40 * scale))
        self._add_flow(root, "h_mc_p1", "motorcycle", "hosur_to_hosur", 0, 300, int(400 * scale))
        self._add_flow(root, "h_car_p1", "car", "hosur_to_hosur", 0, 300, int(200 * scale))
        self._add_flow(root, "m_mc_p1", "motorcycle", "madiwala_to_hosur", 0, 300, int(300 * scale))
        self._add_flow(root, "m_car_p1", "car", "madiwala_to_hosur", 0, 300, int(120 * scale))

        # Period 2: 300 - 600s
        self._add_flow(root, "c_mc_p2", "motorcycle", "corridor_j1_j2_j3", 300, 600, int(400 * scale))
        self._add_flow(root, "c_car_p2", "car", "corridor_j1_j2_j3", 300, 600, int(180 * scale))
        self._add_flow(root, "c_truck_p2", "truck", "corridor_j1_j2_j3", 300, 600, int(30 * scale))
        self._add_flow(root, "h_mc_p2", "motorcycle", "hosur_to_hosur", 300, 600, int(450 * scale))
        self._add_flow(root, "h_car_p2", "car", "hosur_to_hosur", 300, 600, int(220 * scale))
        self._add_flow(root, "m_mc_p2", "motorcycle", "madiwala_to_hosur", 300, 600, int(350 * scale))
        self._add_flow(root, "m_car_p2", "car", "madiwala_to_hosur", 300, 600, int(140 * scale))

        # Emergency Vehicle
        if cfg.emergency_enabled:
            ET.SubElement(
                root,
                "vehicle",
                {
                    "id": f"ambulance_{cfg.name.lower()}",
                    "type": "ambulance",
                    "route": "corridor_j1_j2_j3",
                    "depart": str(cfg.emergency_depart_s),
                    "departLane": "best",
                    "departSpeed": "max",
                },
            )

        tree = ET.ElementTree(root)
        ET.indent(tree, space="    ")
        tree.write(dest_path, encoding="utf-8", xml_declaration=True)
        return dest_path

    @staticmethod
    def _add_flow(
        parent: ET.Element,
        fid: str,
        vtype: str,
        route: str,
        begin: int,
        end: int,
        vph: int,
    ) -> None:
        ET.SubElement(
            parent,
            "flow",
            {
                "id": fid,
                "type": vtype,
                "route": route,
                "begin": str(begin),
                "end": str(end),
                "vehsPerHour": str(vph),
                "departLane": "best",
                "departSpeed": "max",
                "departPos": "base",
            },
        )

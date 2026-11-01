"""
traffic_service/curriculum.py

Curriculum Learning Demand Generator for MARL Corridor Coordination (Stage P6).
Generates multi-stage training demand environments:
- Stage A: Balanced Demand (1:1 ratio, 600 veh/h) for basic phase cycling and min-green stability
- Stage B: Moderate Asymmetric Demand (2:1 ratio, 1200 veh/h) for platoon progression and offset coordination
- Stage C: Full Peak Silk Board Demand (heavy corridor pressure) for anti-starvation and gridlock prevention
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import xml.etree.ElementTree as ET

logger = logging.getLogger("curriculum")


@dataclass
class CurriculumStageConfig:
    stage_id: str
    name: str
    description: str
    arterial_veh_per_hr: int
    cross_veh_per_hr: int
    duration_s: int = 1200
    ambulance_enabled: bool = False
    ambulance_insert_time_s: float = 400.0


CURRICULUM_STAGES: Dict[str, CurriculumStageConfig] = {
    "stage_a": CurriculumStageConfig(
        stage_id="stage_a",
        name="Stage A: Balanced Demand (1:1)",
        description="Balanced arterial vs cross-street flows to learn fundamental phase alternation.",
        arterial_veh_per_hr=300,
        cross_veh_per_hr=300,
        duration_s=1200,
        ambulance_enabled=False,
    ),
    "stage_b": CurriculumStageConfig(
        stage_id="stage_b",
        name="Stage B: Moderate Asymmetry (2:1)",
        description="2:1 arterial priority to learn platoon progression without cross-street starvation.",
        arterial_veh_per_hr=800,
        cross_veh_per_hr=400,
        duration_s=1200,
        ambulance_enabled=False,
    ),
    "stage_c": CurriculumStageConfig(
        stage_id="stage_c",
        name="Stage C: Full Peak Corridor Demand",
        description="Heavy asymmetric peak volume evaluating anti-starvation and coordination.",
        arterial_veh_per_hr=1800,
        cross_veh_per_hr=900,
        duration_s=1200,
        ambulance_enabled=True,
        ambulance_insert_time_s=500.0,
    ),
}


class CurriculumDemandGenerator:
    """Generates valid SUMO route XMLs for curriculum learning stages."""

    def __init__(self, output_dir: Optional[Path | str] = None) -> None:
        self.output_dir = Path(output_dir) if output_dir else Path("data/curriculum")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_stage_routes(
        self,
        stage_id: str,
        output_filepath: Optional[Path | str] = None,
        seed: int = 42,
    ) -> Path:
        """
        Generates a valid SUMO route XML file for the specified curriculum stage.
        Ensures strictly chronological flow definitions as required by SUMO.
        """
        stage_key = stage_id.lower()
        if stage_key not in CURRICULUM_STAGES:
            raise ValueError(f"Unknown curriculum stage: {stage_id}. Choose from: {list(CURRICULUM_STAGES.keys())}")

        cfg = CURRICULUM_STAGES[stage_key]
        dest_path = Path(output_filepath) if output_filepath else self.output_dir / f"{cfg.stage_id}.rou.xml"
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        root = ET.Element(
            "routes",
            {
                "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
                "xsi:noNamespaceSchemaLocation": "http://sumo.dlr.de/xsd/routes_file.xsd",
            },
        )

        # Vehicle Types
        vtypes = [
            ("motorcycle", "motorcycle", "0.9", "12.0", "4.0", "2.2", "45", "1.0", "0.5"),
            ("car", "passenger", "2.0", "15.0", "2.6", "4.5", "50", "2.5", "0.5"),
            ("bus", "bus", "2.5", "12.0", "1.5", "12.0", "40", "3.0", "0.5"),
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

        # Corridor Routes
        routes = [
            ("corridor_full", ["172853382#2", "172853382#3", "1148717038#0", "40696223#1"]),
            ("madiwala_cross", ["92196679#0", "1148717038#0"]),
            ("hosur_local", ["172853382#3", "1148717038#0"]),
        ]
        for rid, edges in routes:
            ET.SubElement(root, "route", {"id": rid, "edges": " ".join(edges)})

        # Split arterial and cross demands across vehicle classes
        art_mc = int(cfg.arterial_veh_per_hr * 0.60)
        art_car = int(cfg.arterial_veh_per_hr * 0.35)
        art_bus = max(5, int(cfg.arterial_veh_per_hr * 0.05))

        cross_mc = int(cfg.cross_veh_per_hr * 0.65)
        cross_car = int(cfg.cross_veh_per_hr * 0.35)

        # Add Flows
        dur = cfg.duration_s
        self._add_flow(root, f"{cfg.stage_id}_art_mc", "motorcycle", "corridor_full", 0, dur, art_mc)
        self._add_flow(root, f"{cfg.stage_id}_art_car", "car", "corridor_full", 0, dur, art_car)
        self._add_flow(root, f"{cfg.stage_id}_art_bus", "bus", "corridor_full", 0, dur, art_bus)
        self._add_flow(root, f"{cfg.stage_id}_cross_mc", "motorcycle", "madiwala_cross", 0, dur, cross_mc)
        self._add_flow(root, f"{cfg.stage_id}_cross_car", "car", "madiwala_cross", 0, dur, cross_car)

        # Optional Emergency Vehicle
        if cfg.ambulance_enabled:
            ET.SubElement(
                root,
                "vehicle",
                {
                    "id": f"{cfg.stage_id}_ambulance",
                    "type": "ambulance",
                    "route": "corridor_full",
                    "depart": f"{cfg.ambulance_insert_time_s:.1f}",
                    "departLane": "best",
                    "departSpeed": "max",
                },
            )

        tree = ET.ElementTree(root)
        ET.indent(tree, space="    ")
        tree.write(dest_path, encoding="utf-8", xml_declaration=True)
        logger.info(f"Generated {cfg.name} routes at: {dest_path}")
        return dest_path

    @staticmethod
    def _add_flow(
        root: ET.Element,
        flow_id: str,
        vtype: str,
        route: str,
        begin: int,
        end: int,
        vehs_per_hour: int,
    ) -> None:
        if vehs_per_hour <= 0:
            return
        ET.SubElement(
            root,
            "flow",
            {
                "id": flow_id,
                "type": vtype,
                "route": route,
                "begin": str(begin),
                "end": str(end),
                "vehsPerHour": str(vehs_per_hour),
                "departLane": "best",
                "departSpeed": "max",
            },
        )

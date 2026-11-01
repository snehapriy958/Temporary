"""
tests/test_curriculum.py

Unit tests for Curriculum Learning Demand Generation (Stage P6).
Validates Stage A (1:1 balanced), Stage B (2:1 asymmetric), and Stage C (peak corridor).
"""

from __future__ import annotations

import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
import pytest

from traffic_service.curriculum import (
    CurriculumDemandGenerator,
    CURRICULUM_STAGES,
    CurriculumStageConfig,
)


def test_curriculum_stages_definitions():
    assert "stage_a" in CURRICULUM_STAGES
    assert "stage_b" in CURRICULUM_STAGES
    assert "stage_c" in CURRICULUM_STAGES

    stage_a = CURRICULUM_STAGES["stage_a"]
    assert stage_a.arterial_veh_per_hr == 300
    assert stage_a.cross_veh_per_hr == 300  # 1:1 ratio

    stage_b = CURRICULUM_STAGES["stage_b"]
    assert stage_b.arterial_veh_per_hr == 800
    assert stage_b.cross_veh_per_hr == 400  # 2:1 ratio

    stage_c = CURRICULUM_STAGES["stage_c"]
    assert stage_c.arterial_veh_per_hr == 1800
    assert stage_c.cross_veh_per_hr == 900
    assert stage_c.ambulance_enabled is True


def test_generate_stage_a_routes():
    with tempfile.TemporaryDirectory() as tmpdir:
        gen = CurriculumDemandGenerator(output_dir=tmpdir)
        p = gen.generate_stage_routes("stage_a")

        assert p.is_file()
        tree = ET.parse(p)
        root = tree.getroot()
        assert root.tag == "routes"

        # Check vehicle types exist
        vtypes = {elem.attrib["id"] for elem in root.findall("vType")}
        assert {"car", "motorcycle", "bus"}.issubset(vtypes)

        # Check flows
        flows = root.findall("flow")
        assert len(flows) > 0

        # Sum flows by route
        route_vehs = {}
        for f in flows:
            rid = f.attrib["route"]
            vph = int(f.attrib["vehsPerHour"])
            route_vehs[rid] = route_vehs.get(rid, 0) + vph

        # Stage A: corridor_full should equal madiwala_cross (1:1 ratio)
        assert route_vehs["corridor_full"] == route_vehs["madiwala_cross"] == 300


def test_generate_stage_b_routes():
    with tempfile.TemporaryDirectory() as tmpdir:
        gen = CurriculumDemandGenerator(output_dir=tmpdir)
        p = gen.generate_stage_routes("stage_b")

        tree = ET.parse(p)
        root = tree.getroot()

        route_vehs = {}
        for f in root.findall("flow"):
            rid = f.attrib["route"]
            vph = int(f.attrib["vehsPerHour"])
            route_vehs[rid] = route_vehs.get(rid, 0) + vph

        # Stage B: corridor_full (800) vs madiwala_cross (400) (2:1 ratio)
        assert route_vehs["corridor_full"] == 800
        assert route_vehs["madiwala_cross"] == 400


def test_generate_stage_c_with_ambulance():
    with tempfile.TemporaryDirectory() as tmpdir:
        gen = CurriculumDemandGenerator(output_dir=tmpdir)
        p = gen.generate_stage_routes("stage_c")

        tree = ET.parse(p)
        root = tree.getroot()

        # Ambulance vehicle element must exist
        veh = root.find("vehicle")
        assert veh is not None
        assert veh.attrib["id"] == "stage_c_ambulance"
        assert veh.attrib["type"] == "ambulance"
        assert float(veh.attrib["depart"]) == 500.0


def test_unknown_stage_raises_error():
    with tempfile.TemporaryDirectory() as tmpdir:
        gen = CurriculumDemandGenerator(output_dir=tmpdir)
        with pytest.raises(ValueError, match="Unknown curriculum stage"):
            gen.generate_stage_routes("stage_invalid")

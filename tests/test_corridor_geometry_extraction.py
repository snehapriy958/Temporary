"""
tests/test_corridor_geometry_extraction.py

Phase 3B Stage 1 Automated Validation Suite:
Tests the extracted corridor network geometry against the source XML
and verifies adherence to the Phase 3A v1.2 specification.
"""

import json
import pytest
from pathlib import Path

GEOMETRY_JSON_PATH = Path("frontend/src/data/corridorNetworkGeometry.json")
ARCHIVE_JSON_PATH = Path("outputs/geometry/corridor_network_geometry.json")


@pytest.fixture(scope="module")
def geometry_data():
    assert GEOMETRY_JSON_PATH.exists(), f"Extracted geometry file not found: {GEOMETRY_JSON_PATH}"
    with open(GEOMETRY_JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data


def test_geometry_file_existence_and_size():
    """Verify JSON files exist and adhere to bundle size limits."""
    assert GEOMETRY_JSON_PATH.exists()
    assert ARCHIVE_JSON_PATH.exists()

    size_kb = GEOMETRY_JSON_PATH.stat().st_size / 1024.0
    # Uncompressed bundle size must be < 1200 KB for Phase 3B
    assert size_kb < 1200.0, f"Geometry JSON exceeds size budget: {size_kb:.1f} KB"
    assert size_kb > 200.0, f"Geometry JSON unexpectedly small: {size_kb:.1f} KB"


def test_metadata_and_scene_anchor(geometry_data):
    """Verify CRS metadata and Central Silk Board scene anchor."""
    meta = geometry_data.get("metadata", {})
    assert "netOffset" in meta
    assert "convBoundary" in meta
    assert "sceneAnchor" in meta

    anchor = meta["sceneAnchor"]
    assert anchor["name"] == "Central Silk Board (J2)"
    assert anchor["sumo_x"] == 2185.00
    assert anchor["sumo_y"] == 3540.00
    assert anchor["sumo_z"] == 0.00
    assert pytest.approx(anchor["wgs84_lon"], rel=1e-4) == 77.62287
    assert pytest.approx(anchor["wgs84_lat"], rel=1e-4) == 12.91724


def test_key_junctions_present_and_oriented(geometry_data):
    """Verify J1, J2, and J3 exist, have shapes, and follow cardinal geometry."""
    key_j = geometry_data.get("keyJunctions", {})
    junctions = geometry_data.get("junctions", {})

    assert "J1" in key_j
    assert "J2" in key_j
    assert "J3" in key_j

    j1_id = key_j["J1"]["id"]
    j2_id = key_j["J2"]["id"]
    j3_id = key_j["J3"]["id"]

    assert j1_id in junctions
    assert j2_id in junctions
    assert j3_id in junctions

    j1 = junctions[j1_id]
    j2 = junctions[j2_id]
    j3 = junctions[j3_id]

    # Verify positions
    assert pytest.approx(j1["x"], abs=1.0) == 2105.20
    assert pytest.approx(j1["y"], abs=1.0) == 3665.50

    assert pytest.approx(j2["x"], abs=1.0) == 2186.13
    assert pytest.approx(j2["y"], abs=1.0) == 3523.88

    assert pytest.approx(j3["x"], abs=1.0) == 2264.63
    assert pytest.approx(j3["y"], abs=1.0) == 3407.70

    # Verify cardinal relative directions (North is +Y in SUMO, East is +X in SUMO)
    # J1 is North of J2
    assert j1["y"] > j2["y"], f"J1 y ({j1['y']}) should be north of J2 y ({j2['y']})"
    # J3 is South of J2
    assert j3["y"] < j2["y"], f"J3 y ({j3['y']}) should be south of J2 y ({j2['y']})"
    # J1 is West of J2
    assert j1["x"] < j2["x"], f"J1 x ({j1['x']}) should be west of J2 x ({j2['x']})"
    # J3 is East of J2
    assert j3["x"] > j2["x"], f"J3 x ({j3['x']}) should be east of J2 x ({j2['x']})"

    # Shapes must have at least 10 polygon vertices
    assert len(j1["shape"]) >= 10
    assert len(j2["shape"]) >= 10
    assert len(j3["shape"]) >= 10


def test_corridor_spine_edges(geometry_data):
    """Verify critical Hosur Road corridor edges exist with lanes and shapes."""
    edges = geometry_data.get("edges", {})

    spine_ids = [
        "172853382#1",
        "172853382#2",
        "172853382#3",
        "464465165#0",
        "92196679#0",
        "1148717038#0",
        "40696223#1",
        "-148697299",
        "-744783934"
    ]

    for sid in spine_ids:
        assert sid in edges, f"Corridor spine edge {sid} missing from extracted geometry!"
        e = edges[sid]
        assert e["numLanes"] >= 1
        assert len(e["lanes"]) == e["numLanes"]
        for lane in e["lanes"]:
            assert lane["length"] > 0
            assert lane["width"] >= 2.5
            assert len(lane["shape"]) >= 2
            # All SUMO coordinates must be 3D [x, y, z] triples with z=0.0
            for pt in lane["shape"]:
                assert len(pt) == 3
                assert pt[2] == 0.0


def test_flyover_and_underpass_catalog(geometry_data):
    """Verify all 21 flyover and underpass segments are present and categorized."""
    edges = geometry_data.get("edges", {})

    expected_flyovers = {
        "1208112303": ("silk_board_flyover", 7.50),
        "40696222": ("silk_board_flyover", 7.50),
        "1299917512": ("double_decker_flyover", 8.00),
        "1299917517": ("double_decker_flyover", 8.00),
        "1299932382": ("double_decker_flyover", 8.00),
        "1301808818": ("double_decker_flyover", 8.00),
        "519734960": ("double_decker_flyover", 8.00),
        "1299917514": ("double_decker_ramp", 8.00),
        "1301808820": ("double_decker_ramp", 8.00),
        "1303740767": ("electronic_city_expressway", 7.50),
        "133759694": ("electronic_city_expressway", 7.50),
        "160511376": ("electronic_city_expressway", 7.50),
        "1351994264": ("ragigudda_flyover", 8.00),
        "1351994264-AddedOffRampEdge": ("ragigudda_ramp", 8.00),
        "886153772": ("ragigudda_flyover", 8.00),
        "133763758": ("madiwala_underpass", -4.50),
        "133763760": ("madiwala_underpass", -4.50),
        "148210028": ("madiwala_underpass", -4.50),
        "148210029": ("madiwala_underpass", -4.50),
        "148210030": ("madiwala_underpass", -4.50),
        "239438609": ("madiwala_underpass", -4.50)
    }

    assert len(expected_flyovers) == 21

    for fid, (cat, elev) in expected_flyovers.items():
        assert fid in edges, f"Flyover/underpass edge {fid} missing from extracted geometry!"
        e = edges[fid]
        assert e["elevationCategory"] == cat
        assert e["assumedElevation"] == elev
        if elev > 0:
            assert e["isFlyover"] is True
            assert e["isUnderpass"] is False
        else:
            assert e["isFlyover"] is False
            assert e["isUnderpass"] is True


def test_road_connectivity(geometry_data):
    """Verify connectivity between corridor spine links."""
    conns = geometry_data.get("connections", [])
    assert len(conns) > 100, f"Expected >100 connections, found {len(conns)}"

    # Check J1 -> J2 link connection
    has_j1_to_j2 = any(c["fromEdge"] == "172853382#2" and c["toEdge"] == "172853382#3" for c in conns)
    assert has_j1_to_j2, "Missing connection from 172853382#2 to 172853382#3 across J1"

    # Check J2 -> J3 link connection
    has_j2_to_j3 = any(c["fromEdge"] == "172853382#3" and c["toEdge"] == "1148717038#0" for c in conns)
    assert has_j2_to_j3, "Missing connection from 172853382#3 to 1148717038#0 across J2"

    # Check J3 exit connection
    has_j3_exit = any(c["fromEdge"] == "1148717038#0" and c["toEdge"] == "40696223#1" for c in conns)
    assert has_j3_exit, "Missing connection from 1148717038#0 to 40696223#1 across J3"


def test_elevation_provenance_notice(geometry_data):
    """Verify illustrative visualization provenance notice is present."""
    elev = geometry_data.get("elevationAssumptions", {})
    assert "notice" in elev
    notice = elev["notice"]
    assert "illustrative visualization assumptions" in notice.lower()
    assert "not surveyed as-built elevations" in notice.lower()
    assert elev["ASSUMED_FLYOVER_ROAD_ELEVATION"] == 7.50
    assert elev["ASSUMED_DOUBLE_DECKER_ROAD_ELEVATION"] == 8.00
    assert elev["ASSUMED_METRO_VIADUCT_ELEVATION"] == 16.00
    assert elev["ASSUMED_UNDERPASS_DEPRESSION"] == -4.50


def test_unsupported_and_malformed_elements_documented(geometry_data):
    """Verify catalog of unsupported and malformed XML elements."""
    mal = geometry_data.get("unsupportedAndMalformedElements", {})
    assert "planar_z_coordinates" in mal
    assert "internal_edges_omitted" in mal
    assert "default_lane_widths" in mal

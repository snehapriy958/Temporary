"""
tests/test_coordinate_transformation.py

Phase 3B Stage 2 Automated Backend Validation Suite:
Tests the coordinate transformation math, inverse recovery, cardinal directions,
vehicle model heading, and distance preservation against the Stage 1 corridor geometry.
"""

import json
import math
import pytest
from pathlib import Path

GEOMETRY_JSON_PATH = Path("frontend/src/data/corridorNetworkGeometry.json")

# Default Scene Anchor from Phase 3A v1.2
DEFAULT_SCENE_ANCHOR = {
    "name": "Central Silk Board (J2)",
    "sumo_x": 2185.00,
    "sumo_y": 3540.00,
    "sumo_z": 0.00,
    "wgs84_lon": 77.62287,
    "wgs84_lat": 12.91724,
}


def sumo_to_three_coords(x, y, z=0.0, elev=0.0, anchor=DEFAULT_SCENE_ANCHOR):
    return {
        "x": x - anchor["sumo_x"],
        "y": z + elev,
        "z": anchor["sumo_y"] - y,
    }


def three_to_sumo_coords(x, y, z, elev=0.0, anchor=DEFAULT_SCENE_ANCHOR):
    return {
        "x": x + anchor["sumo_x"],
        "y": anchor["sumo_y"] - z,
        "z": y - elev,
    }


def sumo_heading_to_three_yaw(sumo_angle_deg, model_offset_rad=0.0):
    rad = math.radians(sumo_angle_deg)
    yaw_base = math.pi - rad
    yaw_total = yaw_base + model_offset_rad
    return math.atan2(math.sin(yaw_total), math.cos(yaw_total))


def three_yaw_to_sumo_heading(three_yaw_rad, model_offset_rad=0.0):
    yaw_base = three_yaw_rad - model_offset_rad
    deg = 180.0 - math.degrees(yaw_base)
    deg = deg % 360.0
    if deg < 0:
        deg += 360.0
    return 0.0 if deg == 0 else deg


def sumo_heading_to_three_direction(sumo_angle_deg):
    rad = math.radians(sumo_angle_deg)
    return {
        "x": math.sin(rad),
        "y": 0.0,
        "z": -math.cos(rad),
    }


@pytest.fixture(scope="module")
def corridor_data():
    with open(GEOMETRY_JSON_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def test_anchor_maps_to_three_origin():
    res = sumo_to_three_coords(2185.00, 3540.00, 0.0)
    assert res["x"] == 0.0
    assert res["y"] == 0.0
    assert res["z"] == 0.0


def test_j2_centroid_offset_documented(corridor_data):
    j2 = corridor_data["junctions"][corridor_data["keyJunctions"]["J2"]["id"]]
    res = sumo_to_three_coords(j2["x"], j2["y"])

    assert pytest.approx(res["x"], abs=1e-4) == 1.13
    assert pytest.approx(res["z"], abs=1e-4) == 16.12
    offset_dist = math.hypot(res["x"], res["z"])
    assert pytest.approx(offset_dist, abs=1e-3) == 16.159


def test_round_trip_invertibility():
    test_points = [
        (2185.00, 3540.00, 0.0, 0.0),
        (2105.20, 3665.50, 0.0, 0.0),
        (2186.13, 3523.88, 0.0, 8.00),
        (2264.63, 3407.70, 0.0, -4.50),
    ]
    for x, y, z, elev in test_points:
        three = sumo_to_three_coords(x, y, z, elev)
        recovered = three_to_sumo_coords(three["x"], three["y"], three["z"], elev)
        assert pytest.approx(recovered["x"], abs=1e-9) == x
        assert pytest.approx(recovered["y"], abs=1e-9) == y
        assert pytest.approx(recovered["z"], abs=1e-9) == z


def test_cardinal_directions():
    # North
    dir_n = sumo_heading_to_three_direction(0.0)
    assert pytest.approx(dir_n["x"], abs=1e-9) == 0.0
    assert pytest.approx(dir_n["z"], abs=1e-9) == -1.0
    yaw_n = sumo_heading_to_three_yaw(0.0)
    assert pytest.approx(abs(yaw_n), abs=1e-9) == math.pi
    assert pytest.approx(three_yaw_to_sumo_heading(yaw_n), abs=1e-9) in (0.0, 360.0)

    # East
    dir_e = sumo_heading_to_three_direction(90.0)
    assert pytest.approx(dir_e["x"], abs=1e-9) == 1.0
    assert pytest.approx(dir_e["z"], abs=1e-9) == 0.0
    yaw_e = sumo_heading_to_three_yaw(90.0)
    assert pytest.approx(yaw_e, abs=1e-9) == math.pi / 2
    assert pytest.approx(three_yaw_to_sumo_heading(yaw_e), abs=1e-9) == 90.0

    # South
    dir_s = sumo_heading_to_three_direction(180.0)
    assert pytest.approx(dir_s["x"], abs=1e-9) == 0.0
    assert pytest.approx(dir_s["z"], abs=1e-9) == 1.0
    yaw_s = sumo_heading_to_three_yaw(180.0)
    assert pytest.approx(yaw_s, abs=1e-9) == 0.0
    assert pytest.approx(three_yaw_to_sumo_heading(yaw_s), abs=1e-9) == 180.0

    # West
    dir_w = sumo_heading_to_three_direction(270.0)
    assert pytest.approx(dir_w["x"], abs=1e-9) == -1.0
    assert pytest.approx(dir_w["z"], abs=1e-9) == 0.0
    yaw_w = sumo_heading_to_three_yaw(270.0)
    assert pytest.approx(yaw_w, abs=1e-9) == -math.pi / 2
    assert pytest.approx(three_yaw_to_sumo_heading(yaw_w), abs=1e-9) == 270.0


def test_curved_road_headings():
    # J2 Rotary curve 125.4 deg
    h1 = 125.4
    yaw1 = sumo_heading_to_three_yaw(h1)
    assert pytest.approx(yaw1, abs=1e-4) == 0.95295
    assert pytest.approx(three_yaw_to_sumo_heading(yaw1), abs=1e-4) == h1

    # J1 approach curve 154.2 deg
    h2 = 154.2
    yaw2 = sumo_heading_to_three_yaw(h2)
    assert pytest.approx(yaw2, abs=1e-4) == 0.45029
    assert pytest.approx(three_yaw_to_sumo_heading(yaw2), abs=1e-4) == h2


def test_junction_relative_positions(corridor_data):
    j1 = corridor_data["junctions"][corridor_data["keyJunctions"]["J1"]["id"]]
    j2 = corridor_data["junctions"][corridor_data["keyJunctions"]["J2"]["id"]]
    j3 = corridor_data["junctions"][corridor_data["keyJunctions"]["J3"]["id"]]

    t1 = sumo_to_three_coords(j1["x"], j1["y"])
    t2 = sumo_to_three_coords(j2["x"], j2["y"])
    t3 = sumo_to_three_coords(j3["x"], j3["y"])

    # J1 is North-West of J2 (-Z is North, -X is West)
    assert t1["z"] < t2["z"]
    assert t1["x"] < t2["x"]

    # J3 is South-East of J2 (+Z is South, +X is East)
    assert t3["z"] > t2["z"]
    assert t3["x"] > t2["x"]


def test_distance_preservation(corridor_data):
    j1 = corridor_data["junctions"][corridor_data["keyJunctions"]["J1"]["id"]]
    j2 = corridor_data["junctions"][corridor_data["keyJunctions"]["J2"]["id"]]
    j3 = corridor_data["junctions"][corridor_data["keyJunctions"]["J3"]["id"]]

    sumo_1_2 = math.hypot(j2["x"] - j1["x"], j2["y"] - j1["y"])
    sumo_2_3 = math.hypot(j3["x"] - j2["x"], j3["y"] - j2["y"])
    sumo_1_3 = math.hypot(j3["x"] - j1["x"], j3["y"] - j1["y"])

    t1 = sumo_to_three_coords(j1["x"], j1["y"])
    t2 = sumo_to_three_coords(j2["x"], j2["y"])
    t3 = sumo_to_three_coords(j3["x"], j3["y"])

    three_1_2 = math.hypot(t2["x"] - t1["x"], t2["z"] - t1["z"])
    three_2_3 = math.hypot(t3["x"] - t2["x"], t3["z"] - t2["z"])
    three_1_3 = math.hypot(t3["x"] - t1["x"], t3["z"] - t1["z"])

    assert pytest.approx(three_1_2, abs=1e-9) == sumo_1_2
    assert pytest.approx(three_2_3, abs=1e-9) == sumo_2_3
    assert pytest.approx(three_1_3, abs=1e-9) == sumo_1_3

    assert pytest.approx(three_1_2, abs=0.1) == 163.11
    assert pytest.approx(three_2_3, abs=0.1) == 140.21
    assert pytest.approx(three_1_3, abs=0.1) == 303.12

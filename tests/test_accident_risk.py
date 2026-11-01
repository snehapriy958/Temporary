"""
tests/test_accident_risk.py

Unit and integration tests for the Weighted Blackspot Pipeline, Spatial Mapping,
Hotspot Analysis, and Risk-Zone Mapping modules.
Validates that blackspots are treated as weighted spatial observations without
synthetic unrolling or manufactured timestamps.
"""

from pathlib import Path
import pytest

from traffic_service.accident_dataset import (
    AccidentDataPipeline,
    BlackspotRecord,
)
from traffic_service.hotspot_analyzer import (
    Hotspot,
    HotspotAnalyzer,
    SEVERITY_WEIGHT_FATAL,
    SEVERITY_WEIGHT_NON_FATAL,
)
from traffic_service.risk_mapper import RiskMapper, RiskZone
from traffic_service.spatial_mapper import MappedBlackspot, SpatialMapper


NETWORK_FILE = Path(__file__).resolve().parent.parent / "sumo" / "silk_board" / "network" / "silk_board.net.xml"
JUNCTION_MAP = Path(__file__).resolve().parent.parent / "sumo" / "silk_board" / "junction_mapping.json"


@pytest.fixture
def spatial_mapper():
    return SpatialMapper(
        net_path=NETWORK_FILE,
        junction_mapping_path=JUNCTION_MAP,
        max_edge_distance_m=60.0,
        max_junction_distance_m=120.0,
    )


# 1. Blackspot Schema Validation
def test_blackspot_schema_validation():
    spot = BlackspotRecord(
        spot_id="BSP_TEST_01",
        location_name="Silk Board Junction",
        police_station="Madivala",
        latitude=12.9172,
        longitude=77.6228,
        road_name="Hosur Road",
        annual_crashes=34,
        fatal_crashes=8,
        primary_collision_type="SIDE_IMPACT",
        documented_risk_category="CRITICAL",
    )
    assert spot.spot_id == "BSP_TEST_01"
    assert spot.annual_crashes == 34
    assert spot.fatal_crashes == 8
    assert spot.documented_risk_category == "CRITICAL"


# 2. Missing / Invalid Coordinates
def test_missing_and_invalid_coordinates(tmp_path):
    pipe = AccidentDataPipeline(raw_dir=tmp_path, processed_dir=tmp_path)
    assert pipe.validate_coordinate(12.9172, 77.6228) is True
    assert pipe.validate_coordinate(28.6139, 77.2090) is False  # Delhi
    assert pipe.validate_coordinate(0.0, 0.0) is False
    assert pipe.validate_coordinate(None, 77.6228) is False
    assert pipe.validate_coordinate("invalid", 77.6228) is False


# 3. Coordinate Conversion (WGS84 -> SUMO Cartesian)
def test_coordinate_conversion(spatial_mapper):
    x, y = spatial_mapper.wgs84_to_sumo_xy(77.6228, 12.9172)
    assert isinstance(x, float)
    assert isinstance(y, float)
    min_x, min_y, max_x, max_y = spatial_mapper.boundary
    assert min_x <= x <= max_x
    assert min_y <= y <= max_y


# 4. SUMO Edge Mapping
def test_sumo_edge_mapping(spatial_mapper):
    mapped = spatial_mapper.map_point(
        spot_id="BSP_EDGE_01",
        lat=12.9172,
        lon=77.6228,
        annual_crashes=34,
        fatal_crashes=8,
    )
    assert mapped.is_matched is True
    assert mapped.nearest_edge_id is not None
    assert mapped.edge_distance_m <= 60.0
    assert mapped.annual_crashes == 34


# 5. Junction Mapping (J1, J2, J3)
def test_junction_mapping(spatial_mapper):
    mapped_j2 = spatial_mapper.map_point(
        spot_id="BSP_J2",
        lat=12.9172,
        lon=77.6228,
    )
    assert mapped_j2.is_matched is True
    assert mapped_j2.nearest_junction_id is not None


# 6. Outside-Network Blackspots
def test_outside_network_blackspots(spatial_mapper):
    mapped_out = spatial_mapper.map_point(
        spot_id="BSP_OUTSIDE",
        lat=13.1986,
        lon=77.7066,
    )
    assert mapped_out.is_matched is False
    assert mapped_out.unmatched_reason == "outside_network_boundary"


# 7. Hotspot Clustering on Weighted Observations
def test_hotspot_clustering_on_weighted_observations():
    analyzer = HotspotAnalyzer(eps_meters=150.0, min_samples=1)
    spots = [
        MappedBlackspot(
            spot_id=f"BSP_{i}",
            location_name=f"Spot {i}",
            police_station="Madivala",
            latitude=12.9172,
            longitude=77.6228,
            sumo_x=2000.0 + (i * 10.0),
            sumo_y=3000.0 + (i * 10.0),
            annual_crashes=10,
            fatal_crashes=2,
            primary_collision_type="REAR_END",
            documented_risk_category="HIGH",
            nearest_edge_id="edge_1",
            nearest_edge_name="Hosur Road",
            edge_distance_m=12.0,
            nearest_junction_id="node_1",
            junction_distance_m=25.0,
            corridor_junction="J2",
            is_corridor=True,
            is_matched=True,
        )
        for i in range(2)
    ]
    hotspots = analyzer.analyze(spots)
    assert len(hotspots) == 1
    # Total crashes aggregated across clustered blackspots: 10 + 10 = 20
    assert hotspots[0].total_crashes == 20
    assert hotspots[0].fatal_crashes == 4
    assert hotspots[0].blackspot_count == 2


# 8. Severity Weighting (MoRTH Calculation)
def test_severity_weighting():
    analyzer = HotspotAnalyzer(weight_fatal=5.0, weight_non_fatal=2.0)
    # 4 fatal, 6 non-fatal -> (4 * 5.0) + (6 * 2.0) = 20.0 + 12.0 = 32.0
    score = analyzer.compute_severity_score(fatal=4, non_fatal=6)
    assert score == 32.0


# 9. Risk Classification Tiers
def test_risk_classification():
    mapper = RiskMapper()
    assert mapper.classify_risk_tier(65.0) == "CRITICAL"
    assert mapper.classify_risk_tier(45.0) == "HIGH"
    assert mapper.classify_risk_tier(25.0) == "MEDIUM"
    assert mapper.classify_risk_tier(10.0) == "LOW"

    # Multiplier bonus: base 30 * (1 + 0.5 + 0.3) = 54.0
    cri = mapper.compute_composite_risk(30.0, is_corridor=True, has_junction=True)
    assert cri == 54.0


# 10. Empty Dataset Handling
def test_empty_dataset_handling():
    analyzer = HotspotAnalyzer()
    assert analyzer.analyze([]) == []

    mapper = RiskMapper()
    assert mapper.map_hotspots_to_risk_zones([]) == []


# 11. Malformed Records Handling
def test_malformed_records(tmp_path):
    pipe = AccidentDataPipeline(raw_dir=tmp_path, processed_dir=tmp_path)
    assert pipe.normalize_collision_type("side-swipe collision") == "SIDE_IMPACT"
    assert pipe.normalize_collision_type("pedestrian hit") == "PEDESTRIAN"
    assert pipe.normalize_collision_type(None) == "OTHER"

"""
scripts/run_accident_pipeline.py

End-to-end execution of traffic accident and blackspot risk pipeline:
1. Ingest documented corridor blackspot data as weighted spatial observations
2. Spatially project and snap blackspots to SUMO road edges and junctions
3. Run spatial clustering and IRC/MoRTH severity scoring directly on observations
4. Map operational risk tiers (CRITICAL, HIGH, MEDIUM, LOW) across J1/J2/J3
5. Export structured CSV and JSON deliverables
"""

from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from traffic_service.accident_dataset import AccidentDataPipeline
from traffic_service.hotspot_analyzer import HotspotAnalyzer
from traffic_service.risk_mapper import RiskMapper
from traffic_service.spatial_mapper import SpatialMapper


def main() -> None:
    print("=" * 80)
    print("WEIGHTED BLACKSPOT PIPELINE -> HOTSPOT ANALYSIS -> RISK-ZONE MAPPING")
    print("Bengaluru Silk Board Corridor (J1 -> J2 -> J3)")
    print("=" * 80)

    raw_dir = PROJECT_ROOT / "data" / "accidents" / "raw"
    proc_dir = PROJECT_ROOT / "data" / "accidents" / "processed"
    net_path = PROJECT_ROOT / "sumo" / "silk_board" / "network" / "silk_board.net.xml"
    j_map_path = PROJECT_ROOT / "sumo" / "silk_board" / "junction_mapping.json"

    out_acc_dir = PROJECT_ROOT / "outputs" / "accidents"
    out_hs_dir = PROJECT_ROOT / "outputs" / "hotspots"
    out_risk_dir = PROJECT_ROOT / "outputs" / "risk"

    out_acc_dir.mkdir(parents=True, exist_ok=True)
    out_hs_dir.mkdir(parents=True, exist_ok=True)
    out_risk_dir.mkdir(parents=True, exist_ok=True)

    # 1. Ingestion of Weighted Blackspot Observations
    print("\n[Step 1/4] Ingesting & standardizing georeferenced blackspot observations...")
    pipeline = AccidentDataPipeline(raw_dir=raw_dir, processed_dir=proc_dir)
    blackspots = pipeline.run_pipeline()
    total_crashes = sum(b.annual_crashes for b in blackspots)
    total_fatal = sum(b.fatal_crashes for b in blackspots)
    print(f"  -> Ingested {len(blackspots)} documented blackspots.")
    print(f"  -> Total annual crashes represented: {total_crashes} (Fatal: {total_fatal})")
    print(f"  -> Saved: {proc_dir / 'cleaned_accidents.csv'}")

    pipeline.export_csv(out_acc_dir / "cleaned_accidents.csv")

    # 2. Spatial Mapping to SUMO Network
    print("\n[Step 2/4] Mapping blackspots to SUMO road infrastructure...")
    mapper = SpatialMapper(
        net_path=net_path,
        junction_mapping_path=j_map_path,
        max_edge_distance_m=60.0,
        max_junction_distance_m=120.0,
    )
    matched, unmatched = mapper.map_records(blackspots)
    print(f"  -> Snapped to network edges: {len(matched)} blackspots")
    print(f"  -> Outside network distance threshold: {len(unmatched)} blackspots")

    all_mapped = matched + unmatched
    mapping_summary_file = out_acc_dir / "mapping_summary.csv"
    mapper.export_summary(all_mapped, mapping_summary_file)
    print(f"  -> Saved: {mapping_summary_file}")

    # 3. Hotspot Analysis
    print("\n[Step 3/4] Running spatial DBSCAN clustering & severity scoring...")
    analyzer = HotspotAnalyzer(eps_meters=200.0, min_samples=1)
    hotspots = analyzer.analyze(matched)
    print(f"  -> Identified {len(hotspots)} distinct corridor crash hotspots.")

    hotspots_file = out_hs_dir / "hotspots.csv"
    analyzer.export_csv(hotspots_file)
    print(f"  -> Saved: {hotspots_file}")

    for h in hotspots:
        print(
            f"     * {h.hotspot_id}: Lat={h.center_latitude:.4f}, Lon={h.center_longitude:.4f} | "
            f"Blackspots={h.blackspot_count} | Crashes={h.total_crashes} (Fatal={h.fatal_crashes}) | "
            f"Score={h.severity_score} | Rel={h.corridor_relevance}"
        )

    # 4. Risk-Zone Mapping
    print("\n[Step 4/4] Mapping operational risk zones & corridor advisories...")
    risk_mapper = RiskMapper()
    risk_zones = risk_mapper.map_hotspots_to_risk_zones(hotspots)
    print(f"  -> Classified {len(risk_zones)} operational risk zones.")

    risk_json_file = out_risk_dir / "risk_zones.json"
    risk_summary_file = out_risk_dir / "risk_summary.csv"
    risk_mapper.export_json(risk_json_file)
    risk_mapper.export_csv(risk_summary_file)
    print(f"  -> Saved: {risk_json_file}")
    print(f"  -> Saved: {risk_summary_file}")

    print("\n" + "=" * 90)
    print(f"{'ZONE ID':<10} | {'RISK LEVEL':<10} | {'CRI SCORE':<10} | {'CRASHES':<8} | {'FATAL':<6} | {'JUNCTION':<10} | {'ADVISORY SUMMARY':<24}")
    print("-" * 90)
    for z in risk_zones:
        adv_short = z.safety_advisory[:22] + "..." if len(z.safety_advisory) > 22 else z.safety_advisory
        j_str = z.associated_junction or "Approach"
        print(
            f"{z.zone_id:<10} | {z.risk_level:<10} | {z.composite_risk_score:<10.1f} | "
            f"{z.total_crashes:<8} | {z.fatal_crashes:<6} | {j_str:<10} | {adv_short:<24}"
        )
    print("=" * 90)
    print("Weighted blackspot pipeline completed successfully.\n")


if __name__ == "__main__":
    main()

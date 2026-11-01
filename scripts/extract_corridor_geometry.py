#!/usr/bin/env python3
"""
scripts/extract_corridor_geometry.py

Phase 3B Stage 1: Network Geometry Extraction Utility.
Parses sumo/silk_board/network/silk_board.net.xml and extracts the verified
corridor road geometry, lane shapes, junction polygons, connectivity, and
elevated flyover mappings.

Outputs:
  - frontend/src/data/corridorNetworkGeometry.json (Optimized for 3D visualization)
  - outputs/geometry/corridor_network_geometry.json (Archival copy)
"""

import os
import sys
import json
import math
import gzip
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

# Scene Anchor as defined in Phase 3A v1.2
SCENE_ANCHOR = {
    "name": "Central Silk Board (J2)",
    "sumo_x": 2185.00,
    "sumo_y": 3540.00,
    "sumo_z": 0.00,
    "wgs84_lon": 77.62287,
    "wgs84_lat": 12.91724
}

# Key Corridor Junctions
KEY_JUNCTIONS = {
    "J1": {
        "id": "1617743335",
        "name": "Hosur Rd North Feeder (Madiwala Checkpost)",
        "role": "Upstream Feeder Signal"
    },
    "J2": {
        "id": "cluster_10282769895_10775075568_11964440742_11964440743",
        "name": "Central Silk Board Rotary Hub",
        "role": "Primary Corridor Hub"
    },
    "J3": {
        "id": "6970466614",
        "name": "Hosur Rd South Exit (Rupena Agrahara)",
        "role": "Downstream Exit Signal"
    }
}

# Key Corridor Spine Edges (Hosur Road Arterial & Direct Connections)
CORRIDOR_SPINE_EDGES = {
    "172853382#1": "Hosur Road North Inflow to J1",
    "172853382#2": "Hosur Road Approach at J1",
    "-148697299": "J1 Side Cross Approach",
    "148697299": "J1 Side Cross Departure",
    "172853382#3": "Hosur Road Arterial Link (J1 -> J2)",
    "464465165#0": "Hosur Road Northbound Approach at J2",
    "464465164#1": "Hosur Road Northbound Feeder to J2",
    "92196679#0": "Madiwala Side Approach to J2",
    "1148717038#0": "Hosur Road Arterial Link (J2 -> J3)",
    "40696223#1": "Hosur Road Southbound Exit from J3",
    "-744783934": "J3 Side Cross Approach",
    "744783934": "J3 Side Cross Departure",
    "1453814098#0": "Outer Ring Road Eastbound Inflow at J2",
    "239438610#0": "Outer Ring Road Westbound Inflow at J2"
}

# Cataloged Flyover & Underpass Segments (from Phase 3A v1.2)
FLYOVER_SEGMENTS = {
    # Silk Board Central Flyover (Hosur Bypass across J2)
    "1208112303": {
        "category": "silk_board_flyover",
        "description": "Silk Board Flyover (Hosur Bypass Southbound)",
        "assumed_elevation": 7.50,
        "is_ramp": False
    },
    "40696222": {
        "category": "silk_board_flyover",
        "description": "Silk Board Flyover (Hosur Bypass Northbound)",
        "assumed_elevation": 7.50,
        "is_ramp": False
    },
    # Silk Board Double Decker Flyover (BTM -> HSR Road Deck)
    "1299917512": {
        "category": "double_decker_flyover",
        "description": "Silkboard Double Decker Flyover Main Span",
        "assumed_elevation": 8.00,
        "is_ramp": False
    },
    "1299917517": {
        "category": "double_decker_flyover",
        "description": "Silkboard Double Decker Flyover East Span",
        "assumed_elevation": 8.00,
        "is_ramp": False
    },
    "1299932382": {
        "category": "double_decker_flyover",
        "description": "Silkboard Double Decker Flyover Loop",
        "assumed_elevation": 8.00,
        "is_ramp": False
    },
    "1301808818": {
        "category": "double_decker_flyover",
        "description": "Silkboard Double Decker Flyover HSR Approach",
        "assumed_elevation": 8.00,
        "is_ramp": False
    },
    "519734960": {
        "category": "double_decker_flyover",
        "description": "Silkboard Double Decker Flyover Central Span",
        "assumed_elevation": 8.00,
        "is_ramp": False
    },
    # Double Decker Ramps
    "1299917514": {
        "category": "double_decker_ramp",
        "description": "Double Decker Ramp A (Ascending to Deck)",
        "assumed_elevation": 8.00,
        "is_ramp": True
    },
    "1301808820": {
        "category": "double_decker_ramp",
        "description": "Ramp to Hosur Road joining Double Decker Flyover",
        "assumed_elevation": 8.00,
        "is_ramp": True
    },
    # Electronic City Expressway Start (South of J3)
    "1303740767": {
        "category": "electronic_city_expressway",
        "description": "Electronic City Elevated Tollway Southbound",
        "assumed_elevation": 7.50,
        "is_ramp": False
    },
    "133759694": {
        "category": "electronic_city_expressway",
        "description": "Electronic City Elevated Tollway Transition",
        "assumed_elevation": 7.50,
        "is_ramp": False
    },
    "160511376": {
        "category": "electronic_city_expressway",
        "description": "Electronic City Elevated Tollway Northbound",
        "assumed_elevation": 7.50,
        "is_ramp": False
    },
    # Ragigudda Approach Flyover
    "1351994264": {
        "category": "ragigudda_flyover",
        "description": "Ragigudda-Silk Board Integrated Flyover",
        "assumed_elevation": 8.00,
        "is_ramp": False
    },
    "1351994264-AddedOffRampEdge": {
        "category": "ragigudda_ramp",
        "description": "Ragigudda Flyover Off-Ramp to BTM",
        "assumed_elevation": 8.00,
        "is_ramp": True
    },
    "886153772": {
        "category": "ragigudda_flyover",
        "description": "Ragigudda-Silk Board Viaduct West",
        "assumed_elevation": 8.00,
        "is_ramp": False
    },
    # Madiwala Underpass (North of J1)
    "133763758": {
        "category": "madiwala_underpass",
        "description": "Madiwala Underpass Northbound Barrel 1",
        "assumed_elevation": -4.50,
        "is_ramp": False
    },
    "133763760": {
        "category": "madiwala_underpass",
        "description": "Madiwala Underpass Northbound Barrel 2",
        "assumed_elevation": -4.50,
        "is_ramp": False
    },
    "148210028": {
        "category": "madiwala_underpass",
        "description": "Madiwala Underpass Southbound Exit",
        "assumed_elevation": -4.50,
        "is_ramp": False
    },
    "148210029": {
        "category": "madiwala_underpass",
        "description": "Madiwala Underpass Southbound Approach",
        "assumed_elevation": -4.50,
        "is_ramp": False
    },
    "148210030": {
        "category": "madiwala_underpass",
        "description": "Madiwala Underpass Southbound Mid Barrel",
        "assumed_elevation": -4.50,
        "is_ramp": False
    },
    "239438609": {
        "category": "madiwala_underpass",
        "description": "Madiwala Underpass Transition",
        "assumed_elevation": -4.50,
        "is_ramp": False
    }
}

# Highway types included in corridor representation
# We prioritize transit-relevant arterial classes and exclude disconnected residential alleys
CORRIDOR_HIGHWAY_TYPES = {
    "highway.motorway",
    "highway.trunk",
    "highway.trunk_link",
    "highway.primary",
    "highway.primary_link",
    "highway.secondary",
    "highway.tertiary"
}

# Spatial filter radius around Central Silk Board (J2)
CORRIDOR_EXTRACT_RADIUS_M = 1000.0


def extract_corridor_geometry(net_path: str):
    print(f"[Stage 1] Parsing SUMO network XML: {net_path}")
    if not os.path.exists(net_path):
        raise FileNotFoundError(f"Network file not found: {net_path}")

    tree = ET.parse(net_path)
    root = tree.getroot()

    # 1. Location & CRS Metadata
    loc = root.find("location")
    net_offset = [float(x) for x in loc.get("netOffset").split(",")]
    conv_boundary = [float(x) for x in loc.get("convBoundary").split(",")]
    orig_boundary = [float(x) for x in loc.get("origBoundary").split(",")]
    proj_param = loc.get("projParameter")

    metadata = {
        "generator": "Eclipse SUMO netconvert 1.26.0",
        "extraction_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "source_file": "sumo/silk_board/network/silk_board.net.xml",
        "netOffset": net_offset,
        "convBoundary": conv_boundary,
        "origBoundary": orig_boundary,
        "projParameter": proj_param,
        "sceneAnchor": SCENE_ANCHOR,
        "corridorRadiusMeters": CORRIDOR_EXTRACT_RADIUS_M
    }

    # 2. Extract All Junctions
    junc_by_id = {}
    for j in root.findall("junction"):
        jid = j.get("id")
        jtype = j.get("type")
        jx = float(j.get("x"))
        jy = float(j.get("y"))
        inc_lanes = [l for l in j.get("incLanes", "").split() if l]
        int_lanes = [l for l in j.get("intLanes", "").split() if l]
        shape_str = j.get("shape", "").strip()
        shape_pts = []
        if shape_str:
            for pt in shape_str.split():
                if "," in pt:
                    coords = pt.split(",")
                    shape_pts.append([float(coords[0]), float(coords[1])])

        j_obj = {
            "id": jid,
            "type": jtype,
            "x": jx,
            "y": jy,
            "shape": shape_pts,
            "incLanes": inc_lanes,
            "intLanes": int_lanes,
            "isKeyJunction": False
        }
        junc_by_id[jid] = j_obj

    # 3. Extract and Filter Edges
    anchor_x = SCENE_ANCHOR["sumo_x"]
    anchor_y = SCENE_ANCHOR["sumo_y"]
    radius_sq = CORRIDOR_EXTRACT_RADIUS_M ** 2

    corridor_edges = {}
    spine_count = 0
    flyover_count = 0

    for e in root.findall("edge"):
        eid = e.get("id")
        func = e.get("function")
        if func == "internal":
            continue

        e_type = e.get("type", "")
        is_spine = eid in CORRIDOR_SPINE_EDGES
        is_flyover = eid in FLYOVER_SEGMENTS
        is_arterial_type = e_type in CORRIDOR_HIGHWAY_TYPES

        # Inspect lanes
        lanes = []
        edge_coords = []
        for l in e.findall("lane"):
            lid = l.get("id")
            l_idx = int(l.get("index", 0))
            l_speed = float(l.get("speed", 13.89))
            l_length = float(l.get("length", 0.0))
            w_attr = l.get("width")
            l_width = float(w_attr) if w_attr else 3.20

            shape_str = l.get("shape", "").strip()
            pts = []
            for pt in shape_str.split():
                if "," in pt:
                    coords = pt.split(",")
                    px = float(coords[0])
                    py = float(coords[1])
                    pz = float(coords[2]) if len(coords) > 2 else 0.0
                    pts.append([px, py, pz])
                    edge_coords.append([px, py])

            lanes.append({
                "id": lid,
                "index": l_idx,
                "speed": l_speed,
                "length": l_length,
                "width": l_width,
                "shape": pts
            })

        # Determine spatial inclusion
        within_radius = False
        if edge_coords:
            for cx, cy in edge_coords:
                dist_sq = (cx - anchor_x) ** 2 + (cy - anchor_y) ** 2
                if dist_sq <= radius_sq:
                    within_radius = True
                    break

        # Edge is selected if it is:
        # (1) A corridor spine edge, OR
        # (2) A cataloged flyover / underpass segment, OR
        # (3) An arterial/trunk road within the corridor radius
        if is_spine or is_flyover or (is_arterial_type and within_radius):
            edge_obj = {
                "id": eid,
                "name": e.get("name", ""),
                "from": e.get("from"),
                "to": e.get("to"),
                "type": e_type,
                "priority": int(e.get("priority", 1)),
                "numLanes": len(lanes),
                "lanes": lanes,
                "isCorridorSpine": False,
                "isFlyover": False,
                "isUnderpass": False,
                "elevationCategory": "ground_surface",
                "assumedElevation": 0.00
            }

            if is_spine:
                edge_obj["isCorridorSpine"] = True
                edge_obj["corridorRole"] = CORRIDOR_SPINE_EDGES[eid]
                spine_count += 1

            if is_flyover:
                f_info = FLYOVER_SEGMENTS[eid]
                edge_obj["isFlyover"] = f_info["assumed_elevation"] > 0
                edge_obj["isUnderpass"] = f_info["assumed_elevation"] < 0
                edge_obj["elevationCategory"] = f_info["category"]
                edge_obj["assumedElevation"] = f_info["assumed_elevation"]
                edge_obj["isRamp"] = f_info["is_ramp"]
                edge_obj["flyoverDescription"] = f_info["description"]
                flyover_count += 1

            corridor_edges[eid] = edge_obj

    print(f"[Stage 1] Extracted {len(corridor_edges)} corridor edges ({spine_count} spine links, {flyover_count} flyover/underpass segments).")

    # 4. Associate and Filter Connected Junctions
    corridor_junctions = {}
    for eid, e_obj in corridor_edges.items():
        for jid in [e_obj["from"], e_obj["to"]]:
            if jid and jid in junc_by_id and jid not in corridor_junctions:
                corridor_junctions[jid] = junc_by_id[jid]

    # Explicitly ensure all key junctions are included and labeled
    for k_label, k_meta in KEY_JUNCTIONS.items():
        jid = k_meta["id"]
        if jid in junc_by_id:
            j_entry = junc_by_id[jid]
            j_entry["isKeyJunction"] = True
            j_entry["junctionLabel"] = k_label
            j_entry["junctionName"] = k_meta["name"]
            j_entry["role"] = k_meta["role"]
            corridor_junctions[jid] = j_entry
        else:
            raise KeyError(f"Critical error: Key junction {k_label} ({jid}) not found in network!")

    print(f"[Stage 1] Extracted {len(corridor_junctions)} connected junctions.")
    for k_label, k_meta in KEY_JUNCTIONS.items():
        kj = corridor_junctions[k_meta["id"]]
        print(f"  • {k_label} ({kj['junctionName']}): SUMO x={kj['x']:.2f}, y={kj['y']:.2f}, shape_pts={len(kj['shape'])}, incLanes={len(kj['incLanes'])}")

    # 5. Extract Road Connections Between Corridor Edges
    corridor_connections = []
    for c in root.findall("connection"):
        f = c.get("from")
        t = c.get("to")
        if f in corridor_edges and t in corridor_edges:
            corridor_connections.append({
                "fromEdge": f,
                "toEdge": t,
                "fromLane": int(c.get("fromLane", 0)),
                "toLane": int(c.get("toLane", 0)),
                "dir": c.get("dir", ""),
                "state": c.get("state", ""),
                "tl": c.get("tl", ""),
                "linkIndex": int(c.get("linkIndex")) if c.get("linkIndex") is not None else None
            })

    print(f"[Stage 1] Extracted {len(corridor_connections)} road connections between corridor edges.")

    # 6. Extract Traffic Light Programs for Key Junctions
    tls_programs = {}
    for tls in root.findall("tlLogic"):
        tl_id = tls.get("id")
        for k_label, k_meta in KEY_JUNCTIONS.items():
            if k_meta["id"] in tl_id or tl_id == k_meta["id"]:
                phases = []
                for p_idx, p in enumerate(tls.findall("phase")):
                    phases.append({
                        "phaseIndex": p_idx,
                        "duration": float(p.get("duration", 0)),
                        "state": p.get("state", "")
                    })
                tls_programs[k_label] = {
                    "id": tl_id,
                    "junctionLabel": k_label,
                    "type": tls.get("type", "static"),
                    "programID": tls.get("programID", "0"),
                    "numPhases": len(phases),
                    "phases": phases
                }

    print(f"[Stage 1] Extracted traffic light programs for {len(tls_programs)} key junctions (J1, J2, J3).")

    # 7. Document Unsupported or Malformed Elements
    malformed_elements = {
        "planar_z_coordinates": {
            "severity": "Informational",
            "count": sum(len(e["lanes"]) for e in corridor_edges.values()),
            "description": "All lane shape coordinates in silk_board.net.xml have z = 0.00m. Planar horizontal ground truth is preserved; vertical geometry is rendered via explicit illustrative visualization assumptions."
        },
        "internal_edges_omitted": {
            "severity": "Design Decision",
            "count": len([e for e in root.findall("edge") if e.get("function") == "internal"]),
            "description": "Internal micro-edges (function='internal', e.g. ':1617743335_0') are internal junction conflict shapes and omitted from road surface meshes. Junction asphalt polygons (junction.shape) are used instead to represent conflict areas cleanly without overlapping ribbon meshes."
        },
        "default_lane_widths": {
            "severity": "Informational",
            "count": sum(1 for e in corridor_edges.values() for l in e["lanes"] if l["width"] == 3.20),
            "description": "Lanes omitting explicit width attributes in XML default to 3.20 meters as standardized by SUMO netconvert."
        },
        "disallowed_classes_pruned": {
            "severity": "Optimization",
            "description": "Verbose disallow attributes listing transit strings ('tram rail_urban ship container...') were pruned from the 3D runtime payload to minimize bundle size while preserving full geometry."
        }
    }

    # 8. Compute Corridor Bounding Box & Statistics
    all_x = [pt[0] for e in corridor_edges.values() for l in e["lanes"] for pt in l["shape"]]
    all_y = [pt[1] for e in corridor_edges.values() for l in e["lanes"] for pt in l["shape"]]

    bbox = {
        "min_x": round(min(all_x), 2),
        "max_x": round(max(all_x), 2),
        "min_y": round(min(all_y), 2),
        "max_y": round(max(all_y), 2),
        "width_m": round(max(all_x) - min(all_x), 2),
        "height_m": round(max(all_y) - min(all_y), 2)
    }

    total_lane_meters = sum(l["length"] for e in corridor_edges.values() for l in e["lanes"])

    # 9. Assemble Complete Extracted Data Object
    extracted_data = {
        "metadata": metadata,
        "elevationAssumptions": {
            "notice": "All vertical elevations are illustrative visualization assumptions based on IRC:54-1974 & BMRCL design norms. They are NOT surveyed as-built elevations and do not affect SUMO simulation physics.",
            "ASSUMED_FLYOVER_ROAD_ELEVATION": 7.50,
            "ASSUMED_DOUBLE_DECKER_ROAD_ELEVATION": 8.00,
            "ASSUMED_METRO_VIADUCT_ELEVATION": 16.00,
            "ASSUMED_UNDERPASS_DEPRESSION": -4.50,
            "ASSUMED_RAMP_MAX_GRADIENT": 0.04,
            "ASSUMED_PIER_SPACING": 30.0
        },
        "corridorBoundingBox": bbox,
        "keyJunctions": KEY_JUNCTIONS,
        "junctions": corridor_junctions,
        "edges": corridor_edges,
        "connections": corridor_connections,
        "trafficLights": tls_programs,
        "unsupportedAndMalformedElements": malformed_elements,
        "summary": {
            "totalCorridorEdges": len(corridor_edges),
            "totalCorridorLanes": sum(e["numLanes"] for e in corridor_edges.values()),
            "totalLaneMeters": round(total_lane_meters, 2),
            "totalCorridorJunctions": len(corridor_junctions),
            "totalCorridorConnections": len(corridor_connections),
            "keyJunctionCount": len(KEY_JUNCTIONS),
            "flyoverSegmentCount": flyover_count,
            "corridorSpineSegmentCount": spine_count
        }
    }

    return extracted_data


def save_extracted_geometry(data, output_paths):
    json_bytes = json.dumps(data, indent=2).encode("utf-8")
    gz_bytes = gzip.compress(json_bytes)

    for out_path in output_paths:
        p = Path(out_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        print(f"[Stage 1] Writing extracted geometry to {p}...")
        with open(p, "wb") as f:
            f.write(json_bytes)
        size_kb = len(json_bytes) / 1024.0
        gz_size_kb = len(gz_bytes) / 1024.0
        print(f"[Stage 1] Successfully wrote {size_kb:.1f} KB (Gzip: {gz_size_kb:.1f} KB) to {p}")


def main():
    net_xml = "sumo/silk_board/network/silk_board.net.xml"
    targets = [
        "frontend/src/data/corridorNetworkGeometry.json",
        "outputs/geometry/corridor_network_geometry.json"
    ]

    try:
        data = extract_corridor_geometry(net_xml)
        save_extracted_geometry(data, targets)
        print("\n[Stage 1] Network Geometry Extraction completed successfully!")
        return 0
    except Exception as e:
        print(f"[Stage 1] ERROR during geometry extraction: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

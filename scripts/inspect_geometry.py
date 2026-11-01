#!/usr/bin/env python3
"""
scripts/inspect_geometry.py

Inspects silk_board.net.xml to verify junctions, edges, lane widths, shapes,
and connectivity for Stage 1 Network Geometry Extraction.
"""

import xml.etree.ElementTree as ET
import json
import math

def inspect_network():
    net_path = "sumo/silk_board/network/silk_board.net.xml"
    print(f"Parsing {net_path}...")
    tree = ET.parse(net_path)
    root = tree.getroot()

    location = root.find("location")
    print("Location attributes:", location.attrib)

    # 1. Junctions
    junctions = {}
    for j in root.findall("junction"):
        j_id = j.get("id")
        j_type = j.get("type")
        x = float(j.get("x"))
        y = float(j.get("y"))
        inc_lanes = j.get("incLanes", "").split()
        int_lanes = j.get("intLanes", "").split()
        shape = j.get("shape", "")
        shape_pts = []
        if shape:
            for pt in shape.strip().split():
                if "," in pt:
                    px, py = pt.split(",")[:2]
                    shape_pts.append([float(px), float(py)])

        junctions[j_id] = {
            "id": j_id,
            "type": j_type,
            "x": x,
            "y": y,
            "incLanes": inc_lanes,
            "intLanes": int_lanes,
            "shape": shape_pts
        }

    print(f"Parsed {len(junctions)} junctions.")

    # Check key junctions
    key_jids = {
        "J1": "1617743335",
        "J2": "cluster_10282769895_10775075568_11964440742_11964440743",
        "J3": "6970466614"
    }
    for name, jid in key_jids.items():
        if jid in junctions:
            j = junctions[jid]
            print(f"{name} ({jid}): x={j['x']}, y={j['y']}, type={j['type']}, shape_pts={len(j['shape'])}, incLanes={len(j['incLanes'])}")
        else:
            print(f"WARNING: {name} ({jid}) not found in junctions!")

    # 2. Edges & Lanes
    regular_edges = {}
    internal_edges = {}
    types = {}
    for t in root.findall("type"):
        types[t.get("id")] = t.attrib

    flyover_edge_ids = {
        # Silk Board Flyover (Hosur Bypass)
        "1208112303": "silk_board_flyover",
        "40696222": "silk_board_flyover",
        # Silk Board Double Decker
        "1299917512": "double_decker_flyover",
        "1299917517": "double_decker_flyover",
        "1299932382": "double_decker_flyover",
        "1301808818": "double_decker_flyover",
        "519734960": "double_decker_flyover",
        # Ramps
        "1299917514": "double_decker_ramp_a",
        "1301808820": "double_decker_ramp_hosur",
        # Electronic City
        "1303740767": "electronic_city_expressway",
        "133759694": "electronic_city_expressway",
        "160511376": "electronic_city_expressway",
        # Ragigudda
        "1351994264": "ragigudda_flyover",
        "1351994264-AddedOffRampEdge": "ragigudda_ramp",
        "886153772": "ragigudda_flyover",
        # Madiwala Underpass
        "133763758": "madiwala_underpass",
        "133763760": "madiwala_underpass",
        "148210028": "madiwala_underpass",
        "148210029": "madiwala_underpass",
        "148210030": "madiwala_underpass",
        "239438609": "madiwala_underpass"
    }

    matched_flyovers = {}

    for e in root.findall("edge"):
        e_id = e.get("id")
        func = e.get("function")
        if func == "internal":
            internal_edges[e_id] = e
            continue

        lanes = []
        for l in e.findall("lane"):
            l_id = l.get("id")
            idx = int(l.get("index", 0))
            speed = float(l.get("speed", 13.89))
            length = float(l.get("length", 0))
            width_attr = l.get("width")
            # Default lane width in SUMO when omitted is 3.20m
            width = float(width_attr) if width_attr else 3.20
            shape = l.get("shape", "")
            pts = []
            for pt in shape.strip().split():
                if "," in pt:
                    coords = pt.split(",")
                    px, py = float(coords[0]), float(coords[1])
                    pz = float(coords[2]) if len(coords) > 2 else 0.0
                    pts.append([px, py, pz])

            lanes.append({
                "id": l_id,
                "index": idx,
                "speed": speed,
                "length": length,
                "width": width,
                "shape": pts
            })

        e_data = {
            "id": e_id,
            "from": e.get("from"),
            "to": e.get("to"),
            "name": e.get("name", ""),
            "type": e.get("type", ""),
            "priority": int(e.get("priority", 1)),
            "numLanes": len(lanes),
            "lanes": lanes
        }
        regular_edges[e_id] = e_data

        if e_id in flyover_edge_ids:
            matched_flyovers[e_id] = {
                "category": flyover_edge_ids[e_id],
                "edge": e_data
            }

    print(f"Parsed {len(regular_edges)} regular edges and {len(internal_edges)} internal edges.")
    print(f"Matched {len(matched_flyovers)} of {len(flyover_edge_ids)} flyover/underpass edges:")
    for eid, info in matched_flyovers.items():
        print(f"  [{info['category']}] {eid}: name='{info['edge']['name']}', lanes={info['edge']['numLanes']}, from={info['edge']['from']}, to={info['edge']['to']}")

    # 3. Connections
    connections = []
    for c in root.findall("connection"):
        connections.append({
            "from": c.get("from"),
            "to": c.get("to"),
            "fromLane": int(c.get("fromLane", 0)),
            "toLane": int(c.get("toLane", 0)),
            "dir": c.get("dir", ""),
            "state": c.get("state", ""),
            "via": c.get("via", ""),
            "tl": c.get("tl", "")
        })
    print(f"Parsed {len(connections)} road connections.")

if __name__ == "__main__":
    inspect_network()


def inspect_flyover_coordinates():
    net_path = "sumo/silk_board/network/silk_board.net.xml"
    tree = ET.parse(net_path)
    root = tree.getroot()

    flyovers = [
        '1208112303', '40696222', '1299917512', '1299917517', '1299932382',
        '1301808818', '519734960', '1299917514', '1301808820', '1303740767',
        '133759694', '160511376', '1351994264', '1351994264-AddedOffRampEdge',
        '886153772', '133763758', '133763760', '148210028', '148210029',
        '148210030', '239438609'
    ]

    print("\n--- Flyover Detailed Geometry ---")
    for fid in flyovers:
        e = root.find(f"./edge[@id='{fid}']")
        if e is not None:
            lanes = e.findall("lane")
            l0 = lanes[0]
            pts = l0.get("shape", "").split()
            length = float(l0.get("length", 0))
            print(f"{fid:26} | lanes={len(lanes)} | len={length:5.1f}m | {pts[0]} -> {pts[-1]}")

if __name__ == "__main__":
    inspect_flyover_coordinates()


def inspect_tl_logics():
    net_path = "sumo/silk_board/network/silk_board.net.xml"
    tree = ET.parse(net_path)
    root = tree.getroot()

    print("\n--- Traffic Light Programs ---")
    for tls in root.findall("tlLogic"):
        tl_id = tls.get("id")
        if any(k in tl_id for k in ["1617743335", "cluster_10282769895", "6970466614"]):
            print(f"tlLogic id='{tl_id}' type='{tls.get('type')}' programID='{tls.get('programID')}'")
            for idx, p in enumerate(tls.findall("phase")):
                print(f"   [P{idx}] dur={p.get('duration')}s state='{p.get('state')}'")

if __name__ == "__main__":
    inspect_tl_logics()


def inspect_corridor_connections():
    net_path = "sumo/silk_board/network/silk_board.net.xml"
    tree = ET.parse(net_path)
    root = tree.getroot()

    corridor_edges = [
        '172853382#2', '172853382#3', '1148717038#0', '40696223#1',
        '-148697299', '-744783934', '464465165#0', '92196679#0'
    ]

    print("\n--- Key Corridor Connections ---")
    for c in root.findall("connection"):
        f = c.get("from")
        t = c.get("to")
        if f in corridor_edges or t in corridor_edges:
            fl = c.get("fromLane")
            tl = c.get("toLane")
            d = c.get("dir")
            s = c.get("state")
            tl_id = c.get("tl", "")
            idx = c.get("linkIndex", "")
            print(f"Conn: {f}[{fl}] -> {t}[{tl}] | dir={d} state={s} tl={tl_id} idx={idx}")

if __name__ == "__main__":
    inspect_corridor_connections()

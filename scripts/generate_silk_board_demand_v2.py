from pathlib import Path
import xml.etree.ElementTree as ET

PROJECT_ROOT = Path(__file__).resolve().parents[1]

NETWORK_FILE = (
    PROJECT_ROOT
    / "sumo"
    / "silk_board"
    / "network"
    / "silk_board.net.xml"
)

OUTPUT_DIR = (
    PROJECT_ROOT
    / "sumo"
    / "silk_board"
    / "demand"
)

OUTPUT_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

OUTPUT_FILE = (
    OUTPUT_DIR
    / "silk_board.rou.xml"
)


J2 = (
    "cluster_10282769895_10775075568_11964440742_11964440743"
)


# Actual J2 incoming edges
CORRIDOR_ENTRY = "172853382#2"
HOSUR_A = "172853382#3"
HOSUR_B = "464465165#0"
MADIWALA = "92196679#0"


# Actual J2 outgoing edges
HOSUR_OUT_A = "1148717038#0"
HOSUR_OUT_B = "1453814098#0"
MADIWALA_OUT = "239438610#0"
CORRIDOR_EXIT = "40696223#1"


def add_route(parent, route_id, edges):
    ET.SubElement(
        parent,
        "route",
        {
            "id": route_id,
            "edges": " ".join(edges),
        },
    )


def add_flow(
    parent,
    flow_id,
    vehicle_type,
    route,
    begin,
    end,
    vehicles_per_hour,
):
    ET.SubElement(
        parent,
        "flow",
        {
            "id": flow_id,
            "type": vehicle_type,
            "route": route,
            "begin": str(begin),
            "end": str(end),
            "vehsPerHour": str(vehicles_per_hour),
            "departLane": "best",
            "departSpeed": "max",
            "departPos": "base",
        },
    )


def main():

    print("=" * 80)
    print("SILK BOARD J2 - CORRECTED DEMAND GENERATOR")
    print("=" * 80)

    root = ET.Element(
        "routes",
        {
            "xmlns:xsi":
                "http://www.w3.org/2001/XMLSchema-instance",
            "xsi:noNamespaceSchemaLocation":
                "http://sumo.dlr.de/xsd/routes_file.xsd",
        },
    )

    # ========================================================
    # ROUTES
    # ========================================================

    # -------------------------------
    # Corridor J1 -> J2 -> J3
    # -------------------------------

    add_route(
        root,
        "corridor_j1_j2_j3",
        [CORRIDOR_ENTRY, HOSUR_A, HOSUR_OUT_A, CORRIDOR_EXIT],
    )

    # -------------------------------
    # Hosur -> Hosur
    # -------------------------------

    add_route(
        root,
        "hosur_a_to_hosur_a",
        [HOSUR_A, HOSUR_OUT_A],
    )

    add_route(
        root,
        "hosur_a_to_hosur_b",
        [HOSUR_A, HOSUR_OUT_B],
    )

    add_route(
        root,
        "hosur_a_to_madiwala",
        [HOSUR_A, MADIWALA_OUT],
    )

    add_route(
        root,
        "hosur_b_to_hosur_a",
        [HOSUR_B, HOSUR_OUT_A],
    )

    add_route(
        root,
        "hosur_b_to_hosur_b",
        [HOSUR_B, HOSUR_OUT_B],
    )

    add_route(
        root,
        "hosur_b_to_madiwala",
        [HOSUR_B, MADIWALA_OUT],
    )

    # -------------------------------
    # Madiwala -> ...
    # -------------------------------

    add_route(
        root,
        "madiwala_to_hosur_a",
        [MADIWALA, HOSUR_OUT_A],
    )

    add_route(
        root,
        "madiwala_to_hosur_b",
        [MADIWALA, HOSUR_OUT_B],
    )

    add_route(
        root,
        "madiwala_to_madiwala",
        [MADIWALA, MADIWALA_OUT],
    )

    # ========================================================
    # NORMAL PERIOD (0-120s)
    # ========================================================

    add_flow(
        root,
        "hosur_motorcycles_normal",
        "motorcycle",
        "hosur_a_to_hosur_a",
        0,
        120,
        400,
    )

    add_flow(
        root,
        "hosur_cars_normal",
        "car",
        "hosur_a_to_hosur_b",
        0,
        120,
        150,
    )

    add_flow(
        root,
        "hosur_buses_normal",
        "bmtc_bus",
        "hosur_a_to_madiwala",
        0,
        120,
        40,
    )

    add_flow(
        root,
        "madiwala_motorcycles_normal",
        "motorcycle",
        "madiwala_to_hosur_a",
        0,
        120,
        400,
    )

    add_flow(
        root,
        "madiwala_cars_normal",
        "car",
        "madiwala_to_hosur_b",
        0,
        120,
        150,
    )

    add_flow(
        root,
        "madiwala_buses_normal",
        "bmtc_bus",
        "madiwala_to_madiwala",
        0,
        120,
        40,
    )

    add_flow(
        root,
        "corridor_motorcycles_normal",
        "motorcycle",
        "corridor_j1_j2_j3",
        0,
        120,
        350,
    )

    add_flow(
        root,
        "corridor_cars_normal",
        "car",
        "corridor_j1_j2_j3",
        0,
        120,
        150,
    )

    # ========================================================
    # FIRST PEAK (120-240s)
    # ========================================================

    add_flow(
        root,
        "hosur_motorcycles_peak",
        "motorcycle",
        "hosur_a_to_hosur_b",
        120,
        240,
        650,
    )

    add_flow(
        root,
        "hosur_cars_peak",
        "car",
        "hosur_b_to_hosur_a",
        120,
        240,
        250,
    )

    add_flow(
        root,
        "madiwala_motorcycles_peak",
        "motorcycle",
        "madiwala_to_hosur_a",
        120,
        240,
        650,
    )

    add_flow(
        root,
        "madiwala_cars_peak",
        "car",
        "madiwala_to_hosur_b",
        120,
        240,
        250,
    )

    add_flow(
        root,
        "corridor_motorcycles_peak",
        "motorcycle",
        "corridor_j1_j2_j3",
        120,
        240,
        500,
    )

    add_flow(
        root,
        "corridor_cars_peak",
        "car",
        "corridor_j1_j2_j3",
        120,
        240,
        200,
    )

    add_flow(
        root,
        "corridor_buses_peak",
        "bmtc_bus",
        "corridor_j1_j2_j3",
        120,
        280,
        40,
    )

    # ========================================================
    # BMTC BUS CLUSTER (200-280s)
    # ========================================================

    add_flow(
        root,
        "bmtc_hosur_cluster",
        "bmtc_bus",
        "hosur_a_to_madiwala",
        200,
        280,
        120,
    )

    add_flow(
        root,
        "bmtc_madiwala_cluster",
        "bmtc_bus",
        "madiwala_to_madiwala",
        200,
        280,
        120,
    )

    # ========================================================
    # HEAVY PEAK (240-400s)
    # ========================================================

    add_flow(
        root,
        "hosur_motorcycles_heavy_peak",
        "motorcycle",
        "hosur_b_to_madiwala",
        240,
        400,
        800,
    )

    add_flow(
        root,
        "hosur_cars_heavy_peak",
        "car",
        "hosur_a_to_hosur_b",
        240,
        400,
        300,
    )

    add_flow(
        root,
        "madiwala_motorcycles_heavy_peak",
        "motorcycle",
        "madiwala_to_hosur_a",
        240,
        400,
        800,
    )

    add_flow(
        root,
        "madiwala_cars_heavy_peak",
        "car",
        "madiwala_to_hosur_b",
        240,
        400,
        300,
    )

    add_flow(
        root,
        "heavy_vehicles",
        "heavy_vehicle",
        "hosur_a_to_madiwala",
        240,
        400,
        50,
    )

    add_flow(
        root,
        "corridor_motorcycles_heavy",
        "motorcycle",
        "corridor_j1_j2_j3",
        240,
        400,
        600,
    )

    add_flow(
        root,
        "corridor_cars_heavy",
        "car",
        "corridor_j1_j2_j3",
        240,
        400,
        250,
    )

    add_flow(
        root,
        "corridor_trucks_heavy",
        "heavy_vehicle",
        "corridor_j1_j2_j3",
        240,
        400,
        30,
    )

    # ========================================================
    # RECOVERY (400-600s)
    # ========================================================

    add_flow(
        root,
        "hosur_motorcycles_recovery",
        "motorcycle",
        "hosur_a_to_hosur_a",
        400,
        600,
        350,
    )

    add_flow(
        root,
        "hosur_cars_recovery",
        "car",
        "hosur_a_to_hosur_b",
        400,
        600,
        130,
    )

    add_flow(
        root,
        "madiwala_motorcycles_recovery",
        "motorcycle",
        "madiwala_to_hosur_a",
        400,
        600,
        350,
    )

    add_flow(
        root,
        "madiwala_cars_recovery",
        "car",
        "madiwala_to_hosur_b",
        400,
        600,
        130,
    )

    add_flow(
        root,
        "corridor_motorcycles_recovery",
        "motorcycle",
        "corridor_j1_j2_j3",
        400,
        600,
        300,
    )

    add_flow(
        root,
        "corridor_cars_recovery",
        "car",
        "corridor_j1_j2_j3",
        400,
        600,
        120,
    )

    # ========================================================
    # EMERGENCY VEHICLE (J1 -> J2 -> J3) (depart=420)
    # ========================================================

    ET.SubElement(
        root,
        "vehicle",
        {
            "id": "ambulance_0",
            "type": "ambulance",
            "route": "corridor_j1_j2_j3",
            "depart": "420",
            "departLane": "best",
            "departSpeed": "max",
        },
    )

    # ========================================================
    # WRITE XML
    # ========================================================

    tree = ET.ElementTree(root)

    ET.indent(
        tree,
        space="    ",
    )

    tree.write(
        OUTPUT_FILE,
        encoding="utf-8",
        xml_declaration=True,
    )

    print()
    print(f"Network : {NETWORK_FILE}")
    print(f"Output  : {OUTPUT_FILE}")

    print()
    print("Routes generated: 9")
    print("Traffic sources:")
    print("  Hosur Road")
    print("  Madiwala / Sarjapura Road")

    print()
    print("Demand generation complete.")


if __name__ == "__main__":
    main()
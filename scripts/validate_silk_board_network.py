"""
scripts/validate_silk_board_network.py

The M1 acceptance-criteria checker. Runs every check independently, prints
a clear PASS/FAIL per item, and exits nonzero if anything failed. Never
reports success on a check it did not actually run.

Checks (mirrors architecture.md Sec 15 / the parent spec's M1 acceptance
criteria):
  1. SUMO installation (sumo, sumo-gui, netconvert, duarouter present & runnable)
  2. SUMO_HOME and tools/ resolvable
  3. OSM source file exists and is non-trivial
  4. Generated .net.xml exists and is non-trivial
  5. Junction mapping file exists AND is confirmed=true (human-verified)
  6. J1, J2, J3 junction IDs from the mapping actually exist in the network
  7. J2 has real traffic-light logic (tlLogic) defined
  8. J1 and J3 are each directly, correctly connected to J2 (direction-checked)
  9. Network has no fully disconnected components larger than 1 node
  10. Demand/route file exists and contains at least one valid <route>
  11. A real headless SUMO run of silk_board.sumocfg completes without
      erroring and inserts at least one vehicle

Usage:
    python scripts/validate_silk_board_network.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.sumo_env import SumoEnvironmentError, require_sumo_env, silk_board_dir  # noqa: E402


class CheckResult:
    def __init__(self, name: str):
        self.name = name
        self.passed = False
        self.detail = ""

    def ok(self, detail: str = ""):
        self.passed = True
        self.detail = detail
        return self

    def fail(self, detail: str):
        self.passed = False
        self.detail = detail
        return self

    def __str__(self):
        status = "PASS" if self.passed else "FAIL"
        return f"[{status}] {self.name}" + (f" — {self.detail}" if self.detail else "")


def check_sumo_installation(results: list[CheckResult]):
    r = CheckResult("SUMO installation (sumo, sumo-gui, netconvert, duarouter)")
    try:
        env = require_sumo_env()
        duarouter = env.sumo_binary.parent / ("duarouter.exe" if env.sumo_binary.suffix else "duarouter")
        if not duarouter.is_file():
            results.append(r.fail(f"duarouter not found at {duarouter}"))
            return None
        results.append(r.ok(f"{env.version_string}; SUMO_HOME={env.sumo_home}"))
        return env
    except SumoEnvironmentError as exc:
        results.append(r.fail(str(exc)))
        return None


def check_osm_source(results: list[CheckResult], osm_dir: Path):
    r = CheckResult("OSM source file present and non-trivial")
    osm_files = list(osm_dir.glob("*.osm.xml")) if osm_dir.is_dir() else []
    if not osm_files:
        results.append(r.fail(f"No .osm.xml file found in {osm_dir}. Run download_silk_board_osm.py."))
        return
    largest = max(osm_files, key=lambda p: p.stat().st_size)
    size_kb = largest.stat().st_size / 1024
    if size_kb < 1:
        results.append(r.fail(f"{largest} is only {size_kb:.2f} KB — likely an empty/failed download."))
        return
    results.append(r.ok(f"{largest.name} ({size_kb:.1f} KB)"))


def check_net_file(results: list[CheckResult], net_file: Path, sumolib):
    r = CheckResult(".net.xml generated and non-trivial")
    if not net_file.is_file():
        results.append(r.fail(f"{net_file} does not exist. Run build_silk_board_network.py."))
        return None
    size_kb = net_file.stat().st_size / 1024
    if size_kb < 0.5:
        results.append(r.fail(f"{net_file} is only {size_kb:.2f} KB — suspiciously small."))
        return None
    try:
        net = sumolib.net.readNet(str(net_file))
    except Exception as exc:  # noqa: BLE001
        results.append(r.fail(f"sumolib could not parse {net_file}: {exc}"))
        return None
    n_nodes, n_edges = len(net.getNodes()), len(net.getEdges())
    if n_nodes < 3 or n_edges < 2:
        results.append(r.fail(f"Network too small to be a real corridor: {n_nodes} nodes, {n_edges} edges."))
        return None
    results.append(r.ok(f"{net_file.name} ({size_kb:.1f} KB, {n_nodes} nodes, {n_edges} edges)"))
    return net


def check_mapping_confirmed(results: list[CheckResult], mapping_file: Path):
    r = CheckResult("junction_mapping.json exists and is human-confirmed")
    if not mapping_file.is_file():
        results.append(r.fail(f"{mapping_file} not found. Run identify_junctions.py."))
        return None
    mapping = json.loads(mapping_file.read_text())
    if not mapping.get("confirmed", False):
        results.append(r.fail(
            "confirmed=false. This means nobody has visually verified that the "
            "suggested J1/J2/J3 actually correspond to the real Silk Board "
            "corridor. Open sumo-gui, check visually, then run "
            "'identify_junctions.py --confirm'. This check intentionally "
            "cannot be satisfied automatically."
        ))
        return None
    for key in ("J1", "J2", "J3"):
        if key not in mapping:
            results.append(r.fail(f"Mapping is confirmed but missing key '{key}'."))
            return None
    results.append(r.ok(
        f"J1={mapping['J1']['junction_id']} J2={mapping['J2']['junction_id']} "
        f"J3={mapping['J3']['junction_id']}"
    ))
    return mapping


def check_junctions_exist(results: list[CheckResult], net, mapping: dict):
    r = CheckResult("J1/J2/J3 junction IDs exist in the network")
    if net is None or mapping is None:
        results.append(r.fail("Skipped — prerequisite check(s) failed."))
        return
    node_ids = {n.getID() for n in net.getNodes()}
    missing = [
        key for key in ("J1", "J2", "J3")
        if mapping[key]["junction_id"] not in node_ids
    ]
    if missing:
        results.append(r.fail(f"Junction IDs not found in network for: {missing}"))
        return
    results.append(r.ok("All three present"))


def check_j2_traffic_light(results: list[CheckResult], net, mapping: dict):
    r = CheckResult("J2 has real traffic-light logic")
    if net is None or mapping is None:
        results.append(r.fail("Skipped — prerequisite check(s) failed."))
        return
    j2_id = mapping["J2"]["junction_id"]
    node = net.getNode(j2_id) if j2_id in {n.getID() for n in net.getNodes()} else None
    if node is None:
        results.append(r.fail(f"J2 node {j2_id} not found."))
        return
    if node.getType() not in ("traffic_light", "traffic_light_right_on_red"):
        results.append(r.fail(f"J2 ({j2_id}) node type is '{node.getType()}', not a traffic light."))
        return
    tls_list = net.getTrafficLights()
    tls_ids = {t.getID() for t in tls_list}
    if j2_id not in tls_ids and not any(j2_id in t.getID() for t in tls_list):
        results.append(r.fail(f"No tlLogic program found controlling J2 ({j2_id})."))
        return
    results.append(r.ok(f"J2 ({j2_id}) is a signalized junction with tlLogic"))


def check_corridor_connectivity(results: list[CheckResult], net, mapping: dict):
    r = CheckResult("J1 -> J2 and J2 -> J3 directly connected (direction-checked)")
    if net is None or mapping is None:
        results.append(r.fail("Skipped — prerequisite check(s) failed."))
        return
    j1_id, j2_id, j3_id = (mapping[k]["junction_id"] for k in ("J1", "J2", "J3"))

    def directed_edge_exists(a, b):
        for edge in net.getEdges():
            if edge.getFromNode().getID() == a and edge.getToNode().getID() == b:
                return True
        return False

    j1_to_j2 = directed_edge_exists(j1_id, j2_id)
    j2_to_j3 = directed_edge_exists(j2_id, j3_id)
    if not (j1_to_j2 and j2_to_j3):
        missing = []
        if not j1_to_j2:
            missing.append(f"J1({j1_id})->J2({j2_id})")
        if not j2_to_j3:
            missing.append(f"J2({j2_id})->J3({j3_id})")
        results.append(r.fail(f"Missing directed edge(s): {', '.join(missing)}"))
        return
    results.append(r.ok("Both directed edges present"))


def check_no_disconnected_islands(results: list[CheckResult], net):
    r = CheckResult("No disconnected network islands")
    if net is None:
        results.append(r.fail("Skipped — prerequisite check(s) failed."))
        return
    nodes = net.getNodes()
    if not nodes:
        results.append(r.fail("No nodes in network."))
        return
    adjacency: dict[str, set[str]] = {n.getID(): set() for n in nodes}
    for edge in net.getEdges():
        a, b = edge.getFromNode().getID(), edge.getToNode().getID()
        adjacency[a].add(b)
        adjacency[b].add(a)

    visited = set()
    stack = [nodes[0].getID()]
    while stack:
        current = stack.pop()
        if current in visited:
            continue
        visited.add(current)
        stack.extend(adjacency[current] - visited)

    if len(visited) < len(nodes):
        unreached = len(nodes) - len(visited)
        results.append(r.fail(f"{unreached} of {len(nodes)} junctions are unreachable from the rest of the network."))
        return
    results.append(r.ok(f"All {len(nodes)} junctions form one connected component"))


def check_route_file(results: list[CheckResult], routes_file: Path):
    r = CheckResult("Demand/route file exists with at least one valid <route>")
    if not routes_file.is_file():
        results.append(r.fail(f"{routes_file} not found. Run generate_demand.py."))
        return
    content = routes_file.read_text()
    if "<route" not in content:
        results.append(r.fail(f"{routes_file} exists but contains no <route> element."))
        return
    results.append(r.ok(f"{routes_file.name} contains computed route(s)"))


def check_real_simulation_run(results: list[CheckResult], sumocfg: Path, env):
    r = CheckResult("Headless SUMO run of silk_board.sumocfg completes and inserts vehicles")
    if env is None:
        results.append(r.fail("Skipped — SUMO installation check failed."))
        return
    if not sumocfg.is_file():
        results.append(r.fail(f"{sumocfg} not found."))
        return
    cmd = [str(env.sumo_binary), "-c", str(sumocfg)]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(sumocfg.parent), timeout=120)
    output = result.stdout + result.stderr
    if result.returncode != 0:
        results.append(r.fail(f"sumo exited with code {result.returncode}. Output:\n{output[-1500:]}"))
        return
    if "Inserted: 0" in output:
        results.append(r.fail("Simulation ran but inserted 0 vehicles — demand did not reach the network."))
        return
    if "Inserted:" not in output:
        results.append(r.fail(f"Could not confirm vehicle insertion from sumo output:\n{output[-1500:]}"))
        return
    inserted_line = next((line for line in output.splitlines() if "Inserted:" in line), "")
    results.append(r.ok(inserted_line.strip()))


def main() -> None:
    base = silk_board_dir()
    results: list[CheckResult] = []

    env = check_sumo_installation(results)

    sumolib = None
    if env is not None:
        try:
            import sumolib as _sumolib  # noqa: PLC0415
            sumolib = _sumolib
        except ImportError:
            results.append(CheckResult("sumolib importable").fail("Could not import sumolib even though SUMO_HOME resolved."))

    check_osm_source(results, base / "osm")

    net = None
    if sumolib is not None:
        net = check_net_file(results, base / "network" / "silk_board.net.xml", sumolib)
    else:
        results.append(CheckResult(".net.xml generated and non-trivial").fail("Skipped — sumolib unavailable."))

    mapping = check_mapping_confirmed(results, base / "junction_mapping.json")

    check_junctions_exist(results, net, mapping)
    check_j2_traffic_light(results, net, mapping)
    check_corridor_connectivity(results, net, mapping)
    check_no_disconnected_islands(results, net)
    check_route_file(results, base / "demand" / "silk_board.rou.xml")
    check_real_simulation_run(results, base / "silk_board.sumocfg", env)

    print("\n" + "=" * 70)
    print("MILESTONE 1 VALIDATION RESULTS")
    print("=" * 70)
    for res in results:
        print(res)
    print("=" * 70)

    n_passed = sum(1 for res in results if res.passed)
    n_total = len(results)
    print(f"{n_passed}/{n_total} checks passed")

    if n_passed < n_total:
        print(
            "\nMILESTONE 1 IS NOT COMPLETE. Do not proceed to Milestone 2 "
            "(TraCI integration) until every check above passes."
        )
        sys.exit(1)

    print("\nAll M1 checks passed. Manually confirm visually with:")
    print(f"  sumo-gui -c {base / 'silk_board.sumocfg'}")


if __name__ == "__main__":
    main()

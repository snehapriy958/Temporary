"""
scripts/build_silk_board_network.py

Converts an OSM XML file (from download_silk_board_osm.py, or a manually
supplied fixture) into a SUMO .net.xml network using netconvert.

Design choices, and why:
  --geometry.remove          collapse redundant intermediate shape nodes
                              netconvert would otherwise treat as junctions
  --roundabouts.guess         Silk Board itself is a signalized roundabout-
                              like junction in reality; guessing roundabout
                              structure from OSM geometry is safer than
                              assuming a simple 4-way cross
  --ramps.guess                Hosur Road / ORR has ramp-like segments;
                              avoids misclassifying them as regular streets
  --tls.guess-signals          use OSM's highway=traffic_signals tags to
                              seed SUMO traffic-light logic at those nodes
  --tls.discard-simple          avoid generating trivial/degenerate TL
                              programs at 2-way non-junctions
  --tls.join                    merge traffic lights that OSM represents as
                              multiple close-together nodes into one logical
                              signal — relevant for a signalized junction as
                              complex as Silk Board
  --junctions.join               merge OSM's often-duplicated junction nodes
                              (common at big real-world intersections) into
                              a single SUMO junction, which is what makes a
                              single addressable "J2" possible at all
  --keep-edges.by-vclass       restrict to vehicle classes actually modeled
      passenger,bus,motorcycle (Section 6 of the parent spec: motorcycle,
                              car, bus, heavy_vehicle, ambulance)

  --output.street-names        WITHOUT this flag netconvert silently drops
                              OSM "name" tags entirely — verified against a
                              test fixture while building this script; the
                              assumption that names survive by default was
                              wrong and is corrected here (Sec 7 of
                              architecture.md requires preserved road names).

This script does not decide which junction is "J2" — that is a research
label, not something netconvert or OSM knows. See identify_junctions.py.

Usage:
    python scripts/build_silk_board_network.py
    python scripts/build_silk_board_network.py --osm-file path/to/file.osm.xml
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.sumo_env import SumoEnvironmentError, require_sumo_env, silk_board_dir  # noqa: E402

DEFAULT_PREFIX = "silk_board"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--osm-file",
        default=None,
        help="Path to the input .osm.xml file. Defaults to "
        f"sumo/silk_board/osm/{DEFAULT_PREFIX}_bbox.osm.xml (the output of "
        "download_silk_board_osm.py).",
    )
    parser.add_argument(
        "--output-file",
        default=None,
        help="Path to write the .net.xml to. Defaults to "
        f"sumo/silk_board/network/{DEFAULT_PREFIX}.net.xml",
    )
    return parser.parse_args()


def build_network(osm_file: Path, output_file: Path) -> Path:
    env = require_sumo_env()

    if not osm_file.is_file():
        raise FileNotFoundError(
            f"OSM input file not found: {osm_file}\n"
            "Run scripts/download_silk_board_osm.py first, or pass --osm-file "
            "explicitly."
        )

    output_file.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(env.netconvert_binary),
        "--osm-files", str(osm_file),
        "--output-file", str(output_file),
        "--geometry.remove",
        "--roundabouts.guess",
        "--ramps.guess",
        "--junctions.join",
        "--tls.guess-signals",
        "--tls.discard-simple",
        "--tls.join",
        "--tls.set", "1617743335,6970466614",
        "--keep-edges.by-vclass", "passenger,bus,motorcycle",
        "--keep-edges.components", "1",
        "--no-turnarounds", "false",
        "--output.street-names",
        "--output.original-names",
    ]
    print("Running:", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)

    # netconvert reports statistics and non-fatal warnings on stderr even on
    # success — always print them so junction/edge merges are visible, not
    # hidden behind a silent success message.
    if result.stdout.strip():
        print(result.stdout)
    if result.stderr.strip():
        print(result.stderr, file=sys.stderr)

    if result.returncode != 0:
        raise RuntimeError(
            f"netconvert failed with exit code {result.returncode}. See output above."
        )

    if not output_file.is_file():
        raise RuntimeError(
            f"netconvert exited 0 but {output_file} was not created. This should "
            "not happen — treat it as a netconvert bug or a disk/permissions issue."
        )

    size_kb = output_file.stat().st_size / 1024
    if size_kb < 0.5:
        raise RuntimeError(
            f"Generated network {output_file} is suspiciously small "
            f"({size_kb:.2f} KB) — the OSM input likely contained no usable "
            "road data for the configured vclasses."
        )

    print(f"Network written: {output_file} ({size_kb:.1f} KB)")
    return output_file


def main() -> None:
    args = parse_args()
    osm_file = Path(args.osm_file) if args.osm_file else silk_board_dir() / "osm" / f"{DEFAULT_PREFIX}_bbox.osm.xml"
    output_file = Path(args.output_file) if args.output_file else silk_board_dir() / "network" / f"{DEFAULT_PREFIX}.net.xml"

    try:
        build_network(osm_file, output_file)
    except (SumoEnvironmentError, FileNotFoundError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

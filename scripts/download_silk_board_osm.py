"""
scripts/download_silk_board_osm.py

Downloads real OpenStreetMap data for a configurable bounding box around
Bengaluru's Silk Board Junction, using SUMO's own osmGet.py (which queries
the Overpass API).

This script does not fabricate, cache-fake, or synthesize any road data.
If the network request fails, it fails loudly rather than falling back
to placeholder geometry.

Default bounding box:
    Centered on Silk Board Junction (12.9172 N, 77.6228 E), Bengaluru,
    extended along Hosur Road and Outer Ring Road far enough to capture
    one upstream and one downstream junction (the intended J1/J3), while
    staying small enough that PPO training episodes stay fast (Sec 2/4
    of architecture.md).

    west, south, east, north = 77.6140, 12.9090, 77.6320, 12.9250

    This box is a starting point, not a claimed-precise research
    boundary. Widen it with --bbox if J1/J3 fall outside it once you
    inspect the network in sumo-gui.

Usage:
    python scripts/download_silk_board_osm.py
    python scripts/download_silk_board_osm.py --bbox 77.614,12.909,77.632,12.925
    python scripts/download_silk_board_osm.py --output-dir sumo/silk_board/osm --prefix silk_board
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.sumo_env import (  # noqa: E402
    SumoEnvironmentError,
    require_sumo_env,
    silk_board_dir,
)

DEFAULT_BBOX = "77.6140,12.9090,77.6320,12.9250"  # west,south,east,north
DEFAULT_PREFIX = "silk_board"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--bbox",
        default=DEFAULT_BBOX,
        help="west,south,east,north in geographic (lon/lat) coordinates. "
        f"Default: {DEFAULT_BBOX} (Silk Board Junction area, Bengaluru).",
    )
    parser.add_argument(
        "--output-dir",
        default=str(silk_board_dir() / "osm"),
        help="Directory to write the downloaded .osm.xml file to.",
    )
    parser.add_argument(
        "--prefix",
        default=DEFAULT_PREFIX,
        help="Filename prefix for the downloaded OSM file.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download even if the target file already exists.",
    )
    return parser.parse_args()


def validate_bbox(bbox: str) -> tuple[float, float, float, float]:
    parts = bbox.split(",")
    if len(parts) != 4:
        raise ValueError(f"--bbox must be 'west,south,east,north', got: {bbox!r}")
    west, south, east, north = (float(p) for p in parts)
    if not (west < east and south < north):
        raise ValueError(
            f"--bbox is not a valid box (need west<east and south<north): {bbox!r}"
        )
    span_lon = east - west
    span_lat = north - south
    if span_lon > 0.5 or span_lat > 0.5:
        raise ValueError(
            f"--bbox spans {span_lon:.3f} deg lon x {span_lat:.3f} deg lat, which is "
            "far larger than a single-junction corridor needs and will make PPO "
            "training slow (architecture.md Sec 4). Pass a smaller box, or confirm "
            "this is intentional by editing this check."
        )
    return west, south, east, north


def download(bbox: str, output_dir: Path, prefix: str, force: bool) -> Path:
    env = require_sumo_env()
    osm_get_script = env.tools_dir / "osmGet.py"
    if not osm_get_script.is_file():
        raise SumoEnvironmentError(
            f"osmGet.py not found at {osm_get_script}. Your SUMO install may be "
            "missing the tools/ scripts — reinstall SUMO with the full component set."
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    expected_output = output_dir / f"{prefix}_bbox.osm.xml"

    if expected_output.exists() and not force:
        print(f"OSM file already exists at {expected_output} (use --force to re-download).")
        return expected_output

    cmd = [
        sys.executable,
        str(osm_get_script),
        "--bbox", bbox,
        "--prefix", prefix,
        "--output-dir", str(output_dir),
    ]
    print("Running:", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(
            "osmGet.py failed. This is most likely a network issue (no access to "
            "overpass-api.de) or an invalid bounding box.\n"
            f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
        )

    if not expected_output.exists():
        # osmGet.py can exit 0 even when it failed internally (e.g. a network/SSL
        # error printed to stdout without a nonzero exit code) — so a clean return
        # code alone does not mean the download worked. List what actually landed
        # and surface osmGet.py's own stdout so the real cause isn't hidden.
        produced = sorted(p.name for p in output_dir.glob(f"{prefix}*"))
        raise RuntimeError(
            f"osmGet.py exited with code 0 but expected output {expected_output.name} "
            f"was not found in {output_dir}. Files actually present: {produced}\n"
            f"osmGet.py output was:\n{result.stdout}{result.stderr}"
        )

    size_kb = expected_output.stat().st_size / 1024
    if size_kb < 1:
        raise RuntimeError(
            f"Downloaded OSM file {expected_output} is suspiciously small "
            f"({size_kb:.2f} KB) — likely an empty or error response, not real data. "
            f"stdout was:\n{result.stdout}"
        )

    print(f"Downloaded OSM data: {expected_output} ({size_kb:.1f} KB)")
    return expected_output


def main() -> None:
    args = parse_args()
    try:
        bbox = validate_bbox(args.bbox)
        print(f"Bounding box (west,south,east,north): {bbox}")
        download(args.bbox, Path(args.output_dir), args.prefix, args.force)
    except (SumoEnvironmentError, ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

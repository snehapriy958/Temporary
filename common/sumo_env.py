"""
common/sumo_env.py

Environment and toolpath resolution for Eclipse SUMO.
Discovers SUMO_HOME, sumo/sumo-gui binaries, tools/ directory, and handles
cross-platform path lookups.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


class SumoEnvironmentError(RuntimeError):
    """Raised when SUMO or required tools cannot be located."""
    pass


@dataclass
class SumoEnvironment:
    """Holds discovered SUMO paths and metadata."""
    sumo_home: Path
    tools_dir: Path
    sumo_binary: Path
    sumo_gui_binary: Path
    version_string: str


def get_project_root() -> Path:
    """Returns absolute path to the repository root directory."""
    return Path(__file__).resolve().parent.parent


def silk_board_dir() -> Path:
    """Returns absolute path to sumo/silk_board directory."""
    return get_project_root() / "sumo" / "silk_board"


def _candidate_sumo_homes() -> list[Path]:
    candidates: list[Path] = []
    
    # 1. Environment variable SUMO_HOME
    if "SUMO_HOME" in os.environ and os.environ["SUMO_HOME"].strip():
        candidates.append(Path(os.environ["SUMO_HOME"].strip()))

    # 2. Derive from sumo executable if in PATH
    sumo_which = shutil.which("sumo")
    if sumo_which:
        p = Path(sumo_which).resolve()
        # Usually located in <SUMO_HOME>/bin/sumo[.exe]
        if p.parent.name.lower() == "bin":
            candidates.append(p.parent.parent)

    # 3. Standard Windows locations
    win_paths = [
        Path(r"C:\Program Files (x86)\Eclipse\Sumo"),
        Path(r"C:\Program Files\Eclipse\Sumo"),
        Path(r"C:\Eclipse\Sumo"),
    ]
    candidates.extend(win_paths)

    # 4. Standard Linux / macOS locations
    unix_paths = [
        Path("/usr/share/sumo"),
        Path("/usr/local/share/sumo"),
        Path("/opt/homebrew/opt/sumo/share/sumo"),
    ]
    candidates.extend(unix_paths)

    # Deduplicate preserving order
    seen = set()
    deduped = []
    for c in candidates:
        resolved = c.resolve()
        if resolved not in seen:
            seen.add(resolved)
            deduped.append(resolved)
    return deduped


def require_sumo_env() -> SumoEnvironment:
    """
    Validates and resolves the SUMO environment.
    Ensures SUMO_HOME is set and tools/ is added to sys.path.
    Raises SumoEnvironmentError if SUMO is missing or invalid.
    """
    valid_home: Optional[Path] = None

    for candidate in _candidate_sumo_homes():
        if candidate.is_dir():
            # Check for bin/sumo or bin/sumo.exe
            sumo_bin = candidate / "bin" / ("sumo.exe" if sys.platform == "win32" else "sumo")
            if sumo_bin.is_file():
                valid_home = candidate
                break

    if not valid_home:
        raise SumoEnvironmentError(
            "SUMO installation could not be found. Please install SUMO and ensure SUMO_HOME "
            "is set or 'sumo' is on PATH."
        )

    sumo_ext = ".exe" if sys.platform == "win32" else ""
    sumo_bin = valid_home / "bin" / f"sumo{sumo_ext}"
    sumo_gui_bin = valid_home / "bin" / f"sumo-gui{sumo_ext}"
    tools_dir = valid_home / "tools"

    if not sumo_bin.is_file():
        raise SumoEnvironmentError(f"SUMO binary not found at {sumo_bin}")

    # Set SUMO_HOME environment variable
    os.environ["SUMO_HOME"] = str(valid_home)

    # Ensure tools/ directory is in sys.path for sumolib and traci
    if tools_dir.is_dir() and str(tools_dir) not in sys.path:
        sys.path.insert(0, str(tools_dir))

    # Determine version string
    version_str = "SUMO"
    try:
        proc = subprocess.run(
            [str(sumo_bin), "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        first_line = proc.stdout.splitlines()[0] if proc.stdout else ""
        if first_line:
            version_str = first_line.strip()
    except Exception:
        pass

    return SumoEnvironment(
        sumo_home=valid_home,
        tools_dir=tools_dir,
        sumo_binary=sumo_bin,
        sumo_gui_binary=sumo_gui_bin,
        version_string=version_str,
    )

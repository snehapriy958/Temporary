"""
backend/config.py

Configuration settings loaded from environment variables and defaults.
"""

from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file if present
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# Server
HOST: str = os.getenv("HOST", "127.0.0.1")
PORT: int = int(os.getenv("PORT", "8000"))
DEBUG: bool = os.getenv("DEBUG", "false").lower() in ("true", "1", "yes")

# Database
DATABASE_URL: str = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'traffic_dashboard.db'}")

# SUMO
SUMO_CONFIG_PATH: Path = BASE_DIR / os.getenv("SUMO_CONFIG_PATH", "sumo/silk_board/silk_board.sumocfg")
SUMO_GUI: bool = os.getenv("SUMO_GUI", "false").lower() in ("true", "1", "yes")
SUMO_STEP_LENGTH: float = float(os.getenv("SUMO_STEP_LENGTH", "1.0"))

# CORS
cors_raw = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000")
CORS_ORIGINS: list[str] = [origin.strip() for origin in cors_raw.split(",") if origin.strip()]

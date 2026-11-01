"""
backend/routers/health.py

Health check and environment status endpoint.
"""

from __future__ import annotations

from fastapi import APIRouter
from backend.schemas import HealthResponse
from backend.simulation_service import sim_service
from common.sumo_env import require_sumo_env, SumoEnvironmentError

router = APIRouter(prefix="/api", tags=["Health"])


@router.get("/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    """Returns backend system status, SUMO binary availability, and simulation state."""
    sumo_ok = False
    version_str = "Unavailable"
    try:
        env = require_sumo_env()
        sumo_ok = True
        version_str = env.version_string
    except SumoEnvironmentError as e:
        version_str = str(e)

    status_obj = sim_service.get_status()

    return HealthResponse(
        status="ok",
        sumo_available=sumo_ok,
        sumo_version=version_str,
        active_simulation=status_obj.running,
        message="Backend and coordination service active.",
    )

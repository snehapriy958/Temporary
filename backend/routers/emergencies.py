"""
backend/routers/emergencies.py

Emergency vehicle detection, green wave preemption, and traversal events.
"""

from __future__ import annotations

from fastapi import APIRouter
from backend.schemas import EmergencyResponse
from backend.simulation_service import sim_service

router = APIRouter(prefix="/api/emergencies", tags=["Emergencies"])


@router.get("", response_model=EmergencyResponse)
def get_emergencies() -> EmergencyResponse:
    """Returns active emergency vehicle detections, preemption wave status, and historical clearance times."""
    data = sim_service.get_emergencies()
    return EmergencyResponse(**data)

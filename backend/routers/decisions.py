"""
backend/routers/decisions.py

Recent adaptive signal controller and emergency decisions with timestamps and rationales.
"""

from __future__ import annotations

from fastapi import APIRouter
from backend.schemas import DecisionsResponse
from backend.simulation_service import sim_service

router = APIRouter(prefix="/api/decisions", tags=["Decisions"])


@router.get("", response_model=DecisionsResponse)
def get_decisions() -> DecisionsResponse:
    """Returns chronological log of traffic controller decisions and operator actions."""
    items = sim_service.get_decisions()
    return DecisionsResponse(
        total_decisions=len(items),
        decisions=items,
    )

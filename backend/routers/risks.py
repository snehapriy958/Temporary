"""
backend/routers/risks.py

Accident blackspots, MoRTH/IRC risk zones, and geographic hotspot clusters.
"""

from __future__ import annotations

from fastapi import APIRouter
from backend.risk_service import get_full_risk_assessment
from backend.schemas import RisksResponse

router = APIRouter(prefix="/api/risks", tags=["Risks"])


@router.get("", response_model=RisksResponse)
def get_risks() -> RisksResponse:
    """Returns verified accident blackspot risk zones, CRI scores, and clustering hotspots."""
    return get_full_risk_assessment()

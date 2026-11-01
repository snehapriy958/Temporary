"""
backend/routers/signals.py

Traffic light phase monitoring and safe manual override controls.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from backend.schemas import SignalOverrideRequest, SignalOverrideResponse, SignalsResponse
from backend.simulation_service import CommandStatus, sim_service

router = APIRouter(prefix="/api/signals", tags=["Signals"])


@router.get("", response_model=SignalsResponse)
def get_signals() -> SignalsResponse:
    """Returns signal phase status, green/yellow states, and timing for J1, J2, and J3."""
    status_obj = sim_service.get_status()
    signals_map = sim_service.get_signals()
    return SignalsResponse(
        simulation_time=status_obj.simulation_time,
        signals=signals_map,
    )


@router.post("/override", response_model=SignalOverrideResponse)
def override_signal(payload: SignalOverrideRequest) -> SignalOverrideResponse:
    """
    Executes an operator manual signal-phase override.
    Requires explicit confirmation flag. Respects safety constraints and emergency locks.
    Dispatches to the thread-safe TraCI command queue.
    """
    if not payload.confirmed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Override rejected: Operator confirmation flag must be explicitly True.",
        )

    res = sim_service.request_manual_override(
        junction_id=payload.junction_id,
        target_phase=payload.target_phase,
        confirmed=payload.confirmed,
    )

    if not res.success:
        if res.status in {CommandStatus.TIMED_OUT, CommandStatus.EXECUTION_OUTCOME_UNKNOWN}:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail=res.message,
            )
        elif res.status == CommandStatus.CANCELLED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=res.message,
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=res.message,
            )

    return SignalOverrideResponse(
        success=True,
        message=res.message,
        junction_id=res.junction_id or payload.junction_id.upper(),
        applied_phase=res.applied_phase if res.applied_phase is not None else payload.target_phase,
        simulation_time=res.simulation_time,
    )

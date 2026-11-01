"""
backend/routers/simulation.py

Simulation lifecycle controls: status, start, pause, resume, stop, reset.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from backend.schemas import (
    CommandResponse,
    SimulationStartRequest,
    SimulationStatusResponse,
)
from backend.simulation_service import sim_service

router = APIRouter(prefix="/api/simulation", tags=["Simulation"])


@router.get("/status", response_model=SimulationStatusResponse)
def get_simulation_status() -> SimulationStatusResponse:
    """Returns current state of the simulation (running, time, mode, controller)."""
    return sim_service.get_status()


@router.post("/start", response_model=CommandResponse)
def start_simulation(payload: SimulationStartRequest) -> CommandResponse:
    """Starts a new simulation run with validated settings."""
    valid_modes = {"baseline", "coordinated", "marl_ppo", "marl_dqn"}
    if payload.mode.lower() not in valid_modes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid mode '{payload.mode}'. Supported modes: {sorted(list(valid_modes))}.",
        )

    ok, msg = sim_service.start_simulation(
        mode=payload.mode,
        duration=payload.duration,
        seed=payload.seed,
        step_length=payload.step_length,
        decision_interval=payload.decision_interval,
        enable_emergency=payload.enable_emergency,
        gui=payload.gui,
        startup_timeout_s=payload.startup_timeout_s,
    )

    if not ok:
        if "already" in msg.lower():
            status_code = status.HTTP_409_CONFLICT
        elif "timed out" in msg.lower() or "timeout" in msg.lower():
            status_code = status.HTTP_504_GATEWAY_TIMEOUT
        else:
            status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        raise HTTPException(
            status_code=status_code,
            detail=msg,
        )

    return CommandResponse(success=True, message=msg, simulation_time=0.0)


@router.post("/pause", response_model=CommandResponse)
def pause_simulation() -> CommandResponse:
    """Safely pauses an actively stepping simulation."""
    ok, msg = sim_service.pause_simulation()
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=msg,
        )
    return CommandResponse(success=True, message=msg, simulation_time=sim_service._current_sim_time)


@router.post("/resume", response_model=CommandResponse)
def resume_simulation() -> CommandResponse:
    """Resumes a paused simulation."""
    ok, msg = sim_service.resume_simulation()
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=msg,
        )
    return CommandResponse(success=True, message=msg, simulation_time=sim_service._current_sim_time)


@router.post("/stop", response_model=CommandResponse)
def stop_simulation() -> CommandResponse:
    """Safely stops the simulation and cleanly releases SUMO/TraCI resources."""
    ok, msg = sim_service.stop_simulation()
    if not ok:
        status_code = (
            status.HTTP_400_BAD_REQUEST
            if "not currently running" in msg.lower()
            else status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        raise HTTPException(
            status_code=status_code,
            detail=msg,
        )
    return CommandResponse(success=True, message=msg, simulation_time=sim_service._current_sim_time)


@router.post("/reset", response_model=CommandResponse)
def reset_simulation() -> CommandResponse:
    """Resets the simulation to a clean initial state."""
    ok, msg = sim_service.reset_simulation()
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=msg,
        )
    return CommandResponse(success=True, message=msg, simulation_time=0.0)

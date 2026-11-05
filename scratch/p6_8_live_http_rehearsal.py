"""Run the five P6.7 demonstrations through a live Uvicorn HTTP/WebSocket API."""

from __future__ import annotations

import asyncio
import csv
import io
import json
import os
import re
import subprocess
import time
from pathlib import Path

import httpx
import websockets

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "scratch" / "p6_8_live_http_rehearsal_results.json"
BASE = "http://127.0.0.1:8000"
WS_URL = "ws://127.0.0.1:8000/ws/traffic"
JUNCTIONS = ("J1", "J2", "J3")
EXPECTED_ROUTE = ["172853382#2", "172853382#3", "1148717038#0", "40696223#1"]
if OUTPUT.exists():
    raise FileExistsError(f"Refusing to overwrite existing evidence: {OUTPUT}")
if os.environ.get("DATABASE_URL") != "sqlite:///./demo_audit_disposable.db":
    raise RuntimeError("Expected disposable DATABASE_URL")


def process_exists(pid: int | None) -> bool | None:
    if not pid:
        return None
    response = subprocess.run(
        ["tasklist.exe", "/FI", f"PID eq {pid}", "/FO", "CSV"],
        capture_output=True,
        text=True,
        check=False,
    )
    return bool(re.search(rf'"[^"\r\n]+","{pid}"', response.stdout))


async def run_one(client: httpx.AsyncClient, mode: str, duration: int, seed: int, emergency: bool, checkpoint: str | None = None):
    request = {
        "mode": mode,
        "duration": duration,
        "seed": seed,
        "step_length": 1,
        "decision_interval": 5,
        "enable_emergency": emergency,
    }
    if checkpoint:
        request["checkpoint_path"] = checkpoint
    async with websockets.connect(WS_URL, open_timeout=10, close_timeout=3, max_size=2**22) as ws:
        initial = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        started = await client.post(f"{BASE}/api/simulation/start", json=request, timeout=35)
        if started.status_code != 200:
            raise AssertionError(f"{mode} start failed: {started.status_code} {started.text}")
        body = started.json()
        match = re.search(r"UUID: ([^,)]+), PID: (\d+)", body["message"])
        run_id = match.group(1) if match else None
        sumo_pid = int(match.group(2)) if match else None
        phases = {junction: set() for junction in JUNCTIONS}
        active_samples = {junction: 0 for junction in JUNCTIONS}
        positive_speed_samples = {junction: 0 for junction in JUNCTIONS}
        signals_emergency_locked = {junction: False for junction in JUNCTIONS}
        emergency_frames = []
        decision_junctions: set[str] = set()
        telemetry_frames = 0
        telemetry_session_ids = set()
        last_status = None
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=0.005)
                frame = json.loads(raw)
                if frame.get("type") == "TRAFFIC_UPDATE":
                    telemetry_frames += 1
                    if frame.get("session_uuid") is not None:
                        telemetry_session_ids.add(frame["session_uuid"])
                    for junction in JUNCTIONS:
                        signal = frame.get("signals", {}).get(junction, {})
                        if "current_phase" in signal:
                            phases[junction].add(int(signal["current_phase"]))
                        signals_emergency_locked[junction] = (
                            signals_emergency_locked[junction] or bool(signal.get("emergency_locked"))
                        )
                        state = frame.get("junctions", {}).get(junction, {})
                        if state.get("vehicle_count", 0) > 0:
                            active_samples[junction] += 1
                        if state.get("average_speed_kmh", 0) > 0:
                            positive_speed_samples[junction] += 1
                    for decision in frame.get("decisions", []):
                        if decision.get("junction_id") in JUNCTIONS:
                            decision_junctions.add(decision["junction_id"])
                    emergency_frame = frame.get("emergencies", {})
                    if emergency and (emergency_frame.get("active_emergency") or emergency_frame.get("total_completed_events", 0)):
                        emergency_frames.append({
                            "simulation_time_s": frame.get("simulation_time"),
                            "active_emergency": emergency_frame.get("active_emergency"),
                            "locked_junctions": emergency_frame.get("emergency_locked_junctions"),
                            "active_vehicle_id": emergency_frame.get("active_vehicle_id"),
                            "completed_events": emergency_frame.get("total_completed_events"),
                        })
            except asyncio.TimeoutError:
                pass
            status_response = await client.get(f"{BASE}/api/simulation/status", timeout=5)
            last_status = status_response.json()
            if not last_status.get("running") and last_status.get("status") in {"COMPLETED", "STOPPED", "ERROR"}:
                break
        else:
            await client.post(f"{BASE}/api/simulation/stop", timeout=10)
            raise TimeoutError(f"{mode} did not finish within wall-clock bound")
        metrics = (await client.get(f"{BASE}/api/traffic/metrics")).json()
        emergency_api = (await client.get(f"{BASE}/api/emergencies")).json() if emergency else None
        decisions_response = (await client.get(f"{BASE}/api/decisions")).json()
        if decisions_response.get("decisions"):
            decision_junctions.update(
                item.get("junction_id") for item in decisions_response["decisions"]
                if item.get("junction_id") in JUNCTIONS
            )
        pid_exists = process_exists(sumo_pid)
        result = {
            "run_id": run_id,
            "mode": mode,
            "checkpoint_path": checkpoint,
            "request": request,
            "start_http_status": started.status_code,
            "initial_websocket_type": initial.get("type"),
            "terminal_status": last_status,
            "metrics": metrics,
            "telemetry_frames": telemetry_frames,
            "telemetry_session_ids": sorted(telemetry_session_ids),
            "phase_ids_observed": {junction: sorted(values) for junction, values in phases.items()},
            "vehicle_present_frames": active_samples,
            "positive_speed_frames": positive_speed_samples,
            "vehicle_movement_observed": any(value > 0 for value in positive_speed_samples.values()),
            "decision_junctions_observed": sorted(decision_junctions),
            "sumo_pid_from_start_response": sumo_pid,
            "sumo_process_present_after_completion": pid_exists,
            "sumo_process_absent_after_completion": pid_exists is False,
            "emergency_websocket_frames": emergency_frames,
            "emergency_api": emergency_api,
        }
        result["result"] = "PASSED" if (
            last_status.get("run_uuid") == run_id
            and last_status.get("status") == "COMPLETED"
            and last_status.get("error") is None
            and last_status.get("controller") is not None
            and (not telemetry_session_ids or telemetry_session_ids == {run_id})
            and all(len(values) >= 2 for values in phases.values())
            and result["vehicle_movement_observed"]
            and pid_exists is False
            and (mode not in ("marl_ppo", "marl_dqn") or set(decision_junctions) == set(JUNCTIONS))
            and (not emergency or (
                emergency_api.get("total_completed_events", 0) == 1
                and emergency_api.get("events", [{}])[-1].get("completed") is True
                and emergency_api.get("events", [{}])[-1].get("traversal_duration") == 37.0
                and all(signals_emergency_locked.values())
            ))
        ) else "FAILED"
        if result["result"] != "PASSED":
            raise AssertionError(json.dumps(result, indent=2))
        return result


async def main():
    health = (await httpx.AsyncClient().get(f"{BASE}/api/health", timeout=10)).json()
    if health.get("status") != "ok" or not health.get("sumo_available") or health.get("active_simulation"):
        raise AssertionError(f"Unexpected backend health: {health}")
    async with httpx.AsyncClient() as client:
        runs = [
            await run_one(client, "baseline", 120, 99, False),
            await run_one(client, "coordinated", 120, 99, False),
            await run_one(client, "marl_ppo", 90, 99, False, "checkpoints/p6/ppo_stage_a_best.json"),
            await run_one(client, "marl_dqn", 90, 99, False, "checkpoints/p6/dqn_stage_a_best.json"),
            await run_one(client, "coordinated", 500, 42, True),
        ]
    result = {
        "backend_health": health,
        "runs_in_order": [run["mode"] + ("_emergency" if run["request"]["enable_emergency"] else "") for run in runs],
        "unique_run_ids": len({run["run_id"] for run in runs}) == 5,
        "all_passed": all(run["result"] == "PASSED" for run in runs),
        "runs": runs,
        "overall": "PASSED" if all(run["result"] == "PASSED" for run in runs) else "FAILED",
    }
    OUTPUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(main())

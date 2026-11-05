"""Deterministic transition and actual per-step SUMO emergency-safety checks."""

import time
from collections import defaultdict

import pytest

from backend.simulation_service import SimulationService
from backend.database import init_db
from traffic_service.signal_controller import SignalController


class FakeTrafficLight:
    def __init__(self, phase):
        self.phase = phase
        self.phase_changes = []
        self.phase_durations = []

    def getPhase(self, _tls_id):
        return self.phase

    def setPhase(self, _tls_id, phase):
        self.phase = phase
        self.phase_changes.append(phase)

    def setPhaseDuration(self, _tls_id, duration):
        self.phase_durations.append(duration)

    def getNextSwitch(self, _tls_id):
        return 100.0


def test_emergency_preempts_minimum_green_through_yellow_and_resumes(monkeypatch):
    import traffic_service.signal_controller as signal_controller_module

    lights = FakeTrafficLight(phase=0)
    monkeypatch.setattr(signal_controller_module.traci, "trafficlight", lights)
    controller = SignalController(
        "tls",
        green_phases={0, 2},
        yellow_transitions={0: 1, 2: 3},
        min_green=15.0,
        max_green=60.0,
        yellow_duration=4.0,
    )
    controller._last_phase = 0
    controller._phase_start_time = 0.0
    assert controller.get_green_elapsed(5.0) < controller.min_green

    assert controller.lock_emergency_priority(2, sim_time=5.0) == "SWITCHING_YELLOW"
    assert lights.phase == 1
    assert lights.phase_durations == [4.0]
    assert not controller.emergency_locked

    assert controller.lock_emergency_priority(2, sim_time=6.0) == "CLEARING_YELLOW"
    assert lights.phase == 1
    assert lights.phase_changes == [1]

    lights.phase = 2  # SUMO naturally advances after the mandatory yellow.
    assert controller.lock_emergency_priority(2, sim_time=9.0) == "ALREADY_GREEN"
    assert controller.emergency_locked
    assert lights.phase_durations[-1] == 30.0

    controller.release_emergency_priority()
    controller._last_phase = 2
    controller._phase_start_time = 9.0
    assert controller.can_switch(24.0)
    assert controller.request_switch(target_green_phase=0, sim_time=24.0)
    assert lights.phase == 3
    assert lights.phase_durations[-1] == 4.0


def test_emergency_arrival_on_priority_green_locks_without_unneeded_yellow(monkeypatch):
    import traffic_service.signal_controller as signal_controller_module

    lights = FakeTrafficLight(phase=2)
    monkeypatch.setattr(signal_controller_module.traci, "trafficlight", lights)
    controller = SignalController(
        "tls",
        green_phases={0, 2},
        yellow_transitions={0: 1, 2: 3},
        yellow_duration=4.0,
    )

    assert controller.lock_emergency_priority(2, sim_time=12.0) == "ALREADY_GREEN"
    assert controller.emergency_locked
    assert lights.phase_changes == []
    assert lights.phase_durations == [30.0]


def test_live_sumo_emergency_records_actual_signal_state_each_step(monkeypatch):
    import traci

    records = []
    instrumentation_errors = []
    original_broadcast = SimulationService._broadcast_telemetry

    def audited_broadcast(service):
        sim = service._sim
        if sim is not None and sim.sumo_manager.is_running:
            try:
                sim_time = sim.sumo_manager.get_time()
                coordinator = sim.emergency_coordinator
                metrics = coordinator.metrics
                if metrics.vehicle_id and sim_time >= metrics.start_time:
                    vehicle_id = metrics.vehicle_id
                    try:
                        vehicle_exists = vehicle_id in traci.vehicle.getIDList()
                        position = {
                            "edge": traci.vehicle.getRoadID(vehicle_id),
                            "lane": traci.vehicle.getLaneID(vehicle_id),
                            "lane_position_m": traci.vehicle.getLanePosition(vehicle_id),
                            "speed_mps": traci.vehicle.getSpeed(vehicle_id),
                        } if vehicle_exists else None
                    except traci.TraCIException:
                        position = None

                    for junction_id, tls_id in sim.tls_ids.items():
                        controller = sim.controllers[junction_id]
                        phase = traci.trafficlight.getPhase(tls_id)
                        state = traci.trafficlight.getRedYellowGreenState(tls_id)
                        controlled_links = traci.trafficlight.getControlledLinks(tls_id)
                        green_approaches = set()
                        yellow_approaches = set()
                        lane_groups = sim.approach_lanes[junction_id]
                        for signal_index, color in enumerate(state):
                            links = controlled_links[signal_index] if signal_index < len(controlled_links) else ()
                            target = green_approaches if color in "gG" else yellow_approaches if color in "yY" else None
                            if target is None:
                                continue
                            for link in links or ():
                                incoming_lane = link[0]
                                for approach, lanes in lane_groups.items():
                                    if incoming_lane in lanes:
                                        target.add(approach)

                        records.append({
                            "simulation_time": sim_time,
                            "junction_id": junction_id,
                            "tls_id": tls_id,
                            "phase": phase,
                            "next_switch_time": traci.trafficlight.getNextSwitch(tls_id),
                            "raw_signal_state": state,
                            "green_approaches": sorted(green_approaches),
                            "yellow_approaches": sorted(yellow_approaches),
                            "emergency_locked": controller.emergency_locked,
                            "priority_phase": controller.emergency_priority_phase,
                            "expected_priority_phase": sim.corridor_priority_phases[junction_id],
                            "green_phases": sorted(sim.green_phases[junction_id]),
                            "yellow_phases": sorted(sim.yellow_transitions[junction_id].values()),
                            "emergency_stage": coordinator.current_stage,
                            "emergency_active": coordinator.active_emergency_id is not None,
                            "emergency_completed": metrics.completed,
                            "emergency_vehicle_id": vehicle_id,
                            "emergency_position": position,
                            "controller_phase_start_time": controller._phase_start_time,
                            "controller_last_phase": controller._last_phase,
                        })
            except Exception as exc:  # Preserve the simulation; surface observer failures below.
                instrumentation_errors.append(f"{service._current_sim_time}: {exc!r}")
        return original_broadcast(service)

    monkeypatch.setattr(SimulationService, "_broadcast_telemetry", audited_broadcast)
    init_db()
    service = SimulationService()
    started, message = service.start_simulation(
        mode="coordinated",
        duration=500,
        seed=612,
        step_length=1.0,
        decision_interval=5.0,
        enable_emergency=True,
        gui=False,
    )
    assert started, message

    deadline = time.monotonic() + 120.0
    try:
        while time.monotonic() < deadline:
            status = service.get_status()
            if not status.running and status.status in {"COMPLETED", "ERROR", "STOPPED"}:
                break
            time.sleep(0.05)
        else:
            pytest.fail("Live SUMO emergency run did not finish before timeout")

        assert status.status == "COMPLETED", status.error
        assert status.simulation_time == 500.0
        assert service._sim is None
        assert service._thread is None or not service._thread.is_alive()
    finally:
        if service.get_status().running:
            service.stop_simulation()

    assert not instrumentation_errors, instrumentation_errors[:5]
    active_rows = [row for row in records if row["emergency_active"]]
    assert active_rows, "No per-step signal snapshots were recorded while emergency was active"
    assert all(row["emergency_position"] is not None for row in active_rows)
    assert {row["emergency_stage"] for row in active_rows} >= {
        "APPROACHING_J1", "J1_TO_J2", "J2_TO_J3",
    }
    assert len({row["simulation_time"] for row in active_rows}) > 30
    active_times = sorted({row["simulation_time"] for row in active_rows})
    assert all(b - a == pytest.approx(1.0) for a, b in zip(active_times, active_times[1:]))

    by_time = defaultdict(dict)
    for row in active_rows:
        by_time[row["simulation_time"]][row["junction_id"]] = row
    assert all(set(rows) == {"J1", "J2", "J3"} for rows in by_time.values())

    for sim_time, junction_rows in by_time.items():
        for junction_id, row in junction_rows.items():
            # Locked priority signals must show their actual priority phase and no green
            # on the conflicting cross-traffic approach. This checks TraCI output.
            if row["emergency_locked"]:
                assert row["phase"] == row["priority_phase"], (
                    f"{sim_time}s {junction_id}: locked but actual phase={row['phase']} "
                    f"priority={row['priority_phase']} state={row['raw_signal_state']}"
                )
                conflicting = "madiwala" if junction_id == "J2" else "side_cross"
                assert conflicting not in row["green_approaches"], (
                    f"{sim_time}s {junction_id}: conflicting green while emergency lock active; "
                    f"state={row['raw_signal_state']} greens={row['green_approaches']}"
                )

    event = service._emergency_events[-1] if service._emergency_events else None
    assert event is not None and event.completed, "Ambulance did not clear the corridor"
    clearance_time = event.clearance_time
    assert event.arrival_time > 0 and clearance_time > event.arrival_time
    interval_rows = [
        row for row in records
        if event.arrival_time <= row["simulation_time"] <= clearance_time
    ]
    interval_times = sorted({row["simulation_time"] for row in interval_rows})
    by_interval_time = defaultdict(dict)
    for row in interval_rows:
        by_interval_time[row["simulation_time"]][row["junction_id"]] = row
    assert len(interval_times) > 30
    assert all(set(rows) == {"J1", "J2", "J3"} for rows in by_interval_time.values())

    observed_yellow_clearance = set()
    yellow_clearance_details = []
    for junction_id in ("J1", "J2", "J3"):
        junction_sequence = sorted(
            (row for row in interval_rows if row["junction_id"] == junction_id),
            key=lambda row: row["simulation_time"],
        )
        index = 0
        while index < len(junction_sequence):
            row = junction_sequence[index]
            if row["phase"] not in row["yellow_phases"]:
                index += 1
                continue
            start = index
            yellow_phase = row["phase"]
            while index < len(junction_sequence) and junction_sequence[index]["phase"] == yellow_phase:
                index += 1
            next_row = junction_sequence[index] if index < len(junction_sequence) else None
            if next_row and next_row["phase"] == row["expected_priority_phase"]:
                first_yellow = junction_sequence[start]
                conflicting = "madiwala" if junction_id == "J2" else "side_cross"
                assert conflicting not in first_yellow["green_approaches"], (
                    f"{first_yellow['simulation_time']}s {junction_id}: conflicting approach "
                    f"green during emergency yellow clearance; state={first_yellow['raw_signal_state']} "
                    f"greens={first_yellow['green_approaches']}"
                )
                yellow_elapsed_s = next_row["simulation_time"] - first_yellow["simulation_time"]
                scheduled_yellow_s = first_yellow["next_switch_time"] - first_yellow["simulation_time"]
                assert yellow_elapsed_s >= 4.0, (
                    f"{first_yellow['simulation_time']}s {junction_id}: observed yellow-to-green "
                    f"elapsed only {yellow_elapsed_s}s; state={first_yellow['raw_signal_state']} "
                    f"nextSwitch={first_yellow['next_switch_time']}"
                )
                assert yellow_elapsed_s <= 5.0, (
                    f"{first_yellow['simulation_time']}s {junction_id}: yellow clearance lasted "
                    f"{yellow_elapsed_s}s; phase={yellow_phase}, next={next_row['phase']}"
                )
                assert scheduled_yellow_s == pytest.approx(4.0), (
                    f"{first_yellow['simulation_time']}s {junction_id}: SUMO scheduled "
                    f"{scheduled_yellow_s}s yellow before the priority phase"
                )
                assert next_row["simulation_time"] - first_yellow["next_switch_time"] in (0.0, 1.0), (
                    f"{junction_id}: priority phase observation fell outside SUMO's one-step "
                    f"sampling boundary after nextSwitch={first_yellow['next_switch_time']}"
                )
                for yellow_row in junction_sequence[start:index]:
                    assert conflicting not in yellow_row["green_approaches"], (
                        f"{yellow_row['simulation_time']}s {junction_id}: conflicting approach "
                        f"green during yellow clearance; state={yellow_row['raw_signal_state']} "
                        f"greens={yellow_row['green_approaches']}"
                    )
                observed_yellow_clearance.add(junction_id)
                yellow_clearance_details.append({
                    "junction_id": junction_id,
                    "yellow_phase": yellow_phase,
                    "first_yellow_sample_s": first_yellow["simulation_time"],
                    "last_yellow_sample_s": junction_sequence[index - 1]["simulation_time"],
                    "priority_green_sample_s": next_row["simulation_time"],
                    "first_sample_next_switch_s": first_yellow["next_switch_time"],
                    "elapsed_to_priority_green_s": yellow_elapsed_s,
                    "yellow_samples": index - start,
                })
        # Each captured yellow step must be visible in actual SUMO RYG output.
        for row in junction_sequence:
            if row["phase"] in row["yellow_phases"]:
                assert any(color in "yY" for color in row["raw_signal_state"]), (
                    f"{row['simulation_time']}s {junction_id}: yellow phase has no actual "
                    f"yellow in {row['raw_signal_state']}"
                )
    assert observed_yellow_clearance, "No emergency yellow-to-priority transition was observed"

    # At each point in the emergency's current corridor stage, inspect the actual
    # SUMO phase and per-link RYG state at the junction being preempted.
    relevant_junction = {
        "APPROACHING_J1": "J1",
        "J1_TO_J2": "J2",
        "J2_TO_J3": "J3",
    }
    for sim_time, junction_rows in by_interval_time.items():
        stage = next(iter(junction_rows.values()))["emergency_stage"]
        target_junction = relevant_junction.get(stage)
        if target_junction is None:
            continue
        row = junction_rows[target_junction]
        conflicting = "madiwala" if target_junction == "J2" else "side_cross"
        if row["phase"] in row["green_phases"]:
            assert row["phase"] == row["expected_priority_phase"], (
                f"{sim_time}s {target_junction}: actual conflicting green phase "
                f"{row['phase']} during emergency stage {stage}; RYG={row['raw_signal_state']}"
            )
            assert row["emergency_locked"], (
                f"{sim_time}s {target_junction}: priority green without an active lock"
            )
            assert conflicting not in row["green_approaches"], (
                f"{sim_time}s {target_junction}: conflicting approach green "
                f"during priority; state={row['raw_signal_state']} greens={row['green_approaches']}"
            )
        elif row["phase"] in row["yellow_phases"]:
            assert any(color in "yY" for color in row["raw_signal_state"]), (
                f"{sim_time}s {target_junction}: yellow phase has no actual yellow signal "
                f"in {row['raw_signal_state']}"
            )
            assert conflicting not in row["green_approaches"], (
                f"{sim_time}s {target_junction}: conflicting green during yellow clearance; "
                f"state={row['raw_signal_state']} greens={row['green_approaches']}"
            )

    # After clearance, the event is over, every emergency lock is released, and
    # at least one signal/controller update demonstrates normal operation resumed.
    post_clearance = [row for row in records if row["simulation_time"] > clearance_time]
    assert post_clearance
    assert all(not row["emergency_locked"] for row in post_clearance)
    phase_rows = defaultdict(list)
    for row in post_clearance:
        phase_rows[row["junction_id"]].append((row["simulation_time"], row["phase"]))
    assert any(
        first[1] != last[1]
        for rows in phase_rows.values()
        if len(rows) > 1
        for first, last in [(rows[0], rows[-1])]
    ), "No signal phase change was observed after emergency release"
    print({
        "active_steps": len(active_times),
        "interval_steps_including_clearance": len(interval_times),
        "active_interval_s": [active_times[0], active_times[-1]],
        "event_arrival_s": event.arrival_time,
        "event_clearance_s": event.clearance_time,
        "event_traversal_s": event.traversal_duration,
        "per_step_junction_snapshots": len(active_rows),
        "yellow_clearance_details": yellow_clearance_details,
        "sample_timeline": [
            {"time": row["simulation_time"], "junction": row["junction_id"], "phase": row["phase"],
             "state": row["raw_signal_state"], "greens": row["green_approaches"],
             "yellows": row["yellow_approaches"], "locked": row["emergency_locked"],
             "priority": row["priority_phase"], "stage": row["emergency_stage"],
             "edge": (row["emergency_position"] or {}).get("edge")}
            for row in active_rows if row["junction_id"] == "J1" and row["simulation_time"] in {active_times[0], active_times[1], active_times[-1]}
        ],
    })

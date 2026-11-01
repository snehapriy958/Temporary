# Implementation Roadmap: Engineering Plan & Priority Matrix

**Project:** Bengaluru Smart Traffic Coordination System  
**Auditor:** Principal Software Architect, Senior ITS Engineer, & Production QA Lead  
**Date:** October 30, 2026  
**Status:** COMPLETE (Ready for User Review & Formal Approval)

---

## 1. Roadmap Overview & Priority Taxonomy

This implementation roadmap establishes the structured, prioritized engineering plan to transform the current academic prototype into a production-grade, geographically accurate 3D traffic digital twin of Bengaluru's Central Silk Board corridor.

Tasks are rigorously classified according to industry engineering severity:
- **P0 — Critical Correctness & Safety Issues:** Flaws causing invalid physical metrics, hardcoded technical deceptions, or deployment impossibilities. Must be fixed immediately.
- **P1 — Core Architecture & Functional Deficiencies:** Missing foundational capabilities: true decentralized multi-agent actors, real-world data ingestion, dependency manifests, and thread safety.
- **P2 — Major Product & 3D Twin Capabilities:** Dual-scale 3D visualization (CesiumJS corridor + Three.js junction), side-by-side experiment replay, and reverse geospatial projection.
- **P3 — Polish, UX & Performance Optimizations:** 60 FPS motion smoothing, audio alarms, accessibility, and visual polish.

---

## 2. P0 — Critical Correctness & Safety Issues

### Task P0-1: Fix Fuel Consumption Calculation & Unit Conversion Bug
- **Problem:** Fuel consumption is overstated by a factor of ~750x, displaying physically absurd numbers (~17,391 Liters for a 10-minute run of ~100 cars).
- **Evidence:** `traffic_service/state_extractor.py` and `traffic_service/corridor_metrics.py` divide accumulated TraCI fuel (in milligrams) by `1,000.0`, producing **grams** mislabelled as Litres. Historical CSV values (`17391.65` Baseline) are mass in grams.
- **Root Cause:** TraCI's `getFuelConsumption()` returns **milligrams per second (mg/s)**. Converting mass to volume requires dividing by fuel density $\rho$ ($750,000\text{ mg/L}$ or $750\text{ g/L}$ for gasoline).
- **Recommended Fix:**
  Introduce an exact fuel density constant `FUEL_DENSITY_MG_PER_LITER = 750_000.0` (petrol density). Compute:
  $$\text{fuel\_liters} = \frac{\text{accumulated\_fuel\_mg}}{\text{FUEL\_DENSITY\_MG\_PER\_LITER}}$$
  Note: Historical five-seed CSV values are converted aggregate estimates ($V_{\text{grams}} / 750\text{ g/L}$). Fuel mass in kg remains canonical. Mixed-fleet volumetric values are estimated gasoline-equivalent figures.
- **Files Affected:**
  - `traffic_service/state_extractor.py`
  - `traffic_service/corridor_metrics.py`
  - `tests/test_metrics.py`
- **Dependencies:** None.
- **Risk:** Low (code modification is straightforward; changes unit tests).
- **Priority:** **P0**
- **Acceptance Criteria:** A 600s baseline simulation of ~100 vehicles consumes between $15.0\text{ L}$ and $35.0\text{ L}$ of fuel, matching realistic automotive figures.
- **Test Plan:** Add unit test in `test_metrics.py` asserting fuel consumption per vehicle-kilometer is within $[0.06, 0.15]\text{ L/km}$.

---

### Task P0-2: Replace Hardcoded Comparison Chart with Dynamic API Data Binding
- **Problem:** The bar chart in `ControllerComparison.jsx` displays hardcoded static demo numbers and never updates when simulation experiments are run.
- **Evidence:** `frontend/src/components/ControllerComparison.jsx` lines 9–40 define a static `const chartData = [...]` instead of transforming the `compareData` prop.
- **Root Cause:** Placeholder mockup code was left un-integrated.
- **Recommended Fix:**
  Refactor `ControllerComparison.jsx` to dynamically derive `chartData` directly from `compareData.controllers`:
  Extract `mean_travel_time_s`, `total_waiting_time_s`, `mean_queue`, `mean_speed_kmh`, `total_co2_kg`, and `emergency_traversal_duration_s` for Baseline and Coordinated controllers directly from props with clean loading/empty states.
- **Files Affected:**
  - `frontend/src/components/ControllerComparison.jsx`
- **Dependencies:** None.
- **Risk:** Low.
- **Priority:** **P0**
- **Acceptance Criteria:** Changing experiment parameters in the backend or running a new scenario dynamically updates the Recharts bar chart without page reload.
- **Test Plan:** Verify rendering with mock API responses containing differing numbers and assert DOM chart bars reflect the dynamic values.

---

### Task P0-3: Provide Standard Dependency Manifests & Docker Containerization
- **Problem:** No `requirements.txt`, `pyproject.toml`, or `Dockerfile` exists, making developer setup and cloud deployment non-reproducible.
- **Evidence:** Searching for requirements or Dockerfiles in workspace returns 0 files.
- **Root Cause:** Environment relies on global developer machine state.
- **Recommended Fix:**
  1. Author `requirements.txt` and `pyproject.toml` pinning exact backend versions (`fastapi==0.141.1`, `uvicorn==0.52.1`, `traci==1.26.0`, `sumolib==1.26.0`, `sqlalchemy==2.0.52`, `pydantic==2.13.5`, etc.).
  2. Create a multi-stage `Dockerfile` and `docker-compose.yml` defining:
     - `backend`: Python 3.12/3.13 image with Eclipse SUMO 1.26 binaries installed.
     - `frontend`: Node 22 image building Vite and serving static assets via Nginx.
- **Files Affected:**
  - `requirements.txt` (New)
  - `pyproject.toml` (New)
  - `Dockerfile` (New)
  - `docker-compose.yml` (New)
- **Dependencies:** Host Docker engine.
- **Risk:** Low.
- **Priority:** **P0**
- **Acceptance Criteria:** Running `docker-compose up --build` spins up both backend and frontend accessible on `localhost:8000` and `localhost:5173`.
- **Test Plan:** Fresh checkout test on a machine without pre-installed SUMO.

---

### Task P0-4: Restore Missing OSM Source File
- **Problem:** `sumo/silk_board/osm/silk_board_bbox.osm.xml` is missing, causing check failure in `scripts/validate_silk_board_network.py`.
- **Evidence:** Milestone 1 validation script prints `[FAIL] OSM source file present and non-trivial`.
- **Root Cause:** OSM XML was either omitted during Git commit or gitignored.
- **Recommended Fix:**
  Restore the bounding box OSM XML file for Silk Board (`bbox: 77.5800, 12.8190 to 77.7824, 12.9352`) into `sumo/silk_board/osm/silk_board_bbox.osm.xml`.
- **Files Affected:**
  - `sumo/silk_board/osm/silk_board_bbox.osm.xml` (Restore/Add)
- **Dependencies:** None.
- **Risk:** Low.
- **Priority:** **P0**
- **Acceptance Criteria:** `python scripts/validate_silk_board_network.py` passes 10/10 checks.
- **Test Plan:** Execute `validate_silk_board_network.py` and confirm 100% pass rate.

---

## 3. P1 — Core Architecture & Functional Deficiencies

### Task P1-1: True Multi-Agent System (MAS) Decentralization
- **Problem:** Junctions are operated by a centralized procedural script rather than autonomous agents; inter-intersection message queues are never consumed.
- **Evidence:** `MultiIntersectionSimulation` runs on a single thread looping through J1, J2, J3. `hub.get_messages()` is never called.
- **Root Cause:** Simplified prototype shortcut.
- **Recommended Fix:**
  1. Create an abstract `BaseJunctionAgent` and concrete `JunctionAgent` class per intersection.
  2. Each agent possesses:
     - Local private state (approach queues, phase elapsed, local camera/detector observations).
     - Individual inbox/outbox connected to `CorridorCommunicationHub`.
     - Explicit message handling loop consuming `PLATOON_RELEASE`, `UPSTREAM_INFLOW`, and `EMERGENCY_ALERT`.
     - Localized decision policy choosing actions `(KEEP, SWITCH, EXTEND)`.
     - Message acknowledgement (ACK) protocol.
  3. Orchestrator simply steps SUMO and dispatches observations to agents.
- **Files Affected:**
  - `traffic_service/agents/base_agent.py` (New)
  - `traffic_service/agents/junction_agent.py` (New)
  - `traffic_service/communication.py`
  - `traffic_service/multi_intersection_simulation.py`
  - `tests/test_communication.py`
- **Dependencies:** None.
- **Risk:** Medium (refactors simulation decision loop).
- **Priority:** **P1**
- **Acceptance Criteria:** Agents operate via decoupled message passing; messages are parsed, acted upon, and acknowledged; inbox queues do not leak memory.
- **Test Plan:** Unit tests asserting message exchange between J1, J2, and J3 with simulated network latency and message loss.

---

### Task P1-2: Real-World Traffic Data Ingestion Layer (TomTom / Open Traffic APIs)
- **Problem:** Project has zero live traffic ingestion and cannot reflect actual congestion in Bengaluru.
- **Evidence:** Audit confirmed 0 integrations with TomTom, Google Maps, or sensor feeds.
- **Root Cause:** Scope limitation during initial prototype build.
- **Recommended Fix:**
  1. Implement `traffic_service/ingestion/tomtom_client.py` querying TomTom Traffic Flow API for the Silk Board bounding box and arterial segments (Hosur Rd, ORR).
  2. Implement `traffic_service/ingestion/dynamic_demand_adapter.py`:
     - Compares live TomTom segment speeds against free-flow speeds to compute real-time congestion indices.
     - Modulates SUMO vehicle insertion rates or adjusts route entry flows dynamically to mirror live road conditions.
  3. Expose `GET /api/traffic/realworld` and add a UI toggle: "Live Bengaluru Telemetry vs Digital Twin Simulation".
- **Files Affected:**
  - `traffic_service/ingestion/` (New directory)
  - `backend/routers/traffic.py`
  - `backend/config.py`
  - `frontend/src/components/Header.jsx`
- **Dependencies:** TomTom Developer API Key (free tier available) or OpenStreetMap Overpass live fallback.
- **Risk:** Medium (external network dependency; requires graceful offline fallback).
- **Priority:** **P1**
- **Acceptance Criteria:** Backend periodically ingests real-time speeds for Hosur Road; UI displays live travel times alongside simulated digital twin metrics.
- **Test Plan:** Mocked HTTP tests for TomTom client + live integration test with valid API key.

---

### Task P1-3: Microscopic Vehicle Telemetry Stream for 3D Twin
- **Problem:** WebSocket only broadcasts aggregate queues, making individual 3D vehicle rendering impossible.
- **Evidence:** `_broadcast_telemetry` payload lacks per-vehicle `(x, y, z, angle, speed, type)`.
- **Root Cause:** 2D dashboard only required aggregate numbers.
- **Recommended Fix:**
  Extend `simulation_service.py` to extract individual vehicle positions from TraCI:
  ```python
  vehicles = [
      {
          "id": vid,
          "type": traci.vehicle.getTypeID(vid),
          "x": round(x, 2),
          "y": round(y, 2),
          "angle": round(angle, 1),
          "speed": round(speed, 2),
          "lane": traci.vehicle.getLaneID(vid),
      }
      for vid, (x, y), angle, speed in ...
  ]
  ```
  Broadcast either via dedicated high-frequency binary/JSON channel or optimized delta compression.
- **Files Affected:**
  - `backend/simulation_service.py`
  - `backend/websocket_manager.py`
  - `traffic_service/state_extractor.py`
- **Dependencies:** TraCI vehicle query optimization.
- **Risk:** Medium (potential performance impact if streaming thousands of vehicles).
- **Priority:** **P1**
- **Acceptance Criteria:** WebSocket transmits individual vehicle coordinates at $\ge 10\text{ Hz}$ with $<30\text{ ms}$ latency for up to 300 active vehicles.
- **Test Plan:** Benchmark WebSocket frame rates and serialization throughput.

---

### Task P1-4: Implement Inverse Coordinate Transformation (`sumo_xy_to_wgs84`)
- **Problem:** Cannot project SUMO vehicles and road splines onto CesiumJS WGS84 globes without inverse coordinate projection.
- **Evidence:** `spatial_mapper.py` only implements forward `wgs84_to_sumo_xy()`.
- **Root Cause:** Incomplete mapper implementation.
- **Recommended Fix:**
  Add `sumo_xy_to_wgs84(x, y) -> tuple[float, float]` in `traffic_service/spatial_mapper.py` using `sumolib.net.Net.convertXY2LonLat(x, y)` with analytical reverse Karney transverse mercator fallback.
- **Files Affected:**
  - `traffic_service/spatial_mapper.py`
  - `tests/test_accident_risk.py`
- **Dependencies:** None (uses existing sumolib / math formulas).
- **Risk:** Low.
- **Priority:** **P1**
- **Acceptance Criteria:** Round-trip projection `wgs84_to_sumo_xy` followed by `sumo_xy_to_wgs84` yields coordinate error $<0.05\text{ meters}$.
- **Test Plan:** Unit test verifying round-trip conversion accuracy for J1, J2, and J3 coordinates.

---

### Task P1-5: Thread Safety & Datetime Deprecation Migration
- **Problem:** 32 Python 3.13 deprecation warnings on `datetime.utcnow()`; unsynchronized reads on `sim_service._current_sim_time`.
- **Evidence:** Pytest outputs and inspection of `routers/signals.py:56`.
- **Root Cause:** Use of legacy Python datetime APIs and property leakage outside lock.
- **Recommended Fix:**
  1. Replace all `datetime.utcnow()` with `datetime.now(timezone.utc)`.
  2. Implement thread-safe getter `sim_service.get_current_simulation_time()` guarded by `self._lock`.
- **Files Affected:**
  - `backend/models.py`
  - `backend/simulation_service.py`
  - `backend/routers/signals.py`
  - `backend/routers/simulation.py`
  - `tests/test_database.py`
- **Dependencies:** None.
- **Risk:** Low.
- **Priority:** **P1**
- **Acceptance Criteria:** Pytest runs with 0 deprecation warnings; no direct private attribute access in routers.
- **Test Plan:** Run pytest suite with `-W error::DeprecationWarning`.

---

### Task P1-6: Professional Repository Documentation & Architecture Guide
- **Problem:** Root `README.md` is 2 lines long, giving no guidance to evaluators, recruiters, or developers.
- **Evidence:** `README.md` has 132 bytes.
- **Root Cause:** Never written during prototyping.
- **Recommended Fix:**
  Write an extensive, production-grade `README.md` featuring:
  - System architecture diagram (Mermaid).
  - Silk Board corridor domain context (J1, J2, J3, Hosur Road, Madiwala).
  - Quickstart guide (Docker & local manual setup).
  - API documentation overview with example curl commands.
  - Multi-agent coordination algorithms and safety guarantees.
  - 3D digital twin navigation guide.
  - Research and benchmarking performance results.
- **Files Affected:**
  - `README.md`
- **Dependencies:** None.
- **Risk:** Low.
- **Priority:** **P1**
- **Acceptance Criteria:** Evaluator can clone repository, understand architecture, and launch the full stack in $<5\text{ minutes}$.

---

## 4. P2 — Major Product & 3D Twin Capabilities

### Task P2-1: Macro 3D Corridor Twin (CesiumJS / Resium)
- **Problem:** No geographic 3D digital twin of Bengaluru exists; UI is a flat 2D schematic.
- **Evidence:** Audit confirmed 0 WebGL/GIS packages in `package.json`.
- **Recommended Fix:**
  1. Install `cesium` and `resium` in `frontend/`.
  2. Create `frontend/src/components/3d/CesiumCorridorView.jsx`:
     - Centered on Bengaluru Silk Board: `lat: 12.9172, lon: 77.6228, altitude: 800m`.
     - 3D OSM Buildings and terrain elevation.
     - Extruded Hosur Road corridor polyline with congestion heatmap coloration.
     - Live camera presets: "Corridor Flyover", "Silk Board Overhead", "J1 Feeder", "J3 Feeder".
- **Files Affected:**
  - `frontend/package.json`
  - `frontend/src/components/3d/CesiumCorridorView.jsx` (New)
  - `frontend/src/App.jsx`
- **Dependencies:** CesiumJS token or open tile provider.
- **Risk:** Medium (bundle size and WebGL performance).
- **Priority:** **P2**
- **Acceptance Criteria:** User can interactively rotate, tilt, and zoom a 3D globe of Bengaluru with corridor overlays at $\ge 30\text{ FPS}$.

---

### Task P2-2: Microscopic 3D Junction Twin (Three.js / React Three Fiber)
- **Problem:** No microscopic visual twin of Central Silk Board intersection (lanes, vehicles, signals).
- **Evidence:** 2D card diagram only.
- **Recommended Fix:**
  1. Install `three`, `@react-three/fiber`, `@react-three/drei`.
  2. Write a network-to-mesh exporter generating Three.js geometries for Silk Board road lanes from `silk_board.net.xml`.
  3. Create `frontend/src/components/3d/JunctionThreeCanvas.jsx`:
     - Instanced meshes for cars, BMTC buses, motorcycles, and ambulances.
     - Smooth 60 FPS motion interpolation between 1-second SUMO simulation steps.
     - 3D signal light models updating colors in real-time according to signal phases.
- **Files Affected:**
  - `frontend/src/components/3d/` (New directory)
  - `scripts/export_sumo_to_three.py` (New script)
- **Dependencies:** Three.js / React Three Fiber.
- **Risk:** Medium (requires custom 3D mesh rendering and instancing).
- **Priority:** **P2**
- **Acceptance Criteria:** Individual vehicles move through Silk Board intersection along true lane shapes with real-time signal changes.

---

### Task P2-3: Side-by-Side Before-and-After Simulation Comparison View
- **Problem:** Evaluators cannot visually compare Baseline (uncoordinated fixed-time) vs Coordinated adaptive control simultaneously.
- **Evidence:** Current UI runs one simulation at a time.
- **Recommended Fix:**
  Create a split-screen or dual-canvas comparative player allowing synchronous side-by-side playback of identical traffic seeds under Baseline vs Coordinated control, displaying real-time delta counters for queues, travel time, and emissions.
- **Files Affected:**
  - `frontend/src/components/DualSimulationCompare.jsx` (New)
  - `backend/simulation_service.py`
- **Dependencies:** None.
- **Risk:** Low.
- **Priority:** **P2**
- **Acceptance Criteria:** Recruiter can hit "Run Comparison" and watch two synchronized simulations side-by-side with live differential metrics.

---

### Task P2-4: Automated Frontend Testing Suite (Vitest + Testing Library)
- **Problem:** Frontend has 0% automated test coverage.
- **Evidence:** `package.json` lacks test scripts; no tests exist.
- **Recommended Fix:**
  1. Install `vitest`, `@testing-library/react`, `@testing-library/user-event`, `jsdom`.
  2. Write unit tests for all components:
     - `OverviewKPIs.test.jsx`
     - `SimulationControls.test.jsx`
     - `ControllerComparison.test.jsx`
     - `SignalStatusPanel.test.jsx`
     - `EmergencyPanel.test.jsx`
- **Files Affected:**
  - `frontend/package.json`
  - `frontend/vite.config.js`
  - `frontend/src/__tests__/` (New)
- **Dependencies:** Vitest.
- **Risk:** Low.
- **Priority:** **P2**
- **Acceptance Criteria:** `npm test` executes $\ge 20$ component tests with $\ge 80\%$ statement coverage.

---

## 5. P3 — Polish, UX & Performance Optimizations

### Task P3-1: 60 FPS Vehicle Motion Smoothing & Dead Reckoning
- **Problem:** SUMO simulation steps occur once per second (1.0 Hz), which looks choppy if rendered without interpolation.
- **Recommended Fix:** Implement cubic hermite spline or linear dead-reckoning interpolation in Three.js `useFrame` loop.
- **Priority:** **P3**

### Task P3-2: Auditory & Visual Emergency Preemption Cues
- **Problem:** Ambulance detection is visual only.
- **Recommended Fix:** Add optional audio siren alert and prominent red emergency strobe overlay when green wave locks.
- **Priority:** **P3**

### Task P3-3: Glassmorphism Theme Polish & Mobile Ergonomics
- **Problem:** Some UI cards on smaller screens cause horizontal overflow.
- **Recommended Fix:** Responsive breakpoint tuning with Tailwind and backdrop-filter glassmorphism polish.
- **Priority:** **P3**

---

## 6. Execution Phasing & Dependency Graph

```
Phase 1 (Immediate - P0):
  P0-1 (Fix Fuel Bug) ──> P0-2 (Fix Chart Data) ──> P0-3 (Docker/Requirements) ──> P0-4 (OSM Source)
       │
       ▼
Phase 2 (Core Architecture - P1):
  P1-4 (Reverse Coordinates) ──> P1-3 (Vehicle Stream) ──> P1-1 (Decentralized Agents) ──> P1-2 (Live TomTom)
       │
       ▼
Phase 3 (3D Digital Twin - P2):
  P2-1 (Cesium Macro 3D) ──> P2-2 (Three.js Micro 3D) ──> P2-3 (Side-by-Side Compare) ──> P2-4 (Frontend Tests)
       │
       ▼
Phase 4 (Final Polish - P3):
  P3-1 (60 FPS Interpolation) ──> P3-2 (Audio/Visual Cues) ──> P3-3 (UI Polish)
```

---

## 7. Immediate Next Steps & Governance

1. **Review and Align:** Review the 10 audit reports in `docs/AUDIT/`.
2. **Obtain User Authorization:** Do not implement any source code modifications until user approval is received.
3. **Execution Kickoff:** Begin with Phase 1 (Tasks P0-1, P0-2, P0-3, P0-4).

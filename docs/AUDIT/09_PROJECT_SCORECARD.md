# Project Quality Scorecard: 15-Dimensional Evaluation

**Project:** Bengaluru Smart Traffic Coordination System  
**Auditor:** Principal Software Architect, Senior ITS Engineer, & Production QA Lead  
**Date:** October 30, 2026  
**Status:** COMPLETE (Strict, Uninflated Evaluation)

---

## 1. Overall Score Summary

| # | Dimension | Score (/10) | Status | Priority for Modernization |
|---|---|:---:|---|:---:|
| 1 | **Architecture** | **6.5 / 10** | Functional Monolith | P1 |
| 2 | **SUMO Network** | **8.0 / 10** | High-Quality Geometry | P2 |
| 3 | **Simulation Correctness** | **5.5 / 10** | Degraded by Fuel Bug | P0 |
| 4 | **TraCI Integration** | **8.5 / 10** | Robust Lifecycle | P1 |
| 5 | **Backend & API** | **8.0 / 10** | Clean REST & WebSockets | P1 |
| 6 | **Frontend & UI** | **5.0 / 10** | Disconnected Mock Chart | P0 |
| 7 | **Data Quality & Provenance** | **7.0 / 10** | Documented Blackspots | P2 |
| 8 | **Real-Time Capability** | **1.0 / 10** | Non-Existent External Feed | P1 |
| 9 | **Multi-Agent Capability** | **2.5 / 10** | Centralized Heuristic | P1 |
| 10 | **Signal Coordination** | **8.0 / 10** | Effective Green Waves | P2 |
| 11 | **3D Digital Twin Readiness**| **3.5 / 10** | Unbuilt Graphics Stack | P2 |
| 12 | **Testing & QA** | **6.0 / 10** | 36 Backend Tests; 0 Frontend | P1 |
| 13 | **Documentation** | **3.0 / 10** | 2-Line Root README | P1 |
| 14 | **Deployment Readiness** | **2.0 / 10** | Missing Docker & Requirements | P0 |
| 15 | **Recruiter Demo Readiness** | **4.5 / 10** | Needs Polish & Real 3D | P0 |
| **TOTAL** | **Weighted Average** | **5.27 / 10** | **Academic Prototype** | — |

---

## 2. Category-by-Category Deep Evaluation

### 1. Architecture — Score: 6.5 / 10
- **Evidence:** Modular directory layout (`backend/`, `traffic_service/`, `frontend/`, `sumo/`). Clear separation between FastAPI routes and simulation workers.
- **Problems:** Monolithic coupling: the centralized simulation class does everything (state extraction, metrics accumulation, signal switching, emergency waves). Lacks dependency injection.
- **Missing Functionality:** Microservices or clean actor pattern separation; distributed message queue.
- **Priority:** P1

### 2. SUMO Network — Score: 8.0 / 10
- **Evidence:** 7.37 MB network with 1,035 nodes and 2,464 edges compiled with UTM Zone 43N projection. J1, J2, and J3 correctly identified and connected along Hosur Road.
- **Problems:** Raw source file `silk_board_bbox.osm.xml` is missing from `sumo/silk_board/osm/`.
- **Missing Functionality:** Pedestrian crossing logic and dedicated bus priority lanes.
- **Priority:** P2

### 3. Simulation Correctness — Score: 5.5 / 10
- **Evidence:** Headless SUMO runs cleanly; multi-modal vehicle types (cars, buses, bikes, trucks, ambulances) follow realistic dynamics.
- **Problems:** Critical fuel consumption calculation bug: code assumes `getFuelConsumption` is in ml/s instead of mg/s, resulting in a **750x–1000x overestimation** of fuel burned. Queue threshold ($0.1\text{ m/s}$) is overly strict.
- **Missing Functionality:** Correct fuel density factor ($\approx 750,000\text{ mg/L}$); dynamic vehicle rerouting on congestion.
- **Priority:** P0 (Critical Correctness Issue)

### 4. TraCI Integration — Score: 8.5 / 10
- **Evidence:** Clean `SumoManager` wrapper with `isLoaded()` guards; safe phase setting; handles emergency locks; clean stop and reset without zombie processes.
- **Problems:** Requires localhost TCP socket permission, which fails under restrictive sandbox profiles.
- **Missing Functionality:** Subscription-based TraCI API (`traci.vehicle.subscribe`, `traci.junction.subscribeContext`) to minimize IPC overhead.
- **Priority:** P1

### 5. Backend — Score: 8.0 / 10
- **Evidence:** FastAPI with 8 REST routers; Pydantic v2 validation; async WebSocket manager with heartbeat; SQLite persistence.
- **Problems:** Un-synchronized direct reads of `sim_service._current_sim_time` outside lock; 32 `datetime.utcnow()` deprecation warnings.
- **Missing Functionality:** Alembic database migrations; structured JSON logging.
- **Priority:** P1

### 6. Frontend — Score: 5.0 / 10
- **Evidence:** Clean dark-mode Tailwind theme; Lucide React iconography; responsive layout; working start/pause/resume/stop simulation controls.
- **Problems:** `ControllerComparison.jsx` hardcodes static demo numbers in its bar chart instead of using the API data! 2D schematic cards only.
- **Missing Functionality:** Automated test suite; error boundaries; dynamic chart data binding.
- **Priority:** P0

### 7. Data Quality — Score: 7.0 / 10
- **Evidence:** 8 documented accident blackspots derived from official BTP South Division reports (2020–2023) with MoRTH/IRC severity weighting.
- **Problems:** Small sample size (8 blackspots); coarse police station aggregation.
- **Missing Functionality:** Historical hourly time-of-day crash distributions; live incident feeds.
- **Priority:** P2

### 8. Real-Time Capability — Score: 1.0 / 10
- **Evidence:** WebSocket stream broadcasts simulated state in real time.
- **Problems:** **Zero connection to real-world Bengaluru traffic.** No TomTom, Google Maps, CCTV, sensor, or SCATS telemetry.
- **Missing Functionality:** Live traffic provider API ingestion worker; dynamic SUMO demand injection based on live arterial speeds.
- **Priority:** P1

### 9. Multi-Agent Capability — Score: 2.5 / 10
- **Evidence:** `CorridorCommunicationHub` defines message structures; hooks exist for AI observation/action dictionaries.
- **Problems:** No independent agent instances exist; J1, J2, J3 are operated by a single centralized coordinator; message inbox is a dead letter queue (never consumed).
- **Missing Functionality:** Decentralized `JunctionAgent` actors; message parsing and ACKs; MARL/PPO policies.
- **Priority:** P1

### 10. Signal Coordination — Score: 8.0 / 10
- **Evidence:** Green-wave progression along Hosur Road; emergency preemption reduces ambulance traversal time by 18%; strict min-green (15s), max-green (60s), and yellow clearance (4s) enforced.
- **Problems:** Fixed heuristic thresholds; does not learn or adapt to sudden non-recurrent gridlock.
- **Missing Functionality:** Max-pressure distributed control; actuated dilemma-zone protection.
- **Priority:** P2

### 11. 3D Readiness — Score: 3.5 / 10
- **Evidence:** SUMO network projection parameters (UTM Zone 43N) are mathematically accurate and convertable to WGS84.
- **Problems:** No 3D dependencies (`cesium`, `three`, `@react-three/fiber`) installed; `spatial_mapper.py` lacks reverse projection (`sumo_xy_to_wgs84`); WebSocket omits microscopic vehicle coordinates.
- **Missing Functionality:** 3D road/lane mesh generation; low-poly GLTF vehicle models; CesiumJS corridor globe; Three.js junction canvas.
- **Priority:** P2

### 12. Testing — Score: 6.0 / 10
- **Evidence:** 36 pytest automated tests covering APIs, schemas, risk models, communication, and TraCI simulation pass in 12.91s.
- **Problems:** Frontend has 0 tests (0% coverage). Test suite failed to detect the 750x fuel metric calculation error.
- **Missing Functionality:** Vitest/Playwright frontend test suite; load/stress tests for WebSockets; end-to-end integration tests.
- **Priority:** P1

### 13. Documentation — Score: 3.0 / 10
- **Evidence:** `data/accidents/README.md` provides excellent provenance for BTP accident data.
- **Problems:** Root `README.md` is only 2 lines long! Lacks architecture diagrams, prerequisites, installation steps, and API docs.
- **Missing Functionality:** Complete architecture guide; quickstart instructions; developer onboarding documentation.
- **Priority:** P1

### 14. Deployment Readiness — Score: 2.0 / 10
- **Evidence:** `.env.example` provides a template.
- **Problems:** No `requirements.txt` or `pyproject.toml`; no `Dockerfile` or `docker-compose.yml`; no CI/CD pipelines; `frontend/node_modules/` missing.
- **Missing Functionality:** Multi-stage Dockerfile bundling SUMO, Python, and Node; GitHub Actions workflow; environment validation script.
- **Priority:** P0

### 15. Recruiter Demo Readiness — Score: 4.5 / 10
- **Evidence:** UI looks modern at first glance with dark theme and animations; simulation controls respond quickly.
- **Problems:** Any technical recruiter, senior engineer, or ITS specialist looking under the hood will immediately catch:
  1. The static hardcoded numbers in the comparison chart.
  2. The physically absurd fuel consumption numbers (17,391 Liters).
  3. The absence of actual 3D digital twin visualization.
  4. The claim of "Multi-Agent" for a centralized heuristic script.
- **Priority:** P0

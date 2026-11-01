# Milestone Audit: Repository Structure & Architecture

**Project:** Bengaluru Smart Traffic Coordination System  
**Audit Scope:** Complete repository structure, codebase inventory, execution tracing, configurations, and dependency topology  
**Auditor:** Principal Software Architect & QA Lead  
**Date:** October 30, 2026  
**Status:** COMPLETE (Read-Only Audit)

---

## 1. Executive Summary

A comprehensive, non-destructive audit of the `smart-traffic-coordination` repository was conducted to assess its architectural foundation, code quality, and operational readiness for transformation into an enterprise-grade, geographically accurate 3D traffic digital twin of Bengaluru's Central Silk Board corridor.

The repository contains a functional, monolithic hybrid traffic management prototype combining an Eclipse SUMO microscopic traffic simulation, a FastAPI backend with SQLite persistence, a WebSocket telemetry broadcaster, and a React/Tailwind single-page dashboard. 

However, critical foundational deficiencies exist across deployment artifacts, dependency declarations, source file completeness, unit conversion correctness, and frontend mock data decoupling.

---

## 2. Directory Tree & Codebase Inventory

The repository is organized into 9 primary directories:

```
hybrid-traffic-control/
├── backend/                  # FastAPI REST API & WebSocket service
│   ├── routers/              # 8 modular REST endpoints
│   ├── config.py             # Environment configuration loaded from dotenv
│   ├── database.py           # SQLAlchemy SQLite connection and schema seeding
│   ├── main.py               # FastAPI application entry point, CORS, and WS router
│   ├── models.py             # SQLAlchemy ORM models (5 entities)
│   ├── risk_service.py       # Documented blackspot and risk zone queries
│   ├── schemas.py            # Pydantic v2 validation models
│   ├── simulation_service.py # Core background simulation worker and state cache
│   └── websocket_manager.py  # Thread-safe WebSocket connection pool
├── common/                   # Cross-cutting environment utilities
│   ├── sumo_env.py           # SUMO binary, SUMO_HOME, and tools/ path discovery
│   └── __init__.py
├── data/                     # Raw and processed accident blackspot datasets
│   └── accidents/
│       ├── raw/              # 3 raw CSVs and 1 KML of BTP station data
│       ├── processed/        # cleaned_accidents.csv (8 documented blackspots)
│       └── README.md         # Detailed BTP/MoRTH data provenance documentation
├── frontend/                 # React 18 + Vite 5 + Tailwind CSS dashboard
│   ├── src/
│   │   ├── components/       # 10 UI components
│   │   ├── services/         # api.js (REST fetcher) and websocket.js (WS client)
│   │   ├── App.jsx           # Main orchestrator and tab navigator
│   │   ├── index.css         # Tailwind base styles
│   │   └── main.jsx          # React DOM entry point
│   ├── index.html            # HTML shell
│   ├── package.json          # Frontend dependencies
│   ├── package-lock.json     # Resolved npm lockfile
│   ├── postcss.config.js     # PostCSS setup
│   ├── tailwind.config.js    # Tailwind styling configuration
│   └── vite.config.js        # Vite dev server and API/WS reverse proxy config
├── outputs/                  # Static execution summaries and cached risk data
│   ├── corridor/             # corridor_multi_seed_summary.csv (5-seed benchmark)
│   ├── hotspots/             # hotspots.csv (DBSCAN/spatial cluster outputs)
│   └── risk/                 # risk_zones.json (IRC/MoRTH pre-computed risk zones)
├── scripts/                  # Network generation and validation utilities
│   ├── build_silk_board_network.py     # netconvert invocation wrapper
│   ├── evaluate_corridor.py            # Multi-seed baseline vs coordinated evaluator
│   ├── generate_silk_board_demand_v2.py# Demand XML generation script
│   ├── run_accident_pipeline.py        # End-to-end accident processing pipeline
│   └── validate_silk_board_network.py  # 10-point network acceptance validator
├── sumo/                     # SUMO simulation definitions
│   └── silk_board/
│       ├── demand/           # silk_board.rou.xml, vehicle_types.add.xml
│       ├── network/          # silk_board.net.xml (7.37 MB compiled network)
│       ├── osm/              # .gitkeep (OSM raw XML missing)
│       ├── traffic_lights/   # .gitkeep
│       ├── junction_mapping.json # Verified J1, J2, J3 junction IDs and coordinates
│       └── silk_board.sumocfg   # Primary SUMO configuration file
├── tests/                    # Pytest automated test suite (36 tests)
│   ├── fixtures/             # synthetic_corridor.osm.xml
│   ├── conftest.py           # Shared test fixtures
│   ├── test_accident_risk.py # 11 tests for blackspot ingestion and CRI scoring
│   ├── test_api.py           # 12 tests for FastAPI REST endpoints
│   ├── test_communication.py # 5 tests for inter-intersection messaging
│   ├── test_database.py      # 2 tests for SQLite persistence
│   ├── test_metrics.py       # 2 tests for corridor metrics accumulation
│   ├── test_simulation_integration.py # 2 integration tests for TraCI lifecycle
│   ├── test_simulation_service.py     # 1 full background worker lifecycle test
│   └── test_websocket.py     # 1 test for WebSocket telemetry protocol
├── traffic_service/          # Domain-specific ITS and simulation logic
│   ├── accident_dataset.py   # Blackspot parser and validator
│   ├── communication.py      # CorridorCommunicationHub message bus
│   ├── corridor_metrics.py   # Metrics and cumulative emission collector
│   ├── emergency_wave.py     # Green-wave emergency vehicle preemption coordinator
│   ├── hotspot_analyzer.py   # Spatial clustering for accident hotspots
│   ├── multi_intersection_simulation.py # Centralized corridor simulation runner
│   ├── risk_mapper.py        # IRC SP:88 Composite Risk Index (CRI) calculator
│   ├── scenario_generator.py # Synthetic scenario demand injector
│   ├── signal_controller.py  # Single-intersection phase transition controller
│   ├── spatial_mapper.py     # WGS84 to UTM Zone 43N / SUMO coordinate mapper
│   ├── state_extractor.py    # Per-step queue, speed, and emission extractor
│   └── sumo_manager.py       # TraCI process and connection manager
├── .env.example              # Template environment variables
├── .gitignore                # Git exclusions
├── LICENSE                   # MIT License
└── README.md                 # 2-line placeholder documentation
```

---

## 3. Configuration & Dependency Deficiencies

### 3.1 Missing Python Dependency Declarations
- **Problem:** The repository has **NO** `requirements.txt`, `pyproject.toml`, `Pipfile`, or `setup.py` at the root or within `backend/`.
- **Evidence:** Executing directory searches for dependency manifests returned zero results. The runtime relies on whatever global Python environment happens to be present on the host.
- **Risk:** New developers or CI/CD runners cannot reliably reproduce the backend environment. Essential packages identified through source imports include: `fastapi`, `uvicorn`, `pydantic`, `sqlalchemy`, `sumolib`, `traci`, `scikit-learn`, `pandas`, `numpy`, `pytest`, `httpx`, and `python-dotenv`.

### 3.2 Missing Frontend Build Artifacts (`node_modules`)
- **Problem:** `frontend/node_modules/` is not present, meaning `npm run build` or `npm run dev` cannot be executed without running `npm install`.
- **Evidence:** `Test-Path frontend/node_modules` returned `False`.
- **Note:** `package.json` and `package-lock.json` are present, which pins dependencies cleanly.

### 3.3 Containerization & CI/CD Absence
- **Problem:** There is no `Dockerfile`, `docker-compose.yml`, Kubernetes manifest, or `.github/workflows/` CI pipeline.
- **Evidence:** Automated file pattern searches for Docker and GitHub workflows returned zero matches.
- **Impact:** The system cannot be spun up as an isolated multi-container stack (SUMO + FastAPI + React).

### 3.4 Inadequate Repository Documentation
- **Problem:** `README.md` consists of only 2 lines:
  ```markdown
  # smart-traffic-coordination
  Intelligent traffic management through communication and coordination between continuous intersections
  ```
- **Impact:** Lacks setup instructions, architectural diagrams, API documentation, SUMO prerequisites, or demo walkthroughs.

---

## 4. Source Code and Script Drift

### 4.1 Missing Source Scripts Referenced in Comments
In `scripts/build_silk_board_network.py`:
- Line 40 references `identify_junctions.py`.
- Line 67 references `download_silk_board_osm.py`.
Neither file exists in `scripts/` or anywhere else in the workspace.

### 4.2 Missing Raw OSM File
- In `sumo/silk_board/osm/`, only `.gitkeep` is present.
- Running `scripts/validate_silk_board_network.py` failed Check 2:
  ```
  [FAIL] OSM source file present and non-trivial — No .osm.xml file found in sumo\silk_board\osm.
  ```
- While the compiled binary network `silk_board.net.xml` exists, the raw source OSM data from which it was generated is missing from source control.

---

## 5. End-to-End Execution Trace

### 5.1 Request Flow
1. **Frontend Initiation:** User clicks "Start Simulation" in `SimulationControls.jsx`.
2. **API Call:** Sends `POST /api/simulation/start` with `{ mode: "coordinated", duration: 600, seed: 42, ... }`.
3. **Router Dispatch:** Handled by `backend/routers/simulation.py::start_simulation()`.
4. **Service Execution:** Calls `sim_service.start_simulation()`, creating a record in `simulation_runs` and spawning `_run_simulation_worker` in a dedicated background thread.
5. **SUMO/TraCI Spawn:** `MultiIntersectionSimulation` is initialized; `SumoManager.start()` starts `sumo.exe` via `traci.start()`.
6. **Simulation Stepping:** Each 1-second step:
   - `sim.sumo_manager.step()` advances SUMO.
   - `sim.get_states()` extracts queues, wait times, speeds, and emissions.
   - `sim.emergency_coordinator.update()` checks approaching ambulances.
   - Every 5.0 seconds, `_run_coordinated_with_logging()` evaluates queue differentials and issues phase switches or green extensions via TraCI.
   - `ws_manager.broadcast()` sends JSON telemetry over WebSocket `/ws/traffic`.
   - Every 5.0 seconds, snapshots are committed to the `traffic_metrics` SQLite table.
7. **Frontend Ingestion:** `websocket.js` receives `TRAFFIC_UPDATE` and dispatches to React state setters in `App.jsx`, updating `OverviewKPIs`, `LiveCorridorView`, and `SignalStatusPanel`.

### 5.2 Critical Finding: Disconnected Comparison Chart
While live telemetry flows correctly through the WebSocket, the `ControllerComparison.jsx` component completely ignores API data for its bar chart, displaying hardcoded static numbers instead of reading from `/api/experiments/compare`.

---

## 6. Summary of Architectural Findings

| Component | Status | Key Finding |
|---|---|---|
| Project Structure | Clean | Well-partitioned directories and modular separation |
| Dependency Management | Broken | Missing `requirements.txt` / `pyproject.toml` |
| Containerization | Missing | No Dockerfile or compose setup |
| CI/CD | Missing | No automated testing or validation pipelines |
| Documentation | Deficient | 2-line root README |
| Missing Assets | Warning | Raw OSM file and 2 referenced scripts missing |
| End-to-End Tracing | Working | Full execution path from TraCI -> FastAPI -> WebSocket -> React verified |

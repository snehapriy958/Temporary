# Document 04: Feature & API Functionality Audit

**Project:** Smart Traffic Coordination System — Bengaluru Silk Board Corridor  
**Audit Date:** October 31, 2026  
**Auditor:** Principal Software Architect & Full-Stack Reliability Engineer  
**Audit Scope:** Complete REST API Inventory, WebSocket Streaming Contracts, Frontend Component Bindings, and Functional Verification  

---

## 1. Executive Summary: Functional Landscape

The application provides a comprehensive operations cockpit for monitoring and controlling the Bengaluru Silk Board corridor. 

### Key Findings:
1. **REST APIs & WebSocket Feeds:** The backend exposes **17 REST routes** across 8 routers and **1 real-time WebSocket telemetry endpoint** (`/ws/traffic`).
2. **Frontend-Backend Binding:** Every single REST endpoint has a 1:1 typed consumer in `frontend/src/services/api.js`. The React dashboard actively polls or subscribes to all available endpoints.
3. **Data Integrity:** No visual UI component relies on randomized client-side mock generators during active simulation. All dashboard widgets (queues, signal phases, emissions, KPIs, emergency alerts) consume authoritative TraCI telemetry streamed over WebSocket or synchronized via REST recovery.
4. **Placeholders:** In the benchmarking and experimentation views, PPO and DQN reinforcement learning models are explicitly presented as unpopulated placeholders (`mean_travel_time_s: null`, `status: "Not implemented"`).

---

## 2. Backend REST API Endpoints Audit

| HTTP Method & Endpoint | Router File | Function Name | Purpose | Request Schema | Response Schema | Tested? | Operational Classification |
|---|---|---|---|---|---|:---:|---|
| `GET /` | `main.py:68` | `root()` | Service metadata and corridor links | None | Dict (`service`, `corridor`, `docs`, `health`, `websocket`) | Yes | **Working and tested** |
| `GET /api/health` | `routers/health.py:16` | `get_health()` | System health, SUMO binary version, simulation state | None | `HealthResponse` | Yes | **Working and tested** |
| `GET /api/simulation/status` | `routers/simulation.py:27` | `get_simulation_status()` | Current run state, elapsed sim time, mode, seed | None | `SimulationStatusResponse` | Yes | **Working and tested** |
| `POST /api/simulation/start` | `routers/simulation.py:33` | `start_simulation()` | Spawns background SUMO process & TraCI worker | `SimulationStartRequest` | `CommandResponse` | Yes | **Working and tested** |
| `POST /api/simulation/pause` | `routers/simulation.py:69` | `pause_simulation()` | Suspends simulation stepping loop | None | `CommandResponse` | Yes | **Working and tested** |
| `POST /api/simulation/resume` | `routers/simulation.py:78` | `resume_simulation()` | Resumes paused simulation loop | None | `CommandResponse` | Yes | **Working and tested** |
| `POST /api/simulation/stop` | `routers/simulation.py:87` | `stop_simulation()` | Clean shutdown with 5s join and Tier 2 watchdog | None | `CommandResponse` | Yes | **Working and tested** |
| `POST /api/simulation/reset` | `routers/simulation.py:96` | `reset_simulation()` | Resets in-memory state, metrics, and DB link | None | `CommandResponse` | Yes | **Working and tested** |
| `GET /api/traffic/live` | `routers/traffic.py:19` | `get_live_traffic()` | Latest snapshot of J1, J2, J3 queues and speeds | None | `TrafficLiveResponse` | Yes | **Working and tested** |
| `GET /api/traffic/metrics` | `routers/traffic.py:32` | `get_traffic_metrics()` | Cumulative vehicles, wait times, fuel, and emissions | None | `TrafficMetricsResponse` | Yes | **Working and tested** |
| `GET /api/signals` | `routers/signals.py:18` | `get_signals_info()` | Current signal phases, elapsed green, min/max bounds | None | `SignalsResponse` | Yes | **Working and tested** |
| `POST /api/signals/override` | `routers/signals.py:30` | `override_signal()` | Queues operator manual phase change via yellow shield | `SignalOverrideRequest` | `SignalOverrideResponse` | Yes | **Working and tested** |
| `GET /api/emergencies` | `routers/emergencies.py:15` | `get_emergencies_status()` | Active ambulance tracking, preemption locks, ETAs | None | `EmergencyResponse` | Yes | **Working and tested** |
| `GET /api/risks` | `routers/risks.py:14` | `get_risks_and_hotspots()` | MoRTH CRI risk zones and DBSCAN hotspot clusters | None | `RisksResponse` | Yes | **Working and tested** |
| `GET /api/decisions` | `routers/decisions.py:18` | `get_recent_decisions()` | Rolling history of controller actions (KEEP/SWITCH) | None | `DecisionsResponse` | Yes | **Working and tested** |
| `GET /api/experiments/compare` | `routers/experiments.py:27` | `get_controller_comparison()` | Multi-seed benchmark table (Baseline vs Coordinated) | None | `ExperimentCompareResponse` | Yes | **Working and tested** |
| `GET /api/experiments/history` | `routers/experiments.py:126` | `get_experiment_history()` | Historical simulation runs from SQLite database | None | `List[ExperimentHistoryItem]` | Yes | **Working and tested** |

---

## 3. Real-Time Telemetry Streaming: WebSocket `/ws/traffic`

### 3.1 Connection Protocol & Lifecycle
- **Endpoint:** `WS /ws/traffic`
- **Session Management:** `backend/websocket_manager.py` manages dedicated `ClientSession` instances.
- **Single-Writer Guarantee:** Exactly one asyncio task (`_writer_loop`) writes to each client's socket connection, eliminating socket interleaving.
- **Bounded Buffer & Drop Policy:** Each client has an `asyncio.Queue(maxsize=32)`. For replaceable telemetry frames (`TRAFFIC_UPDATE`), a **drop-oldest** policy is enforced if the buffer is saturated by a slow network client, ensuring memory never leaks and healthy clients are isolated.
- **Initial Handshake:** Immediately upon connection, the server sends an authoritative `INITIAL_STATE` payload containing `session_uuid`, initial `sequence_number`, simulation status, and complete corridor snapshot.
- **Heartbeat:** Clients can send `"ping"`; the server replies immediately with a non-replaceable `PONG` frame.

### 3.2 Monotonic Message Sequencing & Stale Frame Elimination
Every broadcast frame includes:
- `session_uuid`: A UUID v4 generated on each simulation start.
- `sequence_number`: A strictly monotonically increasing integer counter.
- `timestamp_utc`: ISO 8601 UTC timestamp.
The frontend `SnapshotRecoveryManager` and `TrafficWebSocket` track these fields:
- Discards out-of-order sequence frames within the active session.
- Rejects frames from superseded simulation sessions.
- Automatically initiates authoritative REST snapshot recovery if frame discontinuity is detected.

---

## 4. Frontend Component Inventory & Data Bindings

| Component File | UI Name / Purpose | Backend Data Source | Telemetry Feed (WS vs REST) | User Interactions | Operational Classification |
|---|---|---|---|---|---|
| `Header.jsx` | Top Navigation & Status Bar | `/api/health`, `/ws/traffic` | Live WS + Periodic REST poll | Tab switching, reconnect trigger | **Working and tested** |
| `OverviewKPIs.jsx` | 6 Core Executive KPI Cards | `metrics` object | Live WS (`TRAFFIC_UPDATE`) | None (Real-time display) | **Working and tested** |
| `LiveCorridorView.jsx` | SVG Schematic Corridor Topology | `junctions`, `signals`, `emergencies` | Live WS (`TRAFFIC_UPDATE`) | Lane queue inspection, signal indicators | **Working and tested** |
| `SignalStatusPanel.jsx` | Signal Phasing & Elapsed Timers | `signals`, `junctions` | Live WS (`TRAFFIC_UPDATE`) | Phase progress inspection | **Working and tested** |
| `SimulationControls.jsx` | Simulation Lifecycle Console | `/api/simulation/*` | REST POST actions | Start, Pause, Resume, Stop, Reset, Mode select | **Working and tested** |
| `EmergencyPanel.jsx` | Ambulance Preemption Tracker | `emergencies` object | Live WS (`TRAFFIC_UPDATE`) | Active preemption banner, ETA countdowns | **Working and tested** |
| `EmissionAnalytics.jsx` | CO2, NOx, and Fuel Area Charts | `metrics` history | Live WS (`TRAFFIC_UPDATE`) | Recharts timeline area chart (last 30 samples) | **Working and tested** |
| `RiskHotspotsPanel.jsx` | Blackspots & Risk Zones List | `/api/risks` | REST initial fetch | Tab toggling (Zones vs Hotspots) | **Working and tested** |
| `ControllerComparison.jsx` | Empirical Benchmark Bar Charts | `/api/experiments/compare` | REST initial fetch | Metric bar chart comparison, table view | **Working and tested** |
| `WhatIfScenario.jsx` | Historical Run Inspector & Sandbox | `/api/experiments/history` | REST poll (every 10s) | Launch scenario, review past run metrics | **Working and tested** |
| `App.jsx` (Modal) | Manual Signal Override Shield | `POST /api/signals/override` | REST POST action | Select TLS (J1/J2/J3), select phase, checkbox confirm | **Working and tested** |
| `App.jsx` (Banner) | Recovery Circuit Breaker Banner | `SnapshotRecoveryManager` | In-memory sync state | "Retry Sync" manual button | **Working and tested** |

---

## 5. Mock vs. Live Data Reality Check

A rigorous inspection of all frontend source files confirmed the following data-binding reality:

1. **No Simulated Random Number Generators in Active Telemetry:**
   - Previous development iterations in early prototypes frequently use `Math.random()` to animate charts when disconnected.
   - In the audited codebase, **all random generators have been eliminated from runtime telemetry**. When disconnected, the UI displays `OFFLINE` badges and retains the last synchronized snapshot rather than inventing phantom vehicle counts.
2. **Deterministic Historical Benchmarks:**
   - In `ControllerComparison.jsx`, the baseline and coordinated numbers are read directly from `outputs/corridor/corridor_multi_seed_summary.csv`.
   - The values (Baseline: 91.05s travel time, 27.85 km/h; Coordinated: 57.50s travel time, 36.40 km/h) represent real 5-seed SUMO experiment outputs.
3. **PPO & DQN Values Explicitly Null:**
   - The frontend gracefully renders empty state rows for PPO and DQN, correctly reflecting their status as "Not implemented".

---

## 6. Functional Robustness & Failure Modes

1. **Backend Unavailability:**
   - If the FastAPI server is shut down, the frontend transitions to `DISCONNECTED`, attempts reconnection with exponential backoff and randomized jitter, and surfaces a persistent failure banner after 3 failed recovery attempts.
2. **SUMO Binary Missing:**
   - `GET /api/health` reports `sumo_available: false` and includes the system error message.
   - `POST /api/simulation/start` fails synchronously with a clear HTTP 400 error: `"SUMO installation could not be found"`.
3. **Slow Network / Client Backpressure:**
   - If a frontend client pauses JavaScript execution (e.g., background browser tab), the backend `ClientSession` drops intermediate `TRAFFIC_UPDATE` frames without disconnecting the client. When resumed, the client receives the freshest frame or reconciles via snapshot.
4. **Mid-Simulation Crash:**
   - If `sumo.exe` crashes or is terminated by the user, the background simulation worker detects the dead process, escalates the watchdog, cleans up database status to `ERROR` or `KILLED_BY_WATCHDOG`, and halts the telemetry broadcast.

---

## 7. Feature Audit Verdict

The functional surface of the application is **cohesive, feature-complete for 2D corridor management, and fully integrated between backend services and frontend components**. There are no broken links, disconnected buttons, or dangling API routes. The entire 2D operations layer is production-grade.

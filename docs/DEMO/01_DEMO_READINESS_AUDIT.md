# Demo Sprint — Day 1: Full Application Readiness Audit

**Project:** Smart Traffic Coordination — Hybrid Traffic Control  
**Audit date:** 2026-11-05  
**Branch inspected:** `marl-p6-2-curriculum-training`  
**Scope:** Audit only. No application/config/training/checkpoint/result/data files were modified. No packages were installed and no training was launched. A time-bounded SUMO CLI run and temporary Vite server were stopped after checks. The backend was not started because its startup code initializes the existing workspace SQLite database and its required dependencies are absent.

## 1. Executive Summary

The frontend can be served locally: Vite 5.4.21 reported ready, and HTTP requests to `/` and `/src/main.jsx` returned 200. The configured frontend test suite passed **75/75** tests. SUMO 1.26.0 is installed, and a headless run using the project SUMO config completed to simulation time 60 with exit code 0.

The full application is **not demo-ready yet**. The only installed Python package is pip; FastAPI, SQLAlchemy, Pydantic, python-dotenv, NumPy, PyTorch, and pytest are absent. Consequently, the backend, application-level SUMO/TraCI connection, backend tests, and full UI → backend → SUMO telemetry loop could not be executed. Existing source and old test definitions describe intended integration but do not substitute for current execution evidence.

The current app offers Fixed-Time (`baseline`), Coordinated Adaptive (`coordinated`), PPO, and DQN. It does not expose MAPPO. The new P6 Stage A checkpoints under `checkpoints/p6/` are not the checkpoint paths used by the existing PPO/DQN runtime modes, which point to root-level historical `checkpoints/marl_ppo_corridor.json` and `checkpoints/marl_dqn_corridor.json`. Given missing Torch and no checkpoint inference test in this audit, do not demonstrate MARL as operational. Coordinated Adaptive is the intended demo choice, but it is **not verified working in this present environment** until the backend integration test runs.

**Readiness score: 48%** under the evidence-weighted method in Section 16. This score reflects demonstrated operational gates, not code completeness or visual quality.

## 2. Current Git and Working-Tree Status

**Status: VERIFIED (inspection only).** Branch remains `marl-p6-2-curriculum-training`; HEAD is `1d55856` (`feat(p6.1): complete pre-training validation gate...`). No branch switch or commit was made.

The pre-existing modified and untracked files include P6 source changes, routes, Stage A results/checkpoints, training script, and audit reports 27, 29, and 30. They were preserved. This report is the only new project file from this task. No report existed at `docs/DEMO/01_DEMO_READINESS_AUDIT.md` before creation.

## 3. Environment and Dependency Status

| Component | Observed status | Evidence / impact |
|---|---|---|
| Python | Python 3.13.14 at `C:\Program Files\Python313\python.exe` | `python --version`. |
| Python packages | `pip==26.1.2` only | `python -m pip list --format=freeze`; `importlib.util.find_spec` returned false for FastAPI, SQLAlchemy, Pydantic, dotenv, NumPy, Torch, pytest. Backend and Python test suite cannot run. |
| Node.js / npm | Node v22.21.1 / npm 10.9.4 | Version commands succeeded. |
| Frontend packages | Installed | `npm ls --depth=0 --prefix frontend` lists React 18.3.1, Vite 5.4.21, Three.js/React Three Fiber, Recharts and related dependencies. |
| SUMO | Eclipse SUMO 1.26.0, Windows AMD64 | `sumo --version`; binary resolves from PATH. |
| Python dependency manifest | None found | Prior environment audit (report 29) searched current/local history; frontend does have `package.json` and `package-lock.json`. Python environment is not reproducible from repository instructions today. |

`README.md` contains only a project title and one-line description; it has no app setup/run instructions. No root Python requirements/pyproject/lockfile is present. The prior runtime-design report 30 proposes a new runtime but explicitly awaits owner review/setup.

## 4. Backend Audit

| Area | Status | Evidence and impact |
|---|---|---|
| FastAPI entry and router registration | PARTIALLY WORKING (code present; not executed) | `backend/main.py`: `app`, lifespan and routers for health, simulation, traffic, signals, emergencies, risks, decisions and experiments. No runtime proof because FastAPI and SQLAlchemy are absent. |
| Lifecycle API | PARTIALLY WORKING (code path present) | `backend/routers/simulation.py`: GET `/api/simulation/status`; POST `/start`, `/pause`, `/resume`, `/stop`, `/reset`. Start accepts `baseline`, `coordinated`, `marl_ppo`, `marl_dqn`. These endpoints were not called. |
| Live metrics/signals | PARTIALLY WORKING (code path present) | `backend/routers/traffic.py` exposes `/api/traffic/live` and `/metrics`; `backend/routers/signals.py` exposes GET `/api/signals` and confirmed manual override POST `/api/signals/override`. No API responses were observed. |
| Emergency/status/comparison APIs | PARTIALLY WORKING (code path present) | `/api/emergencies`, `/api/health`, and `/api/experiments/compare` are registered. The comparison endpoint reads a historical CSV and uses fallback values; its values are not proof of a live controller comparison. |
| WebSocket | PARTIALLY WORKING (code path present) | `backend/main.py` implements `/ws/traffic`, sends `INITIAL_STATE`, and handles `ping`; `backend/simulation_service.py` broadcasts cached telemetry via the event loop. No live socket connection was made. |
| SUMO lifecycle | PARTIALLY WORKING (code path present) | `SimulationService.start_simulation()` starts a worker; `traffic_service/sumo_manager.py` launches SUMO via TraCI, captures process, and stops/terminates it; worker persists metrics and broadcasts. No integration run was possible. |
| Backend startup | NOT WORKING IN THE AVAILABLE ENVIRONMENT | Required packages are absent. Additionally, `backend.main.lifespan()` calls `init_db()`, while `backend/config.py` defaults `DATABASE_URL` to the repository's `traffic_dashboard.db`. Starting the app with defaults would write to an existing database. Startup was intentionally skipped to preserve it. |

No backend logs, HTTP responses, or runtime errors are available because it was not started. Lack of execution is an environment block, not evidence of a source defect.

## 5. SUMO Simulation Audit

**SUMO engine/config smoke check: VERIFIED WORKING.** Command executed:

```powershell
sumo -c sumo/silk_board/silk_board.sumocfg --end 60 --no-step-log true --duration-log.statistics false --verbose false
```

It exited with code 0 in about 1.35 seconds and produced no error output. The config selects `network/silk_board.net.xml`, `demand/silk_board.rou.xml`, and `demand/vehicle_types.add.xml`, uses one-second steps, and configures no simulation output files. This verifies SUMO can parse/load the configured input and advance a short run. It does **not** verify the Python TraCI connection, actual per-junction observations, route completion, controller timing, or process cleanup through the app.

The network declares static signal programs for the controller's J1 TLS `1617743335`, J2 TLS `GS_cluster_10282769895_10775075568_11964440742_11964440743`, and J3 TLS `6970466614`. The route file includes `corridor_j1_j2_j3` over edges `172853382#2`, `172853382#3`, `1148717038#0`, and `40696223#1`, and multiple flows use this route. `MultiIntersectionSimulation` maps the same TLS identifiers and corridor edges to J1/J2/J3. This is traceable topology/config evidence; a live vehicle trajectory across all three junctions was not recorded in this audit.

The configured route file contains `ambulance_0` on `corridor_j1_j2_j3` with `depart="420"`; its type is in `vehicle_types.add.xml`. A 300-second demo run cannot exercise this ambulance. The 600-second default can reach its injection point, but actual detection, preemption, clearance, and completion remain unverified.

The repository has an existing `tests/test_simulation_integration.py` with baseline and coordinated TraCI stepping/cleanup assertions. It was not run: pytest, NumPy, and the backend/TraCI imports are unavailable in the active interpreter.

## 6. Controller Audit

| Controller | Implementation / dispatch | Audit classification | Demo implication |
|---|---|---|---|
| Fixed-Time | SUMO `static` TLS programs; `MultiIntersectionSimulation.step()` baseline branch leaves phase cycling to SUMO | **PARTIALLY WORKING** | Config loads and advances in SUMO CLI; controller through Python app and API not verified. Candidate fallback demo only after integration run. |
| Coordinated Adaptive | `MultiIntersectionSimulation._run_coordinated_control()`; movement state from `IntersectionStateExtractor`; checks min/max timing and requests safe signal transitions | **PARTIALLY WORKING** | Intended strongest demo controller and preferred over MARL, but current backend integration unavailable. Do not call verified until `tests/test_simulation_integration.py::test_coordinated_mode_stepping` passes in the approved environment and UI flow is exercised. |
| Independent PPO | `PPOAgent`; selected by `marl_ppo`; checkpoint loaded from root-level `checkpoints/marl_ppo_corridor.json`; UI mode selector | **NOT TESTED** | Missing Torch prevents current runtime. Stage A checkpoint under `checkpoints/p6/` is not the default app checkpoint. Historical benchmark in UI is not proof of present inference. Avoid in demo. |
| Independent Double-DQN | `DQNAgent`; selected by `marl_dqn`; root-level `checkpoints/marl_dqn_corridor.json`; UI mode selector | **NOT TESTED** | Missing Torch prevents runtime. Historical P5 material documents a gridlocked/non-converged DQN result; avoid in demo. |
| MAPPO | MAPPO implementation exists in `traffic_service/ai/mappo_agent.py` / controller but no `marl_mappo` mode in backend validation, simulation dispatch, or frontend selector | **NOT WORKING as an integrated demo mode** | Do not claim MAPPO is available from the dashboard. |
| Emergency priority | `EmergencyWaveCoordinator.update()` observes emergency vehicle on corridor edges and locks J1/J2/J3 green progressively; `SignalController` sequences conflicting green through yellow | **PARTIALLY WORKING (source only)** | Ambulance route/type and code exist, but no preemption execution was observed. 300-second run misses 420s injection. Need a bounded 600-second app run and observed event before claiming works. |

The observations are local phase, phase elapsed/time-to-switch, per-approach queues, speed, waiting time, vehicle count, inflow/platoon context, emissions, and approaching-emergency flag (see `MultiIntersectionSimulation.get_ai_observations()`). Normal coordinated/MARL control uses `SignalController.request_switch()` so green-to-green transitions are intended to pass through yellow; configured app controllers use 15-second minimum and 60-second maximum green with a four-second yellow. For emergency mode, `lock_emergency_priority()` holds/extends the corridor phase and clears a conflicting phase through yellow. These are code-path findings, not test results from this environment.

## 7. Frontend Audit

| Feature | Status | Evidence / impact |
|---|---|---|
| Startup / app shell | **VERIFIED WORKING** | `npm run dev --prefix frontend -- --host 127.0.0.1 --port 5173 --strictPort`: Vite 5.4.21 ready in 953ms; GET `/` and `/src/main.jsx` returned 200. Server was stopped after check. |
| Frontend unit tests | **VERIFIED WORKING** | `npm test --prefix frontend`: 75 passed, 0 failed, 18 suites. |
| Dashboard sections | PARTIALLY VERIFIED | Source renders KPIs, controls, J1/J2/J3 topology cards, signals, emergencies, analytics, risks, sandbox and lazy-loaded 3D view. HTTP source serving is verified; visual behavior with backend payloads has not been browser-tested. |
| REST/WebSocket connectivity | NOT TESTED | `frontend/src/services/api.js` uses same-origin `/api`; `vite.config.js` proxies `/api` and `/ws` to localhost:8000. Backend unavailable, so requests/socket cannot connect. UI will show backend/offline/stale states. |
| Controller selection | PARTIALLY WORKING | UI lists Coordinated, Fixed-Time, PPO and DQN. MAPPO absent. PPO/DQN may fail due absent runtime packages and have not been loaded in this environment. |
| Live metrics and vehicle/queue display | NOT TESTED end-to-end | Components are wired to REST/WS data. SUMO CLI alone does not feed dashboard. Corridor view is a topology card view; 3D feature is separate/lazy and not visually verified. |
| Benchmark display | PARTIALLY WORKING / provenance caveat | `ControllerComparison.jsx` derives chart values dynamically from the API, correcting an older stale audit note that said the chart was hardcoded. However, backend `/experiments/compare` reads archived CSV plus hardcoded fallback metrics; the chart is not a live-run comparison. Label historical benchmark data clearly. |
| Emergency visualization | NOT TESTED with live event | `EmergencyPanel.jsx` and `LiveCorridorView.jsx` consume emergency/lock status, but no actual ambulance event reached the UI. |

## 8. End-to-End Integration Audit

| Link | Status | Evidence |
|---|---|---|
| React UI → Vite | **VERIFIED** | Vite started, served dashboard source; 75 frontend tests passed. |
| React UI → FastAPI REST | NOT TESTED | Correct same-origin API calls and Vite proxy are present. Backend packages absent; no API server. |
| React UI → WebSocket | NOT TESTED | `/ws/traffic` path and proxy match in source; no server/client session evidence. |
| FastAPI → SimulationService | NOT TESTED | Route handlers call lifecycle methods, but FastAPI cannot import in current env. |
| SimulationService → SUMO/TraCI | NOT TESTED | Source uses `SumoManager` / TraCI. SUMO CLI success is not TraCI evidence. |
| SUMO → controller → signal updates | NOT TESTED | Integration test definitions exist; none ran. |
| Worker → websocket payload → UI rendering | NOT TESTED | Source wires broadcast and subscriptions; no live payload observed. |
| Stop/cleanup through API | NOT TESTED | Code includes `stop_simulation()` and `SumoManager.stop()`; no process PID lifecycle was observed. |

The complete requested flow is therefore **not verified**. Do not describe the application as live-integrated on the basis of source paths alone.

## 9. Working Features

- Frontend Vite development server and module serving: verified on this machine.
- Frontend test suite: 75/75 pass.
- SUMO 1.26.0 binary and configured network/route/vehicle-type input load: verified for a 60-second headless CLI run.
- Corridor route definition and J1/J2/J3 TLS identifiers: traceable in SUMO XML and simulation source.
- Backend REST, lifecycle, telemetry, websocket, controller and emergency code paths: present, but not operationally verified here.

## 10. Broken or Incomplete Features

1. **Python backend cannot start in current environment.** Required dependencies are absent, and no Python manifest/setup guide exists.
2. **MAPPO is not an integrated user-selectable mode.** App and backend only dispatch baseline/coordinated/PPO/DQN.
3. **Historical comparison data can look live.** The component is dynamically bound, but the API reads archived CSV/fallback values rather than current simulation runs.
4. **Emergency demonstration timing is constrained.** Ambulance departs at 420 seconds; 300-second runs will not exercise it.
5. **No current end-to-end evidence.** API/WebSocket/TraCI/controller/signal/stop behavior is unverified after current environment changes.

## 11. Untested Features

- Backend server startup/health endpoint, API lifecycle, current SQLite schema initialization and persistence.
- Python pytest suite, including integration and runtime-dispatch tests.
- SUMO launched from `SumoManager` over TraCI, state extraction for all junctions, vehicle movement/completion, and process cleanup.
- Fixed-time or coordinated control through the app, signal changes, live queue/metrics updates.
- PPO/DQN model load and inference from the checkpoint paths used by the app.
- Emergency injection, detection, progressive preemption, and UI indication.
- Browser rendering of the React app connected to a running backend; 3D scene behavior.

## 12. P0/P1/P2 Priority Matrix

| Priority | Feature | Day 1 assessment | Next action |
|---|---|---|---|
| P0 | Reproducible backend runtime | Blocked | Owner-approved isolated Python environment and dependencies; avoid touching existing DB during smoke tests by using a disposable database path. |
| P0 | Three-junction SUMO via backend/TraCI | Config CLI verified, application unverified | Run baseline and coordinated integration tests; inspect live J1/J2/J3 telemetry and process cleanup. |
| P0 | Frontend connects to API and live websocket | Unverified | Start API with isolated DB; verify health, initial snapshot, websocket telemetry, controls. |
| P0 | Reliable demo controller | None fully verified in current environment | Verify Coordinated Adaptive first; keep Fixed-Time as fallback only after application integration passes. |
| P0 | Emergency preemption | Code and route exist, execution unverified | Use at least 600-second run and confirm injection at t=420, preemption stage transitions and UI display. |
| P1 | Honest benchmark presentation | API reads archived/static benchmark data | Show as historical benchmark and separate from current live run metrics. |
| P1 | Clear demo instructions / startup script | Missing from README | Document two-terminal startup, env variables, known timing, stop behavior after verification. |
| P2 | MAPPO demo mode | Not integrated and not required for this demo | Keep research work out of the college walkthrough. |
| P2 | Advanced 3D visualization | Present as lazy-loaded source, not visually verified | Optional only after core 2D flow is stable. |

## 13. Five Biggest Demo Blockers

1. **No usable Python backend dependencies.** FastAPI and other required packages are absent; the API has not started.
2. **No safe, verified application start path.** Current backend startup writes/initializes the existing repository SQLite database by default; no disposable DB startup was attempted.
3. **No end-to-end TraCI evidence in the current environment.** A SUMO CLI smoke run does not validate controller dispatch, live state, WebSocket metrics or clean API stop.
4. **No verified demo controller.** Fixed-Time and Coordinated Adaptive have code/test definitions but the backend integration tests could not run. PPO/DQN are additionally unverified and DQN has poor historical benchmark results.
5. **Emergency event has not been demonstrated.** The ambulance enters at 420s, and neither live preemption nor the UI status was exercised.

## 14. Recommended 7-Day Implementation Sequence

**Day 2 — Establish and prove runtime.** After owner approval, create the isolated Python environment following report 30, install only the reviewed backend/MARL dependencies, use a disposable SQLite DB, record exact versions, run imports and focused baseline/coordinated integration tests. No training.

**Day 3 — Prove application SUMO lifecycle.** From the backend, start a short Fixed-Time simulation, confirm SUMO PID, simulation time and J1/J2/J3 states, stop it, and verify no process remains. Then repeat with Coordinated Adaptive.

**Day 4 — Prove the demo flow.** Connect browser to backend; verify REST health, initial WebSocket snapshot, changing signal phases, vehicle counts/queues/metrics, and controls. Fix only blockers found by these checks.

**Day 5 — Emergency demonstration.** Run a bounded 600-second Coordinated Adaptive scenario; verify the t=420 ambulance route, preemption at each junction, clear/recovery behavior, and visible UI status. If it fails, omit the emergency claim rather than simulate it visually.

**Day 6 — Demo polish and truthful labels.** Clearly distinguish historical benchmarks from live metrics, hide or disable unverified PPO/DQN/MAPPO modes for the demo if owner authorizes changes, add minimal run instructions and error/loading behavior.

**Day 7 — Freeze and rehearse.** Use a fixed seed and duration, repeat the full start → observe → emergency → stop sequence twice, record a fallback path, and avoid changes after final rehearsal.

## 15. Exact Commands to Start the Application

The commands below are the expected local commands; the backend command is **not currently executable** because dependencies are missing. Use two terminals from the repository root. Backend startup initializes the database, so on Day 2 it must be given a new disposable DB path before launch; do not run with the current default path during an audit.

**Backend (after authorized runtime setup; safe disposable DB value shown):**

```powershell
$env:DATABASE_URL = "sqlite:///./demo_audit_disposable.db"
$env:SUMO_HOME = "C:\Program Files (x86)\Eclipse\Sumo"
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

This command will create/write `demo_audit_disposable.db` in the working directory and therefore must be run only in an approved setup/demo run. The audit did not execute it.

**Frontend (verified):**

```powershell
npm run dev --prefix frontend -- --host 127.0.0.1 --port 5173 --strictPort
```

Open `http://127.0.0.1:5173/`. Frontend source proxy sends `/api` and `/ws` to `127.0.0.1:8000`.

**SUMO headless config smoke check (verified bounded command):**

```powershell
sumo -c sumo/silk_board/silk_board.sumocfg --end 60 --no-step-log true --duration-log.statistics false --verbose false
```

This is not a substitute for starting SUMO through the backend's TraCI manager.

## 16. Final Demo Readiness Assessment

### Readiness score: 48%

Scoring method: six operational evidence gates totaling 100 points. Full points require execution evidence, not source presence.

| Gate | Weight | Earned | Reason |
|---|---:|---:|---|
| Frontend starts and UI modules serve | 20 | 20 | Vite ready; both HTTP checks returned 200; tests pass. |
| Frontend tests | 10 | 10 | 75/75 pass. |
| SUMO network/config short-run | 20 | 14 | SUMO CLI exited 0 at 60s; route/topology definitions present, but no observed vehicle route completion or TraCI control. |
| Backend starts and APIs answer | 20 | 0 | Missing dependencies; startup not run. |
| App-to-SUMO/controller lifecycle | 20 | 0 | No current application integration evidence. |
| Emergency preemption event verified | 10 | 4 | Route/type and control code exist, but no event execution; t=420 timing known. |
| **Total** | **100** | **48** | **Not ready for a live integrated demonstration yet.** |

Answers to the required questions:

- **Frontend starts?** Yes. Vite served the UI source successfully; 75/75 frontend tests passed.
- **Backend starts?** Not in the current environment. FastAPI and required packages are absent; no startup was attempted because default startup mutates the existing SQLite database.
- **Does SUMO run all three intersections?** The configured network loads and a 60-second SUMO headless run exits successfully; J1/J2/J3 TLS IDs and corridor route appear in config/source. Vehicle progression through all three and completion were not observed in this audit.
- **Do frontend, backend, and SUMO communicate successfully?** Not verified. The frontend-to-API/WebSocket path is wired in source, but backend dependencies are missing and no TraCI application run occurred.
- **Which controller can be demonstrated reliably?** None is verified through the full app in this environment. Coordinated Adaptive is the recommended first candidate once focused integration tests pass; Fixed-Time is the fallback candidate after its app-level test passes. Do not demonstrate PPO/DQN as operational, and MAPPO is not integrated.
- **Does emergency preemption work?** Code and ambulance input exist, but operation is not verified. A 300-second run cannot reach the scheduled t=420 ambulance departure.
- **Single highest-priority Day 2 task:** establish an owner-approved isolated Python runtime, then prove backend startup with a disposable database and run focused baseline/coordinated SUMO integration tests. This unlocks the rest of the demo work without touching P6 results or the existing database.

**Final status: NOT READY for a live full-stack college demo until the Day 2 runtime/backend and controller integration gates pass.** A visual frontend-only walkthrough is possible, but it must be presented as disconnected/mock-free UI rather than a live traffic simulation.

# Demo Sprint — Day 2: Isolated Runtime and Backend Integration Report

**Project:** Smart Traffic Coordination — Hybrid Traffic Control  
**Date:** 2026-11-05  
**Branch / HEAD:** `marl-p6-2-curriculum-training` / `1d55856b1d8b53278d142537f43e1c79314993a7`  
**Scope:** Isolated runtime setup and bounded backend/SUMO integration validation. No global packages were installed, SUMO was not updated, no training was run, and no P6 artifacts/results/datasets/historical reports were touched. The pre-existing application SQLite database was not opened or modified.

## Summary

The isolated environment `.venv-demo` was created with the existing 64-bit Python 3.13.14 and ignored by Git using one `.gitignore` addition. A version-locked package snapshot was recorded in [`requirements-demo.lock.txt`](../../requirements-demo.lock.txt). TraCI and sumolib resolve from the installed SUMO 1.26.0 `tools` tree.

FastAPI started successfully against the approved disposable SQLite URL. Health/status/live/metrics/signals/emergencies APIs responded. Fixed-Time and Coordinated Adaptive both ran through the FastAPI → SimulationService → SUMO/TraCI path for 120 simulated seconds, returned J1/J2/J3 telemetry, and completed cleanly. An additional coordinated-control diagnostic observed 25 decision calls, accepted switch requests, phase changes and yellow phases at every junction. The explicit API stop endpoint also stopped SUMO and the captured process disappeared.

The Vite proxy returned the backend health response; its proxied WebSocket delivered an `INITIAL_STATE` containing J1/J2/J3 and answered ping with PONG. This confirms proxy connectivity and protocol exchange, but the React page was not browser-automated to verify rendered values.

## 1. Initial Git Status and HEAD

Before setup, HEAD was `1d55856b1d8b53278d142537f43e1c79314993a7` on branch `marl-p6-2-curriculum-training`. Existing modified files included the P6 route/controller/tracker/curriculum/simulation changes. Existing untracked items included P6 checkpoints/results/routes/training script and reports 27, 29, 30, plus the Day 1 report. These remain preserved.

This task added only:

- `.venv-demo/` ignore entry to `.gitignore` (required because the existing `.venv` rule did not match `.venv-demo`).
- New, ignored `.venv-demo/` environment.
- New, ignored `demo_audit_disposable.db` created by backend startup.
- [`requirements-demo.lock.txt`](../../requirements-demo.lock.txt), an exact `pip freeze --all` snapshot for the isolated environment.
- This report.

No branch/commit changes, resets, clean/stash operations, or modifications to pre-existing P6 artifacts were made.

## 2. Python Interpreter and Runtime Versions

| Component | Observed value |
|---|---|
| Python executable | `C:\Program Files\Python313\python.exe` base; `.venv-demo\Scripts\python.exe` for all checks |
| Python | 3.13.14 x64 |
| pip | 26.1.2 |
| SUMO executable | `C:\Program Files (x86)\Eclipse\Sumo\bin\sumo.exe` |
| SUMO | Eclipse SUMO 1.26.0, Windows AMD64 |
| SUMO_HOME | `C:\Program Files (x86)\Eclipse\Sumo` |
| TraCI import | `C:\Program Files (x86)\Eclipse\Sumo\tools\traci\__init__.py` |
| TraCI `__version__` attribute | `0.0.0` (module value is non-informative; version is established by bundled path and successful SUMO 1.26.0 TraCI runs) |
| sumolib import / version | `C:\Program Files (x86)\Eclipse\Sumo\tools\sumolib\__init__.py` / `1.26.0` |

The SUMO tools directory was placed on `PYTHONPATH` before importing `traffic_service`. This is necessary because `traffic_service.__init__` imports `sumo_manager`, which imports `traci` before `require_sumo_env()` can add the tools path at runtime. No separate pip `traci` or `sumolib` package was installed.

## 3. Dependency Installation Record

**Status: PASSED.** The resolver installed dependencies only into `.venv-demo`; it selected Windows CPython 3.13 wheels for the compiled packages. No global Python package was installed or upgraded. PyTorch was deliberately omitted: baseline/coordinated controller integration does not use it, and this task does not validate MARL.

Top-level packages and resolved versions:

| Package | Version | Reason |
|---|---:|---|
| FastAPI | 0.162.0 | Backend app, REST and WebSocket routes |
| Uvicorn | 0.54.0 | Local ASGI server; `standard` extra includes WebSocket/runtime support |
| SQLAlchemy | 2.1.8 | Backend models and disposable SQLite database |
| python-dotenv | 1.2.4 | Backend config import |
| NumPy | 2.5.4 | Application and traffic-analysis imports |
| scikit-learn | 1.9.1 | Risk router import / DBSCAN hotspot path |
| pytest | 9.2.0 | Focused integration tests |
| HTTPX | 0.28.1 | API calls and ASGI testing dependency |

Transitive packages and exact versions are pinned in `requirements-demo.lock.txt`, including Pydantic 2.14.3, Starlette 1.10.0, SciPy 1.18.1, AnyIO 4.16.0, WebSockets 17.4, and pip 26.1.2. This lock records resolver output; no global package inventory was changed. The bundle was validated by actual imports, backend startup, API requests, tests, and live TraCI sessions. It is a Day 2 demo runtime, not the historical Stage A environment.

## 4. SUMO, TraCI, and sumolib Verification

**Status: PASSED.** `sumo --version` returned Eclipse SUMO 1.26.0. `SUMO_HOME` was already set to the installation root. Both Python modules imported from the same installation's `tools` directory. `sumolib.__version__` returned 1.26.0; the bundled TraCI module reports `__version__ == "0.0.0"`, so that attribute is not treated as an actual release identifier. SUMO 1.26.0 loaded and ran from the application through TraCI in the focused tests and API runs.

## 5. Database Isolation Verification

**Status: PASSED.** `backend/config.py` reads `DATABASE_URL` from the process environment; when set to `sqlite:///./demo_audit_disposable.db`, `backend.database.engine.url` reported exactly that URL and database name. The path did not exist before Uvicorn startup. Backend lifespan calls `init_db()`, which created and populated the disposable file as expected. Startup did not use the default URL.

Inspection found no other hard-coded `traffic_dashboard.db` database writer in backend/service startup; the default path is defined in `backend/config.py`, and test database setup uses in-memory SQLite. The pre-existing `traffic_dashboard.db` remained at 1,544,192 bytes with last-write time `2026-11-04 21:57:44` before and after the integration checks. The new disposable database is 81,920 bytes and is ignored by the existing `*.db` rule.

## 6. Backend Startup Evidence

**Status: PASSED.** With `SUMO_HOME`, `PYTHONPATH` and `DATABASE_URL` configured as below, this command started Uvicorn:

```powershell
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --log-level info
```

Observed startup output:

```text
INFO:     Started server process [3584]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

The app imported with 14 registered routes. Uvicorn was stopped with Ctrl+C after the checks; port 8000 was no longer listening afterward. A second bounded start/stop check also ended with no listening backend port or SUMO process.

## 7. Health and API Responses

**Status: PASSED.** The direct REST requests returned successful typed responses:

- `GET /api/health`: HTTP 200; `status="ok"`, `sumo_available=true`, `sumo_version="Eclipse SUMO sumo 1.26.0"`, `active_simulation=false`.
- `GET /api/simulation/status`: HTTP 200; initial STOPPED state, mode coordinated, junctions `J1`, `J2`, `J3`.
- `GET /api/traffic/live`: HTTP 200; response contains J1/J2/J3.
- `GET /api/traffic/metrics`: HTTP 200; simulation time 0.0 before start.
- `GET /api/signals`: HTTP 200; response contains J1/J2/J3.
- `GET /api/emergencies`: HTTP 200; no active emergency before a run.

## 8. Fixed-Time Integration Results

**Focused test: PASSED.**

```text
python -m pytest -q -p no:cacheprovider tests/test_simulation_integration.py::test_simulation_lifecycle_and_state_extraction
1 passed in 2.09s
```

The existing test starts `MultiIntersectionSimulation` in `baseline` mode, advances SUMO through TraCI for 15 steps, reads J1/J2/J3 states, checks phase/queue/speed/emissions fields and AI observations, and calls `sim.close()` in `finally`, asserting SUMO is no longer running.

**Backend/API run: PASSED.** `POST /api/simulation/start` with mode `baseline`, duration 120 and seed 42 returned HTTP 200 and a SUMO PID. The status API reached simulation time 120 and `COMPLETED`, with no error. Status, signals, and traffic APIs exposed J1/J2/J3; observed phases included 0–3, total live vehicle observations peaked at 42, and the sampled queue sum peaked at 26. The run's captured PID 3716 was absent from the process list afterward. These are integration observations, not a comparative performance claim.

## 9. Coordinated Adaptive Integration Results

**Focused test: PASSED.**

```text
python -m pytest -q -p no:cacheprovider tests/test_simulation_integration.py::test_coordinated_mode_stepping
1 passed in 2.11s
```

The existing test starts the coordinated mode, advances 20 steps, checks metrics and closes SUMO in `finally`. Since it does not assert control decisions, switch success, or yellow clearance, an additional bounded in-memory diagnostic wrapped the original `_run_coordinated_control()` and `request_switch()` methods without changing their behavior. Over 120 simulated seconds it observed 25 coordinated-control calls with observations for all three junctions, five accepted switch requests (J1 at 20s and 95s; J2 at 85s and 105s; J3 at 110s), six phase changes per junction, and phase IDs 0, 1, 2, and 3 at each junction. Yellow phases 1/3 appeared at all three junctions. Maximum sampled total queues were J1=3, J2=7, J3=4.

**Backend/API run: PASSED.** A coordinated run through `POST /api/simulation/start` (duration 120, seed 42, emergency disabled) returned HTTP 200, reached simulation time 120, and ended `COMPLETED` with no error. The runtime status identified the controller as `Coordinated Adaptive (Inflow-Aware + Green Wave)`. J1/J2/J3 signals and live traffic were returned; phase IDs 0–3 appeared at each junction. Sampled live vehicle-count sum peaked at 30 and queue sum at 11. Captured SUMO PID 11664 was absent afterward.

## 10. Explicit API Stop and SUMO Process Cleanup

**Status: PASSED.** A further coordinated API run (seed 43, duration 600) was started and allowed to reach simulation time 5. `POST /api/simulation/stop` returned HTTP 200 with `Simulation stopped successfully and resources released.` Final status was STOPPED, `running=false`, and PID null. Windows `tasklist` returned no row for captured SUMO PID 28848. No `sumo`/`sumo-gui` process remained, and backend/frontend listener ports 8000/5173 were closed after shutdown.

## 11. Frontend REST/WebSocket Connectivity

**REST proxy: PASSED.** Vite started with the existing frontend package set. `GET http://127.0.0.1:5173/api/health` returned HTTP 200 and the backend health payload, confirming the `/api` proxy.

**WebSocket proxy: PASSED.** A WebSocket client connected to `ws://127.0.0.1:5173/ws/traffic`; Vite proxied it to FastAPI. The first message was `INITIAL_STATE` with status STOPPED and junctions J1/J2/J3. Sending `ping` received `PONG`. This validates the proxy and protocol messages. The browser-rendered React component state was not independently inspected in a browser.

## 12. Failures and Unresolved Blockers

- No failure occurred in the focused Fixed-Time or Coordinated Adaptive checks.
- The first Fixed-Time pytest invocation emitted a `PytestCacheWarning` because the existing `.pytest_cache` path denied a cache write. It still passed; the final rerun with `-p no:cacheprovider` passed without the warning and avoided touching that cache.
- `traci.__version__` is `0.0.0`, not a usable SUMO release number. Import path, `sumolib` version 1.26.0, and successful SUMO 1.26.0 protocol runs establish which bundle was used.
- Browser-rendered DOM/visual state was not tested; only Vite startup, REST proxy, and WebSocket proxy/state exchange were verified.
- Emergency preemption was not exercised in this task. The configured ambulance departs at t=420, so the 120-second tests could not validate it. No MARL mode, checkpoint, or inference path was tested.
- The new lock uses resolved package versions and does not include hashes. Reinstallation requires a working package index; for stronger supply-chain reproducibility, generate and review a hash lock separately before distributing the runtime.

## 13. Exact Reproducible Commands

From repository root in PowerShell, using the environment already created:

```powershell
$env:SUMO_HOME = "C:\Program Files (x86)\Eclipse\Sumo"
$env:PYTHONPATH = "$env:SUMO_HOME\tools;$PWD"
$env:DATABASE_URL = "sqlite:///./demo_audit_disposable.db"
```

Start the backend:

```powershell
.\.venv-demo\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --log-level info
```

Run focused integration tests in another terminal with the same `SUMO_HOME` and `PYTHONPATH`:

```powershell
.\.venv-demo\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_simulation_integration.py::test_simulation_lifecycle_and_state_extraction
.\.venv-demo\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_simulation_integration.py::test_coordinated_mode_stepping
```

Start the frontend in another terminal:

```powershell
npm run dev --prefix frontend -- --host 127.0.0.1 --port 5173 --strictPort
```

Open `http://127.0.0.1:5173/`. Stop API simulations from the UI or via `POST /api/simulation/stop`; then stop Uvicorn with Ctrl+C. Do not start Uvicorn without the disposable `DATABASE_URL` during the demo sprint, since its default points at `traffic_dashboard.db`.

To recreate package versions in a new ignored environment (after confirming it does not already exist):

```powershell
python -m venv .venv-demo
.\.venv-demo\Scripts\python.exe -m pip install -r requirements-demo.lock.txt
```

The lock includes pip and transitive package pins. SUMO remains an external prerequisite and supplies TraCI/sumolib through `SUMO_HOME\tools`.

## 14. Day 3 Recommendation

**Proceed to a controlled browser demonstration rehearsal using Coordinated Adaptive.** Verify actual rendered phase/queue/metric changes during a run and visually confirm the stop control. Then run one bounded 600-second scenario with emergency enabled to test the t=420 ambulance injection, progressive preemption, recovery, and UI indication. Keep Fixed-Time as the verified fallback. Do not include PPO/DQN/MAPPO claims or Stage B/C training in the demo path.

**Day 2 result: PASSED for isolated backend + Fixed-Time/Coordinated SUMO integration.**

# Milestone Audit: Backend Architecture & API Layer

**Project:** Bengaluru Smart Traffic Coordination System  
**Audit Scope:** FastAPI configuration, lifecycle handlers, background workers, thread safety, REST endpoints, WebSocket streaming, database persistence, and security  
**Auditor:** Principal Software Architect & Production QA Engineer  
**Date:** October 30, 2026  
**Status:** COMPLETE (Read-Only Audit)

---

## 1. Executive Summary

The backend service is structured cleanly around FastAPI 0.141.1, Starlette 1.3.1, and SQLAlchemy 2.0.52. It exposes 8 REST routers and a WebSocket telemetry stream, backed by an SQLite database (`traffic_dashboard.db`). Background simulation stepping runs on a dedicated daemon worker thread managed by `SimulationService`.

All 12 REST API tests and the WebSocket protocol test execute and pass successfully. However, several architectural, concurrency, and security weaknesses were identified:
1. **Unsynchronized Reads on Shared State:** While state mutations inside `SimulationService` use `threading.Lock()`, several REST endpoints read attributes (such as `sim_service._current_sim_time`) directly without acquiring the lock.
2. **Hardcoded CORS Origins:** CORS origins are hardcoded with defaults pointing to local Vite ports and lack production environment parametrization.
3. **Deprecated Datetime UTC Methods:** `datetime.utcnow()` is used across models and services, throwing 32 Python 3.13 deprecation warnings.
4. **WebSocket Heartbeat Discrepancy:** The frontend sends text `"ping"`, and the backend responds with `{"type": "PONG"}`. If an unhandled exception occurs on client disconnect, the connection manager relies on a blanket `except Exception:` clause.
5. **Decoupled Comparison Endpoint:** The endpoint `/api/experiments/compare` parses a static CSV file (`corridor_multi_seed_summary.csv`) on disk instead of querying the historical runs in the database.

---

## 2. Framework & Lifespan Architecture

### 2.1 Initialization (`backend/main.py`)
- **Lifespan Context:** Implemented using `@asynccontextmanager async def lifespan(app: FastAPI)`:
  - Initializes database schema via `init_db()` and seeds documented risk zones if empty.
  - Captures the active `asyncio` event loop via `asyncio.get_running_loop()` and passes it to `sim_service.set_event_loop(loop)`.
  - On shutdown, invokes `sim_service.stop_simulation()` to terminate TraCI and join the worker thread.
- **Routers Registered:**
  - `/api/health` (`routers/health.py`)
  - `/api/simulation` (`routers/simulation.py`)
  - `/api/traffic` (`routers/traffic.py`)
  - `/api/signals` (`routers/signals.py`)
  - `/api/emergencies` (`routers/emergencies.py`)
  - `/api/risks` (`routers/risks.py`)
  - `/api/decisions` (`routers/decisions.py`)
  - `/api/experiments` (`routers/experiments.py`)
  - `/ws/traffic` (WebSocket endpoint on root app)

---

## 3. Background Worker & Thread Safety Audit

### 3.1 Worker Thread Lifecycle
- When `/api/simulation/start` is called, `sim_service.start_simulation()` verifies no simulation is currently active, writes an initial `SimulationRun` row with status `RUNNING`, and spawns:
  ```python
  self._thread = threading.Thread(
      target=self._run_simulation_worker,
      daemon=True,
      name="SumoSimulationWorker",
  )
  self._thread.start()
  ```
- The worker executes a loop stepping SUMO:
  - Computes emergency preemption updates.
  - Executes adaptive coordination decisions every 5.0 seconds.
  - Persists metrics every 5.0 seconds.
  - Schedules WebSocket broadcasts via `asyncio.run_coroutine_threadsafe(ws_manager.broadcast(payload), self.loop)`.
  - Introduces `time.sleep(0.02)` pacing to prevent 100% CPU thread starvation.

### 3.2 Concurrency & Lock Analysis
- **Synchronization Mechanism:** `self._lock = threading.Lock()`
- **Protected Operations:** `start_simulation`, `pause_simulation`, `resume_simulation`, `stop_simulation`, `reset_simulation`, and in-memory telemetry writes (`self._current_sim_time`, `self._latest_states`, `self._cached_metrics`).
- **Defects / Lock Leaks:**
  1. In `routers/signals.py` line 56:
     ```python
     simulation_time=sim_service._current_sim_time  # Read directly without acquiring sim_service._lock!
     ```
  2. In `routers/simulation.py` lines 64, 76, 83:
     `sim_service._current_sim_time` is accessed directly for command responses outside the lock.
  3. In `simulation_service.py` line 234:
     `self._thread.join(timeout=5.0)` is correctly called outside the lock to prevent deadlock, but if the thread fails to terminate within 5 seconds, `_cleanup_sim()` forcefully sets `_running = False` while TraCI might still be in an indeterminate state.

---

## 4. REST API Endpoint Analysis & Tracing

### 4.1 Trace: Simulation Lifecycle (`/api/simulation/*`)
- `POST /api/simulation/start`:
  - **Payload Validation:** Pydantic `SimulationStartRequest`: validates `mode in ['baseline', 'coordinated']`, `duration >= 10`, `step_length > 0`, `decision_interval >= 1.0`.
  - **Behavior:** Returns `409 Conflict` if already running; returns `400 Bad Request` if invalid mode; returns `422 Unprocessable Entity` if duration < 10.
- `POST /api/simulation/pause`:
  - Changes status to `PAUSED`. Worker thread pauses stepping and sleeps 100ms per iteration.
- `POST /api/simulation/resume`:
  - Clears `_paused` flag; worker resumes stepping.
- `POST /api/simulation/stop`:
  - Signals stop requested, joins thread, updates DB status to `STOPPED`, and terminates TraCI.
- `POST /api/simulation/reset`:
  - Invokes stop, clears in-memory queues, resets time to 0.0.

### 4.2 Trace: Live Telemetry (`/api/traffic/live`)
- Fetches `sim_service.get_live_junctions()`.
- Reads cached `_latest_states` under lock.
- If stepping has not started, returns clean placeholder `JunctionStateSchema` objects with zeroed queues and default signal phases.
- Verified: Frontend receives authentic live SUMO junction state.

### 4.3 Trace: Manual Signal Override (`/api/signals/override`)
- Requires `{ junction_id: "J2", target_phase: 0, confirmed: true }`.
- If `confirmed` is `False`, raises `HTTP 400`.
- In `sim_service.request_manual_override()`:
  - If emergency lock is active on that junction, rejects override to preserve life safety.
  - If valid, sets phase via `ctrl.request_switch(target_green_phase, sim_time, force=True)` and logs decision with `is_override=True`.

### 4.4 Trace: Experiment Comparisons (`/api/experiments/compare`)
- **Issue:** Instead of querying the database table `simulation_runs` and computing statistical aggregations across actual executed runs, it reads `outputs/corridor/corridor_multi_seed_summary.csv` from disk with fallback defaults.
- **Impact:** Dynamic experiment runs completed by the user do not automatically update this endpoint unless `evaluate_corridor.py` is executed externally.

---

## 5. WebSocket Telemetry & Reliability

- **Endpoint:** `WS /ws/traffic`
- **Manager:** `ConnectionManager` in `backend/websocket_manager.py` maintains `active_connections: list[WebSocket]`.
- **Connection Handshake:**
  Upon connection, server immediately sends an `INITIAL_STATE` packet with current simulation time, mode, metrics, junctions, signals, and recent decisions.
- **Heartbeat & Keepalive:**
  - Frontend client sends text `"ping"` every 15 seconds.
  - Server replies with `{"type": "PONG"}`.
  - Disconnects are caught and pruned from `active_connections`.
- **Broadcast Architecture:**
  The background worker thread broadcasts telemetry via:
  ```python
  asyncio.run_coroutine_threadsafe(ws_manager.broadcast(payload), self.loop)
  ```
  This is thread-safe and verified non-blocking.

---

## 6. Database Schema & Persistence

### 6.1 Models (`backend/models.py`)
1. **`SimulationRun`**: Primary record of each simulation run (`run_uuid`, `mode`, `status`, `seed`, `duration_requested`, `duration_simulated`, timestamps).
2. **`TrafficMetricRecord`**: Snapshots taken every 5.0 seconds of corridor queue, wait time, speed, CO2, and fuel.
3. **`SignalDecisionRecord`**: Chronological log of controller phase decisions and reasons.
4. **`EmergencyEventRecord`**: Emergency preemption tracking and traversal durations.
5. **`RiskZoneRecord`**: Pre-seeded accident blackspots and risk scores.

### 6.2 SQLite Concurrency
- `connect_args={"check_same_thread": False}` is set on the SQLite engine.
- Session lifecycle: Each write creates and closes an independent `SessionLocal()` within a try-finally block.
- Tested: Concurrent DB writes during rapid stepping passed without database lock errors.

---

## 7. Security, Configuration & Deprecations

1. **Secrets Handling:** No plaintext secrets or passwords exist in the repository. Environment variables are loaded via `.env` with fallback defaults.
2. **CORS:** Defaults to `http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000`. Production deployments must allow setting dynamic domain whitelists.
3. **Deprecation Warnings:**
   - 32 warnings generated by `datetime.datetime.utcnow()`:
     ```
     DeprecationWarning: datetime.datetime.utcnow() is deprecated and scheduled for removal in a future version. Use timezone-aware objects: datetime.datetime.now(datetime.UTC).
     ```
   - Starlette test client deprecation:
     ```
     StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated; install httpx2 instead.
     ```

---

## 8. Audit Verdict & Scorecard

| Area | Score (1–10) | Evaluation |
|---|---|---|
| API Design & Cleanliness | **9/10** | Consistent REST semantics, typed schemas, clean separation |
| Validation & Error Handling | **8/10** | Robust Pydantic models; 400/409/422 status codes properly used |
| Simulation Concurrency | **7/10** | Good background worker, but some un-synchronized property reads |
| WebSocket Reliability | **8/10** | Thread-safe broadcasting with initial state dispatch and ping/pong |
| Persistence Architecture | **7/10** | Good SQLite schema, but compare endpoint reads static CSV |
| Modern Python Standards | **6/10** | 32 deprecation warnings (`utcnow`) need migration to timezone-aware UTC |

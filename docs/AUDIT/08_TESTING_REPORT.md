# Milestone Audit: Quality Assurance & Testing Report

**Project:** Bengaluru Smart Traffic Coordination System  
**Audit Scope:** Automated test execution, pytest suite, integration tests, sandbox behavior, frontend QA, and test coverage gaps  
**Auditor:** Production Software QA Engineer  
**Date:** October 30, 2026  
**Status:** COMPLETE (Read-Only Audit)

---

## 1. Executive Summary

A comprehensive quality assurance assessment was conducted across all unit, integration, simulation, and API test suites.

- **Pytest Suite:** 36 automated tests collected across 8 test modules.
- **Execution Results:**
  - **Standard Sandbox Mode:** 34 tests collected/executed, with `test_simulation_integration.py` failing due to Windows sandbox TCP loopback port binding restrictions (`[WinError 10013] An attempt was made to access a socket in a way forbidden by its access permissions`).
  - **Permitted Network Mode:** **All 36 tests passed in 12.91 seconds** (36 passed, 0 failed, 0 skipped, 32 deprecation warnings).
- **Frontend Test Suite:** **Zero automated tests exist** in `frontend/` (no test scripts, no Vitest/Jest configs, no component tests).
- **Deprecation Warnings:** 32 warnings logged regarding `datetime.datetime.utcnow()` and `starlette.testclient`.

---

## 2. Test Execution Breakdown

### 2.1 Complete Test Matrix (36 Items)

| Module | Test Case | Status | Duration | Focus Area |
|---|---|---|---|---|
| `test_accident_risk.py` | `test_blackspot_schema_validation` | **PASSED** | 0.05s | Pydantic schema validation for blackspots |
| `test_accident_risk.py` | `test_missing_and_invalid_coordinates`| **PASSED** | 0.04s | Rejection of null/malformed lat/lon |
| `test_accident_risk.py` | `test_coordinate_conversion` | **PASSED** | 0.06s | WGS84 to UTM Zone 43N conversion |
| `test_accident_risk.py` | `test_sumo_edge_mapping` | **PASSED** | 0.22s | Snapping GPS coordinates to SUMO edges |
| `test_accident_risk.py` | `test_junction_mapping` | **PASSED** | 0.18s | Snapping GPS coordinates to J1, J2, J3 |
| `test_accident_risk.py` | `test_outside_network_blackspots` | **PASSED** | 0.05s | Boundary checking for coordinates |
| `test_accident_risk.py` | `test_hotspot_clustering_on_weighted_observations` | **PASSED** | 0.35s | Spatial clustering on crash severity |
| `test_accident_risk.py` | `test_severity_weighting` | **PASSED** | 0.04s | IRC/MoRTH severity score formula |
| `test_accident_risk.py` | `test_risk_classification` | **PASSED** | 0.04s | CRITICAL/HIGH/MEDIUM/LOW tiering |
| `test_accident_risk.py` | `test_empty_dataset_handling` | **PASSED** | 0.03s | Edge case: empty CSV dataset |
| `test_accident_risk.py` | `test_malformed_records` | **PASSED** | 0.04s | Corrupted CSV row handling |
| `test_api.py` | `test_health_endpoint` | **PASSED** | 0.12s | `GET /api/health` status & SUMO check |
| `test_api.py` | `test_simulation_status` | **PASSED** | 0.08s | `GET /api/simulation/status` schema |
| `test_api.py` | `test_simulation_start_validation` | **PASSED** | 0.09s | Validation of mode, duration, seed |
| `test_api.py` | `test_traffic_live` | **PASSED** | 0.08s | `GET /api/traffic/live` junction states |
| `test_api.py` | `test_traffic_metrics` | **PASSED** | 0.07s | `GET /api/traffic/metrics` aggregates |
| `test_api.py` | `test_signals_endpoint` | **PASSED** | 0.08s | `GET /api/signals` phase data |
| `test_api.py` | `test_signal_override_validation` | **PASSED** | 0.11s | Rejection of unconfirmed override |
| `test_api.py` | `test_emergencies_endpoint` | **PASSED** | 0.07s | `GET /api/emergencies` payload |
| `test_api.py` | `test_risks_endpoint` | **PASSED** | 0.08s | `GET /api/risks` risk zones & hotspots |
| `test_api.py` | `test_decisions_endpoint` | **PASSED** | 0.07s | `GET /api/decisions` log query |
| `test_api.py` | `test_experiments_compare` | **PASSED** | 0.08s | `GET /api/experiments/compare` summary |
| `test_api.py` | `test_experiments_history` | **PASSED** | 0.07s | `GET /api/experiments/history` records |
| `test_communication.py`| `test_hub_initialization` | **PASSED** | 0.05s | Corridor sequence `[J1, J2, J3]` setup |
| `test_communication.py`| `test_point_to_point_messaging` | **PASSED** | 0.04s | Directed `send()` and `get_messages()` |
| `test_communication.py`| `test_upstream_inflow_propagation` | **PASSED** | 0.05s | J1 -> J2 and J2 -> J3 inflow update |
| `test_communication.py`| `test_platoon_announcement` | **PASSED** | 0.05s | Platoon ETA dispatch and filtering |
| `test_communication.py`| `test_emergency_broadcast` | **PASSED** | 0.05s | Corridor-wide emergency alert |
| `test_database.py` | `test_simulation_run_persistence` | **PASSED** | 0.32s | `SimulationRun` table CRUD |
| `test_database.py` | `test_risk_zone_persistence` | **PASSED** | 0.28s | `RiskZoneRecord` table persistence |
| `test_metrics.py` | `test_empty_metrics_summary` | **PASSED** | 0.05s | Zero-division guard on empty metrics |
| `test_metrics.py` | `test_metrics_accumulation` | **PASSED** | 0.12s | Step-by-step travel time accumulator |
| `test_simulation_integration.py` | `test_simulation_lifecycle_and_state_extraction` | **PASSED** | 1.82s | Full SUMO TraCI start, step, stop |
| `test_simulation_integration.py` | `test_coordinated_mode_stepping` | **PASSED** | 1.71s | Coordinated adaptive control stepping |
| `test_simulation_service.py` | `test_simulation_service_real_run_lifecycle` | **PASSED** | 4.04s | Background worker thread, pause, resume, override, stop |
| `test_websocket.py` | `test_websocket_traffic_stream` | **PASSED** | 1.47s | WS connect, `INITIAL_STATE`, ping/pong |

---

## 3. Sandboxed vs Unsandboxed Execution Findings

### 3.1 The Sandbox TCP Socket Permission Error
When running `pytest tests/test_simulation_integration.py` inside the standard Windows developer sandbox:
```
Could not connect to TraCI server at localhost:52470 
[WinError 10013] An attempt was made to access a socket in a way forbidden by its access permissions
traci.exceptions.FatalTraCIError: Could not connect in 61 tries
```
- **Root Cause:** TraCI operates via a client-server loopback TCP socket connection between Python (`traci.connect`) and the SUMO process (`sumo.exe`).
- **Diagnosis:** Standard Windows sandbox policies prohibit dynamic local TCP socket binding/listening.
- **Verification:** When granted loopback permission (`BypassSandbox: true`), the exact same command initialized the TraCI server on port 58434, connected, stepped, and terminated cleanly in 3.53s without modifying any code.

---

## 4. Warnings and Technical Debt

### 4.1 Deprecated UTC Datetime (32 Warnings)
Throughout `backend/models.py`, `backend/simulation_service.py`, and `tests/test_database.py`:
```python
# Deprecated pattern:
timestamp = datetime.utcnow()
# Recommended replacement:
from datetime import datetime, timezone
timestamp = datetime.now(timezone.utc)
```
Python 3.13 deprecates naive UTC datetimes; continuing to use `utcnow()` will cause breakages in future Python releases.

### 4.2 Missing `rtree` UserWarning
In `sumolib/net/__init__.py:370`:
```
UserWarning: Module 'rtree' not available. Using brute-force fallback.
```
Installing `rtree` (or `shapely`) will accelerate spatial nearest-edge and nearest-junction lookups from $O(N)$ brute-force to $O(\log N)$ spatial indexing.

---

## 5. Untested Components & Coverage Gaps

1. **Frontend Coverage: 0%**
   - Zero test files exist in `frontend/src/`.
   - Critical untested UI workflows:
     - Manual override modal validation and submission.
     - WebSocket reconnect behavior during network dropouts.
     - Simulation control button state transitions (disabled states during running).
     - Responsive behavior on mobile/tablet viewports.
2. **Missing Backend Scenarios:**
   - Multi-client concurrent WebSocket stress testing (>50 simultaneous connections).
   - Recovery behavior when SUMO crashes unexpectedly during stepping.
   - Long-duration simulation runs (>3600 seconds) to test memory leakage in the `_decisions_log` or SQLite connection pool.
   - Inverse coordinate transformation testing (`sumo_xy_to_wgs84`).

---

## 6. Audit Verdict & Scorecard

| Test Suite | Tests Run | Passed | Failed | Skipped | Quality Rating |
|---|---|---|---|---|---|
| Accident Risk & Blackspots | 11 | 11 | 0 | 0 | **10/10** (Comprehensive) |
| REST API Endpoints | 12 | 12 | 0 | 0 | **9/10** (Well-covered) |
| Inter-Intersection Messaging | 5 | 5 | 0 | 0 | **8/10** (Covers hub methods) |
| Database Persistence | 2 | 2 | 0 | 0 | **7/10** (Covers basic CRUD) |
| Metrics Calculation | 2 | 2 | 0 | 0 | **6/10** (Did not catch fuel bug) |
| SUMO TraCI Integration | 2 | 2 | 0 | 0 | **8/10** (Real SUMO execution) |
| Simulation Service Lifecycle| 1 | 1 | 0 | 0 | **9/10** (Full worker lifecycle) |
| WebSocket Protocol | 1 | 1 | 0 | 0 | **8/10** (Handshake & ping/pong) |
| Frontend Testing | 0 | 0 | 0 | 0 | **0/10** (Completely absent) |
| **TOTAL** | **36** | **36** | **0** | **0** | **Overall: 7.2/10** |

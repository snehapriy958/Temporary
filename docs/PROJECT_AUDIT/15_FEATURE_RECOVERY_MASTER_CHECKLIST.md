# Document 15: Feature Recovery Master Checklist and Non-Destructive Preservation Contract

**Project:** Smart Traffic Coordination System — Bengaluru Silk Board Corridor (J1 → J2 → J3)  
**Historical Baseline Branch:** `https://github.com/snehapriy958/smart-traffic-coordination/tree/ai-module`  
**Current Engineering Workspace:** `c:\Developers\Sneha\Projects\hybrid-traffic-control`  
**Audit Date:** November 1, 2026  
**Auditor:** Antigravity Autonomous Agent  
**Operational Status:** AUDIT ONLY (Verification and Tracking Contract — No Application Files Modified)

---

## 1. Master Preservation Contract Principles

This document serves as the binding engineering contract governing all subsequent recovery and development tasks. Every feature identified below must be systematically accounted for, tested, and validated.

### Core Preservation Directives:
1. **Zero Feature Regression:** No capability present in the historical baseline (`ai-module`) may be discarded, permanently disabled, or deprecated unless explicitly instructed by the user.
2. **Zero Engineering Degradation:** The modern architectural hardening introduced in `hybrid-traffic-control` (TraCI Command Queue, watchdog threads, sequenced WebSockets, 3D Digital Twin, snapshot recovery) must remain completely intact.
3. **Additive Integration:** Recovery must be performed purely additively. Missing modules and datasets are restored into their proper packages without overwriting or disrupting existing code.
4. **Multi-Tier Testing:** Every restored capability must be backed by automated unit tests, integration tests, and UI verification.

---

## 2. Master Feature Tracking Table

### Status Definitions:
- **PRESERVED:** Exists in current workspace with equivalent or identical capability and data.
- **IMPROVED:** Exists in current workspace with major architectural hardening, bug fixes, or performance enhancements.
- **MODIFIED:** Exists in current workspace with minor interface changes or refactoring.
- **REMOVED:** Deleted or intentionally stripped in current workspace.
- **REPLACED:** Substituted by an alternative subsystem in current workspace.
- **MISSING:** Inadvertently omitted during repository initialization or file migration.
- **NEW:** Newly developed capability added in the current workspace.

### Recovery Priority:
- **P0 (Critical):** Core algorithm, model weights, or test suite required for project completeness.
- **P1 (High):** API endpoint, simulation dispatch mode, or primary UI control required for full functionality.
- **P2 (Medium):** Historical benchmark dataset, secondary script, or standalone preview tool.
- **P3 (Low / Optional):** Historical raw documentation or auxiliary script.

---

| Feature ID | Feature Name / Subsystem | Historical Baseline Path (`ai-module`) | Current Workspace Path (`hybrid-traffic-control`) | Status | Priority | Required Engineering Action | Acceptance Criteria | Automated Test Required | Final Verification Status |
| :--- | :--- | :--- | :--- | :---: | :---: | :--- | :--- | :--- | :---: |
| **FEAT-001** | Fixed-Time Baseline Controller | `traffic_service/signal_controller.py` | `traffic_service/signal_controller.py` | **PRESERVED** | Baseline | Maintain existing fixed-time logic. | Runs in SUMO; 5-seed benchmark matches historical baseline. | `test_simulation_integration.py` | Verified Pass |
| **FEAT-002** | Coordinated Adaptive Controller | `traffic_service/multi_intersection_simulation.py` | `traffic_service/multi_intersection_simulation.py` | **PRESERVED** | Baseline | Maintain existing inter-junction platoon anticipation. | Anticipates J1 platoons at J2; reduces corridor travel time by ~37%. | `test_simulation_integration.py` | Verified Pass |
| **FEAT-003** | Multi-Agent DQN Controller | `traffic_service/ai/dqn_agent.py` | Omitted | **MISSING** | **P0** | Copy `dqn_agent.py` and `models.py` into `traffic_service/ai/`. | Dueling Double-DQN forward pass and epsilon action selection execute cleanly. | `test_ai_controller.py::test_dqn_forward_pass` | Audit Complete (Pending Copy) |
| **FEAT-004** | Multi-Agent PPO Controller | `traffic_service/ai/ppo_agent.py` | Omitted | **MISSING** | **P0** | Copy `ppo_agent.py` and `models.py` into `traffic_service/ai/`. | Actor-Critic forward pass, value estimation, and action distribution compute cleanly. | `test_ai_controller.py::test_ppo_forward_pass` | Audit Complete (Pending Copy) |
| **FEAT-005** | MARL Coordinator Subsystem | `traffic_service/ai/marl_controller.py` | Omitted | **MISSING** | **P0** | Copy `marl_controller.py` into `traffic_service/ai/`. | Multi-agent coordination across J1, J2, J3 with safety shield enforcement. | `test_ai_controller.py::test_marl_controller_decide` | Audit Complete (Pending Copy) |
| **FEAT-006** | MARL Observation & Action Space | `traffic_service/ai/env.py` | Omitted | **MISSING** | **P0** | Copy `env.py` into `traffic_service/ai/`. | 14-dim observation normalization and 3-action masking execute cleanly. | `test_ai_controller.py::test_observation_vectorizer_shape` | Audit Complete (Pending Copy) |
| **FEAT-007** | Dual NumPy / PyTorch Neural Models | `traffic_service/ai/models.py` | Omitted | **MISSING** | **P0** | Copy `models.py` into `traffic_service/ai/`. | NumPy dense/dueling/actor-critic models execute without PyTorch dependency; PyTorch executes when present. | `test_ai_controller.py::test_dqn_action_selection` | Audit Complete (Pending Copy) |
| **FEAT-008** | Trained MARL DQN Checkpoint | `checkpoints/marl_dqn_corridor.json` | Omitted | **MISSING** | **P0** | Copy JSON weights (982 KB) into `checkpoints/`. | JSON loads into DQN agent; weight matrices match expected layer dimensions. | `test_ai_controller.py::test_checkpoint_load_save` | Audit Complete (Pending Copy) |
| **FEAT-009** | Trained MARL PPO Checkpoint | `checkpoints/marl_ppo_corridor.json` | Omitted | **MISSING** | **P0** | Copy JSON weights (982 KB) into `checkpoints/`. | JSON loads into PPO agent; weight matrices match expected layer dimensions. | `test_ai_controller.py::test_checkpoint_load_save` | Audit Complete (Pending Copy) |
| **FEAT-010** | Automated AI Test Suite | `tests/test_ai_controller.py` | Omitted | **MISSING** | **P0** | Copy `test_ai_controller.py` into `tests/`. | All 12 unit tests pass under pytest in local environment. | `pytest tests/test_ai_controller.py` (12/12) | Audit Complete (Verified in Scratch) |
| **FEAT-011** | Signal Safety Constraint Shield | `traffic_service/signal_controller.py` | `traffic_service/signal_controller.py` | **PRESERVED** | Baseline | Enforce min green (15-20s), max green (60-75s), and yellow clearance (4-6s). | All transitions pass through safety bounds before TraCI dispatch. | `test_ai_controller.py::test_action_masking_min_green` | Verified Pass |
| **FEAT-012** | Corridor Communication Hub | `traffic_service/communication.py` | `traffic_service/communication.py` | **PRESERVED** | Baseline | Maintain inter-junction platoon arrival prediction. | Exchanges queue and inflow messages between J1, J2, J3. | `test_communication.py` (5/5) | Verified Pass |
| **FEAT-013** | Emergency Green Wave Coordinator | `traffic_service/emergency_wave.py` | `traffic_service/emergency_wave.py` | **PRESERVED** | Baseline | Maintain ambulance preemption and green wave corridor lock. | Clears Hosur road green corridor within 250m approach. | `test_metrics.py`, `test_simulation_integration.py` | Verified Pass |
| **FEAT-014** | TraCI Simulation Engine Integration | `traffic_service/multi_intersection_simulation.py` | `traffic_service/multi_intersection_simulation.py` | **MODIFIED** | **P1** | Re-enable MARL dispatch branch (`if self.mode in ("marl_dqn", "marl_ppo")`) during step loop. | SUMO runs cleanly with `marl_dqn` and `marl_ppo` modes. | `test_simulation_integration.py` | Audit Complete (Pending Reconnect) |
| **FEAT-015** | TraCI Dynamic Port Allocation | Basic port usage | `traffic_service/sumo_manager.py` | **IMPROVED** | Core | Preserve dynamic port hunting and retry logic. | Automatically finds free ports to avoid socket collisions. | `test_startup_watchdog.py` | Verified Pass |
| **FEAT-016** | TraCI Thread-Safe Command Queue | Direct calls | `backend/simulation_service.py` | **IMPROVED** | Core | Preserve TraCI command queue (`TraCICommandQueue`). | Mutating calls execute exclusively inside the simulation thread. | `test_command_queue.py` (14/14) | Verified Pass |
| **FEAT-017** | Simulation Watchdog & Process Monitor | Basic Popen | `backend/simulation_service.py` | **IMPROVED** | Core | Preserve background watchdog thread. | Detects hung/crashed TraCI processes and cleans up zombies. | `test_startup_watchdog.py` (18/18) | Verified Pass |
| **FEAT-018** | Snapshot State Recovery Engine | None | `backend/simulation_service.py` | **NEW** | Core | Preserve snapshot capture, state serialization, and rollback. | Captures live simulation state and allows instant rollback. | Snapshot test suite | Verified Pass |
| **FEAT-019** | BTP Accident Dataset & Blackspots | `data/accidents/` (6 files) | `data/accidents/` (6 files) | **PRESERVED** | Core | Maintain raw and processed Bengaluru Traffic Police accident files. | Accident data clean, parsed, and mapped to corridor edges. | `test_accident_risk.py` (11/11) | Verified Pass |
| **FEAT-020** | Spatial Risk Mapper & Hotspot Analyzer| `traffic_service/risk_mapper.py`, `hotspot_analyzer.py` | `traffic_service/risk_mapper.py`, `hotspot_analyzer.py` | **PRESERVED** | Core | Maintain accident risk scoring and hotspot clustering. | Risk scores correlate with vehicle density and historical blackspots. | `test_accident_risk.py` | Verified Pass |
| **FEAT-021** | Scenario Generator (Accident Injection)| `traffic_service/scenario_generator.py` | `traffic_service/scenario_generator.py` | **PRESERVED** | Core | Maintain synthetic scenario and incident injection. | Injects lane blockages and disabled vehicles into TraCI. | `test_accident_risk.py` | Verified Pass |
| **FEAT-022** | Environmental & Corridor Metrics | `traffic_service/corridor_metrics.py` | `traffic_service/corridor_metrics.py` | **IMPROVED** | Core | Preserve expanded HBEFA 3.1 emission calculations. | Accurately calculates CO2, NOx, PM, fuel, queue, and speed. | `test_metrics.py` (10/10) | Verified Pass |
| **FEAT-023** | SQLite Database & Run Logging | `backend/database.py`, `models.py` | `backend/database.py`, `models.py` | **PRESERVED** | Core | Maintain SQLite database schema and metric persistence. | Writes simulation run records, emergencies, and KPI metrics. | `test_database.py` (2/2) | Verified Pass |
| **FEAT-024** | API: Health Check Endpoint | `backend/routers/health.py` | `backend/routers/health.py` | **PRESERVED** | Core | Maintain `/api/health`. | Returns status 200 with DB status and simulation running state. | `test_api.py::test_health_endpoint` | Verified Pass |
| **FEAT-025** | API: Simulation Lifecycle Endpoints | `backend/routers/simulation.py` | `backend/routers/simulation.py` | **IMPROVED** | Core | Update start validation to include `marl_dqn` and `marl_ppo`. | Accepts start, pause, resume, reset, and stop commands. | `test_api.py` | Audit Complete (Pending Validation Update) |
| **FEAT-026** | API: Manual Signal Override | `backend/routers/signals.py` | `backend/routers/signals.py` | **IMPROVED** | Core | Preserve queue-based manual phase override. | Safely overrides signal phases respecting yellow transitions. | `test_api.py::test_signal_override` | Verified Pass |
| **FEAT-027** | API: Composite Corridor Endpoint | `backend/routers/traffic.py` (`/corridor`)| Omitted | **REMOVED** | **P1** | Re-add `GET /api/traffic/corridor` endpoint. | Returns unified corridor metrics, junction states, and signals. | `test_api.py` | Audit Complete (Pending Re-add) |
| **FEAT-028** | API: Controller Benchmark Compare | `backend/routers/experiments.py` | `backend/routers/experiments.py` | **MODIFIED** | **P1** | Re-enable dynamic reading of MARL summary CSV and checkpoint file status. | Returns verified metrics for Baseline, Coordinated, PPO, and reports checkpoint status. | `test_api.py::test_experiments_compare` | Audit Complete (Pending Router Update) |
| **FEAT-029** | API: MARL Detailed Summary Endpoints | `backend/routers/experiments.py` (`/marl-*`)| Omitted | **REMOVED** | **P2** | Re-add `/experiments/marl-summary` and `/experiments/marl-detailed`. | Returns 5-seed statistical tables and per-seed JSON metrics. | `test_api.py` | Audit Complete (Pending Re-add) |
| **FEAT-030** | API: Standalone Dashboard Route | `backend/main.py` (`/dashboard`, `/` HTML) | Omitted | **REMOVED** | **P2** | Re-add static mount and conditional HTML serving on `/` and `/dashboard`. | Browser request to `/` or `/dashboard` serves interactive dashboard. | `test_api.py::test_root_dashboard_html` | Audit Complete (Pending Re-add) |
| **FEAT-031** | WebSocket Monotonic Streaming | Basic unsequenced broadcast | `backend/websocket_manager.py` | **IMPROVED** | Core | Preserve sequenced frames, client session buffering, and drop policies. | Delivers strictly ordered frames with sequence IDs and timestamps. | `test_websocket_ordering.py`, `test_websocket_resilience.py` | Verified Pass |
| **FEAT-032** | 2D Corridor Topology View | `frontend/src/components/LiveCorridorView.jsx`| `frontend/src/components/LiveCorridorView.jsx` | **IMPROVED** | Core | Maintain 2D schematic map with live queue bars and signal circles. | Renders live signal states, approach queues, and ambulance markers. | Frontend Vitest suite | Verified Pass |
| **FEAT-033** | 3D Digital Twin Viewer | None | `frontend/src/components/ThreeCorridorView.jsx`| **NEW** | Core | Preserve React Three Fiber 3D scene, road geometry, and vehicle meshes. | Renders interactive 3D corridor with orbit controls and live vehicles. | `test_coordinate_transformation.py`, `test_corridor_geometry_extraction.py` | Verified Pass |
| **FEAT-034** | Controller Dropdown in Deck | Had 4 options | Has 2 options | **MODIFIED** | **P1** | Re-add `<option value="marl_ppo">` and `<option value="marl_dqn">` in `SimulationControls.jsx`. | User can choose MARL controllers directly from control deck. | Manual UI Verification | Audit Complete (Pending Option Re-add) |
| **FEAT-035** | Controller Benchmark Comparison Panel | `frontend/src/components/ControllerComparison.jsx` | `frontend/src/components/ControllerComparison.jsx` | **MODIFIED** | **P1** | Restore display of trained MARL benchmark metrics in comparison table and charts. | Renders multi-controller bar charts with empirical values and provenance notes. | Frontend Vitest suite | Audit Complete (Pending Display Update) |
| **FEAT-036** | Emergency Preemption Panel | `frontend/src/components/EmergencyPanel.jsx` | `frontend/src/components/EmergencyPanel.jsx` | **IMPROVED** | Core | Maintain ambulance trigger button and route lock indicators. | Triggers ambulance dispatch and shows active green wave status. | Frontend Vitest suite | Verified Pass |
| **FEAT-037** | Accident Risk Hotspots Panel | `frontend/src/components/RiskHotspotsPanel.jsx` | `frontend/src/components/RiskHotspotsPanel.jsx` | **PRESERVED** | Core | Maintain BTP blackspots display and risk breakdown. | Displays Silk Board high-risk zones and station accident counts. | Frontend Vitest suite | Verified Pass |
| **FEAT-038** | Overview KPIs & Emission Analytics | `OverviewKPIs.jsx`, `EmissionAnalytics.jsx` | `OverviewKPIs.jsx`, `EmissionAnalytics.jsx` | **IMPROVED** | Core | Maintain live KPI cards and historical emission charts. | Shows travel time, speed, queues, CO2, and fuel consumption. | Frontend Vitest suite | Verified Pass |
| **FEAT-039** | What-If Scenario Control Deck | `frontend/src/components/WhatIfScenario.jsx` | `frontend/src/components/WhatIfScenario.jsx` | **PRESERVED** | Core | Maintain incident simulation controls and flow adjustment. | Allows user to simulate rain, peak surge, and lane blockages. | Frontend Vitest suite | Verified Pass |
| **FEAT-040** | Snapshot Recovery Modal UI | None | `frontend/src/components/SnapshotModal.jsx` | **NEW** | Core | Preserve snapshot recovery interface. | Lets user inspect, select, and restore simulation checkpoints. | Frontend Vitest suite | Verified Pass |
| **FEAT-041** | Standalone Preview HTML Dashboard | `frontend_preview.html`, `backend/static/index.html` | Omitted | **MISSING** | **P2** | Copy `frontend_preview.html` to root and `backend/static/index.html`. | Opens standalone dashboard connected to `/ws/traffic` without Node.js. | Manual Browser Verification | Audit Complete (Pending Copy) |
| **FEAT-042** | Standalone Launcher Script | `run_dashboard.py` | Omitted | **MISSING** | **P2** | Copy `run_dashboard.py` to repository root. | Running `python run_dashboard.py` launches backend and opens browser. | Command execution test | Audit Complete (Pending Copy) |
| **FEAT-043** | Multi-Seed Simulation Step Traces | `outputs/corridor/` (20 CSV files) | Omitted | **MISSING** | **P2** | Copy 20 per-seed CSVs into `outputs/corridor/baseline/`, `coordinated/`, `marl_dqn/`, `marl_ppo/`. | All 20 step trace CSVs (seeds 1-5) restored for historical reproducibility. | File verification script | Audit Complete (Pending Copy) |
| **FEAT-044** | Multi-Controller Summary Tables | `outputs/corridor/marl_multi_controller_summary.csv` | Omitted | **MISSING** | **P1** | Copy `marl_multi_controller_summary.csv` and `marl_multi_controller_full_stats.csv`. | Benchmark CSVs available for backend experiments router. | `test_api.py::test_experiments_compare` | Audit Complete (Pending Copy) |
| **FEAT-045** | Detailed Multi-Seed Benchmark JSON | `outputs/corridor/marl_multi_seed_detailed.json` | Omitted | **MISSING** | **P2** | Copy detailed metrics JSON into `outputs/corridor/`. | Detailed metrics available for granular analytics API. | File verification script | Audit Complete (Pending Copy) |
| **FEAT-046** | MARL Training Run Logs | `outputs/corridor/training_logs/` (2 JSONs)| Omitted | **MISSING** | **P2** | Copy `training_summary_dqn.json` and `training_summary_ppo.json`. | Training convergence logs and loss histories preserved. | File verification script | Audit Complete (Pending Copy) |
| **FEAT-047** | MARL Training Script | `scripts/train_marl.py` | Omitted | **MISSING** | **P2** | Copy `train_marl.py` into `scripts/`. | Standalone SUMO training loop executes reproducible RL training. | Python syntax check | Audit Complete (Pending Copy) |
| **FEAT-048** | MARL Evaluation Harness Script | `scripts/evaluate_marl.py` | Omitted | **MISSING** | **P2** | Copy `evaluate_marl.py` into `scripts/`. | Multi-seed evaluation script runs all 4 controllers on SUMO. | Python syntax check | Audit Complete (Pending Copy) |
| **FEAT-049** | SUMO Silk Board Network & Demand | `sumo/silk_board/` (network & demand XML) | `sumo/silk_board/` (network & demand XML) | **PRESERVED** | Core | Maintain road network geometry and vehicle demand flows. | SUMO net and demand load without errors in TraCI. | `test_simulation_integration.py` | Verified Pass |
| **FEAT-050** | Official Handover Documentation | `docs/presentation_handover_document.pdf`, `freatures_report.pdf` | Omitted | **MISSING** | **P3** | Copy historical PDF documents into `docs/historical/`. | Preserves original academic provenance and team attribution. | File existence check | Audit Complete (Pending Copy) |

---

## 3. Engineering Acceptance Protocol for Recovery

When executing the recovery plan in future turns upon user approval, every item in the checklist must satisfy the following verification protocol:

1. **Copy Verification:** The target file must be copied verbatim or integrated additively without corrupting encoding (UTF-8 preservation).
2. **Import Verification:** Python packages must import cleanly in Python 3.13 without deprecation warnings or missing symbols.
3. **Automated Test Verification:** All 121 existing backend tests + the 12 restored AI tests must pass (133/133 tests passing).
4. **API Verification:** The FastAPI backend must start cleanly and respond to all historical and modern endpoints.
5. **WebSocket Telemetry Verification:** The WebSocket stream `/ws/traffic` must broadcast frames cleanly under both Coordinated and MARL modes.
6. **Frontend UI Verification:** The React Vite frontend must build with zero errors (`npm run build`), pass all Vitest tests, and render all 4 controllers in the control deck and benchmark comparison views.
7. **Zero Regression Guarantee:** The Isolated Actuated Controller Plan (`ISOLATED_ACTUATED_CONTROLLER_PLAN.md` v3.1) and all existing audit documents (01–14) must remain intact.

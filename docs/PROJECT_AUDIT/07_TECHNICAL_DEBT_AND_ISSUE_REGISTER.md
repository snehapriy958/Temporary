# Document 07: Technical Debt & Issue Register

**Project:** Smart Traffic Coordination System — Bengaluru Silk Board Corridor  
**Audit Date:** October 31, 2026  
**Auditor:** Principal Software Architect & Reliability Auditor  
**Audit Scope:** Codebase Defects, Architectural Debt, Performance Bottlenecks, Deprecation Warnings, and 3D Blockers  

---

## 1. Issue Prioritization Framework

Issues discovered during this audit are prioritized into four strict engineering tiers:
- **P0 (Critical Correctness / Safety):** Active defects causing data corruption, race conditions, crashes, or safety violations.
- **P1 (Core Functionality / Model Integration):** Architectural deficiencies, missing core components, or functional gaps that limit the primary mission of the system.
- **P2 (Important Quality / Performance Improvement):** Code health, deprecation cleanup, optimization, and testing improvements.
- **P3 (Future Enhancement):** Strategic evolutionary upgrades reserved for later development phases.

---

## 2. Prioritized Technical Debt & Defect Register

| Issue ID | Severity | Category | Title | Location | Blocks 3D? | Status |
|---|:---:|---|---|---|:---:|:---:|
| **ISSUE-01** | **P1** | **3D Digital Twin** | Complete Absence of 3D Rendering Pipeline | `frontend/src/` | **YES** | Open |
| **ISSUE-02** | **P1** | **ML / AI Models** | PPO & DQN Reinforcement Learning Unimplemented | `backend/routers/experiments.py:98` | No | Open |
| **ISSUE-03** | **P1** | **Multi-Agent Systems**| Centralized Monolithic Stepping vs True Decentralized MAS | `traffic_service/multi_intersection_simulation.py:200` | No | Open |
| **ISSUE-04** | **P2** | **Simulation API** | Scenario Generator Not Exposed in Simulation API | `traffic_service/scenario_generator.py:31` | No | Open |
| **ISSUE-05** | **P2** | **Code Health** | Deprecated `datetime.utcnow()` Usage | `backend/models.py`, `backend/database.py` | No | Open |
| **ISSUE-06** | **P2** | **Network Geometry** | Flyover Grade Separation Simplification in SUMO | `sumo/silk_board/demand/silk_board.rou.xml` | No | Open |
| **ISSUE-07** | **P2** | **Frontend Perf** | Single Unsplit JavaScript Bundle (> 600 kB) | `frontend/dist/assets/index-DVoXwBD8.js` | No | Open |
| **ISSUE-08** | **P3** | **Verification** | Absence of Browser E2E Integration Tests | `frontend/` (No Playwright/Cypress) | No | Open |

---

## 3. Deep-Dive Issue Analysis

### ISSUE-01: Complete Absence of 3D Rendering Pipeline
- **Severity:** **P1** (Blocks 3D Development)
- **Category:** Architecture / Frontend
- **Location:** `frontend/src/components/`, `frontend/package.json`
- **What is Wrong:**
  The frontend currently visualizes the Silk Board corridor strictly through a **2D schematic SVG topology component** (`LiveCorridorView.jsx`). There is no 3D canvas, no WebGL context, no 3D rendering engine (Three.js, Babylon.js, or Cesium), and no 3D asset loader (gITF/OBJ).
- **Why it Matters:**
  Phase 3 requires immersive 3D digital twin visualization of the Silk Board junction, vehicle meshes, traffic light signals, terrain, and buildings. Proceeding to Phase 3 without establishing a WebGL engine foundation is impossible.
- **Dependencies:**
  Requires integrating `@react-three/fiber` / `three` or a dedicated WebGL engine, importing 3D terrain/road meshes, and projecting vehicle TraCI coordinates into 3D world space.
- **Blocks 3D Development:** **YES (Direct Blocker for Phase 3).**

---

### ISSUE-02: PPO & DQN Reinforcement Learning Models Unimplemented
- **Severity:** **P1** (Core Functionality)
- **Category:** ML / Optimization
- **Location:** `backend/routers/experiments.py:98-115`, `traffic_service/multi_intersection_simulation.py:175-195`
- **What is Wrong:**
  PPO and DQN are documented in project roadmaps, and clean observation/action hooks exist in `MultiIntersectionSimulation`, but no neural networks, training loops, reward functions, or weight checkpoints exist in the repository. The API returns `status="Not implemented"`.
- **Why it Matters:**
  The project is often described as "Hybrid AI Traffic Control", but the current AI component is limited to offline DBSCAN clustering and heuristic state machines.
- **Remediation Recommendation:**
  Develop an OpenAI Gym / Farama Gymnasium environment (`sumo_gym_env.py`), define multi-agent reward formulations (delay + queue + collision penalties), train policies using Stable-Baselines3 or Ray RLLib, and export PyTorch/ONNX checkpoints for runtime inference.
- **Blocks 3D Development:** **NO.** 3D digital twin rendering can animate existing rule-based and baseline vehicles without requiring RL models.

---

### ISSUE-03: Centralized Monolithic Stepping vs True Decentralized MAS
- **Severity:** **P1** (Architecture)
- **Category:** Multi-Agent Systems
- **Location:** `traffic_service/multi_intersection_simulation.py:200-245`
- **What is Wrong:**
  While an inter-intersection message bus (`CorridorCommunicationHub`) exists, all three junctions (J1, J2, J3) are updated synchronously inside a single centralized `MultiIntersectionSimulation.step()` method on a single thread. There are no independent agent actors, separate processes, or decentralized lifecycle failure handlers.
- **Why it Matters:**
  If the platform is intended to demonstrate multi-agent resilience (e.g., J2 surviving communication loss with J1), the current monolithic architecture cannot simulate node failure, message corruption, or decentralized consensus.
- **Remediation Recommendation:**
  Decouple J1, J2, and J3 into distinct `JunctionAgent` instances that run local decision loops and exchange asynchronous messages over the hub.
- **Blocks 3D Development:** **NO.** 3D visualization is decoupled from whether the backend stepping logic is centralized or distributed.

---

### ISSUE-04: Scenario Generator Not Exposed in Simulation API
- **Severity:** **P2** (Quality / Usability)
- **Category:** Backend API
- **Location:** `traffic_service/scenario_generator.py`, `backend/routers/simulation.py:33`
- **What is Wrong:**
  `traffic_service/scenario_generator.py` defines 4 rich scenario presets (`NORMAL`, `HIGH_DEMAND`, `CORRIDOR_EMERGENCY`, `INCIDENT_CONGESTION`) with demand scaling factors ($1.0\text{--}1.5$). However, the `POST /api/simulation/start` endpoint schema (`SimulationStartRequest`) only accepts `mode`, `duration`, `seed`, `enable_emergency`, and `gui`. It does not accept a `scenario` parameter.
- **Why it Matters:**
  Operators cannot launch incident congestion or peak rush-hour scenarios directly from the dashboard controls; they must manually modify route XML files on disk.
- **Remediation Recommendation:**
  Add an optional `scenario: str = "NORMAL"` field to `SimulationStartRequest`, invoke `ScenarioGenerator.generate()` if a non-default scenario is selected, and link the route file to the active SUMO session.
- **Blocks 3D Development:** **NO.**

---

### ISSUE-05: Deprecated `datetime.utcnow()` Usage Across Backend & Tests
- **Severity:** **P2** (Code Health)
- **Category:** Backend Standards
- **Location:** `backend/models.py:38,55,71,88`, `backend/database.py`, `tests/test_database.py:44`
- **What is Wrong:**
  The codebase extensively uses `datetime.utcnow()`. In Python 3.12 and 3.13, `datetime.utcnow()` is formally deprecated and emits hundreds of `DeprecationWarning`s during test execution:
  `DeprecationWarning: datetime.datetime.utcnow() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.now(datetime.UTC).`
- **Why it Matters:**
  Produces 360+ noisy warnings during test execution and will break when Python removes the deprecated API in future releases.
- **Remediation Recommendation:**
  Replace all occurrences with `datetime.now(timezone.utc)`.
- **Blocks 3D Development:** **NO.**

---

### ISSUE-06: Flyover Grade Separation Simplification in SUMO
- **Severity:** **P2** (Simulation Realism)
- **Category:** SUMO Simulation Network
- **Location:** `sumo/silk_board/demand/silk_board.rou.xml`
- **What is Wrong:**
  The real-world Silk Board elevated flyover allows express vehicles traveling between Hosur Road and Madiwala to completely bypass the ground-level rotary. In the simulation demand routes, all traffic is routed through ground-level intersection J2 to maximize queue stress.
- **Why it Matters:**
  Ground-level congestion in the simulation is slightly more severe than physical reality during off-peak hours because through-traffic cannot use the flyover bypass.
- **Remediation Recommendation:**
  Add a dedicated `express_flyover` route in `silk_board.rou.xml` allocating 30-40% of passenger car flows directly over the bridge without entering J2's conflict zone.
- **Blocks 3D Development:** **NO.** (In fact, having 3D bridges will make visualizing the flyover exciting in Phase 3).

---

### ISSUE-07: Single Unsplit JavaScript Bundle (> 600 kB)
- **Severity:** **P2** (Frontend Performance)
- **Category:** Build & Bundle Optimization
- **Location:** `frontend/dist/assets/index-DVoXwBD8.js` (632.01 kB)
- **What is Wrong:**
  Vite compilation produces a single monolithic JS bundle of $632\text{ kB}$ (uncompressed), triggering Vite's bundle size warning:
  `(!) Some chunks are larger than 500 kB after minification.`
  This occurs because `recharts` and all sub-panels are imported statically into `App.jsx`.
- **Why it Matters:**
  Adding heavy 3D WebGL libraries (such as Three.js, which adds 500+ kB) to the existing bundle without code-splitting will degrade initial page load times.
- **Remediation Recommendation:**
  Configure `build.rollupOptions.output.manualChunks` in `vite.config.js` to split vendor dependencies (`react`, `recharts`, `lucide-react`) and use `React.lazy()` for secondary dashboard tabs (`EmissionAnalytics`, `ControllerComparison`, `RiskHotspotsPanel`).
- **Blocks 3D Development:** **NO.** (Should be addressed as part of Phase 3 frontend setup).

---

### ISSUE-08: Absence of Browser End-to-End (E2E) Automation
- **Severity:** **P3** (Testing Quality)
- **Category:** QA & Verification
- **Location:** `frontend/`
- **What is Wrong:**
  Frontend tests are limited to Node.js unit tests with mocked WebSockets (`websocket.test.js`). There are no automated browser tests (Playwright or Cypress) to verify button clicks, canvas rendering, SVG zoom/pan, or DOM updates in real browser engines.
- **Why it Matters:**
  Manual testing is required to verify visual rendering regressions in the browser.
- **Remediation Recommendation:**
  Set up Playwright to run headless Chromium smoke tests on core dashboard interactions.
- **Blocks 3D Development:** **NO.**

---

## 4. Technical Debt Audit Verdict

The codebase is **completely free of P0 critical safety defects and blocking runtime errors**. Concurrency and synchronization issues have been thoroughly resolved. The technical debt consists entirely of **P1 architectural enhancements (adding 3D visualization, developing true RL models, and MAS decentralization)** and **P2 quality improvements (deprecation cleanup and bundle splitting)**.

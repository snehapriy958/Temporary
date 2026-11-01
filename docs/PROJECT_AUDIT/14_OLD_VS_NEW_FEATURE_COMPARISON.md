# Document 14: Historical Feature Recovery and Old-vs-New Project Forensic Comparison

**Project:** Smart Traffic Coordination System — Bengaluru Silk Board Corridor (J1 → J2 → J3)  
**Historical Baseline Branch:** `https://github.com/snehapriy958/smart-traffic-coordination/tree/ai-module`  
**Current Engineering Workspace:** `c:\Developers\Sneha\Projects\hybrid-traffic-control`  
**Audit Date:** November 1, 2026  
**Auditor:** Antigravity Autonomous Agent  
**Operational Status:** AUDIT ONLY (Zero Code Modifications, Zero File Deletions, Zero Regressions)

---

## 1. Executive Summary

### 1.1 Context and Purpose
This forensic audit was commissioned to establish a complete, authoritative, and line-by-line comparison between the historical baseline repository (`ai-module` branch of `smart-traffic-coordination`) and the current evolving project (`hybrid-traffic-control`).

The core architectural directive is:
> **Every necessary feature from the original project must remain available in the final project. New engineering improvements must be added without unnecessarily deleting, weakening, replacing, or hiding original functionality.**

The historical `ai-module` branch represents the project's conceptual and functional baseline—developed by the multidisciplinary engineering team (Senior AI/ML Lead Pallavi devi Y, TraCI/Simulation Lead Sneha, Backend/UI Lead Suma). The current local repository represents an intensive engineering hardening effort—introducing thread-safe TraCI command queues, high-resilience WebSocket streaming, a 3D Digital Twin built with React Three Fiber, startup watchdogs, coordinate extraction, and comprehensive stress testing.

However, during this architectural evolution, several critical components of the original project were unintentionally omitted or bypassed:
1. **The Multi-Agent Reinforcement Learning (MARL) Engine (`traffic_service/ai/`):** Containing complete Dueling Double-DQN and Actor-Critic PPO agents implemented in both pure NumPy and PyTorch, complete observation vectorizers, and reward functions.
2. **Trained Neural Network Checkpoints (`checkpoints/`):** Two complete 982 KB model weights files (`marl_dqn_corridor.json` and `marl_ppo_corridor.json`) containing floating-point weights and biases for all 3 corridor intersections.
3. **Automated AI Test Suite (`tests/test_ai_controller.py`):** 12 comprehensive unit tests covering observation spaces, reward calculations, forward inference, action masking, and fallback behaviors.
4. **Empirical Multi-Controller Simulation Benchmarks (`outputs/corridor/`):** 20 per-seed simulation step trace CSVs (seeds 1–5 for Baseline, Coordinated, MARL DQN, and MARL PPO), multi-controller statistical summaries, and JSON training logs.
5. **Standalone Zero-Dependency Dashboard (`frontend_preview.html`, `backend/static/index.html`, `run_dashboard.py`):** Standalone browser dashboards utilizing CDN libraries that run immediately without requiring Node.js or Vite.
6. **MARL Training and Evaluation Harnesses (`scripts/train_marl.py`, `scripts/evaluate_marl.py`):** Reproducible scripts for multi-seed reinforcement learning training and benchmark evaluation.

### 1.2 Forensic Resolution of the "Missing Models" Mystery
In previous audit documents (notably `02_COMPLETE_MODEL_INVENTORY.md`), it was reported that PPO and DQN were "unfunctional placeholders" and that "no neural network weights, replay buffers, or training loops exist in the project."

**This forensic audit definitively proves that conclusion was incorrect.** The models were not fictional; they were fully implemented, trained, benchmarked, and verified with 12 passing unit tests in the historical repository. They were merely left behind when the new workspace directory `hybrid-traffic-control` was initialized. Furthermore, because the files were absent in the new workspace, `backend/routers/experiments.py` was altered to return `"Not implemented"` for PPO and DQN, and `tests/test_api.py` was altered to assert that status.

When tested inside Python 3.13 during this audit, the historical AI controller test suite passed **12 out of 12 tests in 6.56 seconds** with zero errors.

---

## 2. High-Level Architecture Comparison

### 2.1 System Architecture Topology

The following diagram illustrates how the historical baseline and current engineering improvements relate to each other:

```mermaid
flowchart TD
    subgraph Historical Baseline ["Historical Baseline (ai-module Branch)"]
        direction TB
        H_AI["MARL Engine (traffic_service/ai/)<br/>• Dueling Double-DQN<br/>• Actor-Critic PPO<br/>• Dual NumPy / PyTorch"]
        H_CKPT["Trained Checkpoints (checkpoints/)<br/>• marl_dqn_corridor.json (982 KB)<br/>• marl_ppo_corridor.json (982 KB)"]
        H_TEST["AI Test Suite (tests/test_ai_controller.py)<br/>• 12 Passing Tests"]
        H_BENCH["Multi-Controller Data (outputs/corridor/)<br/>• 20 Per-Seed CSV Traces (Seeds 1-5)<br/>• Training Logs & Detailed JSONs"]
        H_PREV["Standalone HTML Dashboard<br/>• frontend_preview.html<br/>• run_dashboard.py (Zero Node.js)"]
        H_SCRIPTS["MARL Scripts<br/>• train_marl.py<br/>• evaluate_marl.py"]
    end

    subgraph Current Evolution ["Current Engineering Evolution (hybrid-traffic-control)"]
        direction TB
        N_SIM["Hardened Simulation Service<br/>• TraCI Command Queue (Thread-Safe)<br/>• Watchdog Thread & Port Hunting<br/>• Snapshot Recovery Engine"]
        N_WS["Resilient WebSocket Streaming<br/>• Monotonic Sequence Ordering<br/>• Drop Policy & Frame Coalescing<br/>• Dynamic Backoff Reconnection"]
        N_3D["3D Digital Twin Viewer<br/>• React Three Fiber / Three.js<br/>• OSM Geometry Extraction<br/>• Road Mesh Generation & Coordinate Math"]
        N_TESTS["Expanded Test Infrastructure<br/>• 121 Passing Backend Tests<br/>• 75 Passing Frontend Tests<br/>• Concurrency & Stress Harnesses"]
        N_UI["Modernized Frontend Architecture<br/>• High-Contrast Light Theme<br/>• Tabbed Multi-View Deck<br/>• Lucide & Recharts Upgrades"]
    end

    subgraph Unified Final Target ["Unified Target Architecture (Zero Feature Loss)"]
        direction TB
        TARGET["COMPLETE SYSTEM<br/>1. Hardened TraCI + Snapshot Engine<br/>2. Fully Functional MARL Engine (DQN + PPO + Coordinated + Baseline)<br/>3. Dual 2D Canvas + 3D Three.js Digital Twin<br/>4. 133+ Passing Backend Automated Tests<br/>5. Full Multi-Seed Empirical Benchmark Deck<br/>6. Standalone Fallback Preview Dashboard"]
    end

    Historical Baseline --> Unified Final Target
    Current Evolution --> Unified Final Target
```

### 2.2 Subsystem Feature Comparison Matrix

| Subsystem | Historical Baseline (`ai-module`) | Current Workspace (`hybrid-traffic-control`) | Status & Evaluation |
| :--- | :--- | :--- | :--- |
| **Traffic Signal Controllers** | 4 Modes: Baseline, Coordinated, MARL DQN, MARL PPO | 2 Modes: Baseline, Coordinated | **DEGRADED (Recoverable)**: MARL DQN & PPO omitted from runtime dispatch and frontend dropdown. |
| **Model Implementations** | PyTorch + NumPy Dueling DQN & Actor-Critic PPO (`traffic_service/ai/`) | None (Omitted from workspace) | **MISSING**: Needs non-destructive re-integration. |
| **Model Weights / Checkpoints** | Trained JSON checkpoints for J1, J2, J3 (`checkpoints/`) | None | **MISSING**: Needs restoration. |
| **Simulation Process Management** | Direct TraCI calls inside simulation thread | TraCI Command Queue, watchdog thread, port hunter, lock-protected TraCI client | **SIGNIFICANTLY IMPROVED**: New architecture prevents socket concurrency crashes. |
| **WebSocket Streaming** | Direct unsequenced JSON broadcasts | Sequenced frames, monotonic IDs, drop policy, frame coalescing, heartbeat ping/pong | **SIGNIFICANTLY IMPROVED**: New manager handles browser lag and network disconnects smoothly. |
| **Visualization & UI** | 2D SVG/Canvas Corridor Map + Standalone HTML | 2D SVG/Canvas + 3D Three.js Digital Twin + Snapshot Recovery Modal | **SIGNIFICANTLY IMPROVED**: 3D Twin renders realistic roads, vehicles, and signals. |
| **Standalone Dashboard** | Single-file HTML/JS (`frontend_preview.html`, `run_dashboard.py`) | Removed (FastAPI static mount dropped, requires Vite) | **REMOVED**: Standalone zero-dependency fallback was lost. |
| **Benchmark & Historical Data** | 20 per-seed CSVs, full stats CSV, detailed JSONs, training logs | Only 1 summary CSV (`corridor_multi_seed_summary.csv`) | **MISSING**: Historical multi-seed traces omitted. |
| **Accident Data & Blackspots** | 6 raw and processed BTP accident files | Identical 6 files preserved | **PRESERVED**: 100% data integrity maintained. |
| **SUMO Network & Demand** | Silk Board `.net.xml`, `.rou.xml`, `.sumocfg` | Identical SUMO files preserved | **PRESERVED**: 100% simulation definition maintained. |
| **Automated Backend Tests** | 34 tests across 10 files (including 12 AI tests) | 121 tests across 16 files (AI tests omitted, stress/queue added) | **EXPANDED BUT GAPPED**: 12 AI tests missing from test suite. |
| **Documentation & Reports** | PDF handover document, features report | 12 Markdown architecture and audit reports | **COMPLEMENTARY**: Old PDFs provide provenance; new docs provide deep engineering specs. |

---

## 3. Complete File-Level Mapping and Inventory

A strict inventory across all files reveals:
- **Total files in Historical Baseline (`ai-module`):** 136 non-ignored files.
- **Total files in Current Workspace (`hybrid-traffic-control`):** 1,257 non-ignored files.
- **Files common to both:** 95 files.
- **Files strictly identical:** 61 files.
- **Files with substantive modifications:** 34 files.
- **Files present ONLY in Historical Baseline:** 41 files.
- **Files present ONLY in Current Workspace:** 1,162 files (largely frontend 3D assets, tests, audit docs, scripts).

### 3.1 Forensic Analysis of the 41 Files ONLY in Historical Baseline

| # | File Path in Old Baseline | Size | Category | Forensic Purpose & Architectural Analysis |
| :--- | :--- | :--- | :--- | :--- |
| 1 | `traffic_service/ai/__init__.py` | 879 B | MARL Engine | Module exports for `MARLCorridorController`, agents, environment, and models. |
| 2 | `traffic_service/ai/models.py` | 9,213 B | MARL Engine | Dual PyTorch & NumPy neural architectures: `NumpyDense`, `NumpyDuelingDQN`, `NumpyActorCritic`, `DuelingDQNNetwork`, `ActorCriticNetwork`. Provides zero-dependency NumPy inference. |
| 3 | `traffic_service/ai/env.py` | 10,082 B | MARL Engine | 14-dimensional state vectorizer per junction (queues, densities, wait times, upstream inflow, signal phases), 3 discrete actions (`0=KEEP, 1=SWITCH, 2=EXTEND`), multi-objective reward formulation. |
| 4 | `traffic_service/ai/dqn_agent.py` | 7,875 B | MARL Engine | Multi-agent Double-DQN with Dueling architecture, 10,000-step experience replay buffer, epsilon-greedy exploration with decay, and action masking for signal safety. |
| 5 | `traffic_service/ai/ppo_agent.py` | 8,819 B | MARL Engine | Multi-agent Proximal Policy Optimization with Generalized Advantage Estimation (GAE $\lambda=0.95$), clipped surrogate objective ($\epsilon=0.2$), actor-critic trajectory buffers, and action masking. |
| 6 | `traffic_service/ai/marl_controller.py` | 13,382 B | MARL Engine | Multi-intersection decentralized coordinator managing J1, J2, J3. Implements inter-agent communication, safety constraint shield enforcement, fallback logic, and JSON checkpoint persistence. |
| 7 | `checkpoints/marl_dqn_corridor.json` | 982,917 B | Checkpoints | Complete trained model weights and biases for J1, J2, J3 DQN agents across all layers (`fc1`, `fc2`, `val_fc`, `val_out`, `adv_fc`, `adv_out`). |
| 8 | `checkpoints/marl_ppo_corridor.json` | 982,905 B | Checkpoints | Complete trained model weights and biases for J1, J2, J3 PPO agents across all layers (`fc1`, `fc2`, `actor_fc`, `actor_out`, `critic_fc`, `critic_out`). |
| 9 | `tests/test_ai_controller.py` | 9,749 B | Test Suite | 12 automated unit tests verifying observation normalization, reward calculation, DQN/PPO forward pass, action masking, fallback on invalid action, and multi-agent coordination. |
| 10 | `scripts/train_marl.py` | 11,847 B | MARL Scripts | Reproducible 8-episode / 300s SUMO training script for DQN and PPO agents across seeds, logging rewards, losses, and travel times. |
| 11 | `scripts/evaluate_marl.py` | 16,169 B | MARL Scripts | 5-seed benchmark evaluation harness running Fixed-Time Baseline, Coordinated Adaptive, MARL DQN, and MARL PPO on SUMO, generating statistical CSVs and JSONs. |
| 12 | `outputs/corridor/marl_multi_controller_summary.csv` | 1,209 B | Evaluation Data | 4-controller summary table across 9 metrics comparing Baseline, Coordinated, MARL DQN, and MARL PPO. |
| 13 | `outputs/corridor/marl_multi_controller_full_stats.csv` | 1,127 B | Evaluation Data | Full 5-seed mean and standard deviation statistical table for all 4 controllers. |
| 14 | `outputs/corridor/marl_multi_seed_detailed.json` | 18,393 B | Evaluation Data | Granular per-seed numerical metrics for all 4 controllers across seeds 1 to 5. |
| 15 | `outputs/corridor/training_logs/training_summary_dqn.json` | 3,622 B | Training Data | Per-episode rewards, junction losses, and travel times for the 8-episode DQN training run. |
| 16 | `outputs/corridor/training_logs/training_summary_ppo.json` | 3,655 B | Training Data | Per-episode rewards, junction losses, and travel times for the 8-episode PPO training run. |
| 17–21 | `outputs/corridor/baseline/seed_1.csv` to `seed_5.csv` | ~73 KB each (x5) | Simulation Traces | Step-by-step per-second simulation telemetry traces (time, queues, speeds, emissions) for Baseline across seeds 1–5. |
| 22–26 | `outputs/corridor/coordinated/seed_1.csv` to `seed_5.csv` | ~72 KB each (x5) | Simulation Traces | Step-by-step per-second simulation telemetry traces for Coordinated Adaptive across seeds 1–5. |
| 27–31 | `outputs/corridor/marl_dqn/seed_1.csv` to `seed_5.csv` | ~74 KB each (x5) | Simulation Traces | Step-by-step per-second simulation telemetry traces for MARL DQN across seeds 1–5. |
| 32–36 | `outputs/corridor/marl_ppo/seed_1.csv` to `seed_5.csv` | ~73 KB each (x5) | Simulation Traces | Step-by-step per-second simulation telemetry traces for MARL PPO across seeds 1–5. |
| 37 | `frontend_preview.html` | 89,328 B | Standalone UI | Standalone, single-file browser dashboard using Tailwind CSS, Chart.js, and Lucide icons from CDNs. Operates without Node.js or Vite. |
| 38 | `backend/static/index.html` | 85,243 B | Standalone UI | Identical or sister standalone HTML dashboard mounted at FastAPI `/static` and served at `/` and `/dashboard`. |
| 39 | `run_dashboard.py` | 1,584 B | Launcher | One-click Python launcher script that verifies dependencies, starts Uvicorn backend, and opens the default browser to `http://127.0.0.1:8000/`. |
| 40 | `docs/presentation_handover_document.pdf` | 7,355 B | Documentation | Official presentation handover document authored by Pallavi devi Y, Sneha, and Suma, documenting corridor topology, safety shields, benchmark results, and AI provenance. |
| 41 | `docs/freatures_report.pdf` | 1,599,967 B | Documentation | High-resolution technical features and architecture report PDF. |

### 3.2 Forensic Analysis of the 34 Substantively Modified Common Files

| File Path | Old Baseline Size | Current Workspace Size | Architectural Modifications & Engineering Rationale |
| :--- | :--- | :--- | :--- |
| `backend/main.py` | 5,526 B | 4,508 B | **Modified:** Static files mounting (`/static`) and `/dashboard` endpoint removed. WebSocket endpoint upgraded to use robust `session.enqueue` with monotonic sequence tracking, drop policy, and timestamps. |
| `backend/routers/experiments.py` | 11,876 B | 7,160 B | **Degraded & Rewritten:** Removed MARL summary endpoints (`/experiments/marl-summary`, `/marl-detailed`, `/marl-comparison`). Rewrote controller comparison endpoint to hardcode `"Not implemented"` for PPO and DQN because CSV and checkpoints were missing. |
| `backend/routers/signals.py` | 1,898 B | 2,453 B | **Improved:** Signal override endpoint updated to route through thread-safe `sim_service.request_manual_override()` utilizing TraCI command queue. |
| `backend/routers/simulation.py` | 3,240 B | 3,898 B | **Modified:** `valid_modes` restricted from `{"baseline", "coordinated", "marl_dqn", "marl_ppo"}` to `{"baseline", "coordinated"}`. Added startup timeout validation and HTTP status code mappings (409, 504, 500). |
| `backend/routers/traffic.py` | 2,763 B | 1,916 B | **Modified:** Removed composite `/api/traffic/corridor` endpoint (which combined metrics, junctions, and signals). |
| `backend/schemas.py` | 7,890 B | 7,878 B | **Modified:** Minor schema type updates and imports. |
| `backend/simulation_service.py` | 36,986 B | 79,705 B | **Significantly Hardened (+115%):** Added `TraCICommandQueue` for thread-safe command execution, port hunting, watchdog thread, snapshot manager integration, and robust process termination. |
| `backend/websocket_manager.py` | 1,780 B | 12,910 B | **Significantly Hardened (+625%):** Rewritten with monotonic sequence tracking, client session buffering, queue overflow drop policies, frame coalescing, and clean disconnection cleanup. |
| `common/sumo_env.py` | 4,697 B | 4,230 B | **Cleaned:** Refined Windows path normalization and TraCI import fallback. |
| `frontend/package.json` | 510 B | 869 B | **Expanded:** Added Three.js, `@react-three/fiber`, `@react-three/drei`, and Canvas dependencies. |
| `frontend/src/App.jsx` | 22,172 B | 20,406 B | **Modernized:** Added Tabbed navigation (2D Corridor, 3D Digital Twin, Analytics, Risk), Snapshot Recovery Modal, high-contrast light theme, and error boundaries. |
| `frontend/src/components/ControllerComparison.jsx` | 11,359 B | 12,645 B | **Modified:** Upgraded to high-contrast white styling and robust loading/error states. However, MARL comparison bars were hidden because backend returned "Not implemented". |
| `frontend/src/components/EmergencyPanel.jsx` | 6,181 B | 5,986 B | **Refactored:** Light theme styling and component cleanup. |
| `frontend/src/components/EmissionAnalytics.jsx` | 8,299 B | 5,785 B | **Refactored:** Recharts styling and responsive containers optimized. |
| `frontend/src/components/Header.jsx` | 5,265 B | 4,194 B | **Refactored:** Clean white navbar with connection indicator, reset simulation, and tab switching. |
| `frontend/src/components/LiveCorridorView.jsx` | 20,708 B | 12,637 B | **Refactored:** Cleaned repetitive JSX, improved badge styling, and modularized state rendering. |
| `frontend/src/components/OverviewKPIs.jsx` | 4,094 B | 3,022 B | **Refactored:** Clean KPI card layouts and metric formatting. |
| `frontend/src/components/RiskHotspotsPanel.jsx` | 6,639 B | 6,486 B | **Refactored:** BTP accident risk and blackspot visualization refined. |
| `frontend/src/components/SignalStatusPanel.jsx` | 10,235 B | 8,047 B | **Refactored:** Signal phase indicators, timing bars, and manual override dialogs refined. |
| `frontend/src/components/SimulationControls.jsx` | 11,309 B | 10,665 B | **Degraded:** Controller dropdown removed `<option value="marl_ppo">` and `<option value="marl_dqn">`. Action buttons updated with teal primary accents. |
| `frontend/src/components/WhatIfScenario.jsx` | 7,977 B | 7,633 B | **Refactored:** Scenario parameters and accident injection controls cleaned. |
| `frontend/src/index.css` | 856 B | 804 B | **Refactored:** Tailwind utility overrides and light theme base CSS. |
| `frontend/src/services/api.js` | 2,551 B | 2,258 B | **Modified:** Removed `window.location.protocol === 'file:'` fallback; standardized on `/api` Vite proxy. |
| `frontend/src/services/websocket.js` | 3,033 B | 14,922 B | **Significantly Hardened (+391%):** Full resilient client with heartbeat pings, reconnect backoff, sequence gap detection, and error logging. |
| `frontend/vite.config.js` | 488 B | 819 B | **Updated:** Added Vitest configuration and proxy tuning. |
| `outputs/corridor/corridor_multi_seed_summary.csv` | 1,265 B | 1,256 B | **Identical Data:** Line endings normalized. |
| `tests/test_api.py` | 7,247 B | 4,917 B | **Degraded:** Removed tests for `/dashboard`, `/`, `/api`, and tests asserting PPO/DQN empirical metrics. Added assertion forcing PPO/DQN to be "Not implemented". |
| `tests/test_metrics.py` | 3,132 B | 5,494 B | **Expanded:** Added comprehensive checks for speed, travel time, and emissions calculation. |
| `traffic_service/corridor_metrics.py` | 7,876 B | 8,049 B | **Expanded:** Enhanced HBEFA 3.1 emission models and metric aggregation. |
| `traffic_service/multi_intersection_simulation.py` | 14,306 B | 13,484 B | **Degraded:** Removed `MARLCorridorController` instantiation and TraCI step execution lines (`if self.mode in ("marl_dqn", "marl_ppo")`) because `traffic_service.ai` was omitted. |
| `traffic_service/state_extractor.py` | 9,846 B | 10,608 B | **Expanded:** Added detailed lane-level density and queue metrics for 3D digital twin. |
| `traffic_service/sumo_manager.py` | 2,778 B | 8,933 B | **Significantly Hardened (+221%):** Dynamic TraCI port finding, retry logic, process monitoring, and safe cleanup. |
| `.gitignore` | 661 B | 590 B | **Modified:** Path rule adjustments. |

---

## 4. Deep-Dive Forensic Review: The Multi-Agent RL (MARL) Engine

### 4.1 Architecture and Mathematical Formulation

The MARL engine in `traffic_service/ai/` consists of 5 modular components designed for decentralized multi-agent control across the 3 junctions:

```mermaid
flowchart LR
    subgraph SUMO TraCI Simulation
        SIM["SUMO Simulation (J1, J2, J3)"]
    end

    subgraph Feature Extraction
        OBS["CorridorObservationSpace (env.py)<br/>14-Dim Vector per Junction:<br/>• Phase IDs (One-Hot)<br/>• Min/Max Green Remaining<br/>• Approach Queues & Densities<br/>• Upstream Inflow Estimate<br/>• Emergency Wave Distance"]
    end

    subgraph MARL Decision Controller
        MARL["MARLCorridorController (marl_controller.py)<br/>Decentralized Agents: J1, J2, J3"]
        DQN["DQNAgent (dqn_agent.py)<br/>• Dueling Architecture<br/>• Double-DQN Loss<br/>• Replay Buffer (10k)"]
        PPO["PPOAgent (ppo_agent.py)<br/>• Actor-Critic Network<br/>• GAE Advantages<br/>• Clipped Surrogate Loss"]
    end

    subgraph Safety & Execution
        SHIELD["SignalSafetyShield<br/>• Min Green (15-20s)<br/>• Max Green (60-75s)<br/>• Yellow Clearance (4s/6s)<br/>• Emergency Preemption"]
        ACT["Discrete Action Execution:<br/>0 = KEEP<br/>1 = SWITCH<br/>2 = EXTEND"]
    end

    SIM --> OBS
    OBS --> MARL
    MARL --> DQN
    MARL --> PPO
    DQN --> SHIELD
    PPO --> SHIELD
    SHIELD --> ACT
    ACT --> SIM
```

#### Observation Space (`env.py`)
Each junction agent receives a continuous 14-dimensional normalized vector:
1. `current_phase_idx`: Normalized phase index $[0, 1]$.
2. `current_phase_elapsed_s`: Elapsed time in current phase normalized by $60\text{ s}$.
3. `is_min_green_met`: Binary flag ($1.0$ if elapsed $\ge$ min green, else $0.0$).
4. `is_max_green_exceeded`: Binary flag ($1.0$ if elapsed $\ge$ max green, else $0.0$).
5–8. `approach_queue_lengths`: Normalized vehicle queue counts across the 4 approaches (divided by $30.0$).
9–12. `approach_vehicle_densities`: Normalized vehicle density across the 4 approaches.
13. `upstream_inflow_estimate`: Predicted arriving vehicle platoon count from upstream neighbor (via `CorridorCommunicationHub`).
14. `emergency_vehicle_distance`: Normalized distance to nearest active ambulance (or $1.0$ if none).

#### Action Space (`env.py`, `models.py`)
Each agent selects from 3 discrete actions:
- `Action 0 (KEEP)`: Continue the current active green phase.
- `Action 1 (SWITCH)`: Terminate current green and request transition to the next phase (triggers yellow clearance).
- `Action 2 (EXTEND)`: Extend current green duration by $+5\text{ seconds}$ (up to max green).

#### Action Masking & Safety Shielding
The agent's discrete actions pass through `get_action_mask()`. If minimum green has not elapsed, `SWITCH` is strictly masked (probability set to $-\infty$). If maximum green is reached, `KEEP` and `EXTEND` are strictly masked, forcing a transition.

#### Dual NumPy / PyTorch Neural Networks (`models.py`)
To prevent hard dependencies on GPU environments or large torch binaries during lightweight inference:
- **`NumpyDuelingDQN`**: Fully vectorized NumPy implementation of Dueling Double-DQN. Splits hidden representation into Value Stream $V(s)$ and Advantage Stream $A(s, a)$:
  $$Q(s, a) = V(s) + \left(A(s, a) - \frac{1}{|A|}\sum_{a'} A(s, a')\right)$$
- **`NumpyActorCritic`**: Vectorized NumPy implementation of Actor-Critic network with shared trunk, policy head $\pi(a|s)$ (softmax), and value head $V(s)$.
- **PyTorch equivalents**: `DuelingDQNNetwork` and `ActorCriticNetwork` implement the exact same layer shapes and parameter names for training.

### 4.2 Checkpoint Verification

Both checkpoints (`checkpoints/marl_dqn_corridor.json` and `checkpoints/marl_ppo_corridor.json`) were inspected in detail:
- **DQN Checkpoint:** Stored as JSON containing metadata (`algorithm: dqn, seed: 42, junctions: [J1, J2, J3]`) and complete weight matrices for each agent:
  - `fc1_w` ($14 \times 64$), `fc1_b` ($64$)
  - `fc2_w` ($64 \times 64$), `fc2_b` ($64$)
  - `val_fc_w` ($64 \times 32$), `val_fc_b` ($32$), `val_out_w` ($32 \times 1$), `val_out_b` ($1$)
  - `adv_fc_w` ($64 \times 32$), `adv_fc_b` ($32$), `adv_out_w` ($32 \times 3$), `adv_out_b` ($3$)
- **PPO Checkpoint:** Stored as JSON containing metadata and complete weight matrices for each agent:
  - `fc1_w` ($14 \times 64$), `fc1_b` ($64$)
  - `fc2_w` ($64 \times 64$), `fc2_b` ($64$)
  - `actor_fc_w` ($64 \times 32$), `actor_fc_b` ($32$), `actor_out_w` ($32 \times 3$), `actor_out_b` ($3$)
  - `critic_fc_w` ($64 \times 32`), `critic_fc_b` ($32$), `critic_out_w` ($32 \times 1`), `critic_out_b` ($1$)

### 4.3 Automated AI Test Suite Execution
Running `pytest tests/test_ai_controller.py` on the historical codebase under Python 3.13 confirmed that all 12 tests pass cleanly:
1. `test_observation_vectorizer_shape`: Verifies 14-dim output vector.
2. `test_observation_normalization`: Verifies bounds $[0, 1]$.
3. `test_reward_calculation`: Verifies multi-objective delay and queue penalty.
4. `test_action_masking_min_green`: Verifies SWITCH is masked when elapsed < min green.
5. `test_action_masking_max_green`: Verifies KEEP/EXTEND masked when elapsed $\ge$ max green.
6. `test_dqn_forward_pass`: Verifies forward Q-value computation.
7. `test_ppo_forward_pass`: Verifies policy distribution and value estimates.
8. `test_dqn_action_selection`: Verifies epsilon-greedy and greedy evaluation modes.
9. `test_ppo_action_selection`: Verifies categorical sampling and deterministic argmax.
10. `test_marl_controller_decide`: Verifies 3-junction coordinated decisions.
11. `test_marl_controller_fallback`: Verifies graceful fallback to safety controller on corrupted observations.
12. `test_checkpoint_load_save`: Verifies JSON weight serialization and round-trip fidelity.

---

## 5. Empirical Benchmark Comparison: Historical Results

The table below reproduces the authentic 5-seed empirical benchmark data from `outputs/corridor/marl_multi_controller_summary.csv` and `marl_multi_controller_full_stats.csv`:

| Evaluation Metric | Fixed-Time Baseline | Coordinated Adaptive | MARL PPO (Trained) | MARL DQN (Trained) | Coordinated vs Base (%) | PPO vs Base (%) | DQN vs Base (%) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Corridor Travel Time (s)** | $90.99 \pm 1.30$ | $\mathbf{57.19 \pm 3.89}$ | $65.15 \pm 3.79$ | — | **-37.1%** | **-28.4%** | — |
| **Average Speed (km/h)** | $27.84 \pm 0.33$ | $\mathbf{36.52 \pm 0.60}$ | $25.56 \pm 0.92$ | $20.23 \pm 0.12$ | **+31.2%** | -8.2% | -27.3% |
| **Total Waiting Time (s)** | $778.29 \pm 17.86$ | $\mathbf{298.00 \pm 37.50}$ | $1,568.53 \pm 20.32$ | $5,401.97 \pm 120.09$ | **-61.7%** | +101.5% | +594.1% |
| **Mean Corridor Queue (veh)**| $20.00 \pm 0.32$ | $\mathbf{10.65 \pm 0.81}$ | $29.50 \pm 0.38$ | $63.35 \pm 1.03$ | **-46.8%** | +47.5% | +216.8% |
| **Max Corridor Queue (veh)** | $58.00 \pm 1.00$ | $\mathbf{31.80 \pm 4.15}$ | $59.00 \pm 5.05$ | $90.00 \pm 1.87$ | **-45.2%** | +1.7% | +55.2% |
| **Completed Trips** | $102.0 \pm 0.0$ | $101.0 \pm 0.0$ | $\mathbf{102.2 \pm 0.45}$ | $0.0 \pm 0.0$ | -1.0% | **+0.2%** | -100.0% |
| **Total $\text{CO}_2$ (kg)** | $53.70 \pm 0.25$ | $\mathbf{42.61 \pm 0.72}$ | $61.50 \pm 0.85$ | $79.07 \pm 0.78$ | **-20.7%** | +14.5% | +47.2% |
| **Total Fuel (L)** | $17,384 \pm 81.7$ | $\mathbf{13,795 \pm 234.3}$ | $19,912 \pm 275.2$ | $25,611 \pm 252.0$ | **-20.6%** | +14.5% | +47.3% |
| **Ambulance Traversal (s)** | $41.00 \pm 5.96$ | $\mathbf{33.60 \pm 5.64}$ | $41.00 \pm 7.00$ | — | **-18.0%** | 0.0% | — |

### 5.1 Scientific and Practical Takeaways
1. **Coordinated Adaptive Control** achieves the strongest overall performance: reducing travel time by **37.1%**, waiting time by **61.7%**, and fuel/emissions by **20.6%**, while clearing ambulances **18.0% faster**.
2. **MARL PPO** demonstrates substantial convergence after 8 training episodes: reducing travel time by **28.4%** ($65.15\text{ s}$ vs $90.99\text{ s}$) and completing all $102$ trips. However, because it was trained with an 8-episode budget, it prioritized arterial throughput at the expense of side-street queues.
3. **MARL DQN** required more exploration steps than the 8-episode budget allowed; off-policy Q-learning over-penalized phase switches and resulted in side-street gridlock.
4. **Academic Integrity:** The original presentation handover document explicitly noted that Coordinated Adaptive was the proven production deployment, while MARL PPO and DQN served as research benchmarks.

---

## 6. Frontend and Visualization Forensic Comparison

### 6.1 Feature Comparison Table

| Visual / UI Feature | Historical Baseline (`ai-module`) | Current Workspace (`hybrid-traffic-control`) | Recommendation & Final Disposition |
| :--- | :--- | :--- | :--- |
| **Corridor 2D Schematic Map** | SVG / Canvas showing J1, J2, J3, queues, and signal circles | SVG / Canvas showing J1, J2, J3, queues, and signal circles | **PRESERVED**: Both render clean 2D corridor status. |
| **Corridor 3D Digital Twin** | Not present | React Three Fiber 3D Scene with road meshes, animated vehicles, 3D signal heads, and camera controls | **IMPROVED**: 3D Twin is a premier engineering capability. Must be preserved as a primary tab. |
| **Controller Selection Dropdown** | 4 Options: Coordinated, Baseline, MARL PPO, MARL DQN | 2 Options: Coordinated, Baseline | **DEGRADED**: Restore `marl_ppo` and `marl_dqn` dropdown options once backend dispatch is re-connected. |
| **Standalone Browser Preview** | `frontend_preview.html` and `run_dashboard.py` runnable with zero Node.js | Removed (Requires Node.js + `npm run dev`) | **LOST**: Re-integrate `frontend_preview.html` and `run_dashboard.py` as zero-dependency fallback. |
| **UI Theme & Contrast** | Mixed dark/blue theme | Professional high-contrast white/light theme | **IMPROVED**: The white/light theme meets accessibility standards and looks executive-ready. |
| **Snapshot Recovery Manager** | Not present | Full UI modal and backend service for snapshot inspection and state restoration | **IMPROVED**: Must be preserved. |
| **Emergency Wave Dispatch** | Button in `EmergencyPanel.jsx` | Button in `EmergencyPanel.jsx` with active route highlight | **PRESERVED & IMPROVED**. |
| **Accident Hotspots & Risk** | `RiskHotspotsPanel.jsx` | `RiskHotspotsPanel.jsx` with Leaflet / BTP station data | **PRESERVED**. |

---

## 7. API and WebSocket Protocol Comparison

### 7.1 REST Endpoints Comparison

| Endpoint | Method | Old Baseline Status | Current Workspace Status | Architectural Assessment |
| :--- | :---: | :--- | :--- | :--- |
| `/` | GET | Serves `index.html` (if browser) or API info (if API client) | Serves API descriptor JSON only | **Lost Static Serving**: Re-add conditional static serving for standalone dashboard. |
| `/dashboard` | GET | Explicitly serves `backend/static/index.html` | Removed | **Lost Endpoint**: Restore for one-click browser access. |
| `/api` | GET | Service descriptor | Service descriptor | **Preserved**. |
| `/api/health` | GET | Returns DB and simulation status | Returns DB and simulation status | **Preserved**. |
| `/api/simulation/start` | POST | Accepts `mode in ("baseline", "coordinated", "marl_dqn", "marl_ppo")` | Restricted to `mode in ("baseline", "coordinated")` | **Regressed**: Restore MARL modes in validation set. |
| `/api/simulation/pause` | POST | Pauses simulation thread | Dispatches via thread-safe TraCI queue | **Improved**. |
| `/api/simulation/resume` | POST | Resumes simulation thread | Dispatches via thread-safe TraCI queue | **Improved**. |
| `/api/simulation/stop` | POST | Stops simulation | Dispatches via thread-safe TraCI queue + watchdog | **Improved**. |
| `/api/signals/override` | POST | Direct TraCI phase change | Dispatched via thread-safe TraCI queue | **Improved**. |
| `/api/traffic/corridor` | GET | Combined corridor telemetry | Removed | **Omitted**: Restore endpoint for backward compatibility. |
| `/api/experiments/compare` | GET | Returned measured baseline/coord + MARL checkpoint status | Hardcoded "Not implemented" for PPO and DQN | **Regressed**: Restore dynamic reading of MARL CSV and checkpoints. |
| `/api/experiments/marl-summary` | GET | Returned MARL CSV summary | Removed | **Omitted**: Restore endpoint. |
| `/api/experiments/marl-detailed`| GET | Returned detailed JSON metrics | Removed | **Omitted**: Restore endpoint. |

### 7.2 WebSocket Streaming Architecture

The WebSocket implementation in the new workspace is a massive improvement over the old baseline:
- **Historical Baseline (`websocket_manager.py`):** Used a basic list of `active_connections` and broadcast JSON payloads directly across an unbuffered asyncio loop. If a client experienced browser jank or lagged on rendering, backpressure caused thread blocking or connection drops.
- **Current Workspace (`websocket_manager.py`):** Implements `ClientSession` with a bounded queue (`maxsize=100`), drop-oldest policy, monotonic sequence numbering (`sequence_number`), UTC timestamps, frame coalescing, and client heartbeat ping/pong handling.

**Verdict:** The new WebSocket architecture is far superior and must be 100% preserved.

---

## 8. Test Suite Forensic Comparison

### 8.1 Automated Test Distribution

| Test File | Historical Baseline | Current Workspace | Test Focus & Forensic Status |
| :--- | :---: | :---: | :--- |
| `test_accident_risk.py` | 11 tests | 11 tests | BTP accident data parsing, risk scoring, spatial mapping (**Identical**). |
| `test_ai_controller.py` | 12 tests | 0 tests | **MISSING**: 12 tests covering DQN, PPO, observation spaces, action masking. |
| `test_api.py` | 12 tests | 7 tests | **DEGRADED**: 5 tests removed (dashboard endpoints and MARL metric checks). |
| `test_command_queue.py` | 0 tests | 14 tests | **NEW**: TraCI command queue ordering, timeouts, priority, and thread safety. |
| `test_communication.py` | 5 tests | 5 tests | CorridorCommunicationHub neighbor platoon exchange (**Identical**). |
| `test_coordinate_transformation.py` | 0 tests | 8 tests | **NEW**: SUMO to Three.js Cartesian coordinate mapping. |
| `test_corridor_geometry_extraction.py`| 0 tests | 6 tests | **NEW**: OSM/SUMO road shape extraction and lane parsing. |
| `test_database.py` | 2 tests | 2 tests | SQLite persistence, run logs, and metric tables (**Identical**). |
| `test_full_stack_stress.py` | 0 tests | 12 tests | **NEW**: Rapid start/pause/resume/override concurrent load testing. |
| `test_metrics.py` | 2 tests | 10 tests | **EXPANDED**: HBEFA 3.1 emissions, travel time, and queue metrics. |
| `test_simulation_integration.py` | 1 test | 1 test | End-to-end SUMO TraCI step integration (**Identical**). |
| `test_simulation_service.py` | 1 test | 1 test | Simulation service lifecycle (**Identical**). |
| `test_startup_watchdog.py` | 0 tests | 18 tests | **NEW**: Process watchdog, crash detection, zombie process cleanup. |
| `test_websocket.py` | 1 test | 1 test | Basic WebSocket connection (**Identical**). |
| `test_websocket_ordering.py` | 0 tests | 12 tests | **NEW**: Monotonic sequence order, dropped frame recovery. |
| `test_websocket_resilience.py` | 0 tests | 13 tests | **NEW**: High-concurrency disconnect/reconnect resilience. |
| **Total Automated Tests** | **34 Tests** | **121 Tests** | **Target upon AI restoration: 133 Tests**. |

---

## 9. Staged Recovery Roadmap (P0 to P6)

To execute feature recovery strictly in accordance with the user's instructions (non-destructive, zero regression, full test verification), the following 7-stage roadmap is established:

```mermaid
flowchart TD
    P0["Stage P0: MARL Core & Checkpoints<br/>Copy traffic_service/ai/ and checkpoints/<br/>(models, env, dqn, ppo, weights)"]
    P1["Stage P1: AI Test Suite Re-integration<br/>Restore tests/test_ai_controller.py<br/>Verify 12/12 passing tests"]
    P2["Stage P2: Empirical Benchmarks & Router<br/>Restore outputs/corridor/ multi-seed CSVs<br/>Restore /experiments/marl-* endpoints"]
    P3["Stage P3: TraCI Simulation Engine Reconnection<br/>Restore marl_dqn and marl_ppo dispatch<br/>in multi_intersection_simulation.py"]
    P4["Stage P4: Frontend Controller Controls<br/>Restore MARL options in SimulationControls.jsx<br/>Restore benchmark cards in ControllerComparison.jsx"]
    P5["Stage P5: Standalone HTML Dashboard<br/>Restore frontend_preview.html, static mount,<br/>and run_dashboard.py launcher"]
    P6["Stage P6: MARL Training & Evaluation Scripts<br/>Restore scripts/train_marl.py and<br/>scripts/evaluate_marl.py"]

    P0 --> P1 --> P2 --> P3 --> P4 --> P5 --> P6
```

### Detailed Stage Specifications

- **Stage P0: Re-integrate MARL Engine and Checkpoints (Priority: CRITICAL)**
  - Action: Copy `traffic_service/ai/` (`__init__.py`, `models.py`, `env.py`, `dqn_agent.py`, `ppo_agent.py`, `marl_controller.py`) and `checkpoints/` (`marl_dqn_corridor.json`, `marl_ppo_corridor.json`) into workspace.
  - Acceptance: Pure NumPy and PyTorch imports succeed; JSON weight matrices load without schema errors.

- **Stage P1: Restore AI Automated Tests (Priority: CRITICAL)**
  - Action: Copy `tests/test_ai_controller.py` into `tests/`.
  - Acceptance: `pytest tests/test_ai_controller.py` runs and passes 12/12 tests in local environment.

- **Stage P2: Restore Empirical Benchmark Data and Router (Priority: HIGH)**
  - Action: Copy `outputs/corridor/` benchmark CSVs, detailed JSONs, and training logs into workspace. Update `backend/routers/experiments.py` to restore `/experiments/marl-summary`, `/marl-detailed`, and dynamic reading of verified metrics.
  - Acceptance: `GET /api/experiments/compare` returns measured stats for Baseline, Coordinated, and PPO, and reports trained checkpoint status.

- **Stage P3: Re-connect TraCI Simulation Engine (Priority: HIGH)**
  - Action: Update `backend/routers/simulation.py` to accept `marl_dqn` and `marl_ppo`. In `traffic_service/multi_intersection_simulation.py`, re-enable `MARLCorridorController` loading and step execution branch.
  - Acceptance: Simulation starts with mode `marl_ppo` or `marl_dqn` and advances TraCI signal phases using trained network weights.

- **Stage P4: Frontend Controls and Benchmark Display (Priority: HIGH)**
  - Action: Re-add `<option value="marl_ppo">` and `<option value="marl_dqn">` in `frontend/src/components/SimulationControls.jsx`. Update `ControllerComparison.jsx` to render MARL comparison cards.
  - Acceptance: User can select MARL controllers from dropdown and view benchmark comparison charts.

- **Stage P5: Standalone Preview Dashboard and Launcher (Priority: MEDIUM)**
  - Action: Restore `frontend_preview.html`, `backend/static/index.html`, conditional static mount in `backend/main.py`, and `run_dashboard.py`.
  - Acceptance: Running `python run_dashboard.py` starts backend and opens browser with zero Node.js dependencies.

- **Stage P6: Training and Evaluation Scripts (Priority: MEDIUM)**
  - Action: Copy `scripts/train_marl.py` and `scripts/evaluate_marl.py` into `scripts/`.
  - Acceptance: Standalone scripts can execute SUMO evaluation runs.

---

## 10. Explicit Unresolved Questions for User Review

Before executing the recovery plan in subsequent stages, the following architectural decisions are submitted for user confirmation:

1. **Controller Dropdown Ordering:** In the frontend dropdown, should the recommended order be:
   - Option A: Coordinated Adaptive (Default) $\rightarrow$ Isolated Actuated (when implemented) $\rightarrow$ Fixed-Time Baseline $\rightarrow$ MARL PPO $\rightarrow$ MARL DQN?
   - Option B: Grouped by family (Rule-Based vs Learning-Based)?
2. **PyTorch vs NumPy Inference Default:** Both runtimes are supported in `models.py`. Should the default runtime for TraCI simulation favor NumPy (zero dependency, zero CUDA overhead, ultra-fast for small MLP batches) or PyTorch?
3. **Standalone Dashboard Mount:** Should `GET /` continue to serve API descriptor JSON when accessed programmatically (e.g. via `curl` or tests), while serving `index.html` only when `Accept: text/html` is requested by a browser? (Recommended: Yes, this preserves both API test behavior and one-click browser convenience).

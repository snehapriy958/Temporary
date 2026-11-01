# Document 02: Complete Model Inventory & Algorithmic Audit

**Project:** Smart Traffic Coordination System — Bengaluru Silk Board Corridor  
**Audit Date:** October 31, 2026  
**Auditor:** Principal Software Architect & ML/RL Systems Auditor  
**Audit Scope:** Deep Codebase Search, Algorithmic Dissection, Model Lineage, and Operational Classification  

---

## 1. Executive Summary: ML & RL Reality Check

A primary mandate of this technical health audit is to rigorously distinguish between **what is actually implemented, trained, and running in production** versus **what is documented as an aspiration or exposed as an architectural placeholder**.

### Definitive Findings:
1. **Reinforcement Learning (PPO / DQN / MARL):** **DO NOT EXIST AS FUNCTIONAL NEURAL NETWORKS.** No PyTorch, TensorFlow, Keras, or ONNX model files (`.pt`, `.pth`, `.onnx`, `.pkl`, `.h5`) exist in the repository. There is no experience replay buffer, no actor-critic architecture, no policy network, and no training loop. In `backend/routers/experiments.py`, both PPO and DQN are explicitly returned with `status="Not implemented"`. Clean observation hooks exist in `MultiIntersectionSimulation.get_ai_observations()` and action dispatch hooks exist in `_apply_ai_actions()`, but they currently connect to no neural network.
2. **Machine Learning / Statistical Clustering:** **DBSCAN Clustering EXISTS and is FUNCTIONAL.** In `traffic_service/hotspot_analyzer.py`, `scikit-learn`'s `sklearn.cluster.DBSCAN` is utilized to perform metric Euclidean clustering on WGS84 blackspots projected into Cartesian UTM Zone 43N coordinates. This is an **offline unsupervised learning pipeline** that produces `outputs/hotspots/hotspots.csv`.
3. **Operational Signal Controllers:** **RULE-BASED / FINITE STATE HEURISTICS.** The active traffic controller running at runtime is a centralized, constraint-enforcing rule-based heuristic with inter-junction inflow anticipation (`CorridorCommunicationHub`) and emergency vehicle preemption (`EmergencyWaveCoordinator`).

---

## 2. Master Model & Algorithm Inventory Table

| Field | Model 1: Coordinated Adaptive Controller | Model 2: Signal Constraint Controller | Model 3: Emergency Green Wave Coordinator | Model 4: Fixed-Time Baseline Controller | Model 5: Spatial DBSCAN Hotspot Clustering | Model 6: MoRTH Composite Risk Index (CRI) | Model 7: PPO Reinforcement Learning | Model 8: DQN Deep Q-Network | Model 9: Demand Scenario Generator |
|---|---|---|---|---|---|---|---|---|---|
| **Model Name** | Coordinated Adaptive Heuristic | SignalController Constraint Engine | EmergencyWaveCoordinator | Static SUMO Fixed-Time Plan | Metric DBSCAN Hotspot Clustering | MoRTH/IRC CRI Risk Mapper | Proximal Policy Optimization (PPO) | Deep Q-Network (DQN) | ScenarioGenerator |
| **Location** | `traffic_service/multi_intersection_simulation.py:246` | `traffic_service/signal_controller.py:16` | `traffic_service/emergency_wave.py:46` | Eclipse SUMO internal engine / `silk_board.net.xml` | `traffic_service/hotspot_analyzer.py:44` | `traffic_service/risk_mapper.py:38` | `backend/routers/experiments.py:98` | `backend/routers/experiments.py:111` | `traffic_service/scenario_generator.py:64` |
| **Purpose** | Dynamic signal phase extension & switching based on approach queue pressure & upstream inflow | Enforces safety constraints (min_green, max_green, yellow clearance) | Corridor-wide progressive green wave priority for approaching ambulances | Uncoordinated baseline traffic signal benchmark | Clusters documented blackspots into geographic high-risk collision zones | Standardizes crash severity and corridor hazard into operational risk tiers | Multi-agent continuous/discrete signal control policy | Value-based discrete phase duration optimization | Parameterized demand scaling (Normal, Peak, Emergency, Incident) |
| **Inputs** | Approach queue lengths, upstream inflow rate, phase elapsed time, min/max green | Current phase, target phase, elapsed green time, emergency lock flag | Ambulance position, speed, distance to stopline, approach lane | SUMO internal time counters | Blackspot Cartesian coordinates $(x, y)$ in UTM Zone 43N | Fatal crashes, non-fatal crashes, corridor relevance, junction proximity | Observation dict: queues, speeds, wait times, inflow, emissions | Q-state: approach queues, current phase, elapsed time | Flow rates, route IDs, vehicle mix, depart intervals |
| **Outputs** | Action decision: KEEP, SWITCH, or EXTEND | Safe phase transition (yellow duration, target green phase) | Immediate priority green hold or yellow transition | Static phase switching based on hardcoded cycle timer | Cluster labels (`labels = dbscan.fit_predict(coords)`) | Composite score (0-100+) & Tier: CRITICAL, HIGH, MEDIUM, LOW | Action: discrete `(0, 1, 2)` or continuous phase durations | Q-values for actions `(0, 1, 2)` | Generated SUMO `.rou.xml` route/flow file |
| **Training Code** | None (Deterministic Heuristic) | None (Deterministic Rule-Base) | None (Deterministic Tracking) | None (Static Plan) | Unsupervised fitting (`DBSCAN.fit_predict`) | None (Domain Formula) | **MISSING** (No training script exists) | **MISSING** (No training script exists) | None (XML Procedural Generator) |
| **Dataset / Env** | Live SUMO TraCI simulation state | TraCI traffic light API | TraCI vehicle & lane API | OSM network configuration | `data/accidents/raw/btp_corridor_blackspots_raw.csv` | `outputs/hotspots/hotspots.csv` | None | None | Parameter presets |
| **Checkpoint** | None (Code-defined rules) | None (Code-defined rules) | None (Code-defined rules) | None (XML definitions) | None (Ephemeral in-memory cluster model) | None (Formulaic thresholds) | **MISSING** (No `.pt`/`.pth` weights) | **MISSING** (No `.pt`/`.pth` weights) | None |
| **Training Status** | Not Applicable | Not Applicable | Not Applicable | Not Applicable | Trained / Fitted offline | Not Applicable | **NOT TRAINED** | **NOT TRAINED** | Not Applicable |
| **Evaluation** | Multi-seed 5-run benchmark (`corridor_multi_seed_summary.csv`) | Verified by unit tests & TraCI safety invariants | Verified by 5-seed emergency traversal evaluation | Evaluated as benchmark baseline | Verified against BTP South Division audit records | Validated against MoRTH IRC:SP:88 guidelines | **NONE** (Metrics are `None`) | **NONE** (Metrics are `None`) | Validated via network route checking |
| **SUMO Integration** | **Directly Integrated** via TraCI | **Directly Integrated** via TraCI | **Directly Integrated** via TraCI | **Directly Integrated** in SUMO | Indirect (Maps to SUMO edges/junctions) | Indirect (Maps to SUMO edges/junctions) | Observation hook exists, model missing | Observation hook exists, model missing | Generates valid SUMO demand XML |
| **Runtime Usage** | **ACTIVE** (Default running controller) | **ACTIVE** (Wraps all signal actions) | **ACTIVE** (Active when emergency enabled) | **ACTIVE** (When `mode="baseline"`) | **OFFLINE** (Pre-computed artifact served) | **OFFLINE** (Pre-computed artifact served) | **UNUSED** (Placeholder only) | **UNUSED** (Placeholder only) | **OFFLINE** (Script utility) |
| **Tests** | `test_simulation_integration.py`, `test_simulation_service.py` | `test_command_queue.py`, `test_simulation_service.py` | `test_communication.py`, `test_simulation_integration.py` | `test_simulation_integration.py` | `test_accident_risk.py` (11 tests) | `test_accident_risk.py` | `backend/routers/experiments.py` contract test | `backend/routers/experiments.py` contract test | Manual script validation |
| **Recommendation** | **KEEP & HARDEN** | **KEEP & HARDEN** | **KEEP & HARDEN** | **KEEP** (Essential benchmark) | **KEEP & AUTOMATE** | **KEEP & INTEGRATE** | **RETAIN HOOKS FOR PHASE 4** | **RETAIN HOOKS FOR PHASE 4** | **INTEGRATE INTO SANDBOX API** |

---

## 3. Seven-Tier Implementation Classification

To eliminate ambiguity between code existence and operational reality, every model is audited across seven strict criteria:

| Model / Algorithm | 1. Source Exists | 2. Pipeline Exists | 3. Model Trained | 4. Checkpoint Exists | 5. Evaluated | 6. Connected to SUMO | 7. Actively Operational | Verdict |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|---|
| **Coordinated Adaptive Heuristic** | YES | YES (Live) | N/A (Rule) | N/A | YES | YES | **YES** | **Fully Operational Rule-Based Model** |
| **SignalController Safety Shield** | YES | YES (Live) | N/A (Rule) | N/A | YES | YES | **YES** | **Fully Operational Safety Controller** |
| **EmergencyWaveCoordinator** | YES | YES (Live) | N/A (Rule) | N/A | YES | YES | **YES** | **Fully Operational Preemption Model** |
| **Fixed-Time Baseline** | YES | YES (SUMO) | N/A (Static) | N/A | YES | YES | **YES** | **Fully Operational Baseline Controller** |
| **DBSCAN Hotspot Clustering** | YES | YES (Offline) | **YES** | N/A (Transient)| YES | YES (Spatial) | **OFFLINE ONLY** | **Fully Functional Offline ML Model** |
| **MoRTH Risk Mapper (CRI)** | YES | YES (Offline) | N/A (Rule) | N/A | YES | YES (Spatial) | **OFFLINE ONLY** | **Fully Functional Risk Model** |
| **PPO Reinforcement Learning** | PARTIAL (Hooks)| **NO** | **NO** | **NO** | **NO** | PARTIAL (Hooks)| **NO** | **Architectural Placeholder** |
| **DQN Deep Q-Network** | PARTIAL (Hooks)| **NO** | **NO** | **NO** | **NO** | PARTIAL (Hooks)| **NO** | **Architectural Placeholder** |
| **Demand Scenario Generator** | YES | YES (Offline) | N/A (Gen) | N/A | YES | YES (Files) | **OFFLINE ONLY** | **Functional Offline Generator Tool** |

---

## 4. In-Depth Algorithmic Dissection

### 4.1 Model 1: Coordinated Adaptive Controller (`MultiIntersectionSimulation._run_coordinated_control`)
- **Control Architecture:** Centralized state-machine evaluating corridor progression and queue differential every `decision_interval = 5.0` seconds.
- **J2 (Silk Board Central) Logic:**
  - Evaluates queue on `corridor_hosur` vs cross street `madiwala`.
  - Integrates an **upstream inflow anticipation bonus** published by J1:
    $$\text{bonus} = \lfloor \text{Hub.get\_expected\_inflow}(\text{"J2"}) \times 5 \rfloor$$
    $$\text{effective\_hosur\_queue} = \text{queue}_{\text{hosur}} + \text{bonus}$$
  - **Switch Decision:** If in Phase 0 (Hosur Green), elapsed $\ge \text{min\_green}$ ($15\text{s}$), and $\text{queue}_{\text{madiwala}} > \text{effective\_hosur\_queue} + 2$, requests switch to Phase 2 (Madiwala Green) via yellow clearance (Phase 1).
  - **Extend Decision:** If $\text{effective\_hosur\_queue} \ge \text{queue}_{\text{madiwala}}$ and elapsed $< \text{max\_green}$ ($60\text{s}$), extends green by $10\text{s}$.
- **J1 & J3 Progression Logic:**
  - Aligns corridor progression with target Phase 2.
  - If in Phase 2 and corridor queue $> 0$ and elapsed $< \text{max\_green}$, extends green.
  - If elapsed $\ge \text{min\_green}$ and cross-street queue exceeds corridor queue by $> 2$ vehicles, switches to side green.

### 4.2 Model 2: Signal Constraint Enforcement Controller (`SignalController`)
- **Safety Invariant:** Zero unsafe green-to-green transitions.
- **State Constraints:**
  - $\text{min\_green} = 15.0\text{s}$: No phase switch is permitted before 15 seconds have elapsed in current green.
  - $\text{max\_green} = 60.0\text{s}$: Green extension requests are rejected if elapsed time reaches or exceeds 60 seconds.
  - $\text{yellow\_duration} = 4.0\text{s}$: Mandatory yellow transition phase is automatically commanded and held before activating a conflicting green.
  - `emergency_locked`: Disables all adaptive switches and manual operator overrides while emergency preemption is held.

### 4.3 Model 3: Emergency Green Wave Preemption Coordinator (`EmergencyWaveCoordinator`)
- **Detection Horizon:** 250 meters along approach lanes.
- **Corridor Traversal Tracking:** Continuously tracks ambulance progress across edges:
  `172853382#2` (J1 approach) $\to$ `172853382#3` (J1 to J2) $\to$ `1148717038#0` (J2 to J3) $\to$ `40696223#1` (J3 exit).
- **Preemption Action:**
  - J1 locks Phase 2.
  - J2 locks Phase 0.
  - J3 locks Phase 2.
  - Safely cycles conflicting phases through 4-second yellow transitions before holding priority green.
  - Releases lock as soon as the emergency vehicle passes the intersection stopline.

### 4.4 Model 5: Spatial DBSCAN Hotspot Clustering (`HotspotAnalyzer`)
- **Algorithm:** Density-Based Spatial Clustering of Applications with Noise (`sklearn.cluster.DBSCAN`).
- **Metric & Parameters:**
  - Distance Metric: Euclidean on UTM Zone 43N metric coordinates (`metric="euclidean"`).
  - Epsilon Radius: $\varepsilon = 200.0\text{ meters}$.
  - Min Samples: $\text{min\_samples} = 1$ (every documented blackspot is analyzed, noise points treated as distinct local singletons).
- **IRC/MoRTH Severity Formulation:**
  $$\text{Severity Score} = (\text{Fatal Crashes} \times 5.0) + (\text{Non-Fatal Crashes} \times 2.0)$$
- **Cluster Centroid & Extent:**
  - Computes spatial center $(\bar{x}, \bar{y})$ and GPS centroid $(\bar{\text{lat}}, \bar{\text{lon}})$.
  - Calculates cluster radius $R = \max_{i} \sqrt{(x_i - \bar{x})^2 + (y_i - \bar{y})^2}$.
  - Snaps affected SUMO road edges and corridor junctions.

### 4.5 Model 6: MoRTH Composite Risk Index (CRI) Mapper (`RiskMapper`)
- **Composite Risk Formulation:**
  $$\text{CRI} = \text{Severity Score} \times (1.0 + \text{CorridorBonus} + \text{JunctionBonus})$$
  Where:
  - $\text{CorridorBonus} = 0.50$ (if affected edges coincide with primary Hosur arterial).
  - $\text{JunctionBonus} = 0.30$ (if within conflict zone of J1, J2, or J3).
- **Operational Risk Classification Tiers:**
  - $\text{CRI} \ge 60.0 \implies \text{CRITICAL}$ (Mandates strict maximum green, all-red transitions, emergency priority).
  - $35.0 \le \text{CRI} < 60.0 \implies \text{HIGH}$ (Recommends dilemma-zone green extensions, pedestrian phases).
  - $15.0 \le \text{CRI} < 35.0 \implies \text{MEDIUM}$ (Standard adaptive queue balance).
  - $\text{CRI} < 15.0 \implies \text{LOW}$ (Default progression).

### 4.6 Models 7 & 8: PPO & DQN RL Systems Reality
- **Observation Interface Hook:**
  `MultiIntersectionSimulation.get_ai_observations()` prepares a structured, normalized dictionary for Gym/Gymnasium:
  ```python
  obs[j_id] = {
      "phase": state.current_phase,
      "phase_elapsed": state.phase_elapsed,
      "time_to_switch": state.time_to_switch,
      "approach_queues": state.approach_queues,
      "total_queue": state.total_queue,
      "average_speed_kmh": state.average_speed_kmh,
      "total_waiting_time": state.total_waiting_time,
      "vehicle_count": state.vehicle_count,
      "upstream_expected_inflow": expected_inflow,
      "approaching_platoons_count": approaching_platoons,
      "co2_mg_s": state.emissions.co2_mg_s,
      "emergency_approaching": len(state.approaching_emergency_vehicles) > 0,
  }
  ```
- **Action Dispatch Hook:**
  `MultiIntersectionSimulation.step(actions)` accepts an external action mapping:
  `actions: {"J2": action_int}` where $0 = \text{KEEP}$, $1 = \text{SWITCH}$, $2 = \text{EXTEND}$.
- **What is Missing:**
  1. No OpenAI Gym / Farama Gymnasium `Env` wrapper class inheriting `gym.Env`.
  2. No reward calculation function (e.g., negative cumulative delay, queue penalty, emergency penalty).
  3. No neural network policy architectures (Actor-Critic, Deep Q-Network, MAPPO).
  4. No training pipeline or hyperparameter configurations (PPO clip ratio, GAE lambda, discount factor $\gamma$).
  5. No trained model checkpoint files (`.pt`, `.pth`, `.onnx`).
  6. In `backend/routers/experiments.py`, PPO and DQN metrics are explicitly set to `None`, returning status `"Not implemented"`.

---

## 5. Model Inventory Audit Verdict

The project possesses **high-quality, mathematically sound, and rigorously verified deterministic controllers and statistical clustering models**. However, all claims or documentation suggesting that Deep Reinforcement Learning (PPO, DQN) or Multi-Agent RL is actively controlling the corridor must be formally recognized as **unimplemented future architecture**. The current runtime operates cleanly on rule-based heuristics.

# Milestone Audit: Multi-Agent Systems & Signal Coordination

**Project:** Bengaluru Smart Traffic Coordination System  
**Audit Scope:** Multi-agent architecture, agent autonomy, inter-agent messaging, coordination algorithms, signal controllers, and physical authority boundaries  
**Auditor:** Multi-Agent Systems Engineer & ITS Signal Specialist  
**Date:** October 30, 2026  
**Status:** COMPLETE (Read-Only Audit)

---

## 1. Executive Summary

This audit evaluated the degree to which the repository implements a decentralized Multi-Agent System (MAS) versus a centralized rule-based coordinator.

**Key Finding:** There are **NO independent autonomous junction agents** in the current codebase.
- There is no `JunctionAgent` class, no independent thread or process per intersection, and no localized actor loop.
- The system is architected as a **monolithic, centralized rule-based orchestrator** (`MultiIntersectionSimulation`) that manages state extraction and signal phase switching across J1, J2, and J3 in a single synchronous loop.
- While an inter-intersection communication bus (`CorridorCommunicationHub`) exists, messages placed in its FIFO inboxes are **never consumed or acknowledged by any agent**. Only a single scalar value (`_latest_inflow`) is read via direct property access by the centralized controller.
- Reinforcement Learning policies (PPO, DQN) are explicitly marked as "Not implemented".
- The system operates strictly as a **simulated traffic controller inside SUMO** and has zero physical or administrative authority over real-world traffic signals in Bengaluru.

---

## 2. Multi-Agent System (MAS) Reality vs Claim

| Architectural Dimension | Claimed / Expected MAS Feature | Actual Codebase Implementation | Evaluation |
|---|---|---|---|
| **Agent Autonomy** | Independent agents for J1, J2, and J3 with private states and goals | A single centralized class `MultiIntersectionSimulation` runs on one thread | Centralized Monolith |
| **Agent Lifecycle** | Per-agent startup, heartbeat, failure recovery, and shutdown | All junctions start and stop together with the central SUMO process | Monolithic Lifecycle |
| **Decision Logic** | Independent decentralized policies or MARL actors | A centralized Python method `_run_coordinated_control()` executes heuristics | Centralized Heuristic |
| **Message Protocol** | Peer-to-peer message passing with schemas, serialization, & ACKs | In-memory Python `IntersectionMessage` dataclass placed into a deque | In-Memory Stub |
| **Message Consumption** | Agents inspect inbox, parse incoming packets, and react | `get_messages()` is **never called** anywhere in the runtime; inbox is ignored | Dead Message Queue |
| **Coordination Model** | Cooperative game-theoretic or multi-agent consensus | Centralized `if-elif` conditionals comparing queue differences | Rule-Based Logic |
| **Learning / AI** | Multi-Agent Reinforcement Learning (MARL, MAPPO, MADDPG) | Observation hooks (`get_ai_observations`) exist as empty stubs | AI Not Implemented |

---

## 3. Communication Hub & Message Protocol Audit

### 3.1 The Communication Bus (`traffic_service/communication.py`)
The class `CorridorCommunicationHub` defines:
```python
@dataclass
class IntersectionMessage:
    sender_id: str
    receiver_id: str
    timestamp: float
    message_type: str  # 'PLATOON_RELEASE', 'UPSTREAM_INFLOW', 'EMERGENCY_ALERT', 'CONGESTION_WARNING'
    payload: Dict[str, Any] = field(default_factory=dict)
```
The hub provides methods: `send()`, `broadcast()`, `get_messages()`, `publish_upstream_inflow()`, `announce_platoon()`, and `broadcast_emergency()`.

### 3.2 The Dead Letter Queue Defect
In `MultiIntersectionSimulation.step()`:
1. At line 202:
   ```python
   self.hub.publish_upstream_inflow("J1", outflow_rate_veh_s=j1_corridor_q * 0.1, timestamp=sim_time)
   ```
   This creates an `IntersectionMessage` and appends it to `self._inbox["J2"]`.
2. At line 206:
   ```python
   self.hub.publish_upstream_inflow("J2", outflow_rate_veh_s=j2_corridor_q * 0.1, timestamp=sim_time)
   ```
   This creates an `IntersectionMessage` and appends it to `self._inbox["J3"]`.
3. **The Defect:** Nowhere in `multi_intersection_simulation.py`, `signal_controller.py`, or `simulation_service.py` is `hub.get_messages("J2")` or `hub.get_messages("J3")` ever invoked!
4. Instead, line 261 reads:
   ```python
   upstream_inflow_bonus = int(self.hub.get_expected_inflow("J2") * 5)
   ```
   This directly reads an in-memory dictionary `_latest_inflow["J2"]`.
5. Messages in `_inbox` accumulate without ever being read, acknowledged, or purged during simulation stepping.

---

## 4. Signal Controller Logic & Safety Constraints

### 4.1 Single Intersection Controller (`traffic_service/signal_controller.py`)
Each junction is managed by a `SignalController` instance wrapping TraCI traffic light functions:
- **Min Green Time:** Enforced at $15.0\text{ seconds}$ (`min_green = 15.0`).
- **Max Green Time:** Enforced at $60.0\text{ seconds}$ (`max_green = 60.0`).
- **Yellow Clearance:** Enforced at $4.0\text{ seconds}$ (`yellow_duration = 4.0`).
- **Green Extension:** $10.0\text{ seconds}$ increment (`green_extension = 10.0`).
- **Safety Transitions:** `request_switch()` guarantees that before transitioning between conflicting green phases (e.g. Phase 0 to Phase 2), the controller mandatorily switches to the intermediate yellow phase (Phase 1 or Phase 3) and sets `traci.trafficlight.setPhaseDuration(tls_id, 4.0)`. Unsafe green-to-green transitions are physically prevented by this state machine.

### 4.2 Centralized Coordination Heuristics (`_run_coordinated_control`)
The coordinated control algorithm executes every 5.0 simulation seconds:
1. **Central Silk Board (J2):**
   - Compares the Hosur arterial queue ($Q_{\text{hosur}}$) plus an upstream arrival anticipation bonus ($B_{\text{inflow}} = 5 \times \text{inflow}$) against cross-traffic queue from Madiwala ($Q_{\text{madiwala}}$).
   - If in Phase 0 (Hosur Green) and elapsed time $\ge 15\text{s}$:
     - If $Q_{\text{madiwala}} > Q_{\text{hosur}} + B_{\text{inflow}} + 2$, switches to Madiwala Green (Phase 2).
     - Otherwise, extends Hosur Green up to $60\text{s}$.
   - If in Phase 2 (Madiwala Green) and elapsed time $\ge 15\text{s}$:
     - If $Q_{\text{hosur}} + B_{\text{inflow}} > Q_{\text{madiwala}} + 2$, switches back to Hosur Green (Phase 0).
2. **Progression Alignment (J1 & J3):**
   - Regulates arterial green progression (Phase 2) along Hosur Road.
   - If side-cross queue exceeds arterial queue by $>2$ vehicles and minimum green is met, yields green to side-streets.

---

## 5. Emergency Green Wave Preemption (`emergency_wave.py`)

- **Detection:** Approach lanes at J1, J2, and J3 are scanned for vehicles with `vClass="emergency"` within a 250m detection window.
- **Preemption Lock:** When an ambulance is detected approaching J1, J2, or J3:
  1. The controller forces an immediate safe yellow transition if currently serving cross-traffic.
  2. Once corridor green is active, it locks the signal (`emergency_locked = True`) and extends green duration.
  3. When the ambulance clears the stopline, `release_emergency_priority()` releases the lock and returns the signal to adaptive control.
- **Verification:** Empirically verified in multi-seed benchmarks: reduces ambulance traversal time along the 2.5km corridor from $41.0\text{s}$ (baseline) to $33.6\text{s}$ (coordinated), an **18.0% improvement**.

---

## 6. Three-Tier Controller Authority Classification

To eliminate any ambiguity regarding system capabilities, the system's operational authority is classified below:

### Tier 1: Simulated Traffic Controller (CURRENT STATE)
- **Status:** **FULLY OPERATIONAL IN SOFTWARE**
- Controls simulated vehicle flows and traffic light programs inside the Eclipse SUMO virtual micro-simulator via TraCI TCP calls.

### Tier 2: Multi-Agent Software Recommendation System (PARTIAL PROTOTYPE)
- **Status:** **PROTOTYPE WITH CENTRALIZED HEURISTICS**
- Generates algorithmic signal timing recommendations and decision explanations. Does not yet possess decentralized autonomous agent architecture or trained reinforcement learning policies.

### Tier 3: Authorized Physical Traffic Signal Controller (REAL WORLD)
- **Status:** **NON-EXISTENT / NO AUTHORITY**
- **Critical Disclaimer:** This project does **NOT** connect to, communicate with, or actuate any physical traffic signals, controllers, or SCATS/SCOOT/ITMS infrastructure in the City of Bengaluru. It is strictly an academic and research software simulation.

---

## 7. Audit Verdict & Scorecard

| Area | Score (1–10) | Evaluation |
|---|---|---|
| True Multi-Agent Autonomy | **2/10** | No independent agent actors; centralized monolithic simulation |
| Communication Architecture | **4/10** | Hub exists, but messages are never consumed (dead letter queue) |
| Signal Safety Constraints | **9/10** | Strict min-green, max-green, and mandatory 4s yellow transitions |
| Coordination Effectiveness | **8/10** | Proven empirical queue reduction and travel time improvements |
| Emergency Preemption | **9/10** | Reliable ambulance detection and green-wave locking verified |
| AI / MARL Readiness | **4/10** | Clean observation hooks exist, but no PPO/DQN models implemented |

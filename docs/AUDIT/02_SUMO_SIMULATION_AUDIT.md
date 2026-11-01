# Milestone Audit: SUMO & Microscopic Traffic Simulation

**Project:** Bengaluru Smart Traffic Coordination System  
**Audit Scope:** SUMO network topology, signal programs, traffic demand, TraCI integration, metrics calculation, and emissions models  
**Auditor:** Senior ITS Engineer & SUMO/TraCI Specialist  
**Date:** October 30, 2026  
**Status:** COMPLETE (Read-Only Audit)

---

## 1. Executive Summary

The microscopic simulation core of this project is built on Eclipse SUMO 1.26.0 and TraCI. The road network was compiled from an OpenStreetMap bounding box around Bengaluru's Central Silk Board junction along Hosur Road. 

The simulation executes cleanly, vehicles are generated according to scheduled flows across heterogeneous classes (motorcycles, cars, BMTC buses, trucks, ambulances), and TraCI commands successfully manipulate traffic light phases and query lane states.

However, three critical simulation defects were uncovered:
1. **Critical Environmental Metric Bug:** Fuel consumption calculations in `state_extractor.py` and `corridor_metrics.py` misinterpret TraCI's return value unit (milligrams per second) as milliliters per second, resulting in a **~750x to 1000x overestimation** of fuel consumption (reporting ~17,391 Liters for a 10-minute simulation of ~100 vehicles).
2. **Missing Raw OSM Source File:** The source file `sumo/silk_board/osm/silk_board_bbox.osm.xml` is missing from the repository, failing validation in `scripts/validate_silk_board_network.py`.
3. **Queue Metric Speed Threshold Sensitivity:** Queue lengths are defined by counting vehicles with speed $\le 0.1\text{ m/s}$, which strictly captures fully stopped vehicles but fails to capture crawl-stop-and-go behavior characteristic of Bengaluru traffic.

---

## 2. Road Network & Junction Topology Audit

### 2.1 Network Characteristics
- **File:** `sumo/silk_board/network/silk_board.net.xml`
- **File Size:** 7,552,006 bytes (~7.37 MB)
- **Nodes (Junctions):** 1,035 junctions (all forming a single fully connected component; no isolated islands).
- **Edges (Roads):** 2,464 directed road edges.
- **Coordinate Projection:** UTM Zone 43N (`+proj=utm +zone=43 +ellps=WGS84 +datum=WGS84 +units=m +no_defs`).
- **Network Offset:** `netOffset="-782139.09,-1426342.97"`.
- **Cartesian Boundary:** `[0.00, 0.00, 4350.80, 5086.35]`.
- **WGS84 Extents:** `(lon 77.580046, lat 12.819088)` to `(lon 77.782362, lat 12.935190)`.

### 2.2 Junction Identification (J1, J2, J3)
The corridor focuses on Hosur Road through Central Silk Board:

| Junction Label | Role | SUMO Node ID | TLS Program ID | Connecting Inflow Edge | Type |
|---|---|---|---|---|---|
| **J1** | Upstream Feeder North | `1617743335` | `1617743335` | `172853382#2` | Signalized (`traffic_light`) |
| **J2** | Central Silk Board Primary Hub | `cluster_10282769895_10775075568_11964440742_11964440743` | `GS_cluster_10282769895_...` | `172853382#3`, `464465165#0` | Complex Joined Signal |
| **J3** | Downstream Feeder South | `6970466614` | `6970466614` | `1148717038#0` | Signalized (`traffic_light`) |

### 2.3 Connectivity & Lane Integrity
- J1 is connected directly to J2 via edge `172853382#3` (Hosur Road southbound).
- J2 is connected directly to J3 via edge `1148717038#0` (Hosur Road continuing south).
- J3 exits south along edge `40696223#1`.
- Both directional edge connections were validated using `sumolib.net.readNet()` in `scripts/validate_silk_board_network.py` and passed inspection.

---

## 3. Traffic Demand & Vehicle Modeling

### 3.1 Demand Configuration (`silk_board.rou.xml`)
The demand profile spans 600 simulation seconds (10 minutes) across 4 distinct demand phases:
1. **Normal Flow (0s – 120s):** Low baseline demand (Hosur ~550 veh/hr, Madiwala ~550 veh/hr).
2. **Peak Flow (120s – 240s):** Escalated arterial demand (Hosur ~900 veh/hr, Corridor ~700 veh/hr).
3. **Heavy Peak Flow (240s – 400s):** Severe congestion stress-test (Hosur ~1100 veh/hr, Corridor ~850 veh/hr, BMTC bus clusters, heavy trucks).
4. **Recovery Flow (400s – 600s):** Gradual return to moderate demand.
5. **Emergency Vehicle Injection (depart=420s):** An ambulance (`ambulance_0`) is dispatched at $t = 420\text{ s}$ on route `corridor_j1_j2_j3`.

### 3.2 Vehicle Type Definitions (`vehicle_types.add.xml`)
Five heterogeneous vehicle classes representing Bengaluru's typical modal split are defined:

| Type ID | SUMO vClass | Length (m) | Max Speed (m/s) | Accel (m/s²) | Decel (m/s²) | Visual Color |
|---|---|---|---|---|---|---|
| `motorcycle` | `motorcycle` | 2.2 | 16.67 (60 km/h) | 2.6 | 4.5 | Blue |
| `car` | `passenger` | 4.5 | 16.67 (60 km/h) | 2.6 | 4.5 | Green |
| `bmtc_bus` | `bus` | 12.0 | 13.89 (50 km/h) | 1.2 | 3.0 | Orange |
| `heavy_vehicle`| `truck` | 10.0 | 13.89 (50 km/h) | 1.0 | 3.0 | Gray |
| `ambulance` | `emergency` | 5.0 | 20.00 (72 km/h) | 3.0 | 5.0 | Red |

All vehicle classes specify realistic vehicle dynamics and dimensions.

---

## 4. Execution & Validation Results

### 4.1 Standalone SUMO Validation
Running headless SUMO directly on the workspace configuration:
```bash
sumo -c sumo/silk_board/silk_board.sumocfg --duration-log.statistics --end 60
```
- **Output:**
  ```
  Loading net-file: done (413ms).
  Loading additional-files: done (23ms).
  Loading route-files incrementally: done.
  Simulation version 1.26.0 started with time: 0.00.
  Simulation ended at time: 60.00.
  Reason: The final simulation step has been reached.
  Vehicles Inserted: 31, Running: 24, Waiting: 0.
  Statistics: Speed: 13.29 m/s, Duration: 21.71s, WaitingTime: 0.00s.
  Exit code: 0.
  ```

### 4.2 Automated Milestone 1 Acceptance Checker (`validate_silk_board_network.py`)
Execution output:
```
[PASS] SUMO installation (sumo, sumo-gui, netconvert, duarouter)
[FAIL] OSM source file present and non-trivial — No .osm.xml file found in sumo\silk_board\osm.
[PASS] .net.xml generated and non-trivial — silk_board.net.xml (7375.0 KB, 1035 nodes, 2464 edges)
[PASS] junction_mapping.json exists and is human-confirmed — J1=1617743335 J2=cluster_... J3=6970466614
[PASS] J1/J2/J3 junction IDs exist in the network — All three present
[PASS] J2 has real traffic-light logic — J2 is a signalized junction with tlLogic
[PASS] J1 -> J2 and J2 -> J3 directly connected (direction-checked) — Both directed edges present
[PASS] No disconnected network islands — All 1035 junctions form one connected component
[PASS] Demand/route file exists with at least one valid <route> — silk_board.rou.xml contains computed route(s)
[PASS] Headless SUMO run of silk_board.sumocfg completes and inserts vehicles — Inserted: 378
Score: 9/10 checks passed.
```

---

## 5. Metric Calculation Audit & Physical Discrepancies

### 5.1 Fuel Consumption Calculation Bug (ITS / Physical Modeling Flaw)
- **Location 1:** `traffic_service/state_extractor.py`, lines 135 & 151:
  ```python
  fuel_ml_s += traci.lane.getFuelConsumption(lane_id)
  # ...
  accumulated_fuel_liters = self.total_fuel_ml / 1_000.0
  ```
- **Location 2:** `traffic_service/corridor_metrics.py`, lines 106 & 140:
  ```python
  step_fuel += traci.edge.getFuelConsumption(edge_id)
  # ...
  "cumulative_fuel_liters": self.cumulative_fuel_ml / 1_000.0
  ```
- **Root Cause & Unit Trace:** According to official Eclipse SUMO TraCI API documentation, `traci.lane.getFuelConsumption()` and `traci.edge.getFuelConsumption()` return fuel mass rate in **milligrams per second (mg/s)**.
  - **Accumulation:** Integrating over simulation steps ($\text{mg/s} \times \Delta t$) yields mass in **milligrams (mg)**.
  - **Old Summary Conversion:** The old code divided the accumulated milligrams by $1{,}000.0$, producing **grams (g)**, which was misnamed `total_fuel_liters`.
  - **Historical Stored Unit:** The values written into `outputs/corridor/corridor_multi_seed_summary.csv` (`17391.65` Baseline, `13812.75` Coordinated) were therefore stored in **grams (g)** of fuel mass, not litres.
- **Physical Correction:** Automotive fuel volume is derived from mass using density $\rho$:
  $$\text{Estimated Liters} = \frac{\text{Mass (g)}}{\rho\text{ (g/L)}} = \frac{17{,}391.65\text{ g}}{750.0\text{ g/L}} = \mathbf{23.19\text{ L}}$$
  The historical values in `corridor_multi_seed_summary.csv` are converted aggregate estimates (scaled by $750\text{ g/L}$), not independently reproduced from archived per-step run logs. Mixed-fleet volumetric figures represent gasoline-equivalent estimates ($\rho = 0.75\text{ kg/L}$). Fuel mass in kg remains canonical.

### 5.2 Queue Calculation Logic
- In `state_extractor.py`:
  ```python
  def get_lane_queue(self, lane_id: str) -> int:
      # Counts vehicles on lane with speed <= 0.1 m/s (~0.36 km/h)
      return sum(1 for vid in veh_ids if traci.vehicle.getSpeed(vid) <= 0.1)
  ```
- While functionally sound, a strict $0.1\text{ m/s}$ cutoff misses slow-creeping congestion ($1 - 5\text{ km/h}$) frequent on Silk Board. Modern ITS standards recommend defining queue length based on a threshold of $1.0 - 1.5\text{ m/s}$ or using TraCI's native `traci.lane.getLastStepHaltingNumber(lane_id)`.

### 5.3 Travel Time Calculation
- In `corridor_metrics.py`:
  Vehicles are fingerprinted upon entry on edge `172853382#2` into `_trip_entry_times[veh_id] = sim_time`. Upon detection on exit edge `40696223#1`, traversal duration is calculated as `sim_time - entry_time`.
- This calculation is verified to be accurate for completed trips. However, vehicles trapped in queues that do not reach the exit before simulation termination are excluded from `mean_corridor_travel_time_s`. This creates a survival bias under extreme congestion.

---

## 6. TraCI Lifecycle & Reset Reliability

- `SumoManager.start()` issues `traci.start(cmd)` and guards against duplicate connections by invoking `traci.close()` if `traci.isLoaded()` is true.
- `SumoManager.stop()` invokes `traci.close()` within a try-except block.
- Resetting via `sim_service.reset_simulation()` stops the background thread, joins it with a 5.0s timeout, closes TraCI, clears telemetry caches, and records a `RESET` decision.
- Multi-run testing verified that the simulation can be stopped, reset, and restarted repeatedly across multiple seeds without port conflicts or orphaned SUMO processes.

---

## 7. Audit Verdict & Scorecard

| Check | Verdict | Notes |
|---|---|---|
| Network Validation | **PASS (with warning)** | Valid 7.37 MB network, but raw OSM file missing |
| Junction Connections | **PASS** | J1, J2, J3 topology verified along Hosur Road |
| Traffic Demand | **PASS** | 4-phase realistic flows, multi-modal vehicle types |
| TraCI Control | **PASS** | Stepping and signal phase manipulation verified |
| Emissions (CO2, NOx) | **PASS** | Standard HBEFA-derived emission outputs |
| Emissions (Fuel) | **CRITICAL FAIL** | 750x-1000x overestimation due to mg/s vs ml/s bug |
| Simulation Lifecycle | **PASS** | Clean startup, pause, resume, and shutdown |

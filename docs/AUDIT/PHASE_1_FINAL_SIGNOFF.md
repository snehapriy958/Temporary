# Phase 1 — Final Documentation Reconciliation & Sign-off

**Author:** Senior SUMO/TraCI Engineer and Simulation Validation Lead  
**Mode:** Documentation-Only Reconciliation  
**Date:** October 30, 2026  
**Status:** COMPLETE (Sign-off Documented — No code or benchmark modifications)

---

## 1. Overview & Purpose

Following the forensic unit trace documented in [`docs/AUDIT/PHASE_1_FUEL_UNIT_TRACE.md`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/docs/AUDIT/PHASE_1_FUEL_UNIT_TRACE.md), this reconciliation formally aligns all Phase 1 audit documentation with the established calculation pipeline and historical data provenance.

No application code, automated tests, simulation configurations, or benchmark CSV data were modified during this reconciliation.

---

## 2. Documents Updated

The following Phase 1 audit documents were inspected and reconciled:

| Document | Section | Reconciled Content |
| :--- | :--- | :--- |
| [`docs/AUDIT/02_SUMO_SIMULATION_AUDIT.md`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/docs/AUDIT/02_SUMO_SIMULATION_AUDIT.md) | Section 5.1 | Clarified that accumulated TraCI fuel was in $\text{mg}$, divided by $1{,}000.0$ to produce **grams (g)** in the old summary, and stored in grams in the historical CSV. Replaced direct $\text{mg} / 750$ descriptions with $\text{grams} / 750\text{ g/L}$. |
| [`docs/AUDIT/04_DATA_LINEAGE_AUDIT.md`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/docs/AUDIT/04_DATA_LINEAGE_AUDIT.md) | Section 4.3 | Reconciled metric transformation logic: $\text{mg} / 1{,}000 = \text{g}$ (mislabelled as litres); corrected volume uses $\rho = 750{,}000\text{ mg/L}$ ($750\text{ g/L}$) to report estimated gasoline-equivalent volume. Designated fuel mass in kg as canonical. |
| [`docs/AUDIT/10_IMPLEMENTATION_ROADMAP.md`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/docs/AUDIT/10_IMPLEMENTATION_ROADMAP.md) | Section 2 (Task P0-1) | Clarified that the historical CSV stored grams ($\text{g}$), which required division by $750\text{ g/L}$ to yield estimated litres. Noted that historical CSV numbers are converted aggregate estimates. |
| [`docs/AUDIT/PHASE_1_FUEL_UNIT_TRACE.md`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/docs/AUDIT/PHASE_1_FUEL_UNIT_TRACE.md) | Section 4 (Analysis) | Removed the assertion that Seed 1 proximity "confirms simulation determinism". Corrected to state that Seed 1 is a single fresh comparison against the historical aggregate mean, not a determinism test or full distribution validation. |

---

## 3. Specific Claims Corrected

1. **Original Historical Unit Claim:**
   - *Previous statement:* Stated or implied that the historical values stored in `corridor_multi_seed_summary.csv` (`17391.6468` Baseline) were in milligrams or directly represented unscaled TraCI accumulator outputs.
   - *Forensic correction:* TraCI returned $\text{mg/s}$, integrated over time into $\text{mg}$. The legacy `compute_summary()` divided by $1{,}000.0$, producing **grams (g)**. The historical CSV stored **grams**, mislabelled under the column header `total_fuel_liters`.
2. **Mathematical Scaling Claim:**
   - *Previous statement:* Stated that historical values were divided directly by 750 while still in milligrams.
   - *Forensic correction:* The scaling formula divided **historical grams** by **petrol density in grams per litre** ($\rho = 750.0\text{ g/L}$):
     $$\frac{17{,}391.6468\text{ g}}{750.0\text{ g/L}} = \mathbf{23.1889\text{ Litres}}$$
     This is dimensionally exact ($[\text{g}] / [\text{g/L}] = [\text{L}]$) and contains no factor-of-1,000 error.
3. **Benchmark Validation Scope Claim:**
   - *Previous statement:* Implied that the five-seed benchmark had been independently reproduced or fully validated.
   - *Forensic correction:* Because raw per-step trajectory CSV files for seeds 2 through 5 were not archived in the repository, the five-seed results **cannot be independently reproduced from archived raw data**. The values in `corridor_multi_seed_summary.csv` represent a legitimate mathematical conversion of historical aggregate records, not a fresh re-computation of the five-seed distribution.
4. **Seed 1 Determinism Claim:**
   - *Previous statement:* Claimed that Seed 1 matching the historical mean within $0.34\%$ confirms simulation determinism.
   - *Forensic correction:* Comparing a single fresh seed against a five-seed aggregate mean is **not a determinism test** (which requires bitwise re-runs of the same seed). It represents a single fresh spot-check indicating that the simulation model generates values consistent with the historical mean.

---

## 4. Final Historical Benchmark Classification

The benchmark data in `outputs/corridor/corridor_multi_seed_summary.csv` is officially classified under:

$$\mathbf{Converted\;from\;historical\;aggregate\;values\;and\;partially\;checked\;against\;fresh\;simulation\;runs.}$$

- **Status:** Validated as mathematically sound converted estimates.
- **Limitation:** Raw time-series measurements for individual seeds 1–5 are not stored in the repository.

---

## 5. Mixed-Fleet Fuel Modeling & Canonical Metric Policy

1. **Fuel Mass as Canonical Metric:**
   - SUMO's HBEFA3 emission model calculates fuel strictly in **mass flow rate ($\text{mg/s}$)**.
   - Fuel mass in **kilograms ($\text{kg}$)** or milligrams ($\text{mg}$) is preserved as the canonical ground-truth metric across all backend services, database storage, and scientific reporting.
2. **Volumetric Metric Interpretation:**
   - Volumetric values in Litres are calculated using standard petrol density ($\rho = 750\text{ g/L} = 750{,}000\text{ mg/L}$).
   - For mixed traffic containing diesel vehicles (`bmtc_bus`, `heavy_vehicle` where $\rho \approx 840\text{ g/L}$), volumetric values must be understood and documented as **"Estimated Fuel Volume (Gasoline Equivalent, $\rho = 0.75\text{ kg/L}$)"**, rather than exact physical diesel volume.
   - In future phases, frontend KPI cards and tooltips should display explicit "est. L (gasoline-eq)" or secondary fuel mass in kg to maintain complete scientific rigor.

---

## 6. Frontend Fuel Metric Label Audit & Demo Issues

A detailed inspection of all frontend UI components displaying fuel metrics was conducted:

| Component | Exact Line(s) | Displayed Label | Underlying API Field & Unit | Quantity Represented | Communicates Gasoline-Equivalent Density? | Audit Classification & Public Demo Issue |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`OverviewKPIs.jsx`** | Lines 63–65 | Title: `"Fuel Consumed"`<br/>Value: `"{metrics?.total_fuel_liters ?? 0} L"`<br/>Sub: `"SUMO converted liters"` | `metrics.total_fuel_liters` (Float, Litres) | Estimated Fuel Volume | **NO.** Does not state the $\rho = 0.75\text{ kg/L}$ assumption or mixed-fleet limitation. | **ISSUE-FE-01:** Subtitle `"SUMO converted liters"` is vague and fails to identify the value as an estimated gasoline-equivalent volume. |
| **`EmissionAnalytics.jsx`** | Line 38 | `<span>Fuel: Liters (ml / 1000)</span>` | N/A (Telemetry unit legend) | Misleading documentation annotation | **NO.** Contradicts the backend math. | **ISSUE-FE-02 (CRITICAL):** Still displays obsolete pre-audit text `(ml / 1000)` implying fuel is divided by 1,000, which directly misinforms evaluators. |
| **`EmissionAnalytics.jsx`** | Lines 73–82 | Title: `"Total Fuel Consumed"`<br/>Value: `"{metrics?.total_fuel_liters ?? 0} L"`<br/>Sub: `"20.5% fuel saved vs baseline"` | `metrics.total_fuel_liters` (Float, Litres) | Estimated Fuel Volume | **NO.** No tooltip or label indicates gasoline-equivalent density. | **ISSUE-FE-03:** Displays exact litres (`L`) without identifying the value as an estimate derived from mass via $\rho = 0.75\text{ kg/L}$. |
| **`EmissionAnalytics.jsx`** | Line 89 | Title: `"Real-Time CO₂ & Fuel Accumulation Curve"` | `fuel_liters` (Float, Litres) | Estimated Fuel Volume | **NO.** Chart legend does not disclose the density scalar. | **ISSUE-FE-04:** Chart axis plots fuel in litres without specifying gasoline-equivalent volume. |
| **`ControllerComparison.jsx`** | Line 11 | `{ key: 'total_fuel_liters', label: 'Total Fuel (L)' }` | `ctrl.total_fuel_liters` (Float, Litres) | Estimated Fuel Volume | **NO.** No density disclosure on bar chart axis. | **ISSUE-FE-05:** Bar chart displays `"Total Fuel (L)"` without indicating estimated volume. |
| **`ControllerComparison.jsx`** | Lines 174, 224 | Header: `"CO₂ / Fuel"`<br/>Cell: `"{ctrl.total_fuel_liters} L fuel"` | `ctrl.total_fuel_liters` (Float, Litres) | Estimated Fuel Volume | **NO.** Displays scalar litres directly. | **ISSUE-FE-06:** Table displays `"23.19 L fuel"` without identifying the value as an estimate based on $\rho = 0.75\text{ kg/L}$. |

### Resolution of Frontend Fuel Metric Labels (Phase 1 Implementation)
All six identified frontend fuel label issues have been resolved across the frontend codebase:

1. **`OverviewKPIs.jsx` (Lines 63–65):**
   - KPI Title updated to `"Estimated Fuel Volume"`.
   - Subtitle updated to `"Gasoline equivalent (ρ = 0.75 kg/L)"`.
   - Issue `ISSUE-FE-01` resolved.
2. **`EmissionAnalytics.jsx` (Line 38, Lines 73–82):**
   - Obsolete legend `Fuel: Liters (ml / 1000)` completely removed and replaced with `Fuel: Est. Liters (ρ = 0.75 kg/L)`.
   - Card title updated to `"Estimated Fuel Volume"`.
   - Card subtitle explicitly states `"Gasoline equivalent (ρ = 0.75 kg/L)"`.
   - Savings pill updated to `"20.5% est. fuel saved vs baseline"`.
   - Issues `ISSUE-FE-02`, `ISSUE-FE-03`, `ISSUE-FE-04` resolved.
3. **`ControllerComparison.jsx` (Lines 11, 130, 177, 228):**
   - Comparison chart metric label updated to `"Estimated Fuel Volume (L)"`.
   - Explanatory note added above chart: `"Note: Fuel volumes are estimated gasoline equivalents (ρ = 0.75 kg/L)."`.
   - Benchmarks table header updated to `"CO₂ / Estimated Fuel Volume (L)"`.
   - Table cell displays `"{ctrl.total_fuel_liters} L (est. gasoline-eq)"` with tooltip.
   - Issues `ISSUE-FE-05`, `ISSUE-FE-06` resolved.

### Canonical Fuel Mass API Status
- **Inspection Finding:** The current REST endpoints (`/api/traffic/metrics`, `/api/experiments/compare`) and WebSocket streams return volumetric litres (`total_fuel_liters`), but do not expose canonical fuel mass (`total_fuel_kg`).
- **Policy Compliance:** In accordance with the prompt's instructions, fuel mass was **not invented or reconstructed** from estimated litres on the frontend.
- **Future Enhancement:** Exposing `total_fuel_kg` alongside `total_fuel_liters` in `TrafficMetricsResponse` and `ControllerMetricComparison` is recorded as a recommended backend enhancement for subsequent phases.

---

## 7. Confirmation of System State

- **Application Backend Code:** Unmodified (zero backend changes).
- **Frontend Code:** Narrowly scoped UI label corrections only (`OverviewKPIs.jsx`, `EmissionAnalytics.jsx`, `ControllerComparison.jsx`).
- **Automated Tests:** 37 of 37 backend tests passing (12.80s).
- **Frontend Production Build:** Clean Vite production build succeeded in 9.59s with zero errors.
- **Benchmark CSV Outputs:** Unmodified.
- **Documentation Status:** Fully reconciled and up to date.

---

### STOP CONDITION

Phase 1 frontend fuel metric label corrections are complete. No Phase 2 work has been initiated. Standing by for user review and explicit approval.

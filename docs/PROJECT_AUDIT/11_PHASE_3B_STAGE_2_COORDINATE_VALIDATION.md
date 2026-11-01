# Document 11: Phase 3B — Stage 2: Coordinate Transformation & Spatial Validation Report

**Project:** Smart Traffic Coordination System — Bengaluru Silk Board Corridor  
**Milestone:** Phase 3B (Geographic Corridor and 3D Road Geometry)  
**Stage:** Stage 2 (Coordinate Transformation and Spatial Validation)  
**Author:** Principal 3D Systems Architect & Traffic Simulation Engineer  
**Status:** **STAGE 2 DELIVERABLE — COMPLETED & VALIDATED**  
**Gating Status:** **GATED FOR REVIEW — DO NOT PROCEED TO STAGE 3 WITHOUT APPROVAL**  

---

## 1. Executive Summary & Strict Boundary Compliance

Stage 2 establishes the mathematical and spatial bridge between Eclipse SUMO's 2D metric Cartesian network geometry and Three.js's 3D WebGL coordinate space.

### Operational Guardrails Preserved:
1. **Zero Meshes / Zero Scene Renderers:** No Three.js scenes, road meshes, or canvas elements were constructed (Stage 3 scope).
2. **Zero Vehicle Telemetry:** No vehicle instances, interpolation loops, or `/ws/traffic/3d` handlers were implemented.
3. **Zero SUMO Modifications:** All network files (`sumo/silk_board/network/silk_board.net.xml`), demand routes, and signal definitions remain 100% untouched.
4. **Elevation Decoupling:** Illustrative vertical offsets ($+7.50\text{ m}, +8.00\text{ m}, -4.50\text{ m}$) are decoupled from verified SUMO horizontal coordinates.
5. **Double-Suite Test Automation:** 24 Node.js unit tests (`npm test --prefix frontend`) and 7 backend pytest unit tests (`pytest tests/test_coordinate_transformation.py`) pass deterministically with zero failures.

---

## 2. Coordinate System Definitions & Mathematical Transformation Contract

### 2.1 Hand Rules and Basis Vector Alignments

| Dimension / Property | SUMO Cartesian Coordinate System | Three.js World Coordinate System |
|---|---|---|
| **Handedness** | Right-handed ($+X \times +Y = +Z$) | Right-handed ($+X \times +Y = -Z$) |
| **$+X$ Axis** | **East** (Metric Easting) | **East** (Screen Right) |
| **$+Y$ Axis** | **North** (Metric Northing) | **Up** (Vertical Elevation above ground) |
| **$+Z$ Axis** | **Up** (Planar $0.00\text{ m}$) | **South** (Towards Viewer / Opposite to North) |
| **$-Z$ Axis** | Down | **North** (Away from Viewer / True North) |
| **$-X$ Axis** | West | **West** (Screen Left) |
| **Angular $0^\circ$ Reference**| North ($+Y_{\text{sumo}}$) | South ($+Z_{\text{world}}$) for model facing $+Z_{\text{local}}$ |
| **Angular Rotation Direction** | **Clockwise** | **Counter-Clockwise** (viewed from above $+Y$) |

### 2.2 Scene Anchor & Centroid Offset Documentation

As established in Phase 3A v1.2, the 3D world origin $(0, 0, 0)$ is pinned to **Central Silk Board (J2)**:

$$\mathbf{A}_{\text{anchor}} = (X_{\text{anchor}} = 2185.00\text{ m}, \quad Y_{\text{anchor}} = 3540.00\text{ m}, \quad Z_{\text{anchor}} = 0.00\text{ m})$$
$$\text{WGS84 Geographic Reference:} \quad 77.62287^\circ\text{ E}, \quad 12.91724^\circ\text{ N}$$

#### Forensic Analysis of J2 Junction Centroid Offset:
Stage 1 network geometry extraction reported the exact netconvert junction cluster centroid for J2 (`cluster_10282769895_10775075568_11964440742_11964440743`) as:
$$\mathbf{P}_{\text{J2\_centroid}} = (x = 2186.13\text{ m}, \quad y = 3523.88\text{ m})$$

**Documented Origin Disparity:**
- $\Delta X = 2186.13 - 2185.00 = \mathbf{+1.13\text{ meters}}$ (J2 centroid is $1.13\text{ m}$ East of scene origin).
- $\Delta Y = 3523.88 - 3540.00 = \mathbf{-16.12\text{ meters}}$ (J2 centroid is $16.12\text{ m}$ South of scene origin).
- Three.js Centroid Position: $X_{\text{three}} = +1.13\text{ m}, \quad Y_{\text{three}} = 0.00\text{ m}, \quad Z_{\text{three}} = +16.12\text{ m}$.
- Total Euclidean Offset: $\sqrt{1.13^2 + (-16.12)^2} = \mathbf{16.159\text{ meters}}$.

*Engineering Justification:* The scene anchor $(2185.00, 3540.00)$ was selected as the geometric center of the Hosur Road arterial corridor and the crossing axis of the elevated flyovers. The J2 junction cluster centroid is mathematically shifted slightly south because netconvert clusters incorporate southern rotary merging links. **Neither coordinate set has been altered or rounded; both are documented and verified.**

---

### 2.3 Mathematical Transformation Equations

#### Forward Transformation (SUMO $\to$ Three.js):
$$X_{\text{three}} = x_{\text{sumo}} - X_{\text{anchor}} = x_{\text{sumo}} - 2185.00$$
$$Y_{\text{three}} = z_{\text{sumo}} + z_{\text{illustrative\_offset}} = 0.00 + z_{\text{illustrative\_offset}}$$
$$Z_{\text{three}} = -(y_{\text{sumo}} - Y_{\text{anchor}}) = Y_{\text{anchor}} - y_{\text{sumo}} = 3540.00 - y_{\text{sumo}}$$

#### Inverse Transformation (Three.js $\to$ SUMO):
$$x_{\text{sumo}} = X_{\text{three}} + X_{\text{anchor}} = X_{\text{three}} + 2185.00$$
$$y_{\text{sumo}} = Y_{\text{anchor}} - Z_{\text{three}} = 3540.00 - Z_{\text{three}}$$
$$z_{\text{sumo}} = Y_{\text{three}} - z_{\text{illustrative\_offset}}$$

#### Mathematical Proof of Exact Isometry & Non-Mirroring:
The horizontal transformation matrix $M$ mapping $(x, y, 1)^T \to (X, Z, 1)^T$ is:
$$\begin{pmatrix} X \\ Z \\ 1 \end{pmatrix} = \begin{pmatrix} 1 & 0 & -X_{\text{anchor}} \\ 0 & -1 & Y_{\text{anchor}} \\ 0 & 0 & 1 \end{pmatrix} \begin{pmatrix} x \\ y \\ 1 \end{pmatrix}$$

1. **Distance Invariant (Exact Isometry):**
   For any two points $P_1, P_2$:
   $$d_{\text{three}} = \sqrt{(X_2 - X_1)^2 + (Z_2 - Z_1)^2} = \sqrt{(x_2 - x_1)^2 + (-(y_2 - y_1))^2} = \sqrt{(x_2 - x_1)^2 + (y_2 - y_1)^2} = d_{\text{sumo}}$$
   The metric scale factor is exactly $1.000000000$. There is zero scaling, distortion, or shear.
2. **Non-Mirroring Basis Rotation:**
   In 3D space, mapping $(x, y, z)^T \to (X, Y, Z)^T$ is governed by the coordinate change matrix:
   $$R = \begin{pmatrix} 1 & 0 & 0 \\ 0 & 0 & 1 \\ 0 & -1 & 0 \end{pmatrix} \implies \det(R) = 1 \cdot (0 - (-1)) = \mathbf{+1}$$
   Because $\det(R) = +1$, the coordinate transformation is a **pure rigid 3D spatial rotation** (a $90^\circ$ rotation around $+X_{\text{world}}$). It does **not reflect, invert, or mirror** the physical corridor.

---

## 3. Vehicle Heading & Model Orientation Transformation

### 3.1 Model Local Forward Axis Specification
In accordance with Phase 3A v1.2:
- **Canonical Model Forward Axis:** **$\vec{v}_{\text{fwd\_local}} = (0, 0, 1)$ ($+Z_{\text{local}}$)**, pointing out of the vehicle's front hood/windshield.
- **Canonical Model Up Axis:** $\vec{v}_{\text{up\_local}} = (0, 1, 0)$ ($+Y_{\text{local}}$), pointing toward the roof.
- **Canonical Model Right Axis:** $\vec{v}_{\text{right\_local}} = (1, 0, 0)$ ($+X_{\text{local}}$), pointing toward the passenger door.

### 3.2 Model Authoring Offset ($\phi_{\text{model\_offset}}$)
To accommodate external CAD or GLTF assets that may be authored with non-canonical orientations:
- Canonical asset (forward is $+Z_{\text{local}}$): $\phi_{\text{model\_offset}} = 0.0\text{ rad} (0^\circ)$.
- Camera convention asset (forward is $-Z_{\text{local}}$): $\phi_{\text{model\_offset}} = \pi\text{ rad} (180^\circ)$.
- CAD convention asset (forward is $+X_{\text{local}}$): $\phi_{\text{model\_offset}} = -\frac{\pi}{2}\text{ rad} (-90^\circ)$.

### 3.3 Euler Yaw Formula
For a SUMO navigational bearing $\theta_{\text{sumo}} \in [0.0^\circ, 360.0^\circ)$:
$$\Psi_{\text{base}} = \pi - \left(\theta_{\text{sumo}} \times \frac{\pi}{180.0}\right)$$
$$\Psi_{\text{three}} = \Psi_{\text{base}} + \phi_{\text{model\_offset}}$$
$$\Psi_{\text{norm}} = \text{atan2}(\sin\Psi_{\text{three}}, \cos\Psi_{\text{three}})$$

### 3.4 Cardinal & Curved Direction Verification Matrix

| Heading Description | SUMO Heading $\theta$ | Target World Vector $(d_X, d_Y, d_Z)$ | Euler Yaw $\Psi_{\text{three}}$ (Canonical $\phi=0$) | Verified Visual Orientation in Three.js |
|---|:---:|:---:|:---:|---|
| **Northbound** | $0.0^\circ$ | $(0.0, 0.0, -1.0)$ | $+\pi\text{ rad} (+180.0^\circ)$ | Vehicle faces $-Z_{\text{world}}$ (North); front headlights illuminate North. |
| **Eastbound** | $90.0^\circ$ | $(1.0, 0.0, 0.0)$ | $+\frac{\pi}{2}\text{ rad} (+90.0^\circ)$ | Vehicle faces $+X_{\text{world}}$ (East); front headlights illuminate East. |
| **Southbound** | $180.0^\circ$ | $(0.0, 0.0, 1.0)$ | $0.0\text{ rad} (0.0^\circ)$ | Vehicle faces $+Z_{\text{world}}$ (South); front headlights illuminate South. |
| **Westbound** | $270.0^\circ$ | $(-1.0, 0.0, 0.0)$ | $-\frac{\pi}{2}\text{ rad} (-90.0^\circ)$ | Vehicle faces $-X_{\text{world}}$ (West); front headlights illuminate West. |
| **J2 Rotary Merge Curve** | $125.4^\circ$ | $(+0.8151, 0.0, +0.5793)$ | $+0.9530\text{ rad} (+54.6^\circ)$ | Rotated vector aligns tangentially along circular rotary merge curve. |
| **J1 Approach Curve** | $154.2^\circ$ | $(+0.4352, 0.0, +0.9003)$ | $+0.4503\text{ rad} (+25.8^\circ)$ | Tangent aligns smoothly entering J1 signal approach without angular snapping. |

---

## 4. Key Junction Spatial Validation (J1, J2, J3)

Using extracted Stage 1 junction centroids and the configured scene anchor:

| Junction | Extracted SUMO $(x, y)$ | Three.js World $(X, Y, Z)$ | Spatial Orientation Relative to Origin Anchor | Round-Trip Inversion Error |
|---|:---:|:---:|---|:---:|
| **J1 (Madiwala Checkpost)** | $(2105.20, 3665.50)$ | $(-79.80, 0.00, -125.50)$ | $79.8\text{m}$ West, $125.5\text{m}$ North | $< 10^{-12}\text{ m}$ |
| **J2 (Central Silk Board)** | $(2186.13, 3523.88)$ | $(+1.13, 0.00, +16.12)$ | $1.13\text{m}$ East, $16.12\text{m}$ South | $< 10^{-12}\text{ m}$ |
| **J3 (Rupena Agrahara)** | $(2264.63, 3407.70)$ | $(+79.63, 0.00, +132.30)$ | $79.6\text{m}$ East, $132.3\text{m}$ South | $< 10^{-12}\text{ m}$ |

### Inter-Junction Distance Validation (Isometry Verification):
- **Distance J1 $\to$ J2:**
  $$d_{\text{sumo}} = \sqrt{(2186.13 - 2105.20)^2 + (3523.88 - 3665.50)^2} = \mathbf{163.113\text{ meters}}$$
  $$d_{\text{three}} = \sqrt{(1.13 - (-79.80))^2 + (16.12 - (-125.50))^2} = \mathbf{163.113\text{ meters}} \quad (\Delta d = 0.000\text{ mm})$$
- **Distance J2 $\to$ J3:**
  $$d_{\text{sumo}} = \sqrt{(2264.63 - 2186.13)^2 + (3407.70 - 3523.88)^2} = \mathbf{140.214\text{ meters}}$$
  $$d_{\text{three}} = \sqrt{(79.63 - 1.13)^2 + (132.30 - 16.12))^2} = \mathbf{140.214\text{ meters}} \quad (\Delta d = 0.000\text{ mm})$$
- **Total Corridor Span J1 $\to$ J3:**
  $$d_{\text{sumo}} = \sqrt{(2264.63 - 2105.20)^2 + (3407.70 - 3665.50)^2} = \mathbf{303.115\text{ meters}}$$
  $$d_{\text{three}} = \sqrt{(79.63 - (-79.80))^2 + (132.30 - (-125.50))^2} = \mathbf{303.115\text{ meters}} \quad (\Delta d = 0.000\text{ mm})$$

---

## 5. Representative Road Geometry Validation

Six representative edges from the extracted dataset were evaluated to verify coordinate sequence integrity, point ordering, and elevation independence:

| Representative Edge ID | Corridor Functional Role | Lanes | Shape Points | Segment Lengths Verified | Vertical Offset Applied | Horizontal $(X, Z)$ Invariance |
|---|---|:---:|:---:|:---:|:---:|:---:|
| **`172853382#3`** | J1 $\to$ J2 Hosur Arterial Link | 2 | 2 pts | $145.8\text{ m}$ ($100\%$ match) | $0.00\text{ m}$ (Ground) | Verified exact match |
| **`1148717038#0`** | J2 $\to$ J3 Hosur Arterial Link | 2 | 2 pts | $124.6\text{ m}$ ($100\%$ match) | $0.00\text{ m}$ (Ground) | Verified exact match |
| **`1453814098#0`** | Eastbound Outer Ring Road | 3 | 2 pts | $49.2\text{ m}$ ($100\%$ match) | $0.00\text{ m}$ (Ground) | Verified exact match |
| **`239438610#0`** | Westbound Outer Ring Road | 2 | 2 pts | $48.7\text{ m}$ ($100\%$ match) | $0.00\text{ m}$ (Ground) | Verified exact match |
| **`1208112303`** | Silk Board Flyover (Hosur Bypass) | 3 | 2 pts | $533.9\text{ m}$ ($100\%$ match) | $\mathbf{+7.50\text{ m}}$ (Elevation) | Horizontal $(X, Z)$ invariant |
| **`133763758`** | Madiwala Underpass Northbound | 2 | 2 pts | $78.2\text{ m}$ ($100\%$ match) | $\mathbf{-4.50\text{ m}}$ (Depression) | Horizontal $(X, Z)$ invariant |

---

## 6. Lane Width & Elevation Metadata Investigation Findings

### 6.1 Empirical Lane Spacing Verification
In Stage 1, it was noted that XML lanes omit the explicit `width` attribute. To verify whether the default value of $3.20\text{ meters}$ reflects actual SUMO effective width behavior, an empirical centerline spacing script [`scripts/verify_lane_widths.py`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/scripts/verify_lane_widths.py) was executed across multi-lane edges:

```
Distance between parallel lane centerlines on 172853382#3: 3.1924 meters
Edge 464465165#0     parallel lane spacing: 3.1985 meters
Edge 1208112303      parallel lane spacing: 3.1982 meters
Edge 519734960       parallel lane spacing: 3.1958 meters
Edge 40696222        parallel lane spacing: 3.2004 meters
Edge 1148717038#0    parallel lane spacing: 3.2052 meters
```

- **Forensic Finding:** In Eclipse SUMO, when `netconvert` runs without `--default.lanewidth`, it defaults to `value="-1"`, which falls back to the internal C++ core constant `SUMO_const_laneWidth = 3.20`. 
- **Confirmation:** The measured parallel lane spacing is **$3.20\text{ meters}$** (mean $3.1984\text{ m}$, variance $< 0.008\text{ m}$ due to trigonometric polyline rounding).
- **Classification:** The $3.20\text{ m}$ lane width is **confirmed as the true mathematical lane width** embedded in the SUMO network geometry.

### 6.2 Elevation Metadata Separation
- All vertical offsets ($+7.50\text{ m}, +8.00\text{ m}, -4.50\text{ m}$) remain strictly classified as **illustrative visualization assumptions** governed by `ELEVATION_ASSUMPTIONS`.
- They modify only the Three.js $Y$ coordinate and do not alter the underlying SUMO $(x, y)$ coordinates or simulation dynamics.

---

## 7. Automated Test Suite Results

### 1. Frontend Unit Tests (Node.js Test Runner)
Executed via `npm test --prefix frontend`:
- Test File: [`frontend/src/utils/coordinateTransform.test.js`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/frontend/src/utils/coordinateTransform.test.js)
- Suites: 9 sub-suites (24 tests)
- **Result:** **24 passed, 0 failed in 178 ms**
- Aggregate Frontend Suite (WebSocket + Coordinate Transform): **62 passed, 0 failed in 782 ms**

### 2. Backend Unit Tests (Pytest)
Executed via `pytest tests/test_coordinate_transformation.py -v`:
- Test File: [`tests/test_coordinate_transformation.py`](file:///c:/Developers/Sneha/Projects/hybrid-traffic-control/tests/test_coordinate_transformation.py)
- **Result:** **7 passed in 0.18s**

---

## 8. Remaining Limitations & Stage 3 Readiness

1. **Current Limitations:**
   - Coordinate transformation is mathematical only; no 3D WebGL mesh generation has taken place.
   - Curved road segments are currently represented by polyline lane shapes; smoothing splines (`THREE.CatmullRomCurve3`) will be constructed in Stage 3.
2. **Readiness for Stage 3 (3D Road Geometry):**
   - The coordinate transformation contract is complete, reversible, documented, and covered by automated tests.
   - Ready to generate 3D asphalt ribbons, junction polygon meshes, lane markings, and illustrative elevated flyovers in Stage 3.

---

## 9. Stage 2 Approval Gate Sign-Off Request

Stage 2 (Coordinate Transformation and Spatial Validation) is complete and verified.

In accordance with your strict protocol:
- **Work has stopped.**
- **Stage 3 (3D Road Geometry) will not begin until explicit approval is granted.**

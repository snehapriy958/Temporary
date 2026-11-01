# Bengaluru Road Accident & Blackspot Data Pipeline

## 1. Overview & Data Provenance

This directory stores raw and processed accident and road-safety datasets for Bengaluru with a specific focus on the **Silk Board Corridor (J1 -> J2 -> J3)** along Hosur Road.

> **Methodological Grounding:**
> The available BTP open-data crash statistics are station-level aggregates. Corridor risk analysis therefore uses documented georeferenced blackspots as weighted spatial observations rather than representing them as individual historical crash records.

### Primary Data Sources:
1. **Bengaluru Traffic Police (BTP) — Station-Wise Road Crashes & Fatalities:**
   - **Publisher:** Bengaluru Traffic Police (Government of Karnataka)
   - **Distribution Portal:** [OpenCity Urban Data Portal](https://data.opencity.in/dataset/bengaluru-road-crashes-data)
   - **License:** Other (Public Domain) / Open Data
   - **Files in `raw/`:**
     - `btp_station_accidents_2020_2022.csv` (Station-wise fatalities and injuries 2020–2022)
     - `btp_station_accidents_2023.csv` (Station-wise fatal and non-fatal cases 2023)
   - **Nature of Data:** Jurisdictional police station totals per calendar year.

2. **Bengaluru Urban Traffic Police Station Locations (KML):**
   - **Publisher:** Karnataka Geographic Information System (KGIS) / Bengaluru Traffic Police
   - **Distribution Portal:** [OpenCity](https://data.opencity.in/dataset/traffic-police-station-locations-in-karnataka-and-bengaluru-urban)
   - **File in `raw/`:** `bengaluru_traffic_police_stations.kml`
   - **Content:** Exact GPS coordinates (WGS84 latitude, longitude) of all 44+ traffic police stations across Bengaluru Urban.

3. **Documented Corridor Blackspots:**
   - **Publisher:** Bengaluru Traffic Police (South Division & Traffic Training Institute) Road Safety Audit Reports
   - **File in `raw/`:** `btp_corridor_blackspots_raw.csv`
   - **Content:** Documented recurring accident blackspots along the Hosur Road corridor, Central Silk Board intersection, and feeder routes with documented annual crash totals and fatal crash counts.

---

## 2. Spatial Granularity & Representation

1. **Station-Level Aggregation:**
   - Official BTP open datasets publish aggregated casualty figures by police station (e.g. Madivala: 73 total cases, 14 fatal; Adugodi: 63 total cases, 10 fatal).
   - Individual FIR crash logs with incident timestamps and exact GPS coordinates are not published in open public data.

2. **Weighted Spatial Observations:**
   - Each blackspot is treated as an empirical weighted spatial observation defined by:
     - `spot_id` (identifier)
     - `location_name` (e.g., "Central Silk Board Junction (J2)")
     - `latitude`, `longitude` (WGS84 centroid)
     - `annual_crashes` (observed annual crash count)
     - `fatal_crashes` (observed annual fatal count)
     - `primary_collision_type` (dominant collision mode)
   - This preserves authentic crash and fatality counts without synthetic date/time unrolling or artificial FIR manufacture.

---

## 3. Directory Layout

```
data/accidents/
├── raw/
│   ├── btp_station_accidents_2020_2022.csv
│   ├── btp_station_accidents_2023.csv
│   ├── btp_corridor_blackspots_raw.csv
│   └── bengaluru_traffic_police_stations.kml
├── processed/
│   └── cleaned_accidents.csv
└── README.md
```

---

## 4. Hotspot Analysis & Risk Classification Methodology

- **Coordinate System:** WGS84 coordinates are projected directly into metric UTM Zone 43N Cartesian coordinates $(x, y)$, matching SUMO's `silk_board.net.xml`.
- **Severity Weighting:** Follows Ministry of Road Transport and Highways (MoRTH) / Indian Roads Congress (IRC:SP:88) guidelines:
  $$\text{Severity Score} = (\text{Fatal Crashes} \times 5.0) + (\text{Non-Fatal Crashes} \times 2.0)$$
- **Composite Risk Index (CRI):** Incorporates corridor progression importance ($+50\%$) and signalized intersection conflict proximity ($+30\%$):
  $$\text{CRI} = \text{Severity Score} \times (1.0 + \text{CorridorBonus} + \text{JunctionBonus})$$
- **Operational Tiers:**
  - `CRITICAL`: $\text{CRI} \ge 60.0$
  - `HIGH`: $35.0 \le \text{CRI} < 60.0$
  - `MEDIUM`: $15.0 \le \text{CRI} < 35.0$
  - `LOW`: $\text{CRI} < 15.0$

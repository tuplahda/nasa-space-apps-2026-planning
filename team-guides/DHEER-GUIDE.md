# 👨‍🚀 Dheer's Guide: Autonomous Astronaut Agent Engine

* **Team Member:** **Dheer**
* **Assigned AI Tool:** **Antigravity (Gemini Pro)** *(Terminal execution, deep reasoning, direct file edits)*
* **Core Role:** **Backend Lead 1 — Autonomous Digital-Twin Simulation, State Machine & Space Weather**
* **Files Owned:** `backend/models/telemetry.py`, `backend/services/astronaut_sim.py`, `backend/services/donki_service.py`, `backend/main.py`

---

## 🎯 Your Mission
Build the **Autonomous Astronaut Agent (Digital Twin)** that generates realistic, non-hardcoded health telemetry every second, models human activity states, reacts to space weather (NASA DONKI API), and **dynamically recovers on screen** when a treatment is administered.

---

## 📂 Resources, Datasets & Artifacts You Need to Access

| Resource | Path | How You Use It |
| :--- | :--- | :--- |
| **Microgravity Baselines & Physics** | [`data/nasa_baselines_and_thresholds.json`](../data/nasa_baselines_and_thresholds.json) | **PRIMARY:** Resting Zero-G ranges, circadian cosinor HR model, fluid-shift timeline, EVA thermal limits, DONKI/GOES/SRAG space weather gates, and mechanistic recovery anchors. |
| **Unified Scenario Seeds (24 + 6)** | [`data/simulation_scenario_seeds.json`](../data/simulation_scenario_seeds.json) | 6 quantitative crisis trajectories (with 21 first-person symptom logs), 24 synthetic scenario vectors mapped to Yohan's `CPG-*` IDs, state-space ODEs, and PhysioNet/OSDR manifests. |
| **Lab Reference Intervals** | [`data/lab_reference_intervals.json`](../data/lab_reference_intervals.json) | Specimen-aware `i-STAT CG8+/CG4+` & `CBC` reference/warning/critical bands for diagnostic simulation. |
| **Expanded Clinical Protocols** | [`data/rag_protocols_expanded.json`](../data/rag_protocols_expanded.json) | Shared `CPG-01`–`CPG-32` & 8 legacy `SCENARIO_*` IDs so your simulator aligns 1-to-1 with Yohan's RAG. |
| **Safety Guardrails** | [`artifacts/security_and_safety_guardrails.md`](../artifacts/security_and_safety_guardrails.md) | JPL Power-of-Ten rules (no recursion, bounded loops, error handling). |
| **System Mechanics** | [`artifacts/system_mechanics_deep_dive.md`](../artifacts/system_mechanics_deep_dive.md) | Deep breakdown of physiological equations and microgravity fluid shifts. |
| **Frontend Architecture** | [`artifacts/vanilla_frontend_architecture.md`](../artifacts/vanilla_frontend_architecture.md) | WebSocket packet structure expected by Tivesh's UI. |

---

## 🛰️ Handling the Upcoming NASA Private Dataset (Room for Improvement)

> [!IMPORTANT]
> **NASA's official private challenge dataset is expected to drop in ~24 hours.**
> Your code must be architected so that when NASA's dataset arrives, it plugs in seamlessly without rewriting your simulation loop:
> 1. **Priority #1 (Official NASA Dataset):** When the CSV/JSON files arrive, place them in `data/nasa_official_dataset/` and point a loader function to read baseline rows from it.
> 2. **Priority #2 (Our Synthetic Digital Twin Fallback):** If NASA's dataset lacks continuous 1Hz streams or specific scenarios (e.g. Solar Flares, CO2 scrubber failure), your dynamic mathematical generator fills in the missing physiological parameters automatically.

---

## 🛠️ Step-by-Step Technical Tasks

### 1. Telemetry Data Model (`backend/models/telemetry.py`)
Create Pydantic models validating all outgoing packets:
```python
from pydantic import BaseModel, Field
from typing import Optional

class Vitals(BaseModel):
    heart_rate: float = Field(..., ge=30, le=220)
    blood_pressure_sys: float = Field(..., ge=60, le=220)
    blood_pressure_dia: float = Field(..., ge=40, le=140)
    spo2: float = Field(..., ge=70.0, le=100.0)
    hrv_ms: float = Field(..., ge=5.0, le=150.0)
    core_temp_c: float = Field(..., ge=34.0, le=42.0)
    respiration_rate: float = Field(..., ge=6, le=40)

class Environment(BaseModel):
    cabin_co2_mmhg: float
    ambient_radiation_msv_h: float
    suit_pressure_psi: float = 4.3

class TelemetryPacket(BaseModel):
    timestamp: str
    met: str
    astronaut_id: str = "ASTRO-01"
    name: str = "Cmdr. Alex Vance"
    activity_state: str  # SLEEP, RESTING, ARED_EXERCISE, EVA_SPACEWALK
    vitals: Vitals
    environment: Environment
    symptom_log: str
```

### 2. Physiological Math & State Machine (`backend/services/astronaut_sim.py`)
* **1000ms Loop:** Emits 1 packet every second.
* **Realistic Fluctuation:** Add sinus respiratory arrhythmia ($\pm 3\text{ bpm}$) using a sine wave function modulated by respiration rate.
* **Activity Contexts:**
  * `SLEEP`: HR $48\text{--}58$, BP $100/60$, Temp $36.3^\circ\text{C}$, HRV $65\text{--}80\text{ ms}$.
  * `RESTING`: HR $65\text{--}78$, BP $115/75$, Temp $36.8^\circ\text{C}$, HRV $45\text{--}60\text{ ms}$.
  * `ARED_EXERCISE`: HR $130\text{--}165$, BP $155/85$, Temp $37.8^\circ\text{C}$, HRV $15\text{--}25\text{ ms}$.
  * `EVA_SPACEWALK`: HR $95\text{--}125$, Core Temp $37.2^\circ\text{C}$.

### 3. NASA DONKI API Integration (`backend/services/donki_service.py`)
* Fetch space weather from `https://api.nasa.gov/DONKI/SEP?startDate=...&api_key=DEMO_KEY`.
* **Air-gap guardrail:** Cache a real historical solar flare JSON response in `data/donki_cache.json` so the app runs 100% offline if venue Wi-Fi drops.

### 4. Scenario Trigger & Closed-Loop Recovery Endpoints
* `POST /api/scenarios/trigger`: Accepts `{"scenario": "hypercapnia"}` and trends vitals into the crisis over 5–10 seconds.
* `POST /api/treatments/apply`: Accepts `{"treatment": "li_oh_swap_and_o2"}` and trends vitals **smoothly back to nominal baseline** over 5–10 seconds (washout decay math).

---

## 🤖 Master Prompt for Dheer (Copy into Antigravity)

```text
Act as a Senior Aerospace & Biomedical Software Engineer in Antigravity.
We are building the Autonomous Astronaut Agent for NASA Space Apps project A.R.E.S. Med.

Build the simulation service in `/backend`:
1. `models/telemetry.py`: Pydantic models for Vitals, Environment, and TelemetryPacket.
2. `services/astronaut_sim.py`: A stateful biological simulator running on a 1000ms tick. Add sinus respiratory arrhythmia (±3 bpm), activity state transitions (SLEEP, RESTING, EXERCISE, EVA), and support for ingesting an upcoming external NASA dataset with fallback to synthetic generation.
3. Implement crisis injection for 4 key scenarios: "nominal", "solar_flare", "hypercapnia", and "sans".
4. Implement closed-loop recovery: `POST /api/treatments/apply` smoothly recovers vitals back to baseline over 5-10 seconds using a biological decay curve.
5. `services/donki_service.py`: Query NASA DONKI SEP space weather with a local JSON cache fallback for offline air-gapped compliance.
6. `main.py`: Expose WebSocket `/ws/telemetry` streaming 1Hz packets to Tivesh's frontend.
Adhere strictly to JPL Power-of-Ten rules (no recursion, bounded loops, safe memory allocation).
```

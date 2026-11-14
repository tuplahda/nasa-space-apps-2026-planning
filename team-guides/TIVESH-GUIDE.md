# 📈 Tivesh's Guide: Frontend Entirely (Mission Control Console)

* **Team Member:** **Tivesh**
* **Assigned AI Tools:** **ChatGPT Plus (Codex), Claude, Gemini Plus**
* **Tech Stack:** **HTML5 + Modern CSS + Vanilla JavaScript (ES6) + Chart.js (Local Vendor)**
* **Scope:** **YOU OWN THE ENTIRE FRONTEND.** (No merge conflicts with anyone else!)

---

## 🎯 Your Mission
Build the entire **A.R.E.S. Med Mission Control Console** in clean, fast HTML/CSS/JS. You connect to Dheer's WebSocket (`/ws/telemetry`) and Yohan's RAG endpoint (`/api/diagnose`).

---

## 📂 Resources, Datasets & Artifacts You Need to Access

| Resource | Path | How You Use It |
| :--- | :--- | :--- |
| **Frontend Architecture** | [`artifacts/vanilla_frontend_architecture.md`](../artifacts/vanilla_frontend_architecture.md) | **MUST READ:** Exact DOM IDs, layout specs, and API contracts. |
| **2-Mode Clinical Spec** | [`artifacts/clinical_decision_protocol_2_modes.md`](../artifacts/clinical_decision_protocol_2_modes.md) | UI layout requirements for Mode A vs Mode B cards and checklists. |
| **Chart.js Vendor Asset** | `frontend/vendor/chart.umd.min.js` | Local Chart.js library for 100% offline air-gapped biometrics charts. |
| **Microgravity Thresholds** | [`data/nasa_baselines_and_thresholds.json`](../data/nasa_baselines_and_thresholds.json) | Threshold numbers for coloring gauges green, yellow, or red, plus canonical 1 Hz telemetry fields. |
| **Lab Reference Intervals** | [`data/lab_reference_intervals.json`](../data/lab_reference_intervals.json) | Specimen-aware `i-STAT` & `CBC` warning/critical bands for Mode B lab result cards. |

---

## 🛰️ Handling the Upcoming NASA Private Dataset (Room for Improvement)

> [!IMPORTANT]
> **When NASA's official private dataset drops in ~24 hours:**
> NASA may provide new telemetry fields (e.g. blood glucose, intracranial pressure, EEG channels).
> * Your frontend charts and metric cards should be modular: each gauge is a simple `<div>` card with an ID.
> * If a new metric is added (e.g. `intracranial_pressure_mmhg`), you can add a new card in `index.html` in under 2 minutes without restructuring the layout!

---

## 🖥️ The 3-Column Screen You Build

```
+--------------------------------------------------------------------------------------------------------------------+
| [A.R.E.S. Med Logo]   [● Nominal]  [⚡ Solar Flare]  [⚠️ EVA Hypercapnia]  [❓ Mode B Zero-Day]   MET: 042:14:30:12 |
+-------------------------------------+--------------------------------------+---------------------------------------+
| LEFT COLUMN: Vitals & Routine       | CENTER COLUMN: 3D Body HUD           | RIGHT COLUMN: AI Medical Officer      |
| • Live Heart Rate (Chart.js line)   |                                      | • 🔴 20-MIN MARS COMMS DELAY BANNER   |
| • Blood Pressure & SpO2 Chart       |         [ 🧠 Head: SANS-01 ]         |                                       |
| • Cabin CO2 Gauge & Radiation Level |         [ 🫁 Lungs: ECLSS-03 ]       | [MODE A: Known Condition Card]        |
| • 📅 Daily Routine Health Schedule: |         [ ❤️ Heart: CV-02 ]          | • NASA Quote: [NASA-STD-3001 V2 6004] |
|   [✓] 08:00 Orthostatic BP Check    |         [ ☢️ Core: RAD-04 ]          | • CHeCS Pack: TIMP / CMP              |
|   [✓] 13:30 ARED Exercise (100%)    |                                      | • ⚠️ CONTRAINDICATION: NO OPIOIDS     |
|   [ ] 19:00 SANS Optic Disc Scan    |   (Organs glow Cyan ➔ Amber ➔ Red)   |                                       |
| • Crew Readiness Meter (94%)        | [Click organ to isolate diagnostics] | • Interactive Treatment Checklist:    |
| • Live Symptom Ticker:              |                                      |   [ ] Swap LiOH Scrubber Canister     |
|   "Frontal headache, air sluggish"  |                                      |   [ ] Administer 100% O2 via RSP      |
+-------------------------------------+--------------------------------------+---------------------------------------+
| BOTTOM BAR: Houston Flight Audit Ledger (Store-and-Forward Queue)                                                  |
+--------------------------------------------------------------------------------------------------------------------+
```

---

## 🛠️ Files You Own in `frontend/`

```
frontend/
├── index.html              <-- Main dashboard skeleton
├── css/
│   ├── main.css            <-- NASA dark theme (slate-950), glass cards, grid
│   └── holographic.css     <-- 3D body glowing aura, pulse animations, organ pins
├── js/
│   ├── app.js              <-- Main coordinator
│   ├── websocket.js        <-- Connects to ws://localhost:8000/ws/telemetry
│   ├── charts.js           <-- Chart.js rolling 30s line charts
│   ├── body_hud.js         <-- Holographic body avatar with organ pins (SANS-01, CV-02, etc.)
│   └── medical_panel.js    <-- Renders Mode A & Mode B diagnosis cards & checklist
└── vendor/
    └── chart.umd.min.js    <-- Stored locally (100% offline air-gapped)
```

---

## ⚡ Key Integrations & Recovery Signal

1. **Top Scenario Bar Buttons:** Clicking a button tells Dheer's simulator to start a crisis:
   ```javascript
   fetch("http://localhost:8000/api/scenarios/trigger", {
       method: "POST",
       headers: { "Content-Type": "application/json" },
       body: JSON.stringify({ scenario: "hypercapnia" })
   });
   ```

2. **Treatment Checklist Completion:** When user checks off the critical action steps on Roy/Yohan's checklist, notify Dheer's simulator so the astronaut heals:
   ```javascript
   fetch("http://localhost:8000/api/treatments/apply", {
       method: "POST",
       headers: { "Content-Type": "application/json" },
       body: JSON.stringify({ treatment: "li_oh_swap_and_o2" })
   });
   ```

---

## 🤖 Master Prompt for Tivesh (Copy into ChatGPT Plus / Claude)

```text
Act as a Lead Frontend Engineer in Vanilla HTML5, Modern CSS, and JavaScript.
We are building the complete Mission Control Console for NASA Space Apps project A.R.E.S. Med.

Create the frontend in `frontend/`:
1. `index.html`: A 3-column dark NASA theme (#030712 slate-950).
   - Top Header: Title, ticking MET clock, and 4 scenario buttons ("Nominal Orbit", "Solar Flare", "EVA Hypercapnia", "Mode B Zero-Day").
   - Left Column: Heart Rate line chart, Blood Pressure/SpO2 chart (Chart.js), Cabin CO2 gauge, Radiation dosimeter, Daily Routine Schedule card ([✓] 08:00 Orthostatic BP & Hydration, [✓] 13:30 30-min ARED Exercise, [ ] 19:00 Optic Disc SANS Scan) with 94% Readiness meter, and live symptom feed.
   - Center Column: Glowing 3D/2.5D Holographic Body HUD with clickable organ pins (SANS-01 Head, CV-02 Heart, ECLSS-03 Lungs, RAD-04 Core). Shift color from Cyan to Pulsing Red during emergencies.
   - Right Column: AI Medical Officer Panel with 20-min Mars Comms Delay banner, dynamic cards for Mode A (NASA quote, CHeCS pack, contraindication warning) and Mode B (Zero-Day emergency, ABC vital stabilization, Point-of-Care lab orders, drug lockout), and an interactive treatment checklist.
2. `css/main.css` & `css/holographic.css`: Glassmorphism, neon cyan/amber/red accents, and organ pulse animations.
3. `js/websocket.js`: Connects to `ws://localhost:8000/ws/telemetry` to update vitals and charts every 1 second.
4. `js/medical_panel.js`: When checklist is completed, sends POST to `http://localhost:8000/api/treatments/apply`.
Do not use npm or React. Reference local vendor/chart.umd.min.js only.
```

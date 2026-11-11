# Vanilla HTML/CSS/JS Frontend Architecture & Data Contract

This document defines the unified frontend architecture, file structure, DOM IDs, and JavaScript contracts for **A.R.E.S. Med**. Both **Tivesh** (Member 3) and **Roy** (Member 4) will build on this shared structure without merge conflicts.

---

## 📂 Frontend Directory Layout

```
frontend/
├── index.html              <-- Main NASA Mission Control layout (Tivesh & Roy)
├── css/
│   ├── main.css            <-- Dark NASA theme, CSS grid, glassmorphic cards (Tivesh)
│   └── holographic.css     <-- 3D anatomical body glow, pulse animations, organ pins (Tivesh)
├── js/
│   ├── app.js              <-- Coordinator / state entrypoint
│   ├── websocket.js        <-- Live WebSocket subscriber to ws://localhost:8000/ws/telemetry (Tivesh)
│   ├── charts.js           <-- Chart.js rolling 30-second biometric charts (Tivesh)
│   ├── body_hud.js         <-- 3D/2.5D Holographic body avatar with organ pins (Tivesh)
│   └── medical_panel.js    <-- RAG diagnosis card & interactive treatment checklist (Roy)
└── vendor/
    └── chart.umd.min.js    <-- Local standalone Chart.js build (100% offline air-gapped)
```

---

## 🔌 API & WebSocket Contracts

### 1. Live Telemetry Stream (`ws://localhost:8000/ws/telemetry`)
Emitted by **Dheer's Backend** every 1000ms:
```json
{
  "timestamp": "2026-11-14T10:15:30Z",
  "met": "042:14:30:12",
  "astronaut_id": "ASTRO-01",
  "name": "Cmdr. Maya Lin",
  "activity_state": "EVA_SPACEWALK",
  "vitals": {
    "heart_rate": 118,
    "blood_pressure_sys": 142,
    "blood_pressure_dia": 92,
    "spo2": 95.8,
    "hrv_ms": 22.4,
    "core_temp_c": 37.6,
    "respiration_rate": 20
  },
  "environment": {
    "cabin_co2_mmhg": 12.8,
    "ambient_radiation_msv_h": 4.2,
    "suit_pressure_psi": 4.3
  },
  "symptom_log": "Mild throbbing headache behind temples; slight shortness of breath."
}
```

### 2. Scenario Trigger Endpoint (`POST http://localhost:8000/api/scenarios/trigger`)
Called by **Tivesh's Top Bar Buttons**:
* **Payload:** `{"scenario": "hypercapnia"}` (options: `nominal`, `solar_flare`, `hypercapnia`, `sans`, `dehydration`)
* **Response:** `{"status": "ok", "scenario": "hypercapnia", "message": "Injected CO2 scrubber failure."}`

### 3. Anomaly / Diagnostic Event Endpoint (`POST http://localhost:8000/api/diagnose`)
Served by **Yohan's RAG Engine** and rendered by **Roy's Medical Panel**:
```json
{
  "diagnosis_id": "DIAG-2026-0842",
  "condition": "Severe Hypercapnia (CO2 Intoxication)",
  "severity": "CLASS_1_EMERGENCY",
  "confidence": 0.96,
  "triggering_vitals": [
    "Cabin CO2: 12.8 mmHg (Safe Limit: 5.0)",
    "Heart Rate: 118 bpm (Microgravity Max: 100)",
    "BP: 142/92 mmHg"
  ],
  "nasa_citation": {
    "document": "NASA-STD-3001 Vol 1 / ISS Medical Operations Checklist",
    "section": "Section 4.2: Environmental Hypercapnia Countermeasures"
  },
  "action_plan": [
    {"step": 1, "action": "Verify EMU/Suit LiOH Scrubber canister status and swap immediately.", "critical": true},
    {"step": 2, "action": "Administer 100% emergency O2 via face mask.", "critical": true},
    {"step": 3, "action": "Abort ongoing EVA and initiate airlock repressurization sequence.", "critical": true},
    {"step": 4, "action": "Monitor cognitive status; log symptoms at 5-minute intervals.", "critical": false}
  ],
  "source_mode": "DETERMINISTIC_NASA_VERIFIED"
}
```

### 4. Recovery Signal Endpoint (`POST http://localhost:8000/api/scenarios/cure`)
Called when **Roy's Checklist** has all critical items completed:
* **Response:** `{"status": "cured", "message": "Astronaut vitals stabilizing back to microgravity baseline."}`

---

## 🎯 Shared DOM IDs (For Tivesh & Roy)

By agreeing on these exact element IDs in `index.html`, Tivesh and Roy can write their JavaScript independently without breaking each other's code:

| Element ID | Owner | Purpose |
| :--- | :---: | :--- |
| `met-timer` | Tivesh | Displays ticking Mission Elapsed Time |
| `astronaut-name` | Tivesh | Displays "Cmdr. Maya Lin" |
| `activity-badge` | Tivesh | Displays "EVA SPACEWALK" or "RESTING" |
| `hr-val` | Tivesh | Current Heart Rate number |
| `bp-val` | Tivesh | Current BP (e.g. "120/80") |
| `spo2-val` | Tivesh | Current SpO2 percentage |
| `co2-val` | Tivesh | Cabin CO2 value with color shift |
| `rad-val` | Tivesh | Ambient Radiation value |
| `symptom-feed` | Tivesh | First-person astronaut symptom text |
| `routine-schedule-card` | Tivesh | Container for Daily Scheduled Health Checks (Routine Prevention) |
| `readiness-meter` | Tivesh | Displays Crew Health Readiness (e.g. "94% Optimal") |
| `body-avatar-svg` | Tivesh | Center 3D/2.5D Holographic SVG body model |
| `pin-brain`, `pin-heart`, `pin-lungs`, `pin-core` | Tivesh | Organ hotspots that pulse with alert colors |
| `comms-delay-banner` | Roy | Glowing 20-min Mars radio delay alert |
| `diagnosis-card` | Roy | Container for primary condition, severity, and NASA citation |
| `treatment-checklist` | Roy | Container where treatment steps `<input type="checkbox">` are injected |
| `treatment-audit-log` | Roy | Timestamped history of completed medical countermeasures |

---

## 📦 Zero-Internet Vendor Setup (Getting Chart.js)
To make sure the app runs 100% offline at the venue, download the standalone UMD bundle of Chart.js:
* File URL: `https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js`
* Save as: `frontend/vendor/chart.umd.min.js`
* Reference in `index.html`: `<script src="vendor/chart.umd.min.js"></script>`
* **Result:** Zero internet access required at the hackathon!

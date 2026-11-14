# Autonomous Astronaut Agent Engine (Dheer)

**Team Member:** Dheer  
**Subsystem:** Autonomous Astronaut Agent (Digital Twin) & Space Weather Telemetry Engine  
**Project:** A.R.E.S. Med (NASA Space Apps Challenge 2026)  
**Assigned AI Tool:** Antigravity (Gemini Pro)  

---

## Purpose & Scope

This directory contains the standalone and core modules for the **Autonomous Astronaut Agent (Cmdr. Maya Lin / ASTRO-01)**. 

It serves as the heart of Layer 1 in the A.R.E.S. Med architecture:
1. **1Hz Biological Telemetry Generator:** Continuous, non-hardcoded microgravity physiological telemetry (HR, BP, SpO2, HRV, Core Temp, Respiration Rate, VE).
2. **Sinus Respiratory Arrhythmia:** Realistic +/- 3 bpm cyclical heart rate modulation synced to breathing.
3. **Activity State Machine:** Discrete physiological baselines across SLEEP, IVA_REST, ARED_EXERCISE, and EVA_SPACEWALK per NASA-STD-3001.
4. **Crisis Injection Curves:** Dynamic mathematical trends for emergency scenarios (hypercapnia, solar_flare, sans, decompression, dehydration).
5. **Closed-Loop Treatment Recovery:** Smooth exponential washout biological decay returning vitals back to baseline upon countermeasure administration.
6. **NASA DONKI Space Weather Service:** Live Solar Energetic Particle (SEP) queries with local air-gap cache fallback.
7. **Hybrid Dataset Ingestion:** Built-in loader ready to seamlessly ingest official NASA challenge datasets when dropped into data/nasa_official_dataset/.

---

## Directory Structure

```
Autonomous agent(dheer)/
├── README.md                 <-- Subsystem documentation and quickstart
├── astronaut_sim.py          <-- Core physiological simulator & state machine
├── donki_service.py          <-- NASA DONKI space weather client & air-gap cache handler
├── test_agent.py             <-- Standalone test suite & telemetry verification
└── run_sim.py                <-- CLI runner to preview 1Hz live telemetry in terminal
```

> **Note on Backend Integration:**  
> The core engine modules here are also imported directly by backend/services/ so that the unified FastAPI / WebSocket server (/ws/telemetry) and triage endpoints communicate in real time without code duplication.

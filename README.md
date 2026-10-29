# 🚀 A.R.E.S. Med — NASA Space Apps Challenge 2026 (Planning & Research Hub)

**Challenge:** [Create Health Monitoring Software for Astronauts on Space Missions](https://www.spaceappschallenge.org/2026/challenges/health-monitoring-software/?tab=resources)  
**Hackathon Dates:** November 14–15, 2026  
**Code Repository:** `ares-med-space-apps-2026` *(Hackathon Implementation Repo)*

---

## 📌 Project Overview

**A.R.E.S. Med** (*Autonomous Real-time Extraterrestrial Survival & Medical System*) is a three-layer, closed-loop autonomous biomedical telemetry and clinical decision support platform designed for NASA Level V deep-space exploration missions (Artemis cis-lunar & Mars transit) where communication delays up to 20 minutes one-way and solar conjunction blackouts prevent real-time flight surgeon intervention.

### 3-Layer Closed-Loop Architecture
1. **Layer 1: Stateful Astronaut Digital-Twin Agents & Coupled Habitat ECLSS**
   - Generates real-time 1 Hz physiological telemetry (`HR`, `SBP`, `DBP`, `SpO2`, `HRV RMSSD`, `CBT`, `RR`, `VE`) and point-of-care diagnostics (`OCT RNFL`, `Optical Biometry`, `i-STAT`, `C2M2 CBC`, `AI Ultrasound`) grounded in empirical microgravity adaptation equations and coupled to cabin environmental metrics ($pp\text{CO}_2$, $pp\text{O}_2$, radiation dosimetry).
2. **Layer 2: Context-Aware Edge Anomaly Detection Engine + NASA DONKI API**
   - Evaluates incoming telemetry against **adapted microgravity baselines** and **activity context modifiers** (`SLEEP`, `IVA_REST`, `ARED_EXERCISE`, `EVA_SPACEWALK`) per `NASA-STD-3001 Vol 1 & Vol 2`, preventing terrestrial false positives (such as resting microgravity "Space Fever" at $37.8^\circ\text{C}$) while correlating internal physiology with live solar particle events from the **NASA DONKI API**.
3. **Layer 3: Autonomous RAG Medical Officer & CHeCS Inventory Manager**
   - Triggered on anomaly state transitions to retrieve grounded clinical protocols from the **ISS Medical Checklist (`JSC-48522`)**, **`NASA-STD-3001`**, **`OCHMO-TB-004`**, and the **2023 ISS CHeCS Formulary** (`CMP`, `OMP`, `TIMP`, `EMTP`, `Vascular Contingency Pack`).
   - Enforces life-critical spaceflight contraindications (e.g., blocking opioids during hypercapnia; blocking NSAIDs during radiation thrombocytopenia) and closes the loop by feeding executed countermeasures back into Layer 1's recovery equations.

---

## 📂 Repository Structure

| Document | Description |
| :--- | :--- |
| [`docs/01-nasa-space-medicine-research.md`](./docs/01-nasa-space-medicine-research.md) | Complete biomedical research reference: $1g$ vs. $\mu g$ physiological baselines, `NASA-STD-3001` environmental & radiation limits, 8 mathematical anomaly models, CHeCS drug protocols, and NASA Open Data/APIs (`DONKI`, `OSDR`, `SSM`, `PhysioNet`). |
| [`docs/02-master-engineering-plan.md`](./docs/02-master-engineering-plan.md) | System architecture diagram, locked-in JSON Data Contracts (`Contract A`, `Contract B`, `Contract C`), 4 showcase demo scenarios, pre-hackathon checklist (Oct 29 – Nov 13), and 48-hour hackathon timeline. |
| [`docs/03-system-mechanics-deep-dive.md`](./docs/03-system-mechanics-deep-dive.md) | Deep-dive technical analysis of the Closed-Loop Countermeasure Feedback Cycle, Layer 1 state machine, Layer 2 Earth-vs-Space context gate, and Layer 3 dual-mode RAG + offline fallback engine. |
| [`docs/04-rag-knowledge-base-schema.md`](./docs/04-rag-knowledge-base-schema.md) | Document schema and structured clinical protocol cards for all 8 spaceflight medical scenarios and CHeCS medical subpacks. |
| [`docs/05-ui-ux-console-wireframe.md`](./docs/05-ui-ux-console-wireframe.md) | Screen layout, panel breakdown, interactive crisis injector controls, and 2-minute judge demo flow for the Mission Medical Console UI. |

---

## ✅ Pre-Hackathon Checklist (Before Nov 14, 2026)

- [ ] Register free NASA API Key at [https://api.nasa.gov/](https://api.nasa.gov/) for live `DONKI` solar weather polling.
- [ ] Review and finalize the JSON Data Contracts in [`docs/02-master-engineering-plan.md`](./docs/02-master-engineering-plan.md).
- [ ] Assign team roles across Layer 1 (Simulation Engine), Layer 2 (Edge Detector + DONKI), Layer 3 (RAG + CHeCS), and Frontend UI.
- [ ] Verify local dev environment setup (`Node.js`, `Python 3.11+`, `Git`) across all team laptops.

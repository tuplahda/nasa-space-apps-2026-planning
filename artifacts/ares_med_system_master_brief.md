# 🚀 A.R.E.S. Med — Complete System Master Architecture Brief
**Autonomous Real-Time Extraterrestrial Survival & Medical System**  
*NASA Space Apps Challenge 2026 — Official Team & Architecture Guide*

---

## 🌌 1. Executive Summary & The Problem

On long-duration human spaceflights to the Moon and Mars, radio signals take **up to 20 minutes each way** to reach Earth (a 40-minute round-trip comms lag). 

* If an astronaut suffers an acute life-support failure (e.g. cabin $\text{CO}_2$ scrubber breakdown) or a Solar Particle Event (radiation storm), **flight surgeons in Houston cannot provide real-time guidance**.
* Waiting 40 minutes for advice during acute hypoxia or intracranial pressure spikes can be fatal.
* **A.R.E.S. Med** is an onboard, 100% offline, air-gapped **Multi-Agent Health Monitoring & Clinical Decision Support Console**. It continuously tracks crew physiology, detects spaceflight anomalies against microgravity baselines, and prescribes step-by-step verified NASA countermeasures without requiring an internet connection.

---

## 🧠 2. The Decoupled Multi-Agent Architecture (Zero Cheating)

The core architectural strength of A.R.E.S. Med is that **the Astronaut Simulator and the AI Medical Officer are completely decoupled**.

```
+----------------------------------------------------------------------------------------------------+
|                                    DECOUPLED MULTI-AGENT LOOP                                      |
+----------------------------------------------------------------------------------------------------+
|                                                                                                    |
|   [ UI Crisis Trigger / Sliders ]                                                                 |
|                 │                                                                                  |
|                 ▼ (Only perturbs environment / biology)                                            |
|   +---------------------------------------+                                                        |
|   | LAYER 1: Astronaut Digital Twin Agent |                                                        |
|   | • Stateful biological math            |                                                        |
|   | • Respiration & Sinus Arrhythmia      |                                                        |
|   | • Activity (Sleep, Rest, EVA)         |                                                        |
|   +---------------------------------------+                                                        |
|                 │                                                                                  |
|                 ▼ Raw Telemetry Stream (HR: 118, SpO2: 91%, CO2: 13, "Throbbing headache")         |
|   +---------------------------------------+                                                        |
|   | LAYER 2: 60s JPL Sliding Ring Buffer  |                                                        |
|   | • Rolling means & slew-rate filter    |                                                        |
|   | • 3-tick persistence (SEU filter)     |                                                        |
|   +---------------------------------------+                                                        |
|                 │                                                                                  |
|                 ▼ Anomaly Alert (Anomaly detected, but disease is UNKNOWN to the Doctor)           |
|   +---------------------------------------+                                                        |
|   | LAYER 3: NASA Level V RAG Doctor AI   |                                                        |
|   | • Evaluates raw vitals & symptoms     |                                                        |
|   | • Searches NASA Knowledge Base        |                                                        |
|   +---------------------------------------+                                                        |
|                 │                                                                                  |
|         ┌───────┴───────────────────────┐                                                          |
|         ▼                               ▼                                                          |
|   Confidence >= 75%               Confidence < 75%                                                 |
|   [ MODE A: KNOWN DIAGNOSIS ]     [ MODE B: CERTIFIED ABSTENTION ]                                 |
|   "Acute Cabin Hypercapnia"       "Unclassified Novel Anomaly —                                    |
|   NASA-STD-3001 [V2 6004]         Zero-Day ABC Stabilization Active"                               |
|   Checklist: Swap LiOH Canister   Checklist: 100% O2, IV Saline, i-STAT Labs                       |
|         │                               │                                                          |
|         └───────────────┬───────────────┘                                                          |
|                         ▼                                                                          |
|   [ Astronaut/Judge Executes Treatment Checklist on UI ]                                           |
|                         │                                                                          |
|                         ▼ Recovery Signal (POST /api/treatments/apply)                             |
|   [ Layer 1 Astronaut Vitals Dynamically Heal Back to Normal in Real Time! ]                       |
|                                                                                                    |
+----------------------------------------------------------------------------------------------------+
```

### Why the Doctor is "Blind":
1. When you press a crisis button, **the button never tells the Doctor what the illness is**.
2. The button only adjusts biological or environmental parameters (e.g. increases cabin $\text{CO}_2$ by $+10\text{ mmHg}$).
3. The Astronaut Agent’s biology naturally deteriorates (heart rate climbs, $\text{SpO}_2$ drops, astronaut logs a headache).
4. The Doctor AI independently observes the raw biometrics, searches its NASA database, and figures out the diagnosis on its own!

---

## 💾 3. Client vs. Server: Why Page Refreshes Do Not Reset Vitals

> **The Website (Frontend) is just a TV monitor.**  
> **The Astronaut Agent and Database live on the Server (Backend).**

* **The Problem:** If a presenter accidentally hits `Ctrl + R` (refresh) or closes the browser tab while the astronaut is in a crisis at $100\text{ bpm}$, will it reset back to $72\text{ bpm}$?
* **The Solution (SQLite Local Database):**
  1. Every second, Dheer's backend simulator writes the astronaut's active biological state to a local SQLite database (`ares_telemetry.db`):
     ```sql
     astronaut_id: "ASTRO-01",
     heart_rate: 100.4,
     blood_pressure: "142/92",
     spo2: 91.8,
     cabin_co2: 13.2,
     active_condition: "HYPERCAPNIA_CRISIS"
     ```
  2. When Tivesh's website is refreshed or reopened, the very first thing it does is call `GET /api/astronaut/status`.
  3. The website immediately loads the current state: heart rate is still at $100\text{ bpm}$, the 3D body lungs are still pulsing red, and the active NASA checklist is still waiting!
  4. **The demo is completely crash-proof.**

---

## 🩺 4. The 2 Clinical Decision Modes: Mode A vs. Mode B

A.R.E.S. Med is built around strict clinical safety guidelines: **First, Do No Harm**.

```
+----------------------------------------------------------------------------------------------------+
| 🟢 MODE A: KNOWN CONDITION (Confidence >= 75%)   | 🔴 MODE B: NOVEL ANOMALY (Confidence < 75%)     |
+--------------------------------------------------+-------------------------------------------------+
| • Trigger: Pattern matches verified NASA data.   | • Trigger: Unseen stressor or novel anomaly.    |
| • Diagnosis: Exact NASA medical name.            | • Diagnosis: "Unclassified Novel Anomaly —      |
| • Verbatim Standard Citation:                    |              Symptom-Based Stabilization Active"|
|   e.g. NASA-STD-3001 [V2 6004].                  | • Certified Abstention: AI refuses to guess     |
| • Physical CHeCS Packs: Uses only onboard packs  |   or hallucinate a fake disease name.           |
|   (CMP oral pack, TIMP inhalation pack, etc.).   | • Step 1 (ABC Stabilization):                   |
| • Flight Contraindications:                      |   100% O2 via RSP mask + Normal Saline IV.      |
|   e.g. NEVER give opioids during hypercapnia.    | • Step 2 (Point-of-Care Lab Orders):            |
| • Action Checklist: Step-by-step procedural      |   Order i-STAT blood gas, C2M2 CBC, Ultrasound. |
|   actions to resolve the cause.                  | • Step 3 (Drug Lockout):                        |
|                                                  |   🔒 Opioids & NSAIDs LOCKED OUT until labs.    |
|                                                  | • Step 4 (In-Flight Learning):                  |
|                                                  |   Queue for Houston + Save to Onboard RAG.      |
+--------------------------------------------------+-------------------------------------------------+
```

---

## 📈 5. Real-Time Closed-Loop Recovery (The Demo Magic)

When a treatment is administered on the UI, the astronaut doesn't snap back to normal like a light switch. The backend applies a **pharmacodynamic washout equation** over 10 seconds:

$$\text{Vital}_{t+1} = \text{Vital}_t + (\text{Baseline} - \text{Vital}_t) \times 0.25$$

### Second-by-Second Recovery Timeline:
* **T+0s (Emergency Active):** Cabin $\text{CO}_2$ is $13.2\text{ mmHg}$, HR is $118\text{ bpm}$, $\text{SpO}_2$ is $91.4\%$. Lungs/Brain flash pulsing red.
* **T+1s (Treatment Administered):** Presenter checks `[x] Swap LiOH Canister & Don 100% O2 Mask`.
* **T+4s (Healing Begins):** $\text{CO}_2$ drops to $8.1\text{ mmHg}$, HR descends to $98\text{ bpm}$, $\text{SpO}_2$ climbs to $94.2\%$. 3D body shifts to amber caution.
* **T+8s (Stabilization):** $\text{CO}_2$ reaches safe $2.8\text{ mmHg}$, HR drops to $72\text{ bpm}$, $\text{SpO}_2$ reaches $98.5\%$. 3D body returns to calm cyan wireframe.
* **T+10s (Success):** Medical panel displays: **`TREATMENT EFFICACY: 100% — VITALS STABILIZED`**.

---

## 🖥️ 6. The 3-Column Mission Control UI Layout

Built entirely in clean **Vanilla HTML5 + Modern CSS + JavaScript** (no npm, no React build crashes):

```
+--------------------------------------------------------------------------------------------------------------------+
| [A.R.E.S. Med Logo]   [● Nominal]  [⚡ Solar Flare]  [⚠️ EVA Hypercapnia]  [❓ Mode B Zero-Day]   MET: 042:14:30:12 |
+-------------------------------------+--------------------------------------+---------------------------------------+
| LEFT COLUMN (Tivesh): Vitals        | CENTER COLUMN (Tivesh): 3D Body HUD  | RIGHT COLUMN (Roy & Yohan): AI Doctor |
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

## 👥 7. Team Roles & Deliverables

```
+---------------------------------------------------------------------------------------------------------+
|                                    A.R.E.S. MED TEAM ROLES                                              |
+---------------------------------------------------------------------------------------------------------+
|  👨‍🚀 DHEER: Autonomous Agent          |  🩺 YOHAN: Whole RAG System                                      |
|  • Physiological Math & Digital Twin  |  • 60s JPL Ring Buffer & Anomaly Detector                        |
|  • Activity States & Dynamic Vitals   |  • 2-Mode Clinical Protocol (Mode A Known vs Mode B Zero-Day)    |
|  • 1Hz WebSocket Streamer             |  • NASA HRP & CHeCS Formulary Grounding                          |
+---------------------------------------+------------------------------------------------------------------+
|  📊 TIVESH: Frontend Entirely         |  🛠️ ROY: Jack of All Trades (Integration & Pitch Lead)           |
|  • HTML5 + CSS + Vanilla JS           |  • Assists Dheer & Yohan on Backend/AI                           |
|  • 3D Holographic Body HUD            |  • Tests End-to-End Closed-Loop Recovery                         |
|  • Chart.js Biometrics & Routine Bar  |  • Leads Official 7-Slide Deck & 4-Min Timed Presentation        |
+---------------------------------------------------------------------------------------------------------+
```

### 👨‍🚀 Dheer — Autonomous Astronaut Agent (Backend 1)
* **Tool:** Antigravity (Gemini Pro)
* **Owns:** `backend/services/astronaut_sim.py`, `backend/models/telemetry.py`, `backend/services/donki_service.py`
* **Tasks:** 1000ms loop, sinus arrhythmia, activity states (`SLEEP`, `RESTING`, `EXERCISE`, `EVA`), NASA DONKI space weather connector, and `POST /api/treatments/apply` biological recovery.

### 🩺 Yohan — Whole RAG System & AI Medical Officer (Backend 2)
* **Tool:** Antigravity (Gemini Pro)
* **Owns:** `backend/services/ring_buffer.py`, `backend/services/anomaly_detector.py`, `backend/services/rag_engine.py`
* **Tasks:** 60s sliding ring buffer (JPL rules), microgravity baseline evaluator, 2-Mode Clinical Protocol (Mode A vs Mode B Zero-Day), and `POST /api/diagnose`.

### 📊 Tivesh — Frontend Entirely (Mission Control Console)
* **Tool:** ChatGPT Plus / Claude / Gemini Plus
* **Owns:** `frontend/index.html`, `frontend/css/main.css`, `frontend/js/charts.js`, `frontend/js/body_hud.js`, `frontend/js/websocket.js`
* **Tasks:** Dark NASA UI, rolling `Chart.js` line graphs, 3D Holographic Body HUD with glowing organ pins (`SANS-01`, `CV-02`, `ECLSS-03`, `RAD-04`), and Daily Routine Prevention widget (`94% Readiness Meter`).

### 🛠️ Roy — Jack of All Trades (Integration & Pitch Lead)
* **Tool:** DeepSeek Harness / ChatGPT Plus
* **Owns:** `frontend/js/medical_panel.js`, `presentation/7_SLIDES_DECK.md`, `presentation/4_MINUTE_SCRIPT.md`
* **Tasks:** Assists Dheer and Yohan, tests end-to-end closed loop, leads official 7-slide deck, times the 4-minute presentation, and records backup USB demo video.

---

## ⏰ 8. Mauritius Event Deadlines & The 4-Minute Presentation

* **Sunday, Nov 15 — 10:00 AM:** **Code Freeze.** Bug fixes only.
* **Sunday, Nov 15 — 10:30 AM:** Roy records backup 60-second screen video on a USB flash drive.
* **Sunday, Nov 15 — 11:30 AM (HARD DEADLINE):** 7-slide deck, demo video, and NASA portal submitted!
* **Sunday, Nov 15 — 12:00 PM:** Live judging begins! (Strictly **4-minute presentation** + 2-minute Q&A).

### The Winning 4-Minute Live Demo Split:
* **0:00 – 1:00 (Slides 1–4):** Problem (20-min Mars radio delay), Solution, and NASA Datasets.
* **1:00 – 1:30 (Slide 5):** Live dashboard green state (vitals + 3D Holographic Body HUD + Daily Routine Prevention).
* **1:30 – 2:30 (Live Crisis Demo):** Click `[Trigger EVA Hypercapnia]` $\rightarrow$ Vitals spike $\rightarrow$ 3D body turns pulsing red $\rightarrow$ AI Doctor diagnoses Mode A citing *NASA-STD-3001 [V2 6004]*.
* **2:30 – 3:15 (Closed-Loop Recovery):** Check off the treatment boxes $\rightarrow$ Vitals and 3D body dynamically heal back to calm cyan in real time!
* **3:15 – 3:35 (Mode B Zero-Day Demo):** Show Mode B Certified Abstention + High-Risk Drug Lockout.
* **3:35 – 4:00 (Slides 6–7):** Dual-use Earth impact (rural telemedicine, Antarctic bases) & wrap up.

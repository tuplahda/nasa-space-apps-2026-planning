# Mission Medical Console — UI/UX Wireframe & Demo Flow

This document specifies the single-screen **NASA Level V Autonomous Medical Console** layout so the frontend team can build it cleanly with React + Tailwind CSS + Recharts.

---

## 1. Full-Screen Dashboard Layout (Single-Viewport Console)

```text
+--------------------------------------------------------------------------------------------------+
| [NASA A.R.E.S. MED]  Mission Day: FD 84 | Mars Transit  |  [!] EARTH COMMS DELAY: 18m 42s (AUTO) |
| Judge Simulator Controls: [Nominal] [1: CO2 Fault] [4: Solar SPE] [5: EVA Heat/DCS] [Speed: 30x] |
+--------------------------------------------------------------------------------------------------+
| LEFT COL (25% Width)      | CENTER COL (45% Width)                 | RIGHT COL (30% Width)       |
|                           |                                        |                             |
| CREW DIGITAL TWINS (L1)   | LIVE TELEMETRY & BASELINE BANDS (L2)   | AUTONOMOUS RAG CMO (L3)     |
| +-----------------------+ | +------------------------------------+ | +-------------------------+ |
| | * CDR Maya Lin   [68] | | | Selected: CDR Maya Lin (IVA_REST)  | | | ALERT: HYPERCAPNIA      | |
| |   State: IVA_REST     | | | Context Gate: Adapted ug Baseline  | | | Citation: NASA-STD-3001 | |
| |   HR: 88 bpm (YLW)    | | |                                    | | | [V2 6004] / JSC-48522   | |
| +-----------------------+ | | [Chart 1: HR (bpm) & HRV (RMSSD)]  | | +-------------------------+ |
| |   PLT Alex Vance [12] | | |   --- Shaded Band: 52-68 bpm (ug)  | | | CLINICAL REASONING      | |
| |   State: ARED_EXERC   | | |                                    | | | HR 88 bpm in IVA_REST + | |
| |   HR: 154 bpm (GRN)   | | | [Chart 2: SBP/DBP & SpO2 (%)]      | | | Cabin ppCO2 3.8 mmHg.   | |
| +-----------------------+ | |                                    | | +-------------------------+ |
| |   DR. Rossi      [18] | | | [Chart 3: Core Temp (C) & RR]      | | | CHeCS MEDICATION & WARN | |
| |   State: SLEEP        | | |   --- Space Fever Norm: 37.4-38.0C | | | + Ibuprofen 400mg (CMP) | |
| +-----------------------+ | +------------------------------------+ | | ! NO OPIOIDS (Resp Dep) | |
|                           |                                        | +-------------------------+ |
| HABITAT & DONKI SENSORS   | POINT-OF-CARE DIAGNOSTICS & SYMPTOMS   | | CLOSED-LOOP CHECKLIST   | |
| +-----------------------+ | +------------------------------------+ | | [x] 1. Relocate & Fan   | |
| | Cabin ppCO2: 3.8 mmHg | | | Symptom Log: "Throbbing frontal    | | | [x] 2. CAMRAS Scrubber  | |
| | Cabin ppO2:  148 mmHg | | | headache, mild facial flushing..." | | | [ ] 3. Give Ibuprofen   | |
| | DONKI SEP:   NOMINAL  | | | OCT RNFL: 98 um | ALC: 2050 /uL    | | | [ ] 4. Diet RQ -> 0.85  | |
| | BFO Dose: 0.05 mSv/hr | | +------------------------------------+ | +-------------------------+ |
+--------------------------------------------------------------------------------------------------+
```

---

## 2. Key Visual Features Judges Will Notice Immediately

1. **Microgravity vs. Earth Baseline Toggle on Charts:**
   - Every chart shows a green shaded **"Adapted $\mu g$ Safe Zone"** alongside a dotted **"Earth $1g$ Norm"** line so judges visually see *why* space medicine requires specialized software.
2. **Context-Aware Activity Badge:**
   - Shows `PLT Alex Vance` exercising on ARED at `HR = 154 bpm` and `CBT = 39.2 °C` in **GREEN (Nominal Exercise Context)** right next to `CDR Maya Lin` at `HR = 88 bpm` in **YELLOW (IVA Rest Hypercapnia Anomaly)**.
3. **Interactive Closed-Loop Checklist:**
   - Checking off items in the right column visibly triggers a **Recovery Mode badge** on the center charts and decrements the **CHeCS Medication Inventory Counter**.
4. **Queued Store-and-Forward Earth Packet Modal:**
   - A button in the top-right (`[Queued Downlink Packet: 18m 42s]`) opens the structured JSON summary ready for asynchronous transmission to Houston Mission Control.

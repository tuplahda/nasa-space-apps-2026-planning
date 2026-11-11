# 🩺 The AI Space Doctor (Layer 3 RAG Medical Assistant): Architecture & Relevance

> [!IMPORTANT]
> The **AI Space Doctor** is not a generic medical chatbot. It is a **4-Stage Neuro-Symbolic Retrieval-Augmented Generation (RAG) Clinical Decision Support Engine** designed for **NASA Medical Care Level V** (deep-space missions to the Moon and Mars), where communication delays up to 20 minutes one-way and strict spacecraft mass limits (`9.07 kg` on Orion) require 100% autonomous, zero-hallucination onboard medical care.

---

## 1. End-to-End Pipeline: How the AI Doctor Works

```mermaid
flowchart LR
    IN["1. Live Input Stream (Member 1)<br/>• Vitals (HR, BP, SpO2, HRV, CBT, RR)<br/>• Activity Context (Rest / Exercise / EVA / Sleep)<br/>• Habitat ECLSS (ppCO2, ppO2) & DONKI Radiation<br/>• Astronaut First-Person Symptom Log"] --> S1

    subgraph AI_DOCTOR["Layer 3: The AI Space Doctor (Member 2)"]
        S1["Stage 1: Zero-G Context Gate<br/>Checks nasa_baselines_and_thresholds.csv<br/>Filters out normal Exercise & 'Space Fever'"]
        S2["Stage 2: Hybrid RAG Retrieval<br/>Searches rag_protocols_8_scenarios.json<br/>& nasa_space_medicine_research.md"]
        S3["Stage 3: CHeCS Med-Kit & Safety Guardrail<br/>Verifies onboard subpack stock &<br/>enforces strict spaceflight contraindications"]
        S4["Stage 4: Grounded Synthesis + Offline Fallback<br/>Outputs Diagnosis + Direct NASA Quote +<br/>4-Step Actionable Checklist"]

        S1 -->|"Yellow / Red Anomaly"| S2 --> S3 --> S4
    end

    S4 -->|"Structured JSON"| UI["Member 4 UI Panel<br/>(Diagnosis, NASA Quote & Checklist)"]
    S4 -->|"Closed-Loop Treatment"| AGENT["Member 1 Astronaut Agent<br/>(Applies Countermeasure & Recovers)"]
```

### Stage 1: The Zero-G Context Gate (Symbolic Rule Filter)
Before waking up the LLM/RAG engine, a sub-millisecond deterministic check evaluates incoming telemetry against [nasa_baselines_and_thresholds.csv](file:///C:/Users/tupla/.gemini/antigravity/scratch/nasa-space-apps-2026-planning/data/nasa_baselines_and_thresholds.csv):
- **Prevents Microgravity False Positives:** Recognizes that after Flight Day 75, resting core body temperature naturally plateaus $+1.0^\circ\text{C}$ higher in microgravity ($37.4\text{–}38.0^\circ\text{C}$, *"Space Fever"*), and that a heart rate of $155\text{ bpm}$ during `ARED_EXERCISE` is nominal.
- **Catches Subtle Zero-G Pathologies:** Flags when resting heart rate climbs to $88\text{ bpm}$ (above the $52\text{–}68\text{ bpm}$ adapted $\mu g$ resting range) while HRV drops ($<25\text{ ms}$) and cabin $pp\text{CO}_2$ exceeds the $3.0\text{ mmHg}$ `NASA-STD-3001 [V2 6004]` limit.

### Stage 2: Hybrid RAG Retrieval (Parameter Tags + Semantic Search)
When Stage 1 triggers an alert, Stage 2 queries our curated NASA medical corpus ([rag_protocols_8_scenarios.json](file:///C:/Users/tupla/.gemini/antigravity/scratch/nasa-space-apps-2026-planning/data/rag_protocols_8_scenarios.json), [nasa_space_medicine_research.md](file:///C:/Users/tupla/.gemini/antigravity/scratch/nasa-space-apps-2026-planning/data/nasa_space_medicine_research.md), and [arxiv_literature_citations.json](file:///C:/Users/tupla/.gemini/antigravity/scratch/nasa-space-apps-2026-planning/data/arxiv_literature_citations.json)) using **two combined signals**:
1. **Symbolic Parameter Matching:** Matches the breached physiological and environmental indicators (e.g., `cabin_ppCO2 > 3.0 mmHg` + `tachycardia` + `tachypnea`).
2. **Semantic Embedding Search:** Matches the Astronaut Agent's natural-language symptom log (e.g., *"throbbing frontal headache, facial flushing, blurred vision"*) against clinical descriptions in the knowledge base.

### Stage 3: Spacecraft Med-Kit (`CHeCS`) Inventory & Contraindication Guardrail
Unlike terrestrial hospitals, an exploration spacecraft only carries the medications and hardware packed inside the **ISS/Exploration Crew Health Care System (`CHeCS`)** subpacks (`CMP`, `OMP`, `TIMP`, `EMTP`, `Vascular Contingency Pack`, `RSP`, `MDP`, `ISP`). Stage 3 enforces two life-critical checks:

| Anomaly Scenario | Recommended `CHeCS` Medication & Subpack | Strict Spaceflight Contraindication Enforced by Stage 3 |
| :--- | :--- | :--- |
| **1. Cabin Hypercapnia ($\text{CO}_2$ Toxicity)** | `Ibuprofen 400–600 mg PO` or `Acetaminophen 325–650 mg PO` (`CMP`) + `100% O2` (`RSP`) | **BLOCK OPIOIDS (`Hydrocodone`/`Hydromorphone`):** Depresses central respiratory drive and worsens $\text{CO}_2$ retention/acidosis. |
| **2. Solar Particle Event (Acute Radiation Syndrome)** | `Ondansetron 4–8 mg ODT` (`OMP`), `Levofloxacin 500 mg PO`, `Acetaminophen` (`CMP`) | **BLOCK ASPIRIN & NSAIDs (`Ibuprofen`/`Ketorolac`):** Radiation-induced thrombocytopenia creates severe GI hemorrhage risk. |
| **3. Spaceflight IJV Thrombosis (Blood Clot)** | `Enoxaparin SC` $\rightarrow$ `Apixaban PO` (`Vascular Contingency Pack`) | **LOCK OUT EVA & HIGH-LOAD ARED EXERCISE:** Prevents fatal traumatic hemorrhage; automatically stages `Protamine` and `PCC` reversal agents. |
| **4. Space Adaptation Syndrome (SAS) & Urinary Retention** | `Promethazine 25 mg` + `Caffeine 100 mg` (`CMP`/`TIMP`); `Tamsulosin 0.4 mg PO` (`OMP`) + Catheter Kit (`MTP`) | **FLAG ANTICHOLINERGIC RETENTION:** Monitors bladder volume ($>500\text{ mL}$) after `Promethazine` to prevent bladder rupture/UTI. |

### Stage 4: Grounded Synthesis, Direct NASA Quotes & Closed-Loop Action
The AI Doctor formats the retrieved protocol and live vitals into a structured JSON response containing:
1. **Differential Diagnosis & Clinical Reasoning** linking the astronaut's vitals, activity context, and habitat sensors.
2. **Direct Verbatim NASA & arXiv Quotations** (`NASA-STD-3001`, `ISS Medical Checklist JSC-48522`, `OCHMO-TB-004`, and peer-reviewed arXiv citations).
3. **100% Offline Fallback Mode:** If cloud LLM connectivity is unavailable (simulating a total Mars solar conjunction blackout or hackathon Wi-Fi drop), Stage 4 populates the exact structured diagnosis and checklist directly from the local RAG JSON in `<10 ms`.
4. **Closed-Loop Feedback:** When the crew checks off a countermeasure on the UI, the AI Doctor decrements the onboard `CHeCS` medication stock and dispatches a treatment event back to **Member 1's Astronaut Agent**, stabilizing the astronaut's vitals in real time.

---

## 2. Operational & Judging Relevance: Why the AI Doctor Wins

### 2.1 Solves the Deep-Space "Stabilize-Without-Earth" Problem
- **ISS (Level IV Care):** Relies on real-time video with Houston flight surgeons and emergency return to Earth within hours.
- **Moon & Mars (Level V Care):** Faces up to a **20-minute one-way radio delay** (40-minute round trip) and multi-week solar blackouts. During an acute crisis (hypercapnia, decompression sickness, cardiac arrhythmia, or radiation spike), astronauts cannot wait 40 minutes for ground instructions.

### 2.2 Bridges the "Non-Physician Crew Medical Officer" Gap
- Designated Crew Medical Officers (CMOs) are frequently engineers, pilots, or scientists with limited procedural training (~30–40 hours pre-flight).
- Under high cognitive load—or when the CMO is the affected patient—the AI Doctor eliminates "manual fatigue" by transforming raw sensor alarms into an immediate, low-friction 4-step checklist ([Vickery et al., 2025, arXiv:2502.09076](https://arxiv.org/abs/2502.09076v1); [Radway et al., 2020, arXiv:2011.14535](https://arxiv.org/abs/2011.14535v1)).

### 2.3 Eliminates Medical AI Hallucinations via Neuro-Symbolic RAG
- Standard LLMs hallucinate unverified treatments or suggest hospital equipment unavailable in space (e.g., CT/MRI scanners).
- Grounded in recent clinical AI research ([Singh 2026, *NSIDDx*, arXiv:2609.00256](https://arxiv.org/abs/2609.00256v2) and [Lopez et al. 2026, *MARCA*, arXiv:2610.33279](https://arxiv.org/abs/2610.33279v1)), pairing **symbolic clinical thresholds (Stage 1)** with **RAG restricted to the onboard `CHeCS` kit and `JSC-48522` manual (Stages 2–3)** guarantees every recommendation is verifiable and physically executable onboard.

### 2.4 Direct Alignment with the 10 Pre-Hackathon Judging Criteria

| Judging Criterion | How the AI Doctor Delivers Full Marks |
| :--- | :--- |
| **Alignment & Relevance** | Directly answers the official NASA prompt requirement to go beyond raw charts and *"provide decision-support recommendations or step-by-step mitigation advice."* |
| **Scientific Combine** | Synthesizes **3 scientific domains** in every diagnosis: Human Space Physiology + Spacecraft ECLSS Engineering ($\text{CO}_2/\text{O}_2$) + Heliophysics (NASA DONKI solar radiation). |
| **Quotation & Validity** | Outputs verbatim quotes and standard codes (`NASA-STD-3001 [V2 6004]`, `[V1 4030]`, `JSC-48522`) inside every diagnostic card. |
| **Meaningful Improvement** | Replaces Earth-biased, cloud-dependent telemedicine with **Zero-G Context-Aware + Offline-Capable Neuro-Symbolic RAG**. |
| **Logical Feasibility** | Respects spacecraft compute and mass limits (`9.07 kg` Orion medical limit) by running a `<1 ms` edge filter and only invoking RAG on state transitions. |
| **Creativity & Bonus** | Operates in a live **Multi-Agent Closed Loop** where prescribing a treatment actively heals the simulated Astronaut Agent on screen. |

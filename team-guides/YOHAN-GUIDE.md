# 🩺 Yohan's Guide: Whole RAG System & Level V AI Medical Officer

* **Team Member:** **Yohan**
* **Assigned AI Tool:** **Antigravity (Gemini Pro)** *(Grounding, system guardrails, RAG architecture)*
* **Core Role:** **Backend Lead 2 — Anomaly Detection, 2-Mode Clinical Protocol & Grounded RAG Engine**
* **Files Owned:** `backend/services/ring_buffer.py`, `backend/services/anomaly_detector.py`, `backend/services/rag_engine.py`, `backend/routes/diagnose.py`

---

## 🎯 Your Mission
Build the **Autonomous NASA Level V Crew Medical Officer AI (RAG Agent)** that monitors Dheer's astronaut telemetry, evaluates anomalies against microgravity baselines using a JPL-compliant sliding ring buffer, and executes our **Strict 2-Mode Clinical Decision Protocol**:
* **MODE A:** KNOWN CONDITION (Confidence $\ge 0.75$) $\rightarrow$ Exact NASA protocol, verbatim quotation, CHeCS physical subpack formulary, and flight contraindications.
* **MODE B:** NOVEL / UNSEEN ANOMALY (Confidence $< 0.75$) $\rightarrow$ **Certified Abstention** (no hallucination) + 4-Step Zero-Day Space Medicine Protocol (ABC vital stabilization, Point-of-Care lab orders, drug lockout, in-flight RAG learning).

---

## 📂 Resources, Datasets & Artifacts You Need to Access

| Resource | Path | How You Use It |
| :--- | :--- | :--- |
| **Expanded RAG Protocols (40)** | [`data/rag_protocols_expanded.json`](../data/rag_protocols_expanded.json) | **PRIMARY:** 8 spaceflight scenarios (with `layer1_equations`) + 32 NASA Space Medicine CPGs (`CPG-01`–`CPG-32`) as pre-processed RAG chunks. |
| **CHeCS Formulary (54 Meds)** | [`data/checs_formulary.json`](../data/checs_formulary.json) | Pre-processed ISS CHeCS subpack formulary (`CMP`, `OMP`, `TIMP`, `EMTP`, `RSP`, `ISP`), doses, and hard lockout rules. |
| **NASA-STD-3001 Rules (26)** | [`data/nasa_std_3001_rules.json`](../data/nasa_std_3001_rules.json) | Verbatim clinical, radiation, atmospheric, and JSC 20584 SMAC threshold rules for `nasa_direct_quote`. |
| **Onboard Hardware Specs (5)** | [`data/onboard_hardware_specs.json`](../data/onboard_hardware_specs.json) | Point-of-care diagnostic specs (`i-STAT`, `Ultrasound-2`, `C2M2`, `PanOptic/OCT`, `Tempus Pro`) for Mode B lab orders. |
| **8 Legacy Scenarios** | [`data/rag_protocols_8_scenarios.json`](../data/rag_protocols_8_scenarios.json) | Original 8 scenarios (preserved for backward compatibility). |
| **NASA Research Notes** | [`data/nasa_space_medicine_research.md`](../data/nasa_space_medicine_research.md) | Clinical evidence, ISS medical checklist excerpts, and CHeCS formulary notes. |
| **Microgravity Thresholds** | [`data/nasa_baselines_and_thresholds.json`](../data/nasa_baselines_and_thresholds.json) | Threshold numbers used by your edge anomaly detector. |
| **arXiv Citations** | [`data/arxiv_literature_citations.json`](../data/arxiv_literature_citations.json) | Academic papers to cite for AI and space medicine validation. |
| **Clinical Protocol Spec** | [`artifacts/clinical_decision_protocol_2_modes.md`](../artifacts/clinical_decision_protocol_2_modes.md) | **MUST READ:** Exact JSON schema and clinical rules for Mode A vs Mode B. |
| **Safety Guardrails** | [`artifacts/security_and_safety_guardrails.md`](../artifacts/security_and_safety_guardrails.md) | Deterministic fallback rules, ring buffer specifications, anti-hallucination. |

---

## 🛰️ Handling the Upcoming NASA Private Dataset (Room for Improvement)

> [!IMPORTANT]
> **When NASA's official private dataset drops in ~24 hours:**
> 1. If NASA includes new clinical case studies or risk matrices, place the text/JSON files in `data/nasa_official_protocols/`.
> 2. Build your RAG ingestion script (`rag_engine.py`) with a dynamic document loader that scans both `data/rag_protocols_8_scenarios.json` AND any new files in `data/nasa_official_protocols/`.
> 3. This ensures any new NASA guidelines are automatically indexed into your vector/keyword store without breaking your API!

---

## 🛠️ Step-by-Step Technical Tasks

### 1. Sliding Ring Buffer & SEU Filter (`backend/services/ring_buffer.py`)
* Fixed 60-slot pre-allocated buffer for each vital (HR, BP, $\text{SpO}_2$, $\text{CO}_2$).
* Enforces JPL Power-of-Ten rules: no recursion, static loop bounds.
* Calculates 10-second rolling averages and slew-rates.
* Requires **3 consecutive abnormal ticks** before triggering an anomaly (filters single-tick cosmic ray bit-flips).

### 2. The 2-Mode RAG Engine (`backend/services/rag_engine.py`)
Loads our pre-processed, offline-ready datasets into your local vector/keyword store:
* [`data/rag_protocols_expanded.json`](../data/rag_protocols_expanded.json) (8 legacy scenarios + 32 `CPG-01`–`CPG-32` clinical protocols)
* [`data/checs_formulary.json`](../data/checs_formulary.json) (54 ISS CHeCS medications + spaceflight lockouts)
* [`data/nasa_std_3001_rules.json`](../data/nasa_std_3001_rules.json) (26 verbatim NASA-STD-3001 & JSC 20584 SMAC rules)
* [`data/onboard_hardware_specs.json`](../data/onboard_hardware_specs.json) (5 onboard diagnostic devices)
* [`data/nasa_space_medicine_research.md`](../data/nasa_space_medicine_research.md)

When an anomaly packet arrives, it queries the local knowledge base and computes a **Retrieval Confidence Score (0.0 to 1.0)**:

#### 🟢 MODE A: KNOWN CONDITION (Confidence $\ge 0.75$)
* Diagnose the condition strictly using the matched NASA protocol.
* Quote the exact NASA standard code and verbatim rule in `nasa_direct_quote`.
* Prescribe ONLY medications physically present in the 2023 ISS CHeCS subpacks (`CMP`, `OMP`, `TIMP`, `EMTP`, `VCP`).
* Enforce contraindications:
  * *NEVER prescribe opioids during Hypercapnia* (respiratory acidosis risk).
  * *NEVER prescribe NSAIDs/Aspirin during Acute Radiation Syndrome* (platelet depletion & bleeding risk).

#### 🔴 MODE B: UNSEEN / NOVEL ANOMALY (Confidence $< 0.75$)
* **Certified Abstention:** Do NOT guess or hallucinate an unverified disease name! Set `diagnosis: "Unclassified Novel Anomaly — Symptom-Based Stabilization Active"`.
* Execute the **4-Step Zero-Day Space Medicine Protocol**:
  1. **ABC Vital Stabilization:** 
     * If $\text{SpO}_2 < 92\%$: `100% O2 via Respiratory Support Pack (RSP)`.
     * If $\text{SBP} < 90\text{ mmHg}$: `0.9% Normal Saline IV via ISP` + supine Trendelenburg.
     * If Core Temp $> 38.5^\circ\text{C}$: Active cooling + `Acetaminophen via CMP`.
  2. **Onboard Point-of-Care Diagnostics (`MDP`):** Order immediate `i-STAT` blood gas/chemistry panel, `C2M2` Complete Blood Count (CBC), 12-lead ECG, or AI-guided Ultrasound.
  3. **"First, Do No Harm" Drug Lockout:** Explicitly lock out high-risk drug classes (`Opioids`, `NSAIDs`, `Anticoagulants`) in `safety_warning` until `i-STAT` and `CBC` labs confirm safety.
  4. **Priority Earth Uplink & In-Flight RAG Learning:** Flag `store_and_forward_priority: "EMERGENCY"` for Earth Flight Surgeons and set `save_candidate_to_local_rag: true` so the new pattern is saved to the onboard RAG database for future crew protection.

### 3. Triage API Endpoint (`POST /api/diagnose`)
Accepts the anomaly profile and returns the structured Mode A or Mode B JSON in under 50ms (deterministic fallback mode).

---

## 🤖 Master Prompt for Yohan (Copy into Antigravity)

```text
Act as a Biomedical Flight Surgeon and Senior AI Safety Engineer in Antigravity.
We are building the Anomaly Detection and RAG Medical Officer for NASA Space Apps project A.R.E.S. Med.

Implement the clinical services in `/backend`:
1. `services/ring_buffer.py`: A 60-second fixed-size ring buffer adhering to JPL Power-of-Ten rules (no unbounded growth, no recursion) that computes rolling averages, slew rates, and applies a 3-tick persistence debounce.
2. `services/anomaly_detector.py`: Evaluates incoming ticks against `data/nasa_baselines_and_thresholds.json` taking activity state (SLEEP, REST, EXERCISE, EVA) into account.
3. `services/rag_engine.py`: Loads `data/rag_protocols_8_scenarios.json` into an offline local retrieval engine with dynamic document loading for upcoming NASA datasets, and executes our strict 2-Mode Clinical Decision Protocol:
   - MODE A (Confidence >= 0.75): Known condition. Return exact NASA standard citation (NASA-STD-3001), verbatim quote, medications strictly from 2023 CHeCS subpacks (CMP, TIMP, etc.), and flight contraindications (e.g. lockout opioids during Hypercapnia).
   - MODE B (Confidence < 0.75): Unseen anomaly. Trigger Certified Abstention (do not hallucinate a disease name). Execute the 4-Step Zero-Day Space Medicine Protocol: 1) ABC Vital Stabilization (RSP O2, ISP Saline, cooling), 2) Point-of-Care Lab Orders (i-STAT, C2M2 CBC, Ultrasound), 3) Drug Lockout (Lock Opioids/NSAIDs), 4) Priority Earth Uplink + In-Flight RAG Learning flag.
4. Expose `POST /api/diagnose` returning the structured JSON payload. Ensure execution takes <50ms with a deterministic fallback mode for full offline reliability.
```

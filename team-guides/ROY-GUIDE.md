# 🛠️ Roy's Guide: Jack of All Trades (Backend/AI Assistant & Pitch Lead)

* **Team Member:** **Roy**
* **Assigned AI Tools:** **DeepSeek Harness, ChatGPT Plus**
* **Scope:** **Backend/AI Assistant + End-to-End System Integration + Pitch & Submission Lead**

---

## 🎯 Your Mission
You are the **force multiplier and system integrator** of the team. 
1. **Assist Dheer:** Help refine the Autonomous Astronaut Agent's physiological recovery math and NASA DONKI space weather connector.
2. **Assist Yohan:** Help test the RAG engine's Mode A vs. Mode B JSON outputs, contraindication rules, and point-of-care lab orders.
3. **End-to-End Integration:** Test the closed-loop handshake between Tivesh's frontend and the backend (triggering crises $\rightarrow$ RAG diagnosis $\rightarrow$ treatment recovery).
4. **Lead Presentation & Submission:** Own the official **7-Slide Deck**, **4-Minute Pitch Script**, backup demo recording, and NASA Mauritius submission portal.

---

## 📂 Resources, Datasets & Artifacts You Need to Access

| Resource | Path | How You Use It |
| :--- | :--- | :--- |
| **Submission Rules** | [`artifacts/official_hackathon_submission_rules.md`](../artifacts/official_hackathon_submission_rules.md) | **MUST READ:** 7-slide structure, 4-minute presentation limit, 11:30 AM Sunday deadline. |
| **2-Mode Clinical Spec** | [`artifacts/clinical_decision_protocol_2_modes.md`](../artifacts/clinical_decision_protocol_2_modes.md) | Verify medical accuracy of Mode A prescriptions and Mode B Zero-Day orders. |
| **Frontend Architecture** | [`artifacts/vanilla_frontend_architecture.md`](../artifacts/vanilla_frontend_architecture.md) | DOM IDs and API endpoints used for end-to-end integration testing. |
| **Safety Guardrails** | [`artifacts/security_and_safety_guardrails.md`](../artifacts/security_and_safety_guardrails.md) | Test deterministic fallback and anti-hallucination compliance. |
| **8 Emergency Protocols** | [`data/rag_protocols_8_scenarios.json`](../data/rag_protocols_8_scenarios.json) | Reference for verifying AI differential diagnoses. |

---

## 🛰️ Handling the Upcoming NASA Private Dataset (Room for Improvement)

> [!IMPORTANT]
> **When NASA's official private dataset drops in ~24 hours:**
> You will act as the data pipeline lead:
> 1. Review the newly released NASA challenge files (CSVs, images, or JSON schemas).
> 2. Determine which tables contain physiological baselines (pass to Dheer) and which contain clinical guidelines or cases (pass to Yohan).
> 3. Verify that the system still runs end-to-end with the new data loaded.

---

## ⏰ Critical Hackathon Deadlines (Mauritius Local Time)
* **Sunday, Nov 15 at 10:00 AM:** Internal code freeze.
* **Sunday, Nov 15 at 10:30 AM:** Record backup 60-second screen demo on a USB flash drive.
* **Sunday, Nov 15 at 11:30 AM (HARD DEADLINE):** Presentation materials (7 slides + demo video + working app) **MUST BE READY**.
* **Sunday, Nov 15 at 12:00 PM:** Live judging begins! (4-minute presentation strictly enforced).

---

## 🛠️ Your Exact Tasks Breakdown

### 1. Assisting Dheer (Autonomous Astronaut Agent)
* Verify that Dheer's simulator in `backend/services/astronaut_sim.py` has smooth mathematical recovery curves (washout equation) when treatments are applied (`POST /api/treatments/apply`).
* Ensure NASA DONKI space weather data has an air-gapped local JSON fallback so the app never fails without Wi-Fi.

### 2. Assisting Yohan (Whole RAG System)
* Test both clinical modes via curl/Postman:
  * **Mode A ($\text{Confidence} \ge 0.75$):** Does it return verbatim NASA standard quotes and physical CHeCS packs (`CMP`, `TIMP`)? Does it lock out opioids during Hypercapnia?
  * **Mode B ($\text{Confidence} < 0.75$):** Does it trigger Certified Abstention? Does it output ABC vital stabilization, point-of-care lab orders (`i-STAT`, `C2M2`), and the High-Risk Drug Lockout?

### 3. End-to-End Testing & System Integration
* Walk through the entire user journey:
  1. Open `frontend/index.html` in Chrome.
  2. Click `[Trigger EVA Hypercapnia]`.
  3. Verify Tivesh's $\text{CO}_2$ gauge and Heart Rate climb, and the 3D body lungs/brain flash red.
  4. Verify the medical panel pops up with Hypercapnia protocol and treatment checklist.
  5. Check off the boxes $\rightarrow$ verify that vitals and 3D body heal back to calm cyan.

### 4. Official 7-Slide Deck & 4-Minute Presentation Lead
* **Slide 1:** Team & Project Intro (Dheer, Yohan, Tivesh, Roy / *A.R.E.S. Med*)
* **Slide 2:** The Problem (20-min Mars comms blackout, life-support emergencies, no real-time Houston access)
* **Slide 3:** Your Solution (Closed-loop: Digital-Twin Agent $\rightarrow$ Edge Anomaly Engine $\rightarrow$ Grounded RAG Doctor)
* **Slide 4:** NASA Data & Resources (NASA DONKI API, NASA HRP Evidence Book, NASA-STD-3001, CHeCS Formulary)
* **Slide 5:** Project Demonstration *(The Live Prototype Demo)*
* **Slide 6:** Results, Impact & Limitations (What works, who benefits, remaining limitations)
* **Slide 7:** Conclusion & Next Steps (Deep-space & Earth telemedicine)

### 5. Rehearsing the 4-Minute Presentation (Timed to the Second!)
* **0:00 – 1:00 (Slides 1–4):** The Problem (20-min Mars radio lag) + Solution + NASA Datasets.
* **1:00 – 1:30 (Slide 5):** Live dashboard overview (vitals stream + 3D Holographic Body HUD + Daily Routine Prevention schedule).
* **1:30 – 2:30 (Live Crisis Demo):** Click `[Trigger EVA Hypercapnia]` $\rightarrow$ Vitals spike $\rightarrow$ 3D Body turns red $\rightarrow$ AI Doctor diagnoses Mode A citing *NASA-STD-3001 [V2 6004]*.
* **2:30 – 3:15 (Closed-Loop Recovery):** Check off the treatment steps $\rightarrow$ Vitals and 3D body dynamically heal back to green!
* **3:15 – 3:35 (Mode B Zero-Day Demo):** Show Mode B Certified Abstention + Drug Lockout.
* **3:35 – 4:00 (Slides 6–7):** Dual-use Earth impact (rural telemedicine, Antarctic bases) & wrap up.

---

## 🤖 Master Prompt for Roy (Copy into DeepSeek / ChatGPT)

```text
Act as a Full-Stack Systems Integrator and NASA Space Apps Pitch Strategist.
We are building A.R.E.S. Med for the NASA Space Apps Challenge.
Team Structure:
- Dheer: Autonomous Astronaut Agent (Python/FastAPI)
- Yohan: Whole RAG System & 2-Mode Clinical Decision Protocol (FastAPI)
- Tivesh: Entire Frontend (HTML/CSS/JS + 3D Body HUD)
- Roy (Me): Jack of all trades, assisting Dheer and Yohan, testing integration, and leading the pitch.

1. Write integration test scripts to verify the closed-loop recovery between Dheer's simulator (`POST /api/treatments/apply`) and Yohan's RAG endpoint (`POST /api/diagnose`).
2. Generate the slide content for our Official 7-Slide Deck adhering strictly to the NASA Mauritius guidelines (Title, Problem, Solution, NASA Data, Demo, Results/Impact, Conclusion).
3. Write a word-for-word, 4-minute presentation script synchronized with the live prototype demonstration (triggering a crisis, showing the 3D body HUD turn red, executing the NASA checklist, and watching the vitals recover).
4. Review the NASA CHeCS formulary and contraindication rules to ensure Yohan's RAG responses are 100% medically accurate.
```

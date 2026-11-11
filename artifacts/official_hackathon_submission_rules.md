# Official NASA Space Apps Submission & Presentation Rules (Mauritius)

This document contains the official requirements, judging criteria, presentation structure, and deadlines for the local NASA Space Apps Challenge event.

---

## ⏰ Critical Timeline (Mauritius Local Time)
- **Saturday, 14 November at 09:00:** NASA submission platform opens.
- **Sunday, 15 November at 11:30 (HARD INTERNAL DEADLINE):** All project and presentation materials (7-slide deck, demo video, working prototype, repo) **MUST BE READY**.
- **Sunday, 15 November at 12:00:** Live judging and team presentations begin.
- **Sunday, 15 November at 23:59:** NASA platform closes. *(Must click "Submit for Judging" — saving a draft is NOT submitting).*

---

## 🎤 Sunday Live Presentation Format (7 Minutes Total)
- **4 Minutes:** Project presentation and live demonstration (**Strictly enforced by timers**).
- **2 Minutes:** Judges' Q&A and feedback.
- **1 Minute:** Scoring and team transition.

> [!IMPORTANT]
> **Presentation Best Practices:**
> - Not every team member needs to speak. Pick 1 or 2 confident speakers (Roy + Dheer/Yohan) to present and drive the live demo cleanly.
> - **Zero-Internet Failsafe:** Do not rely on venue Wi-Fi! Run the demo 100% locally on localhost (`FastAPI` + `React`). Have a pre-recorded backup video ready in case of unexpected technical glitches.

---

## 📊 The 25-Point Judging Criteria (5 Points Each)
1. **Impact (5 pts):** The significance and potential benefits of the solution (deep space survival + remote Earth telemedicine).
2. **Creativity (5 pts):** Originality and innovation (Digital-twin simulation agents feeding an offline RAG Medical Officer during comms blackout).
3. **Validity (5 pts):** Scientific grounding, technical feasibility, and practicality (NASA HRP evidence baselines, JPL Power-of-Ten safety guardrails).
4. **Relevance (5 pts):** Alignment with challenge & **meaningful use of NASA data** (Direct integration of NASA DONKI, NASA-STD-3001, and HRP datasets).
5. **Presentation (5 pts):** Clarity, effectiveness, and polished demonstration.

---

## 📑 Mandatory 7-Slide Deck Structure (Official Template)
*Strict limit: Up to 7 slides total (including title).*

* **Slide 1 — Team & Project Introduction:**
  * Team name & members (Dheer, Yohan, Tivesh, Roy).
  * Project name: **A.R.E.S. Med** (*Autonomous Real-time Extraterrestrial Survival & Medical System*).
  * Selected Challenge: *Create Health Monitoring Software for Astronauts on Space Missions*.
  * 1-sentence value proposition.
* **Slide 2 — The Problem:**
  * The 20-minute deep-space communication lag to Mars.
  * Why Earth flight surgeons cannot help during sudden solar radiation or life-support crises.
  * Microgravity physiological deconditioning.
* **Slide 3 — Your Solution:**
  * Closed-loop 3-layer architecture: Astronaut Digital Twin $\rightarrow$ Edge Anomaly Detector $\rightarrow$ Grounded RAG Medical Officer.
  * Offline-first, autonomous clinical decision support.
* **Slide 4 — NASA Data & Resources (Crucial for Scoring):**
  * **NASA DONKI API:** Space weather / Solar Energetic Particle (SEP) events.
  * **NASA Human Research Program (HRP) Evidence Book:** Microgravity physiological baselines.
  * **NASA-STD-3001 & ISS Medical Operations Checklist:** Verified clinical emergency countermeasures.
  * *Explicitly show how this data drives the code, not just static logos.*
* **Slide 5 — Project Demonstration (The Core Score Booster):**
  * Live demo / UI screenshots of the dashboard in action.
  * The crisis injection flow: Trigger Hypercapnia/Solar Flare $\rightarrow$ vitals spike $\rightarrow$ RAG prescribes verified checklist.
* **Slide 6 — Results, Impact & Limitations:**
  * What was achieved in 48 hours (working end-to-end telemetry + RAG pipeline).
  * Who benefits: Astronauts on Artemis/Mars, Antarctic bases, remote Earth clinics.
  * Transparent limitations (e.g. simulated wearable sensors rather than physical medical hardware).
* **Slide 7 — Conclusion & Next Steps:**
  * Summary of value.
  * Roadmap: Wearable biosensor hardware integration, edge model quantisation (Edge TPU).

# New Scientific Literature from arXiv: Edge Astronaut Wearables, System-Level Autonomy Simulators & Neuro-Symbolic Clinical RAG

> [!NOTE]
> Retrieved using the `literature-search-arxiv` skill (`scripts/search_arxiv.py`). Please review arXiv's API Terms of Use at https://info.arxiv.org/help/api/index.html and verify individual paper licenses prior to redistribution.

---

## 🎯 Why This New Information Is Crucial for Our Project

Our first research document covered **NASA biological thresholds and medication checklists (`NASA-STD-3001`, `JSC-48522`)**, but it was missing **peer-reviewed AI, software engineering, and hardware feasibility literature** to justify *how* our software architecture works.

These **15 arXiv papers (including brand-new 2025–2026 research)** fill four critical gaps for the hackathon judges:
1. **Hardware & Edge Feasibility (`Layer 1 & 2`):** Proves how astronaut smart sensors extract cardiac features on ultra-low-power chips at the edge.
2. **Deep-Space Simulator Design (`Layer 1 Environment & Agent Coupling`):** Cites NASA JPL's **"System-Level Autonomy"** framework for coupling habitat life-support simulators with crew models.
3. **Why Neuro-Symbolic + Multi-Agent RAG Beats Standard Chatbots (`Layer 2 + Layer 3`):** Cites brand-new 2026 clinical AI research (*NSIDDx* and *MARCA*) proving that combining **symbolic rules (Layer 2)** + **RAG with drug-contraindication verification (Layer 3)** prevents medical hallucinations in low-resource/isolated settings.
4. **Low-Cognitive-Load UI for 22-Minute Mars Delays (`Frontend UI`):** Cites space human-factors papers on designing step-by-step procedural medical UIs for isolated operators.

---

## 1. On-Device Astronaut Wearable Sensors & Musculoskeletal Tech (Layer 1)

- **At the Edge of the Heart: ULP FPGA-Based CNN for On-Device Cardiac Feature Extraction in Smart Health Sensors for Astronauts** — Rahman et al. (2026) | https://arxiv.org/abs/2604.25799v1
  - *Quote/Insight for Judges:* Demonstrates real-time Seismocardiography (SCG) cardiac feature extraction directly on an ultra-low-power wearable FPGA (`Lattice iCE40UP5K`), proving the **Logical Feasibility** of our edge wearable telemetry architecture.
- **Space Physiology and Technology: Musculoskeletal Adaptations, Countermeasures, and Opportunities for Wearable Systems** — Khan, Varghese, Kassanos, Farina (2024) | https://arxiv.org/abs/2404.03363v2
  - *Quote/Insight for Judges:* Links wearable telemetry directly to closed-loop resistive exercise countermeasures in microgravity.

---

## 2. Deep-Space Autonomous Simulators & Telemetry Anomaly Detection (Layer 1 & Layer 2)

- **Modeling Considerations for Developing Deep Space Autonomous Spacecraft and Simulators** — Agia, Vila, Bandyopadhyay, Bayard (JPL / Caltech, 2024) | https://arxiv.org/abs/2401.11371v1
  - *Quote/Insight for Judges:* Defines **System-Level Autonomy** that jointly reasons across interconnected subsystems (spacecraft ECLSS life support + astronaut health) rather than isolated single-sensor rules.
- **Spacecraft Anomaly Detection with Attention Temporal Convolution Network** — Liu et al. (2023) | https://arxiv.org/abs/2303.06879v1
- **A Comparison of Deep Learning Architectures for Spacecraft Anomaly Detection** — Lakey, Schlippe (2024) | https://arxiv.org/abs/2403.12864v2
- **Operations for Autonomous Spacecraft** — Castano, Vaquero, Rossi, Verma (JPL, 2021) | https://arxiv.org/abs/2111.10970v1

---

## 3. Neuro-Symbolic & Multi-Agent Clinical RAG in Low-Resource Settings (Layer 3 AI Medical Officer)

- **NSIDDx: A Design Framework for Neuro-Symbolic, Practitioner-First Differential Diagnosis in Low-Resource Settings** — Singh (2026) | https://arxiv.org/abs/2609.00256v2
  - *Quote/Insight for Judges:* Shows why pure LLM+RAG can produce unverifiable outputs on rare/extreme presentations, and why our **Neuro-Symbolic Pipeline** (pairing deterministic `NASA-STD-3001` threshold rules in Layer 2 with RAG retrieval in Layer 3) ensures verifiable clinical reliability.
- **Multi-Agent Retrieval-Augmented Causality Assessment (MARCA) of Individual Case Safety Reports in Pharmacovigilance** — Lopez, Boccia, Sessa (2026) | https://arxiv.org/abs/2610.33279v1
  - *Quote/Insight for Judges:* Validates combining literature RAG with automated drug-contraindication verification (matching our `CHeCS` Contraindication Guardrail).
- **Unanimously Wrong: Certified Abstention from How Medical LLM Consensus Forms** — Wang, Wang, Yang (2026) | https://arxiv.org/abs/2610.07570v1
- **ClinAgent: A ReAct-Based Agent for Conversational Access to Clinical Trial Information** — Vaccarella et al. (2026) | https://arxiv.org/abs/2609.13860v1

---

## 4. Mars Radiation Modeling & Isolated Medical UI Design (Scenarios & Frontend)

- **Crewed Missions to Mars: Modeling the Impact of Astrophysical Charged Particles on Astronauts and Their Health** — Atri et al. (2022) | https://arxiv.org/abs/2208.00892v2
- **Modeling the effectiveness of radiation shielding materials for astronaut protection on Mars** — Gakis, Atri (2022) | https://arxiv.org/abs/2205.13786v3
- **Limitations in Predicting the Space Radiation Health Risk for Exploration Astronauts** — Chancellor, Blue, Cengel, Auñón-Chancellor (2017) | https://arxiv.org/abs/1710.07311v4
- **Evaluating the Effects of Situated and Embedded Visualisation in Augmented Reality Guidance for Isolated Medical Assistance** — Vickery et al. (2025) | https://arxiv.org/abs/2502.09076v1
- **Beyond LunAR: An augmented reality UI for deep-space exploration missions** — Radway et al. (2020) | https://arxiv.org/abs/2011.14535v1

# Day-1 Codebase Structure & Tech Stack Blueprint (For November 14)

When the hackathon begins on **November 14, 2026**, use this blueprint to initialize the application codebase in under 10 minutes.

---

## 1. Recommended Tech Stack

- **Backend (`backend/`):** **Python 3.11+ & FastAPI**
  - **Layer 1 Simulator:** Pure Python state machine + NumPy for exact physiological equations (`1 Hz` WebSocket or SSE stream).
  - **Layer 2 Edge Anomaly Engine:** Deterministic Python evaluator reading [`../data/nasa_baselines_and_thresholds.json`](../data/nasa_baselines_and_thresholds.json) + `httpx` client for live **NASA DONKI API** (`/DONKI/SEP` & `/DONKI/FLR`).
  - **Layer 3 Autonomous RAG:** Hybrid semantic + structured retriever over [`../data/rag_protocols_8_scenarios.json`](../data/rag_protocols_8_scenarios.json) with Gemini API + 100% offline deterministic fallback.
- **Frontend (`frontend/`):** **React (Vite + TypeScript) + Tailwind CSS + Recharts + Lucide Icons**
  - Dark-mode NASA Mission Medical Console rendering live telemetry bands, Earth vs. Microgravity baseline toggles, 1-click Crisis Injector buttons, and the Closed-Loop Countermeasure Checklist.

---

## 2. Target Application Folder Structure

```text
ares-med/
├── backend/
│   ├── data/
│   │   ├── nasa_baselines_and_thresholds.json   # Copy from planning repo /data
│   │   └── rag_protocols_8_scenarios.json       # Copy from planning repo /data
│   ├── layer1_agents/
│   │   ├── astronaut_agent.py                   # Stateful Digital Twin + Scenario Math
│   │   └── habitat_eclss.py                     # Coupled O2/CO2 (RQ 0.92 vs 0.85) & Radiation
│   ├── layer2_edge/
│   │   ├── anomaly_detector.py                  # Adapted ug Context Gate & Risk Scorer (0-100)
│   │   └── donki_client.py                      # Live NASA DONKI API Poller + Offline Cache
│   ├── layer3_rag/
│   │   ├── rag_engine.py                        # Hybrid Retriever + Gemini / Offline Synthesizer
│   │   └── checs_inventory.py                   # CHeCS Subpack Stock & Contraindication Guardrail
│   ├── main.py                                  # FastAPI Server (REST + WebSocket /ws/telemetry)
│   └── requirements.txt
└── frontend/
    ├── src/
    │   ├── components/
    │   │   ├── HeaderBar.tsx                    # Mission Clock, Comms Delay Badge, Crisis Buttons
    │   │   ├── CrewDigitalTwinList.tsx          # Left Column: 4 Astronaut Cards + Habitat Sensors
    │   │   ├── LiveTelemetryCharts.tsx          # Center Column: HR/HRV, BP/SpO2, CBT/RR w/ ug Bands
    │   │   ├── AutonomousRagPanel.tsx           # Right Column: Diagnosis, CHeCS Warn, Checklist
    │   │   └── EarthDownlinkModal.tsx           # Store-and-Forward Telemetry Packet Viewer
    │   ├── types/
    │   │   └── contracts.ts                     # Matches Contract A, B, and C JSON schemas
    │   └── App.tsx
    └── package.json
```

# A.R.E.S. Med frontend

Vanilla HTML/CSS/JavaScript, the existing GLB, and local Three.js r170/font dependencies. No build step or npm installation is required for the application.

## Run

From the repository root, use separate terminals:

```powershell
# Existing backend, in its usual Python environment:
python -m pip install -r backend/requirements.txt
python -m backend.main

# Frontend:
python -m http.server 5500 --bind 127.0.0.1 --directory frontend
```

Open http://localhost:5500/ . Use normal browser zoom (Ctrl+0) if this site was previously zoomed out. Do not open index.html through file://. Port 5500 is already allowed by the backend CORS configuration. An existing compatible API can be selected with `?api=http%3A%2F%2Flocalhost%3A8001`; HTTPS hosting needs an HTTPS backend and a permitted frontend origin.

The application now requires backend telemetry. There is no rehearsal selector, local-demo switch, automatic mock fallback, or production import of mock_data.js. Existing mock_data.js and demo_cases.json remain as legacy test fixtures only; mode=demo does not enable a local mode.

## Assessment insights

After an explicitly requested consultation, the right panel shows a plain-English explanation with the original technical assessment in an expandable section. `data/user_explanations.json` contains forty fixed project-authored descriptions, each linked to the original record in the repository's `data/rag_protocols_expanded.json`. These descriptions explain what a protocol covers; they are not clinically reviewed. Unknown protocol IDs show an unavailable message, and Mode B does not infer a disease. Technical API responses, medication instructions, safety rules, and PDF report content are unchanged.

The expandable evidence card records the backend's monitoring flags and supplied reference ranges, the crew's symptom report, and the source telemetry time. Missing or unreliable readings are not substituted. The incident timeline distinguishes browser requests from observed backend events. Before-and-after comparison freezes the actual reading snapshot at the action request and updates its latest column from received telemetry; it never labels a numeric change as medical improvement. Its heart-rate trace contains at most sixty observed samples, with gaps for unavailable readings. Final readings and incident history are available through the clickable crew member panel after the doctor panel resets, until the next incident or page reload. Open it with a click, Enter, or Space; close it with the close button or Escape. The history view uses the left column while open and restores the vital cards when closed. Completed plain-English assessment and evidence content clear from the doctor panel only after backend-confirmed nominal recovery. They are session observations, not a persistent medical audit or a confirmation that an illness was cured.

## Simulation and doctor consultation

Simulate Crisis calls `POST /api/scenarios/simulate-crisis` with `{ "streaming": true }`. The server chooses a random crisis and advances the astronaut agent. The frontend does not choose a named scenario or make a diagnosis request as part of this action.

Live vitals, the HR trace, threshold colors, organ status and telemetry-alert banner continue updating immediately from the incoming observations and edge assessment. These are monitoring alerts, not diagnoses.

Consult Doctor is a separate control. For a streaming incident it calls `POST /api/scenarios/analyze-crisis` with `{ "incident_id": current_id }`. This endpoint evaluates the server's current telemetry; it does not accept a client packet. The current backend enables it only after anomalous telemetry has appeared (awaiting_doctor). Layer 3 remains idle in this streaming flow until the operator request. The next assessment is delivered through the telemetry stream. Duplicate requests and results for obsolete incidents are guarded.

Outside the streaming-incident flow, the explicit consultation button uses `POST /api/diagnose` with the latest validated client snapshot, stripping dashboard-only fields and scenario hints. Legacy named-scenario backend paths may independently evaluate the doctor automatically; they were not changed. Unrequested legacy diagnoses are not displayed as button-requested consultations, and hiding them is not represented as server-side execution gating.

Consultation provenance displays request/receipt times in Mauritius time, the source telemetry timestamp, measured request-to-result latency, and a clear notice when newer telemetry has arrived. For streamed consultation, source time is taken from the first frame carrying its result and retained during recovery updates. A connection failure retains readings with disconnected/stale labels and pauses physiological motion; it never produces mock readings or assessments.

Checklist items remain timestamped session acknowledgements, not administration records. When returned, a backend-modeled physical action is submitted separately through `POST /api/treatments/apply` with its incident_id/action_id. Some Mode B incidents have no such action. Streaming incidents do not universally auto-recover: Reset Simulation explicitly uses the existing nominal scenario endpoint and waits for a real nominal snapshot, allowing another test without inventing a cure.

## Viewer and appearance

The GLB anatomy remains unchanged: BODY_SURFACE, BRAIN, HEART, LUNG_LEFT, LUNG_RIGHT, EYE_LEFT, EYE_RIGHT, OPTIC_NERVE_LEFT, OPTIC_NERVE_RIGHT. No skeleton or other anatomy was added.

The image reference informs navy surfaces, cyan/electric-blue wire detail and restrained lavender internal-organ accents. Amber/red retain monitoring severity meanings. Equal-color, equal-intensity left/right lights replace the previous unequal cyan/blue keys. Shared holographic materials deliberately suppress the eyes' realistic white/pupil vertex-color contrast; faint eyes and optic nerves retain their original position, dimensions and connections.

Brain and eye/optic-nerve layers have independent visibility and focus controls while sharing SANS-01 status. Heart, paired lungs and core have distinct targets. Selecting an organ smoothly interpolates camera position and OrbitControls target to its bounds, dims non-selected anatomy, preserves alert colors and pauses idle orbit. New selections replace pending transitions; manual orbit cancels them. Reset restores overview, both neuro-ocular layers, material presentation and idle-orbit preference. Ordinary pan/zoom limits and aspect-aware fitting remain controlled.

The overview camera is slightly elevated so the very faint horizontal elliptical scanner has a visible gridded interior. Its shader clips the grid to an ellipse; it stays attached to the anatomical root and cannot intercept selection. It hides during organ inspection and reduced-motion operation.

Idle rotation is 1.8 times its prior speed. Heartbeat and respiratory phases accumulate elapsed time at the latest valid observed rates: one cycle per 60/BPM and 60/respiration_rate seconds. Rates may change without resetting phase. The heart and lungs animate around their own centers, preserving placement; breathing expansion is restrained (maximum 1.8% lateral, 1.2% vertical, 2.3% depth). Missing/nonpositive rates, stale data after five seconds and reduced-motion preferences stop physiological motion instead of substituting a rate.

The original dashboard panel hierarchy is retained, with larger ordinary text (14px), larger vital values, stronger contrast, independent panel scrolling, tablet/mobile stacking and no fixed tiny-text scaling. Short desktop windows can scroll the page to preserve useful anatomy height. The model's lower cut edge is framed just above its bottom control panel.

## Changed files

- index.html: removed rehearsal/demo controls; explicit consultation, layer/focus controls, monitoring alert, assessment provenance, simulation reset.
- style.css: coordinated navy/cyan/lavender palette, readable typography, organ controls, responsive layouts and short-window scrolling.
- js/app.js: backend-only lifecycle, separate simulation/consultation, live alerts, freshness/provenance and incident guards.
- js/body_hud.js: holographic rendering, balanced lights, camera transitions, independent layers, elliptical scanner and telemetry animation.
- js/body_dynamics.js (new): testable phases, target grouping, material presentation and fitting calculations.
- js/medical_panel.js: clears stale citation tooltips when resetting a consultation.
- tests/frontend.test.mjs, tests/body_dynamics.test.mjs (new), tests/integration.mjs: relevant regression and real-server checks.

Backend and Blender/GLB files were not edited in this revision. No commit or push was made.

## Verification

22 automated frontend checks pass (17 console/loader/controller checks and five dynamics checks). These exercise strict payloads, missing data, source status, independent brain/eye visibility, actual GLB loader/picking/materials, camera centering and interrupted/reset transitions, organ-centered motion, phase/rate timing, stale/reduced-motion behavior, live pre-consultation alerts, duplicate requests, and obsolete incident results.

Real-server integration on an isolated instance passed local HTTP asset delivery, CORS, 1 Hz WebSocket/reconnect, named API compatibility, diagnosis fixtures, randomly selected streaming incidents, absence of a doctor result before consultation, Mode A/B after consultation, modeled recovery and stale/duplicate action rejection. The test resets its simulator to the original nominal state. Its previous assumption of automatic recovery for streaming Mode B was removed to match the actual backend contract.

Desktop Chrome screenshots were inspected at normal zoom. The actual hologram, scanner, layer/focus controls, selected-heart enlargement, surrounding-organ dimming and paused idle orbit were observed. A final layout/lighting refinement followed that inspection. Browser automation then stopped during refresh because it could not verify the current URL; mobile visual QA and final browser-console inspection remain unverified. Automated checks do not substitute for those visual checks.

Run with recent Node.js (24+), without npm:

```powershell
node frontend/tests/frontend.test.mjs
node frontend/tests/body_dynamics.test.mjs
node frontend/tests/assessment_insights.test.mjs
# Existing backend/frontend running; this changes test simulator state:
node frontend/tests/integration.mjs
# For a separate test backend, optionally set:
$env:ARES_TEST_API = "http://localhost:8001"
```

Use the existing backend's declared dependencies. The default port-8000 process returned a health error during this session, so live checks used an isolated port-8001 instance; the pre-existing port-8000 process was left untouched. Restart the existing backend in its intended environment if its API returns errors.

The technical verification subtitle is omitted; its supplied verification value and verified-citation availability remain explicit. Displayed time suffixes use MET as a label only; timestamp values, timezones, and calculations are unchanged. This simulation does not establish medical validation, treatment administration, Earth-message delivery or a persistent clinical audit.

# A.R.E.S. Med frontend

Uses the original HTML/CSS prototype. No build step, npm, framework, or new backend.

## Launch

From the repository root:

```powershell
python -m http.server 5500 --bind 127.0.0.1 --directory frontend
```

Open http://127.0.0.1:5500/ in a modern WebGL 2 browser. Do not use file://. Port 5500 is already allowed by the backend CORS configuration.

Explicit offline demo: http://127.0.0.1:5500/?mode=demo

Default API: http://localhost:8000. Override an existing compatible server with `?api=http%3A%2F%2F127.0.0.1%3A8000`. HTTPS hosting requires an HTTPS backend and a permitted origin.

Run the existing backend in its usual Python environment:

```powershell
python -m pip install -r backend/requirements.txt
python -m backend.main
```

## Files

Modified `index.html`, `style.css`, `js/body_hud.js`. Preserved prototype structure, IDs, color system and panel hierarchy. Corrected the broken stylesheet link. Replaced only the static anatomical SVG with the bounded real-model viewport and controls.

Created:
- `js/app.js`: application, source switching and clinical stream coordination.
- `js/telemetry.js`: packet validation, missing-value handling, activity-aware statuses, formatting and rolling 60-sample history/HR trace.
- `js/websocket.js`: validated WebSocket frames, duplicate/out-of-order suppression, stale detection, bounded 1-30s reconnect plus jitter, existing HTTP telemetry fallback.
- `js/scenarios.js`: actual backend API contracts and scenario aliases.
- `js/medical_panel.js`: Mode A/B/nominal rendering, source/citation handling, timestamped interactive checklist and explicit simulated recovery.
- `js/mock_data.js`: four offline scenarios, varying telemetry and local recovery.
- `data/baselines.json`: unchanged repository threshold snapshot; refresh when the source changes.
- `data/demo_cases.json`: repository sample packets and deterministic-engine response snapshots, always labeled as unverified demonstration assessments.
- `vendor/`: pinned Three.js r170, required addons, original Manrope/DM Mono fonts and licenses; no external runtime dependencies.
- `tests/frontend.test.mjs`, `tests/integration.mjs`: focused tests without npm. Node is only a developer test tool.

Reused `assets/models/ares_upper_body_hologram.glb` without modification. Left the older models/ assets untouched.

## Confirmed endpoints

| Endpoint | Use |
| --- | --- |
| `WS /ws/telemetry` | 1 Hz agent frames, edge assessment and available rag_diagnosis |
| `GET /api/telemetry/current` | HTTP fallback and fresh post-trigger snapshot |
| `POST /api/scenarios/trigger` | scenario: nominal, hypercapnia, solar_flare, zero_day |
| `POST /api/diagnose` | Strict TelemetryPacket fields; excludes broadcast-only fields and scenario/force-mode hints |
| `POST /api/treatments/apply` | treatment: li_oh_swap_and_o2 for hypercapnia; standard countermeasure protocol otherwise |
| `GET /api/simulation/state`, `GET /health` | Integration validation and original-scenario restoration |

The crisis button triggers the astronaut agent, then diagnoses the next matching snapshot. Subsequent streamed results follow the dynamically changing agent. Dropdown changes alone do not inject scenarios. UI solar maps to solar_flare; zero-day maps to zero_day.

## Anatomy

Actual GLB nodes: BODY_SURFACE, BRAIN, HEART, LUNG_LEFT, LUNG_RIGHT. Mesh resources have corresponding _Mesh names. No skeleton exists or is required. Export is already +Y up, +Z forward.

Viewer includes translucent skin, depth-safe visible internals, restrained edge/scanning effects, heartbeat/critical pulses, drag rotation, bounded zoom, idle orbit, reset, resize and disposal. Internal organs are raycast first, skin only as fallback. Labels also support keyboard selection. The window event `ares:organ-selected` supplies regionId/region_id, meshName/selected_mesh_name and available telemetry. Selecting an organ creates no diagnosis.

Backend edge statuses are authoritative. Local physiological presentation uses repository activity bands. Cumulative radiation exposure limits are not converted into invented instantaneous thresholds; missing assessment data stays unknown.

## Source and clinical behavior

Both the backend astronaut agent and local demo are synthetic. Footer labels SIMULATED TELEMETRY and distinguishes the sources. API connection/stale state is separate. After 5.5 seconds without initial backend packets, local demo starts while connection retries continue. Explicit local demo stops backend connections; Connect to backend resumes them.

Offline assessments are labeled repository example snapshots and remove NASA citations. Mode B abstains from naming a disease. Citation display requires a backend-supplied primary-source quote and HTTPS NASA link; otherwise unavailable. Returned source/verification, CHeCS, contraindication, stabilization, diagnostic-order and uplink fields retain their provenance. Project treatment content is labeled unverified; uplink metadata does not establish delivery.

Checkboxes record session acknowledgement with Mauritius timestamps, not administration. A separate recovery button enables after critical steps (or all steps when none is critical). It calls the existing simulator endpoint, blocks duplicate/concurrent submission, permits retry after failure, and requires fresh backend telemetry. Repeated copies of an action plan preserve acknowledgements; plan/scenario changes reset them. Audit is bounded and in memory only.

## Validation

All seven modules passed syntax checks. All 14 frontend tests passed, covering validation, strict payloads, activity baselines, edge authority, four demos, API errors, checklist retention/submission guards, Mode B/citation states, obsolete responses, reconnect/stale/polling, and actual GLB loading, hierarchy, upright bounds, materials, fitting and through-skin picking.

Real-server integration passed HTTP asset delivery, CORS for port 5500, 1 Hz WebSocket/reconnect, four scenario triggers, strict diagnosis requests, changing agent CO2, simulated recovery, and Mode A/B sample responses. Original scenario restored. git diff --check passed. No backend files changed; no commit or push.

With Node 24+ (no packages required):

```powershell
node --test frontend/tests/frontend.test.mjs
# Both existing servers must run; briefly changes simulator scenarios:
node frontend/tests/integration.mjs
```

## Limitations

Actual browser screenshots, WebGL rendering, pointer controls and responsive visual QA were not completed. Browser extension access was unavailable; native computer use stopped because it could not verify Chrome's current URL. Loader/material/raycast tests do not prove visual correctness or absence of browser-only errors.

The existing dependency-free backend fallback fails at TelemetryPacket.model_dump(). The tested FastAPI/Pydantic environment works with declared requirements. Backend code was left unchanged.

Explicit diagnosis of the backend nominal agent's full resting symptom sentence can return Mode B despite nominal edge telemetry. The frontend preserves that response. The offline nominal fixture uses the engine's accepted No symptoms phrase and returns nominal normally.

This prototype does not establish medical validation, treatment administration, Earth delivery, or a persistent clinical audit.

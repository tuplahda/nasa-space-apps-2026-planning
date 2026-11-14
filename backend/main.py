"""
A.R.E.S. Med — Autonomous Space Health Monitoring & Level V RAG Medical Officer Server.

Integrates:
1. Autonomous Astronaut Simulation Engine (Dheer) — 1Hz telemetry generator & state machine.
2. 60s Sliding Ring Buffer & Microgravity Anomaly Detector (Yohan).
3. Level V 2-Mode Clinical RAG Medical Officer (Yohan).
4. Live WebSocket streaming (/ws/telemetry) to Mission Control Console (Tivesh & Roy).
5. Closed-loop treatment recovery and scenario injection REST endpoints.

Complies strictly with JPL Power-of-Ten safety rules and contains zero emojis.
"""

import asyncio
from contextlib import asynccontextmanager
from functools import wraps
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import logging
import os
from threading import Event, RLock, Thread
from time import monotonic
from typing import Any, Dict, List
from urllib.parse import parse_qs, urlparse

os.environ.setdefault("SystemRoot", r"C:\Windows")

from backend.models.telemetry import AnomalyAssessment, DEMO_ASTRONAUT_ID, TelemetryPacket
from backend.routes.diagnose import (
    FASTAPI_AVAILABLE,
    SWAGGER_DIAGNOSE_EXAMPLES,
    anomaly_detector,
    build_contract_b_response,
    execute_diagnosis_pipeline,
    rag_engine,
    router as diagnose_router,
)
from backend.services.astronaut_sim import NOMINAL_SYMPTOM_LOG, astronaut_sim
from backend.services.donki_service import donki_service

logger = logging.getLogger("ares_med.server")

ALLOWED_ORIGINS = [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost:5500",
    "http://127.0.0.1:5500",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]


class ConnectionManager:
    """Manages active WebSocket connections to Mission Control dashboards."""

    def __init__(self) -> None:
        self.active_connections: List[Any] = []

    async def connect(self, websocket: Any) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info("New dashboard connected to /ws/telemetry. Active: %d", len(self.active_connections))

    def disconnect(self, websocket: Any) -> None:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info("Dashboard disconnected. Active: %d", len(self.active_connections))

    async def broadcast(self, message: str) -> None:
        await asyncio.gather(*(self._send(connection, message)
                               for connection in list(self.active_connections)))

    async def _send(self, connection: Any, message: str) -> None:
        try:
            await asyncio.wait_for(connection.send_text(message), timeout=0.1)
        except Exception:
            self.disconnect(connection)
            try:
                await asyncio.wait_for(connection.close(code=1013), timeout=0.1)
            except Exception:
                pass


manager = ConnectionManager()


latest_telemetry: Dict[str, Any] | None = None
simulation_lock = RLock()
offline_simulation_lock = simulation_lock


def _simulation_locked(method):
    """Keep synchronous simulation operations atomic; never hold across an await."""
    @wraps(method)
    def locked(*args, **kwargs):
        with simulation_lock:
            return method(*args, **kwargs)
    return locked


@_simulation_locked
def run_simulation_command(action: Any, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Validate controls consistently across REST, WebSocket, and offline HTTP."""
    if action == "trigger_scenario":
        return astronaut_sim.trigger_scenario(payload.get("scenario") or payload.get("scenario_id"))
    if action == "apply_treatment":
        return astronaut_sim.apply_treatment(payload.get("treatment") or payload.get("action"))
    if action == "set_activity":
        return astronaut_sim.set_activity_state(payload.get("activity_state") or payload.get("activity"))
    return {"status": "error", "message": "Unknown simulation command."}


@_simulation_locked
def cure_simulation() -> Dict[str, Any]:
    """Apply the existing recovery alias under the shared state lock."""
    return astronaut_sim.cure_scenario()


def command_status(result: Dict[str, Any]) -> int:
    return 400 if result["status"] == "error" else 200


def simulation_state_snapshot() -> Dict[str, Any]:
    """Read state while the caller holds simulation_lock."""
    return {
        "astronaut_id": astronaut_sim.astronaut_id,
        "name": astronaut_sim.name,
        "activity_state": astronaut_sim.activity_state,
        "active_scenario": astronaut_sim.active_scenario,
        "is_recovering": astronaut_sim.is_recovering,
        "active_treatment": astronaut_sim.active_treatment,
        "scenario_progression": round(astronaut_sim.scenario_progression, 3),
        "tick_count": astronaut_sim.tick_count,
        "external_dataset_loaded": astronaut_sim.external_dataset_loaded,
    }


@_simulation_locked
def simulation_response(path: str):
    """Capture shared state atomically, then let callers serialize/send unlocked."""
    if path == "/health":
        return 200, {
            "status": "NOMINAL",
            "system": "A.R.E.S. Med Level V Clinical Engine & Simulation",
            "operation_mode": "100%_OFFLINE_AIR_GAPPED_READY",
            "active_astronaut": astronaut_sim.name,
            "activity_state": astronaut_sim.activity_state,
            "active_scenario": astronaut_sim.active_scenario,
        }
    if path == "/api/simulation/state":
        return 200, simulation_state_snapshot()
    if path in ("/api/telemetry/current", "/api/astronaut/status"):
        if latest_telemetry is None:
            return 503, {"message": "Telemetry is starting."}
        return 200, latest_telemetry
    if path == "/api/scenarios/list":
        return 200, astronaut_sim.list_available_scenarios()
    if path == "/api/simulation/schedule":
        return 200, astronaut_sim.get_routine_schedule()
    if path == "/api/space-weather":
        report = donki_service.get_space_weather(force_active_flare=(astronaut_sim.active_scenario == "solar_flare"))
        return 200, report.to_dict()
    return 404, {"title": "Not Found", "status": 404}


def recovery_diagnosis(
    recorded: Dict[str, Any], packet: TelemetryPacket, assessment: AnomalyAssessment, status: str,
    policy=None,
) -> Dict[str, Any]:
    """Carry recorded context through recovery while applying current safety lockouts."""
    # Copy on write: citations/quotes and protocol metadata remain read-only.
    context = dict(recorded)
    context["rag_metrics"] = dict(recorded["rag_metrics"])
    policy = policy if policy is not None else rag_engine._medication_safety_policy(packet)
    prescriptions, medications, contraindications = rag_engine._apply_deterministic_safety_filter(
        context.get("prescriptions", []), context.get("checs_medications", []),
        context.get("contraindications_locked", []), packet, assessment, policy,
    )
    blocked, _ = policy
    checklist = [step for step in context.get("action_checklist", [])
                 if not any(name in step["action"].lower() for name in blocked)]
    context.update({
        "recovery_status": status,
        "source_mode": "RECORDED_DIAGNOSIS_RECOVERY_CONTEXT",
        "execution_time_ms": 0.0,
        "triggering_vitals": assessment.triggering_vitals_summary,
        "organ_hud_status": assessment.organ_hud_status,
        "risk_score_0_100": assessment.risk_score_0_100,
        "readiness_score_0_100": assessment.readiness_score_0_100,
        "severity": assessment.nasa_priority_class,
        "clinical_reasoning": "Monitoring recovery from the recorded diagnosis using the current physiological assessment.",
        "prescriptions": prescriptions,
        "checs_medications": medications,
        "contraindications_locked": contraindications,
        "action_checklist": checklist,
        "action_plan": checklist,
        "autonomous_checklist": checklist,
        "hardware_and_diagnostics": [step for step in context.get("hardware_and_diagnostics", [])
                                     if not any(name in step.lower() for name in blocked)],
        "checs_subpack": " / ".join(sorted({item["checs_pack"] for item in prescriptions})) or "NONE",
    })
    context["rag_metrics"]["retrieval_latency_ms"] = 0.0
    return context


def refresh_treatment_options(decision, packet, assessment, policy=None) -> None:
    """Refresh a condition's countermeasures only when its lockout policy changes."""
    policy = policy if policy is not None else rag_engine._medication_safety_policy(packet)
    key = (rag_engine._knowledge_revision, decision["scenario_id"], tuple(policy[0]), tuple(policy[1]))
    if astronaut_sim._treatment_policy_key == key:
        return
    options = rag_engine.get_treatment_options(decision["scenario_id"], packet, assessment, policy)
    options.extend(str(step["action"]) for step in decision.get("action_checklist", []))
    astronaut_sim.set_treatment_options(options, policy_key=key)


@_simulation_locked
def advance_telemetry() -> Dict[str, Any]:
    """Advance the shared simulation and publish one snapshot for all readers."""
    global latest_telemetry
    was_recovering = astronaut_sim.is_recovering
    packet = astronaut_sim.step()
    payload = packet.model_dump()
    payload["simulation_incident"] = astronaut_sim.incident_id
    previous = latest_telemetry or {}
    same_incident = (previous.get("simulation_incident") == astronaut_sim.incident_id
                     and previous.get("astronaut_id") == packet.astronaut_id)

    # Keep the scenario label for the dashboard. The evaluator receives observations.
    packet.active_scenario_id = None
    packet.stateless_evaluation = False
    assessment = anomaly_detector.evaluate_packet(packet)
    payload["stateless_evaluation"] = False
    # Localized symptoms can be meaningful with nominal monitored vitals.
    has_symptoms = bool(packet.symptom_log.strip()) and packet.symptom_log != NOMINAL_SYMPTOM_LOG
    if has_symptoms and not astronaut_sim.is_recovering:
        assessment.trigger_rag_consultation = True
    recovery_monitoring = was_recovering or astronaut_sim.is_recovering
    status = "NONE"
    if recovery_monitoring:
        assessment.trigger_rag_consultation = False
        status = "ACTIVE" if astronaut_sim.is_recovering else "COMPLETE"
        if same_incident and previous.get("rag_diagnosis"):
            policy = rag_engine._medication_safety_policy(packet)
            payload["rag_diagnosis"] = recovery_diagnosis(previous["rag_diagnosis"], packet, assessment, status, policy)
            if astronaut_sim.is_recovering:
                refresh_treatment_options(payload["rag_diagnosis"], packet, assessment, policy)
    payload["recovery_status"] = status
    payload["anomaly_assessment"] = assessment.model_dump()
    payload["routine_schedule"] = astronaut_sim.get_routine_schedule(assessment.readiness_score_0_100)
    payload["mission_readiness_pct"] = assessment.readiness_score_0_100

    if assessment.trigger_rag_consultation:
        try:
            decision = rag_engine.diagnose(packet, assessment)
            payload["rag_diagnosis"] = decision
            if decision.get("mode") == "MODE_A_KNOWN_CONDITION":
                refresh_treatment_options(decision, packet, assessment)
            else:
                astronaut_sim.set_treatment_options([])
        except Exception:
            logger.exception("Diagnosis failed for a simulation tick")

    latest_telemetry = payload
    return payload


async def refresh_weather_loop() -> None:
    """Keep remote I/O in a worker so telemetry and HTTP reads use cached weather."""
    while True:
        try:
            await asyncio.to_thread(donki_service.refresh)
        except Exception:
            logger.exception("Weather refresh failed")
        await asyncio.sleep(1.0)


def run_offline_weather(stop: Event) -> None:
    while not stop.is_set():
        try:
            donki_service.refresh()
        except Exception:
            logger.exception("Weather refresh failed")
        stop.wait(1.0)


async def broadcast_telemetry_loop() -> None:
    """Broadcast one shared frame per second."""
    clock = asyncio.get_running_loop()
    await asyncio.sleep(1.0)
    while True:
        started = clock.time()
        try:
            payload = advance_telemetry()
            if manager.active_connections:
                await manager.broadcast(json.dumps(payload))
        except Exception:
            logger.exception("Simulation tick failed")
        await asyncio.sleep(max(0.0, 1.0 - (clock.time() - started)))


def run_offline_telemetry(stop: Event) -> None:
    """Advance the standard-library server without relying on dashboard polling."""
    while not stop.is_set():
        started = monotonic()
        try:
            advance_telemetry()
        except Exception:
            logger.exception("Simulation tick failed")
        stop.wait(max(0.0, 1.0 - (monotonic() - started)))


if FASTAPI_AVAILABLE:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Start background 1Hz simulation loop
        advance_telemetry()
        sim_task = asyncio.create_task(broadcast_telemetry_loop())
        weather_task = asyncio.create_task(refresh_weather_loop())
        try:
            yield
        finally:
            sim_task.cancel()
            weather_task.cancel()
            await asyncio.gather(sim_task, weather_task, return_exceptions=True)

    app = FastAPI(
        title="A.R.E.S. Med — Astronaut Rapid Evaluation Support & Medical System API",
        version="1.0.0",
        description=(
            "Astronaut Rapid Evaluation Support & Medical System (A.R.E.S. Med): "
            "Closed-Loop Multi-Agent Spaceflight Biotelemetry, 60s JPL Ring Buffer, "
            "Microgravity Edge Anomaly Detector, and 2-Mode Neuro-Symbolic RAG Engine."
        ),
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization"],
    )

    app.include_router(diagnose_router)

    @app.get("/", include_in_schema=False)
    async def root_redirect() -> RedirectResponse:
        """Redirect root URL to the offline API console (/docs)."""
        return RedirectResponse(url="/docs")

    @app.get("/docs", include_in_schema=False, response_class=HTMLResponse)
    @app.get("/redoc", include_in_schema=False, response_class=HTMLResponse)
    async def offline_api_docs() -> str:
        return render_offline_api_docs(include_openapi=True)

    @app.get("/health", tags=["System Health"])
    async def health_check() -> Dict[str, str]:
        """Health check endpoint for mission control readiness."""
        return simulation_response("/health")[1]

    @app.websocket("/ws/telemetry")
    async def websocket_telemetry_endpoint(websocket: WebSocket) -> None:
        """
        WebSocket stream emitting 1Hz TelemetryPackets to Tivesh's Mission Control HUD.
        Also accepts JSON commands to trigger scenarios or apply treatments.
        Commands support flat fields, a nested payload, or a separate command key.
        Every acknowledgement includes result. Activity replies retain the activity alias.
        """
        await manager.connect(websocket)
        try:
            status, snapshot = simulation_response("/api/telemetry/current")
            if status == 200:
                await websocket.send_text(json.dumps(snapshot))

            while True:
                data_text = await websocket.receive_text()
                try:
                    cmd = json.loads(data_text)
                    if not isinstance(cmd, dict):
                        raise ValueError("Expected a JSON object.")
                except ValueError as error:
                    await websocket.send_text(json.dumps({"type": "ERROR", "message": str(error)}))
                    continue

                action = cmd.get("command", cmd.get("action"))
                payload = cmd.get("payload", cmd)
                if not isinstance(payload, dict):
                    result = {"status": "error", "message": "Expected a JSON object payload."}
                else:
                    result = run_simulation_command(action, payload)
                reply = {"type": "COMMAND_ACK", "action": action, "result": result}
                if action == "set_activity" and result["status"] == "ok":
                    reply["activity"] = result["activity_state"]
                await websocket.send_text(json.dumps(reply))
        except WebSocketDisconnect:
            pass
        finally:
            manager.disconnect(websocket)

    @app.post("/api/scenarios/trigger", tags=["Simulation Control"])
    async def trigger_scenario_endpoint(payload: Dict[str, Any]) -> JSONResponse:
        """
        Trigger an acute emergency scenario in the astronaut simulation.
        Supported scenarios: 'nominal', 'hypercapnia', 'solar_flare', 'sans', 'decompression', 'dehydration'.
        """
        result = run_simulation_command("trigger_scenario", payload)
        return JSONResponse(result, status_code=command_status(result))

    @app.post("/api/treatments/apply", tags=["Simulation Control"])
    async def apply_treatment_endpoint(payload: Dict[str, Any]) -> JSONResponse:
        """Start recovery with a supported simulated countermeasure."""
        result = run_simulation_command("apply_treatment", payload)
        return JSONResponse(result, status_code=command_status(result))

    @app.post("/api/scenarios/cure", tags=["Simulation Control"])
    async def cure_scenario_endpoint() -> Dict[str, Any]:
        """Convenience alias for recovery initiation."""
        return cure_simulation()

    @app.get("/api/simulation/state", tags=["Simulation Control"])
    async def simulation_state_endpoint() -> Dict[str, Any]:
        """Retrieve current astronaut state machine telemetry parameters."""
        return simulation_response("/api/simulation/state")[1]

    @app.post("/api/simulation/activity", tags=["Simulation Control"])
    async def set_activity_endpoint(payload: Dict[str, Any]) -> JSONResponse:
        """Change activity to SLEEP, IVA_REST, ARED_EXERCISE, or EVA_SPACEWALK."""
        result = run_simulation_command("set_activity", payload)
        return JSONResponse(result, status_code=command_status(result))

    @app.get("/api/astronaut/status", tags=["Simulation Control"])
    @app.get("/api/telemetry/current", tags=["Simulation Control"])
    async def current_telemetry_endpoint() -> JSONResponse:
        """Read the latest simulation snapshot without advancing the clock."""
        status, snapshot = simulation_response("/api/telemetry/current")
        return JSONResponse(snapshot, status_code=status)

    @app.get("/api/scenarios/list", tags=["Simulation Control"])
    async def list_scenarios_endpoint() -> List[Dict[str, str]]:
        """List all available crisis trajectories and 24 scenario seeds."""
        return simulation_response("/api/scenarios/list")[1]

    @app.get("/api/simulation/schedule", tags=["Simulation Control"])
    async def simulation_schedule_endpoint() -> Dict[str, Any]:
        """Get daily flight operational schedule and active block."""
        return simulation_response("/api/simulation/schedule")[1]

    @app.get("/api/space-weather", tags=["Space Weather"])
    async def space_weather_endpoint() -> Dict[str, Any]:
        """Get live or air-gapped NASA DONKI space weather report."""
        return simulation_response("/api/space-weather")[1]

else:
    app = None  # type: ignore


OFFLINE_API_DOCS = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>A.R.E.S. Med — Offline API Console</title>
  <style>
    body { font-family: system-ui, -apple-system, sans-serif; background: #0b1120; color: #e2e8f0; margin: 0; padding: 24px; }
    .container { max-width: 1080px; margin: 0 auto; }
    .header { border-bottom: 1px solid #1e293b; padding-bottom: 16px; margin-bottom: 24px; display: flex; justify-content: space-between; align-items: center; }
    .badge { background: #10b981; color: #022c22; font-weight: 700; padding: 4px 10px; border-radius: 999px; font-size: 12px; }
    .endpoint { background: #111827; border: 1px solid #1e293b; border-radius: 8px; margin-bottom: 18px; padding: 16px; }
    .method-post { background: #2563eb; color: #fff; font-weight: 700; padding: 4px 10px; border-radius: 4px; font-size: 13px; margin-right: 10px; }
    .method-get { background: #059669; color: #fff; font-weight: 700; padding: 4px 10px; border-radius: 4px; font-size: 13px; margin-right: 10px; }
    .path { font-family: monospace; font-size: 15px; font-weight: 600; color: #93c5fd; }
    select, textarea, button { font-family: monospace; border-radius: 6px; border: 1px solid #334155; background: #020617; color: #f8fafc; padding: 10px; }
    textarea { width: 100%; height: 220px; box-sizing: border-box; margin-top: 10px; font-size: 13px; }
    button { background: #3b82f6; color: white; font-weight: 600; border: none; cursor: pointer; padding: 10px 18px; margin-top: 10px; margin-right: 8px; }
    button:hover { background: #2563eb; }
    pre { background: #020617; border: 1px solid #1e293b; padding: 14px; border-radius: 6px; overflow-x: auto; font-size: 13px; color: #a7f3d0; max-height: 480px; }
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <div>
        <h1 style="margin:0;font-size:24px;">A.R.E.S. Med — Astronaut Rapid Evaluation Support &amp; Medical System API</h1>
        <p style="margin:6px 0 0;color:#94a3b8;font-size:14px;">Simulation controls and diagnostic API examples</p>
        __OPENAPI_LINK__
      </div>
      <span class="badge">OFFLINE</span>
    </div>

    <div class="endpoint">
      <div><span class="method-post">POST</span><span class="path">/api/scenarios/trigger</span> — Inject Crisis Scenario</div>
      <p style="font-size:13px;color:#94a3b8;">Use these demo shortcuts or get the full scenario list.</p>
      <button onclick="sendPost('/api/scenarios/trigger', JSON.stringify({scenario: 'hypercapnia'}), 'scenarioResp')">Trigger Hypercapnia</button>
      <button onclick="sendPost('/api/scenarios/trigger', JSON.stringify({scenario: 'solar_flare'}), 'scenarioResp')">Trigger Solar Flare</button>
      <button onclick="sendPost('/api/scenarios/trigger', JSON.stringify({scenario: 'zero_day'}), 'scenarioResp')">Trigger Mode B Demo</button>
      <button onclick="sendPost('/api/scenarios/trigger', JSON.stringify({scenario: 'nominal'}), 'scenarioResp')">Reset to Nominal</button>
      <button onclick="sendGet('/api/scenarios/list', 'scenarioResp')">List Scenarios</button>
      <pre id="scenarioResp">// Scenario response will appear here...</pre>
    </div>

    <div class="endpoint">
      <div><span class="method-post">POST</span><span class="path">/api/scenarios/cure</span> - Start Simulated Recovery</div>
      <p style="font-size:13px;color:#94a3b8;">Initiate closed-loop biological recovery curve.</p>
      <button onclick="sendPost('/api/scenarios/cure', '{}', 'recoveryResp')">Start Simulated Recovery</button>
      <pre id="recoveryResp">// Recovery response will appear here...</pre>
    </div>

    <div class="endpoint">
      <div><span class="method-post">POST</span><span class="path">/api/diagnose</span> — Run Level V Clinical RAG Triage</div>
      <label style="font-size:13px;color:#cbd5e1;">Select Scenario Payload: </label>
      <select id="exampleSelect" onchange="loadExample(this.value)"></select>
      <textarea id="reqBody"></textarea>
      <div>
        <button onclick="sendPost('/api/diagnose', document.getElementById('reqBody').value)">Execute /api/diagnose</button>
      </div>
      <pre id="postResp">// Response will appear here...</pre>
    </div>

    <div class="endpoint">
      <div><span class="method-get">GET</span><span class="path">/api/simulation/state</span> — Current Simulation Status</div>
      <button onclick="sendGet('/api/simulation/state')">Inspect Simulation State</button>
      <button onclick="sendGet('/api/telemetry/current')">Get Current Telemetry Packet</button>
      <button onclick="sendGet('/api/space-weather')">Check Space Weather</button>
      <button onclick="sendGet('/api/diagnose/protocols')">Inspect RAG Protocols</button>
      <pre id="getResp">// Response will appear here...</pre>
    </div>
  </div>

  <script>
    const examples = __EXAMPLES_JSON__;
    function loadExample(key) {
      document.getElementById('reqBody').value = JSON.stringify(examples[key].value, null, 2);
    }
    const exampleSelect = document.getElementById('exampleSelect');
    for (const [key, example] of Object.entries(examples)) {
      exampleSelect.add(new Option(example.summary, key));
    }
    loadExample(exampleSelect.value);

    async function sendRequest(url, options, targetId) {
      const out = document.getElementById(targetId);
      out.textContent = 'Executing...';
      out.dataset.status = 'pending';
      try {
        const response = await fetch(url, options);
        const text = await response.text();
        let displayed = text;
        try { displayed = JSON.stringify(JSON.parse(text), null, 2); } catch {}
        out.dataset.status = response.ok ? 'success' : 'error';
        const failure = response.ok ? '' : 'Request failed. ';
        out.textContent = `${failure}HTTP ${response.status} ${response.statusText}\n${displayed}`;
      } catch (error) {
        out.dataset.status = 'error';
        out.textContent = `Request failed: ${error.message}`;
      }
    }

    async function sendPost(url, bodyStr, targetId = 'postResp') {
      return sendRequest(url, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: bodyStr || document.getElementById('reqBody').value
      }, targetId);
    }

    async function sendGet(url, targetId = 'getResp') {
      return sendRequest(url, {method: 'GET'}, targetId);
    }
  </script>
</body>
</html>
"""


def render_offline_api_docs(*, include_openapi: bool = False) -> str:
    examples = json.dumps(SWAGGER_DIAGNOSE_EXAMPLES).replace("<", "\\u003c")
    link = '<a href="/openapi.json" style="color:#93c5fd;">OpenAPI schema</a>' if include_openapi else ""
    return OFFLINE_API_DOCS.replace("__OPENAPI_LINK__", link).replace("__EXAMPLES_JSON__", examples)


class AresMedStdlibRequestHandler(BaseHTTPRequestHandler):
    """Zero-dependency standard-library HTTP handler for air-gapped operation."""

    def _send_json(self, status_code: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        origin = self.headers.get("Origin", "http://localhost:8000")
        if origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
        else:
            self.send_header("Access-Control-Allow-Origin", "http://localhost:8000")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, status_code: int, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send_json(200, {"status": "ok"})

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/docs", "/redoc"):
            self._send_html(200, render_offline_api_docs())
            return
        status, snapshot = simulation_response(parsed.path)
        if status != 404:
            self._send_json(status, snapshot)
            return
        if parsed.path == "/api/diagnose/buffer-status":
            qs = parse_qs(parsed.query)
            astro_id = qs.get("astronaut_id", [DEMO_ASTRONAUT_ID])[0]
            with simulation_lock:
                mgr = anomaly_detector.get_or_create_buffer(astro_id)
                snapshot = mgr.get_snapshot_summary()
            self._send_json(200, snapshot)
            return
        if parsed.path == "/api/diagnose/protocols":
            self._send_json(
                200,
                {
                    "total_protocols": len(rag_engine.protocols),
                    "scenario_ids": list(rag_engine.protocol_by_id.keys()),
                    "dynamic_docs_loaded": rag_engine.dynamic_docs_loaded,
                    "candidates_in_learning_queue": len(rag_engine.candidate_rag_buffer),
                    "checs_inventory": rag_engine.checs_inventory,
                },
            )
            return
        self._send_json(404, {"title": "Not Found", "status": 404})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
        try:
            data = json.loads(raw_body) if raw_body.strip() else {}
        except ValueError:
            self._send_json(400, {"title": "Invalid JSON payload", "status": 400})
            return

        if not isinstance(data, dict):
            self._send_json(400, {"status": "error", "message": "Expected a JSON object."})
            return

        action = {
            "/api/scenarios/trigger": "trigger_scenario",
            "/api/treatments/apply": "apply_treatment",
            "/api/simulation/activity": "set_activity",
        }.get(parsed.path)
        if action:
            result = run_simulation_command(action, data)
            self._send_json(command_status(result), result)
            return

        if parsed.path == "/api/scenarios/cure":
            result = cure_simulation()
            self._send_json(command_status(result), result)
            return

        if parsed.path == "/api/diagnose":
            try:
                with simulation_lock:
                    result = execute_diagnosis_pipeline(data)
                self._send_json(200, result)
            except (ValueError, TypeError):
                self._send_json(422, {"detail": [{"loc": ["body"], "type": "value_error",
                                                "msg": "Invalid telemetry payload."}]})
            except Exception as exc:
                self._send_json(
                    500,
                    {
                        "type": "https://ares-med.nasa.local/problems/diagnosis-failure",
                        "title": "Deterministic Fallback Triggered",
                        "status": 500,
                        "error_class": exc.__class__.__name__,
                    },
                )
            return

        if parsed.path == "/api/diagnose/evaluate-tick":
            try:
                packet = TelemetryPacket.model_validate(data)
            except (ValueError, TypeError):
                self._send_json(422, {"detail": [{"loc": ["body"], "type": "value_error",
                                                "msg": "Invalid telemetry payload."}]})
                return
            try:
                with simulation_lock:
                    packet.active_scenario_id = None
                    packet.stateless_evaluation = False
                    assessment = anomaly_detector.evaluate_packet(packet)
                    rag_out = rag_engine.diagnose(packet, assessment) if assessment.trigger_rag_consultation else None
                    result = build_contract_b_response(assessment, packet, rag_out)
                self._send_json(200, result)
            except Exception as error:
                logger.exception("Tick evaluation failed")
                self._send_json(500, {"title": "Tick evaluation failed", "status": 500,
                                      "error_class": error.__class__.__name__})
            return

        self._send_json(404, {"title": "Not Found", "status": 404})


def run_server(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Start the A.R.E.S. Med API server (uses uvicorn if installed, else stdlib HTTPServer)."""
    if FASTAPI_AVAILABLE:
        try:
            import uvicorn

            uvicorn.run("backend.main:app", host=host, port=port, reload=False)
            return
        except ImportError:
            pass
    server = HTTPServer((host, port), AresMedStdlibRequestHandler)
    print(f"[A.R.E.S. Med] Offline Server & API Console listening on http://{host}:{port}/docs")
    stop = Event()
    telemetry_thread = Thread(target=run_offline_telemetry, args=(stop,), daemon=True)
    weather_thread = Thread(target=run_offline_weather, args=(stop,), daemon=True)
    telemetry_thread.start()
    weather_thread.start()
    try:
        with server:
            server.serve_forever()
    finally:
        stop.set()
        telemetry_thread.join()
        weather_thread.join(timeout=2.0)


if __name__ == "__main__":
    run_server()

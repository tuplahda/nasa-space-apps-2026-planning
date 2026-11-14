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
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import logging
import os
from typing import Any, Dict, List, Optional, Set
from urllib.parse import parse_qs, urlparse

os.environ.setdefault("SystemRoot", r"C:\Windows")

from backend.models.telemetry import TelemetryPacket
from backend.routes.diagnose import (
    FASTAPI_AVAILABLE,
    SWAGGER_DIAGNOSE_EXAMPLES,
    anomaly_detector,
    build_contract_b_response,
    execute_diagnosis_pipeline,
    rag_engine,
    router as diagnose_router,
)
from backend.services.astronaut_sim import astronaut_sim
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
        for connection in list(self.active_connections):
            try:
                await connection.send_text(message)
            except Exception:
                self.disconnect(connection)


manager = ConnectionManager()


async def broadcast_telemetry_loop() -> None:
    """
    Background 1000ms loop:
    1. Steps the Autonomous Astronaut Simulation (Cmdr. Maya Lin).
    2. Feeds packet into Yohan's 60s Ring Buffer & Anomaly Detector.
    3. Broadcasts the full telemetry packet over WebSocket to Tivesh's HUD.
    """
    while True:
        try:
            packet = astronaut_sim.step()
            packet.stateless_evaluation = False

            # Feed tick into edge anomaly detector and 60-second sliding ring buffer
            assessment = anomaly_detector.evaluate_packet(packet)

            # Assemble payload for WebSocket broadcast
            p_dict = packet.model_dump()
            p_dict["anomaly_assessment"] = assessment.model_dump()
            p_dict["routine_schedule"] = astronaut_sim.get_routine_schedule()
            p_dict["mission_readiness_pct"] = assessment.readiness_score_0_100

            if assessment.trigger_rag_consultation:
                rag_out = rag_engine.diagnose(packet, assessment)
                p_dict["rag_diagnosis"] = (
                    rag_out.model_dump()
                    if hasattr(rag_out, "model_dump")
                    else rag_out
                )

            msg_json = json.dumps(p_dict)
            await manager.broadcast(msg_json)

        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("Simulation tick error: %s", exc)

        await asyncio.sleep(1.0)


if FASTAPI_AVAILABLE:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse, RedirectResponse

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Start background 1Hz simulation loop
        sim_task = asyncio.create_task(broadcast_telemetry_loop())
        yield
        # Graceful shutdown
        sim_task.cancel()
        try:
            await sim_task
        except asyncio.CancelledError:
            pass

    app = FastAPI(
        title="A.R.E.S. Med — Astronaut Rapid Evaluation Support & Medical System API",
        version="1.0.0",
        description=(
            "Astronaut Rapid Evaluation Support & Medical System (A.R.E.S. Med): "
            "Closed-Loop Multi-Agent Spaceflight Biotelemetry, 60s JPL Ring Buffer, "
            "Microgravity Edge Anomaly Detector, and 2-Mode Neuro-Symbolic RAG Engine."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
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
        """Redirect root URL directly to Swagger UI (/docs)."""
        return RedirectResponse(url="/docs")

    @app.get("/health", tags=["System Health"])
    async def health_check() -> Dict[str, str]:
        """Health check endpoint for mission control readiness."""
        return {
            "status": "NOMINAL",
            "system": "A.R.E.S. Med Level V Clinical Engine & Simulation",
            "operation_mode": "100%_OFFLINE_AIR_GAPPED_READY",
            "active_astronaut": astronaut_sim.name,
            "activity_state": astronaut_sim.activity_state,
            "active_scenario": astronaut_sim.active_scenario,
        }

    @app.websocket("/ws/telemetry")
    async def websocket_telemetry_endpoint(websocket: WebSocket) -> None:
        """
        WebSocket stream emitting 1Hz TelemetryPackets to Tivesh's Mission Control HUD.
        Also accepts JSON commands to trigger scenarios or apply treatments.
        """
        await manager.connect(websocket)
        try:
            # Emit immediate initial frame upon connection
            init_packet = astronaut_sim.step()
            init_dict = init_packet.model_dump()
            assessment = anomaly_detector.evaluate_packet(init_packet)
            init_dict["anomaly_assessment"] = assessment.model_dump()
            init_dict["routine_schedule"] = astronaut_sim.get_routine_schedule()
            init_dict["mission_readiness_pct"] = assessment.readiness_score_0_100
            await websocket.send_text(json.dumps(init_dict))

            while True:
                data_text = await websocket.receive_text()
                try:
                    cmd = json.loads(data_text)
                    action = cmd.get("action", "")
                    if action == "trigger_scenario":
                        scen = cmd.get("scenario", "nominal")
                        res = astronaut_sim.trigger_scenario(scen)
                        await websocket.send_text(json.dumps({"type": "COMMAND_ACK", "result": res}))
                    elif action == "apply_treatment":
                        treatment = cmd.get("treatment", "Standard Protocol")
                        res = astronaut_sim.apply_treatment(treatment)
                        await websocket.send_text(json.dumps({"type": "COMMAND_ACK", "result": res}))
                    elif action == "set_activity":
                        act = cmd.get("activity_state", "IVA_REST")
                        astronaut_sim.set_activity_state(act)
                        await websocket.send_text(json.dumps({"type": "COMMAND_ACK", "activity": astronaut_sim.activity_state}))
                except Exception as parse_err:
                    await websocket.send_text(json.dumps({"type": "ERROR", "message": str(parse_err)}))
        except WebSocketDisconnect:
            manager.disconnect(websocket)

    @app.post("/api/scenarios/trigger", tags=["Simulation Control"])
    async def trigger_scenario_endpoint(payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Trigger an acute emergency scenario in the astronaut simulation.
        Supported scenarios: 'nominal', 'hypercapnia', 'solar_flare', 'sans', 'decompression', 'dehydration'.
        """
        scen = payload.get("scenario") or payload.get("scenario_id") or "nominal"
        return astronaut_sim.trigger_scenario(scen)

    @app.post("/api/treatments/apply", tags=["Simulation Control"])
    async def apply_treatment_endpoint(payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Administer a countermeasure treatment, triggering smooth biological recovery.
        """
        treatment = (
            payload.get("treatment")
            or payload.get("action")
            or "Standard Emergency Countermeasure"
        )
        return astronaut_sim.apply_treatment(treatment)

    @app.post("/api/scenarios/cure", tags=["Simulation Control"])
    async def cure_scenario_endpoint() -> Dict[str, Any]:
        """Convenience alias for recovery initiation."""
        return astronaut_sim.cure_scenario()

    @app.get("/api/simulation/state", tags=["Simulation Control"])
    async def simulation_state_endpoint() -> Dict[str, Any]:
        """Retrieve current astronaut state machine telemetry parameters."""
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

    @app.post("/api/simulation/activity", tags=["Simulation Control"])
    async def set_activity_endpoint(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Change current activity state: SLEEP, IVA_REST, ARED_EXERCISE, EVA_SPACEWALK."""
        act = payload.get("activity_state") or payload.get("activity") or "IVA_REST"
        astronaut_sim.set_activity_state(act)
        return {"status": "ok", "activity_state": astronaut_sim.activity_state}

    @app.get("/api/telemetry/current", tags=["Simulation Control"])
    async def current_telemetry_endpoint() -> Dict[str, Any]:
        """Fetch the current instant telemetry packet over HTTP without WebSocket."""
        packet = astronaut_sim.step()
        packet.stateless_evaluation = False
        assessment = anomaly_detector.evaluate_packet(packet)
        p_dict = packet.model_dump()
        p_dict["anomaly_assessment"] = assessment.model_dump()
        return p_dict

    @app.get("/api/scenarios/list", tags=["Simulation Control"])
    async def list_scenarios_endpoint() -> List[Dict[str, str]]:
        """List all available crisis trajectories and 24 scenario seeds."""
        return astronaut_sim.list_available_scenarios()

    @app.get("/api/simulation/schedule", tags=["Simulation Control"])
    async def simulation_schedule_endpoint() -> Dict[str, Any]:
        """Get daily flight operational schedule and active block."""
        return astronaut_sim.get_routine_schedule()

    @app.get("/api/space-weather", tags=["Space Weather"])
    async def space_weather_endpoint() -> Dict[str, Any]:
        """Get live or air-gapped NASA DONKI space weather report."""
        rep = donki_service.get_space_weather(
            force_active_flare=(astronaut_sim.active_scenario == "solar_flare")
        )
        return rep.to_dict()

else:
    app = None  # type: ignore


OFFLINE_SWAGGER_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>A.R.E.S. Med — Swagger UI (Offline Air-Gapped Edition)</title>
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
        <p style="margin:6px 0 0;color:#94a3b8;font-size:14px;">Interactive OpenAPI Console • Simulation Engine • 60s Ring Buffer • 2-Mode Clinical RAG</p>
      </div>
      <span class="badge">OAS 3.1 • 100% OFFLINE</span>
    </div>

    <div class="endpoint">
      <div><span class="method-post">POST</span><span class="path">/api/scenarios/trigger</span> — Inject Crisis Scenario</div>
      <p style="font-size:13px;color:#94a3b8;">Trigger emergency scenario: nominal, hypercapnia, solar_flare, sans, decompression, dehydration.</p>
      <button onclick="sendPost('/api/scenarios/trigger', '{\\n  \\"scenario\\": \\"hypercapnia\\"\\n}')">Trigger Hypercapnia</button>
      <button onclick="sendPost('/api/scenarios/trigger', '{\\n  \\"scenario\\": \\"solar_flare\\"\\n}')">Trigger Solar Flare</button>
      <button onclick="sendPost('/api/scenarios/trigger', '{\\n  \\"scenario\\": \\"nominal\\"\\n}')">Reset to Nominal</button>
    </div>

    <div class="endpoint">
      <div><span class="method-post">POST</span><span class="path">/api/treatments/apply</span> — Administer Countermeasure</div>
      <p style="font-size:13px;color:#94a3b8;">Initiate closed-loop biological recovery curve.</p>
      <button onclick="sendPost('/api/treatments/apply', '{\\n  \\"treatment\\": \\"LiOH Canister Replacement & 100% O2 Flush\\"\\n}')">Apply Recovery Treatment</button>
    </div>

    <div class="endpoint">
      <div><span class="method-post">POST</span><span class="path">/api/diagnose</span> — Run Level V Clinical RAG Triage</div>
      <label style="font-size:13px;color:#cbd5e1;">Select Scenario Payload: </label>
      <select id="exampleSelect" onchange="loadExample(this.value)">
        <option value="eva_hypercapnia">1. EVA Hypercapnia (Mode A - Known Condition &gt;= 75%)</option>
        <option value="nominal_iva_rest">2. Nominal IVA Rest (Healthy Baseline)</option>
        <option value="zero_day_unseen">3. Unseen Zero-Day Anomaly (Mode B - Certified Abstention)</option>
        <option value="solar_particle_storm">4. Solar Particle Event (SPE Radiation Warning)</option>
        <option value="sans_neuro_ocular">5. SANS Neuro-Ocular Syndrome (Oct/Globe Changes)</option>
        <option value="hypoxia_decompression">6. Acute Cabin Decompression / Hypoxia</option>
      </select>
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
      <button onclick="sendGet('/api/diagnose/protocols')">Inspect 8 RAG Protocols</button>
      <pre id="getResp">// Response will appear here...</pre>
    </div>
  </div>

  <script>
    const examples = __EXAMPLES_JSON__;
    function loadExample(key) {
      document.getElementById('reqBody').value = JSON.stringify(examples[key], null, 2);
    }
    loadExample('eva_hypercapnia');

    async function sendPost(url, bodyStr) {
      const out = document.getElementById('postResp');
      out.textContent = 'Executing...';
      const t0 = performance.now();
      const res = await fetch(url, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: bodyStr || document.getElementById('reqBody').value
      });
      const data = await res.json();
      const dt = (performance.now() - t0).toFixed(2);
      out.textContent = `// HTTP ${res.status} (${dt} ms round-trip)\\n` + JSON.stringify(data, null, 2);
    }

    async function sendGet(url) {
      const out = document.getElementById('getResp');
      out.textContent = 'Fetching...';
      const res = await fetch(url);
      const data = await res.json();
      out.textContent = `// HTTP ${res.status} (${url})\\n` + JSON.stringify(data, null, 2);
    }
  </script>
</body>
</html>
"""


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
        if parsed.path in ("/", "/docs"):
            rendered = OFFLINE_SWAGGER_HTML.replace(
                "__EXAMPLES_JSON__", json.dumps(SWAGGER_DIAGNOSE_EXAMPLES)
            )
            self._send_html(200, rendered)
            return
        if parsed.path == "/health":
            self._send_json(
                200,
                {
                    "status": "NOMINAL",
                    "system": "A.R.E.S. Med Level V Clinical Engine & Simulation",
                    "operation_mode": "100%_OFFLINE_AIR_GAPPED_READY",
                    "active_astronaut": astronaut_sim.name,
                    "activity_state": astronaut_sim.activity_state,
                    "active_scenario": astronaut_sim.active_scenario,
                },
            )
            return
        if parsed.path == "/api/simulation/state":
            self._send_json(
                200,
                {
                    "astronaut_id": astronaut_sim.astronaut_id,
                    "name": astronaut_sim.name,
                    "activity_state": astronaut_sim.activity_state,
                    "active_scenario": astronaut_sim.active_scenario,
                    "is_recovering": astronaut_sim.is_recovering,
                    "active_treatment": astronaut_sim.active_treatment,
                    "scenario_progression": round(astronaut_sim.scenario_progression, 3),
                    "tick_count": astronaut_sim.tick_count,
                    "external_dataset_loaded": astronaut_sim.external_dataset_loaded,
                },
            )
            return
        if parsed.path == "/api/telemetry/current":
            packet = astronaut_sim.step()
            packet.stateless_evaluation = False
            assessment = anomaly_detector.evaluate_packet(packet)
            p_dict = packet.model_dump()
            p_dict["anomaly_assessment"] = assessment.model_dump()
            self._send_json(200, p_dict)
            return
        if parsed.path == "/api/scenarios/list":
            self._send_json(200, astronaut_sim.list_available_scenarios())
            return
        if parsed.path == "/api/simulation/schedule":
            self._send_json(200, astronaut_sim.get_routine_schedule())
            return
        if parsed.path == "/api/space-weather":
            rep = donki_service.get_space_weather(
                force_active_flare=(astronaut_sim.active_scenario == "solar_flare")
            )
            self._send_json(200, rep.to_dict())
            return
        if parsed.path == "/api/diagnose/buffer-status":
            qs = parse_qs(parsed.query)
            astro_id = qs.get("astronaut_id", ["ASTRO-01"])[0]
            mgr = anomaly_detector.get_or_create_buffer(astro_id)
            self._send_json(200, mgr.get_snapshot_summary())
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

        if parsed.path == "/api/scenarios/trigger":
            scen = data.get("scenario") or data.get("scenario_id") or "nominal"
            self._send_json(200, astronaut_sim.trigger_scenario(scen))
            return

        if parsed.path == "/api/treatments/apply":
            treatment = (
                data.get("treatment")
                or data.get("action")
                or "Standard Emergency Countermeasure"
            )
            self._send_json(200, astronaut_sim.apply_treatment(treatment))
            return

        if parsed.path == "/api/scenarios/cure":
            self._send_json(200, astronaut_sim.cure_scenario())
            return

        if parsed.path == "/api/simulation/activity":
            act = data.get("activity_state") or data.get("activity") or "IVA_REST"
            astronaut_sim.set_activity_state(act)
            self._send_json(200, {"status": "ok", "activity_state": astronaut_sim.activity_state})
            return

        if parsed.path == "/api/diagnose":
            try:
                result = execute_diagnosis_pipeline(data)
                self._send_json(200, result)
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
            packet = TelemetryPacket.model_validate(data)
            packet.stateless_evaluation = False
            assessment = anomaly_detector.evaluate_packet(packet)
            rag_out = (
                rag_engine.diagnose(packet, assessment)
                if assessment.trigger_rag_consultation
                else None
            )
            self._send_json(200, build_contract_b_response(assessment, packet, rag_out))
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
    print(f"[A.R.E.S. Med] Offline Server & Swagger UI listening on http://{host}:{port}/docs")
    server.serve_forever()


if __name__ == "__main__":
    run_server()

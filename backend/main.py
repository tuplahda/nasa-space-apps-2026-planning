"""
A.R.E.S. Med — Autonomous Space Health Monitoring & Level V RAG Medical Officer Server.

Mounts Yohan's Clinical Triage & RAG endpoints (`/api/diagnose`) and provides:
1. Full FastAPI + Swagger UI (`http://127.0.0.1:8000/docs`) when run with FastAPI/Uvicorn.
2. Built-in zero-dependency HTTP + Interactive Swagger Tester fallback (`python -m backend.main`)
   using Python's standard library `http.server` so `/docs` works even in air-gapped stdlib mode.
"""

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from typing import Any, Dict
from urllib.parse import parse_qs, urlparse

os.environ.setdefault("SystemRoot", r"C:\Windows")

from backend.models.telemetry import TelemetryPacket
from backend.routes.diagnose import (
    FASTAPI_AVAILABLE,
    SWAGGER_DIAGNOSE_EXAMPLES,
    anomaly_detector,
    execute_diagnosis_pipeline,
    rag_engine,
    router as diagnose_router,
)

ALLOWED_ORIGINS = [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost:5500",
    "http://127.0.0.1:5500",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

if FASTAPI_AVAILABLE:
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import RedirectResponse

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
        """Redirect root URL directly to Swagger UI (`/docs`)."""
        return RedirectResponse(url="/docs")

    @app.get("/health", tags=["System Health"])
    async def health_check() -> Dict[str, str]:
        """Health check endpoint for local mission control readiness."""
        return {
            "status": "NOMINAL",
            "system": "A.R.E.S. Med Level V Clinical Engine",
            "operation_mode": "100%_OFFLINE_AIR_GAPPED_READY",
        }
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
        <p style="margin:6px 0 0;color:#94a3b8;font-size:14px;">Interactive OpenAPI / Swagger Console • 60s JPL Ring Buffer • 2-Mode Neuro-Symbolic RAG Engine</p>
      </div>
      <span class="badge">OAS 3.1 • 100% OFFLINE</span>
    </div>

    <div class="endpoint">
      <div><span class="method-post">POST</span><span class="path">/api/diagnose</span> — Execute 2-Mode Clinical Decision Protocol (&lt;50ms)</div>
      <div style="margin-top:12px;">
        <label style="font-size:13px;color:#94a3b8;">Select Example Preset: </label>
        <select id="presetSelect" onchange="loadPreset()"></select>
      </div>
      <textarea id="reqBody"></textarea>
      <div>
        <button onclick="sendPost('/api/diagnose')">Execute POST /api/diagnose</button>
        <button style="background:#4f46e5;" onclick="sendPost('/api/diagnose/evaluate-tick')">Execute POST /api/diagnose/evaluate-tick (Stateful 3-Tick Debounce)</button>
      </div>
      <h4 style="margin:14px 0 6px;color:#cbd5e1;">Response Payload:</h4>
      <pre id="postResp">Click "Execute POST /api/diagnose" to inspect the Mode A or Mode B clinical response...</pre>
    </div>

    <div class="endpoint">
      <div><span class="method-get">GET</span><span class="path">/api/diagnose/protocols</span> &amp; <span class="path">/api/diagnose/buffer-status</span></div>
      <button style="background:#059669;" onclick="sendGet('/api/diagnose/protocols')">Execute GET /api/diagnose/protocols</button>
      <button style="background:#059669;" onclick="sendGet('/api/diagnose/buffer-status?astronaut_id=ASTRO-01')">Execute GET /api/diagnose/buffer-status</button>
      <button style="background:#059669;" onclick="sendGet('/health')">Execute GET /health</button>
      <pre id="getResp">Click any GET button above...</pre>
    </div>
  </div>
  <script>
    const EXAMPLES = __EXAMPLES_JSON__;
    const sel = document.getElementById('presetSelect');
    Object.keys(EXAMPLES).forEach(k => {
      const opt = document.createElement('option');
      opt.value = k;
      opt.textContent = EXAMPLES[k].summary;
      sel.appendChild(opt);
    });
    function loadPreset() {
      const k = sel.value;
      document.getElementById('reqBody').value = JSON.stringify(EXAMPLES[k].value, null, 2);
    }
    loadPreset();
    async function sendPost(url) {
      const out = document.getElementById('postResp');
      out.textContent = 'Executing...';
      const t0 = performance.now();
      const res = await fetch(url, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: document.getElementById('reqBody').value });
      const data = await res.json();
      const dt = (performance.now() - t0).toFixed(2);
      out.textContent = `// HTTP ${res.status} (${dt} ms round-trip)\\n` + JSON.stringify(data, null, 2);
    }
    async function sendGet(url) {
      const out = document.getElementById('getResp');
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
                    "system": "A.R.E.S. Med Level V Clinical Engine",
                    "operation_mode": "100%_OFFLINE_AIR_GAPPED_READY",
                },
            )
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
            self._send_json(
                200,
                {"assessment": assessment.model_dump(), "rag_consultation": rag_out},
            )
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
    print(f"[A.R.E.S. Med] Offline Level V RAG Server & Swagger UI listening on http://{host}:{port}/docs")
    server.serve_forever()


if __name__ == "__main__":
    run_server()

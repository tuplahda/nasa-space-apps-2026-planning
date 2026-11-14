"""Regression coverage for recovery, treatment controls and the offline console."""

import asyncio
import io
import json
import re
import shutil
import subprocess
from unittest.mock import Mock, patch

import pytest
from fastapi import WebSocketDisconnect

import backend.main as server
from backend.evaluate_blind_seeds import PARAPHRASED_HELD_OUT_CASES
from backend.models.telemetry import TelemetryPacket
from backend.services.anomaly_detector import EdgeAnomalyDetector
from backend.services.astronaut_sim import AstronautSimulationEngine
from backend.services.rag_engine import LocalMedicalRAGEngine


@pytest.fixture
def simulation(monkeypatch):
    monkeypatch.setattr(server, "astronaut_sim", AstronautSimulationEngine())
    monkeypatch.setattr(server, "anomaly_detector", EdgeAnomalyDetector())
    monkeypatch.setattr(server, "rag_engine", LocalMedicalRAGEngine())
    monkeypatch.setattr(server, "latest_telemetry", None)
    monkeypatch.setattr(server.donki_service, "get_space_weather", server.donki_service._get_cache_fallback)
    return server.astronaut_sim


def crisis(scenario):
    assert server.run_simulation_command("trigger_scenario", {"scenario": scenario})["status"] == "ok"
    for _ in range(20):
        frame = server.advance_telemetry()
    return frame


@pytest.mark.parametrize("scenario", ["hypercapnia", "decompression", "heat_strain", "solar_flare"])
def test_recovery_keeps_diagnosis_and_does_not_relearn(simulation, scenario):
    frame = crisis(scenario)
    diagnosis_id = frame["rag_diagnosis"]["scenario_id"]
    candidates = len(server.rag_engine.candidate_rag_buffer)
    assert simulation.cure_scenario()["status"] == "ok"
    with patch.object(server.rag_engine, "diagnose", wraps=server.rag_engine.diagnose) as diagnose:
        for _ in range(30):
            frame = server.advance_telemetry()
            result = frame.get("rag_diagnosis")
            if result:
                assert result["scenario_id"] == diagnosis_id
                assert result["mode"] == "MODE_A_KNOWN_CONDITION"
            assert frame["routine_schedule"]["crew_readiness_score"] == frame["mission_readiness_pct"]
        assert diagnose.call_count == 0
    assert len(server.rag_engine.candidate_rag_buffer) == candidates
    assert simulation.active_scenario == "nominal"


@pytest.mark.parametrize("scenario,medication", [
    ("solar_flare", "Ondansetron"), ("sans", "Acetazolamide"),
    ("orthostatic_intolerance", "0.9% Normal Saline"),
])
def test_active_condition_formulary_medications_are_valid_treatments(simulation, scenario, medication):
    frame = crisis(scenario)
    assert frame["rag_diagnosis"]["mode"] == "MODE_A_KNOWN_CONDITION"
    result = server.run_simulation_command("apply_treatment", {"action": medication})
    assert result["status"] == "ok"
    assert simulation.is_recovering


def test_treatment_options_clear_when_condition_changes(simulation):
    crisis("solar_flare")
    assert server.run_simulation_command("trigger_scenario", {"scenario": "hypercapnia"})["status"] == "ok"
    for treatment in ("Ondansetron", "typo", ""):
        assert server.run_simulation_command("apply_treatment", {"treatment": treatment})["status"] == "error"
    assert not simulation.is_recovering


def test_checklist_actions_remain_valid_during_recovery(simulation):
    frame = crisis("solar_flare")
    action = frame["rag_diagnosis"]["action_checklist"][0]["action"]
    assert simulation.apply_treatment(action)["status"] == "ok"
    server.advance_telemetry()
    assert simulation.apply_treatment(action)["status"] == "ok"


@pytest.mark.parametrize("scenario,medication", [
    ("solar_flare", "Ibuprofen"), ("hypercapnia", "Hydromorphone"),
])
def test_treatment_aliases_preserve_safety_lockouts(simulation, scenario, medication):
    crisis(scenario)
    result = server.run_simulation_command("apply_treatment", {"treatment": medication})
    assert result["status"] == "error"
    assert not simulation.is_recovering


def stdlib_post(payload, path="/api/diagnose/evaluate-tick"):
    handler = server.AresMedStdlibRequestHandler.__new__(server.AresMedStdlibRequestHandler)
    body = json.dumps(payload).encode()
    handler.path = path
    handler.headers = {"Content-Length": str(len(body))}
    handler.rfile = io.BytesIO(body)
    handler._send_json = Mock()
    handler.do_POST()
    return handler._send_json.call_args.args


@pytest.mark.parametrize("path", ["/api/diagnose", "/api/diagnose/evaluate-tick"])
def test_stdlib_tick_rejects_invalid_payload_with_json(path):
    status, body = stdlib_post({"vitals": {"heart_rate": "invalid"}}, path)
    assert status == 422
    assert body.get("detail")


def test_stdlib_tick_pipeline_failure_is_structured_json():
    with patch.object(server.anomaly_detector, "evaluate_packet", side_effect=RuntimeError("failed")):
        status, body = stdlib_post({})
    assert status == 500
    assert body["error_class"] == "RuntimeError"


def test_held_out_ocular_wording_matches_without_relabeling(simulation):
    row = next(row for row in PARAPHRASED_HELD_OUT_CASES if row["case"] == "PARA-06-CORNEAL-ABRASION")
    packet = TelemetryPacket.model_validate(row["payload"])
    result = server.rag_engine.diagnose(packet, server.anomaly_detector.evaluate_packet(packet))
    assert result["scenario_id"] == "CPG-22"
    assert result["mode"] == "MODE_A_KNOWN_CONDITION"


def test_skin_abrasion_wording_cannot_become_an_ocular_diagnosis(simulation):
    packet = TelemetryPacket(
        vitals={"heart_rate": 81, "blood_pressure_sys": 122, "blood_pressure_dia": 78,
                "spo2": 98, "respiration_rate": 16, "core_temp_c": 37, "hrv_ms": 44},
        symptom_log="Grit scratched my forearm while tearing fabric.",
    )
    result = server.rag_engine.diagnose(packet, server.anomaly_detector.evaluate_packet(packet))
    assert result["scenario_id"] != "CPG-22"


def test_stale_incident_diagnosis_is_not_reused_for_a_new_recovery(simulation):
    previous = crisis("solar_flare")
    simulation.trigger_scenario("hypercapnia")
    simulation.cure_scenario()
    frame = server.advance_telemetry()
    assert frame["simulation_incident"] != previous["simulation_incident"]
    assert "rag_diagnosis" not in frame


def test_new_radiation_hazard_preserves_lockouts_during_recovery(simulation, monkeypatch):
    crisis("hypercapnia")
    candidates = len(server.rag_engine.candidate_rag_buffer)
    simulation.cure_scenario()
    monkeypatch.setattr(server.donki_service, "get_space_weather",
                        lambda **kwargs: server.donki_service._get_cache_fallback(True))
    frame = server.advance_telemetry()
    assert all("ibuprofen" not in medication["medication"].lower()
               for medication in frame["rag_diagnosis"]["prescriptions"])
    assert any("NSAID" in warning for warning in frame["rag_diagnosis"]["contraindications_locked"])
    assert simulation.apply_treatment("Ibuprofen")["status"] == "error"
    assert len(server.rag_engine.candidate_rag_buffer) == candidates
    for _ in range(12):
        frame = server.advance_telemetry()
    assert frame["rag_diagnosis"]["scenario_id"] in ("SCENARIO_4_SOLAR_RADIATION_ARS", "CPG-09")
    assert frame["rag_diagnosis"]["mode"] == "MODE_A_KNOWN_CONDITION"


def test_schedule_tracks_current_readiness(simulation):
    normal = server.advance_telemetry()
    emergency = crisis("hypercapnia")
    assert emergency["routine_schedule"]["crew_readiness_score"] == emergency["mission_readiness_pct"]
    assert emergency["mission_readiness_pct"] < normal["mission_readiness_pct"]
    assert simulation.get_routine_schedule()["crew_readiness_score"] == emergency["mission_readiness_pct"]


def test_scenario_catalog_exposes_supported_canonical_controls(simulation):
    ids = [entry["id"] for entry in simulation.list_available_scenarios()]
    assert len(ids) == len(set(ids)) == 33
    assert {"zero_day", "dehydration"}.issubset(ids)


def test_websocket_acknowledgements_and_treatment_fallback(simulation, monkeypatch):
    crisis("solar_flare")
    commands = iter([
        {"action": "set_activity", "activity_state": "IVA_REST"},
        {"command": "apply_treatment", "action": "Ondansetron"},
        {"action": "apply_treatment", "payload": {"action": "Ondansetron"}},
    ])

    class Socket:
        def __init__(self):
            self.messages = []

        async def accept(self):
            pass

        async def receive_text(self):
            command = next(commands, None)
            if command is None:
                raise WebSocketDisconnect()
            return json.dumps(command)

        async def send_text(self, text):
            self.messages.append(json.loads(text))

    monkeypatch.setattr(server, "manager", server.ConnectionManager())
    socket = Socket()
    asyncio.run(server.websocket_telemetry_endpoint(socket))
    replies = [message for message in socket.messages if message.get("type") == "COMMAND_ACK"]
    assert len(replies) == 3
    assert all(reply["result"]["status"] == "ok" for reply in replies)
    assert replies[0]["activity"] == replies[0]["result"]["activity_state"]


def test_console_uses_card_outputs_and_handles_non_json():
    node = shutil.which("node")
    html = server.render_offline_api_docs(include_openapi=True)
    assert 'id="scenarioResp"' in html and 'id="recoveryResp"' in html
    if node is None:
        pytest.skip("Node is unavailable for the console JavaScript runtime check")
    script = re.search(r"<script>(.*?)</script>", html, re.S)[1]
    harness = r'''
const vm = require('node:vm');
const fs = require('node:fs');
const nodes = {};
const context = {
  document: {getElementById(id) {
    return nodes[id] ||= {textContent: '', value: '', dataset: {}, add(option) {this.value ||= option.value}};
  }},
  Option: function(text, value) {this.value = value},
  fetch: async () => ({ok: false, status: 503, statusText: 'Unavailable', text: async () => '<html>failure</html>'})
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(0, 'utf8'), context);
(async () => {
  await context.sendPost('/bad', '{}', 'scenarioResp');
  if (!nodes.scenarioResp.textContent.includes('503') || !nodes.scenarioResp.textContent.includes('<html>failure</html>')) throw Error('Non-JSON error lost');
  context.fetch = async () => ({ok: true, status: 200, statusText: 'OK', text: async () => '{"status":"ok"}'});
  await context.sendGet('/ok', 'recoveryResp');
  if (!nodes.recoveryResp.textContent.includes('ok')) throw Error('Wrong response target');
  context.fetch = async () => {throw Error('offline')};
  await context.sendGet('/offline', 'recoveryResp');
  if (!nodes.recoveryResp.textContent.includes('offline')) throw Error('Network error lost');
})().catch(error => {console.error(error);process.exitCode = 1});
'''
    result = subprocess.run([node, "-e", harness], input=script, text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr

import pytest

from backend import main as server
from backend.services.anomaly_detector import EdgeAnomalyDetector
from backend.services.astronaut_sim import AstronautSimulationEngine


@pytest.fixture
def simulator(monkeypatch):
    def reset():
        engine = AstronautSimulationEngine()
        monkeypatch.setattr(server, "astronaut_sim", engine)
        monkeypatch.setattr(server, "latest_telemetry", None)
        monkeypatch.setattr(server, "latest_earth_report", None)
        monkeypatch.setattr(server, "anomaly_detector", EdgeAnomalyDetector())
        monkeypatch.setattr(server.donki_service, "get_space_weather", server.donki_service._get_cache_fallback)
        return engine
    return reset


def run_seed(reset, seed, duration=24):
    engine = reset()
    ticks = engine.tick_count
    ack = server.simulate_crisis_action({"streaming": True, "seed": seed, "duration_ticks": duration})
    assert ack == {"status": "ok", "incident_id": engine.incident_id}
    assert engine.tick_count == ticks
    assert server.simulation_response("/api/telemetry/current")[0] == 503
    assert server.get_or_create_latest_earth_report()["status"] == "pending"
    assert engine.tick_count == ticks
    frames = [server.advance_telemetry() for _ in range(10)]
    for frame in frames:
        assert frame["astronaut_id"] == "ASTRO-01"
        assert frame["name"] == "Cmdr. Alex Vance"
        assert "active_scenario_id" not in frame
        assert "mode_hint" not in frame
        assert "reveal" not in frame["blind_incident"]
    for frame in frames[:2]:
        assert frame["blind_incident"]["phase"] == "observing"
        assert frame["anomaly_assessment"]["alert_level"] == "NOMINAL"
        assert "rag_diagnosis" not in frame
    return engine, ack["incident_id"], frames


def test_seeded_telemetry_requires_streamed_evidence(simulator):
    _, _, first = run_seed(simulator, 2)
    _, _, repeated = run_seed(simulator, 2)
    _, _, different = run_seed(simulator, 0)
    assert [x["vitals"] for x in first] == [x["vitals"] for x in repeated]
    assert [x["vitals"] for x in first] != [x["vitals"] for x in different]
    for frames, mode in ((first, "MODE_A_KNOWN_CONDITION"), (different, "MODE_B_NOVEL_ANOMALY")):
        assessment = next(frame for frame in frames if "rag_diagnosis" in frame)
        assert assessment["anomaly_assessment"]["trigger_rag_consultation"]
        assert assessment["rag_diagnosis"]["mode"] == mode
        assert bool(assessment["blind_incident"]["actions"]) == ("MODE_A" in mode)


def test_recovery_and_previous_incident_are_distinct(simulator):
    engine, incident_id, frames = run_seed(simulator, 2, duration=15)
    action_id = frames[-1]["blind_incident"]["actions"][0]["id"]
    initial_co2 = frames[-1]["environment"]["cabin_co2_mmhg"]
    for invalid in ({"incident_id": incident_id - 1, "action_id": action_id},
                    {"incident_id": incident_id, "action_id": "restore_cooling"},
                    {"treatment": "standard countermeasure protocol"}):
        assert server.run_simulation_command("apply_treatment", invalid)["status"] == "error"
        assert not engine.is_recovering
    assert server.cure_simulation()["status"] == "error"
    valid = {"incident_id": incident_id, "action_id": action_id}
    assert server.run_simulation_command("apply_treatment", valid)["status"] == "ok"
    assert server.run_simulation_command("apply_treatment", valid)["status"] == "error"
    frame = server.advance_telemetry()
    assert frame["blind_incident"]["recovery_cause"] == "operator"
    assert frame["environment"]["cabin_co2_mmhg"] < initial_co2
    for _ in range(10):
        frame = server.advance_telemetry()
    assert frame["blind_incident"]["phase"] == "complete"
    assert frame["blind_incident"]["reveal"] == "hypercapnia"

    ack = server.simulate_crisis_action({"streaming": True, "seed": 0, "duration_ticks": 15})
    assert ack["incident_id"] > incident_id
    assert server.run_simulation_command("apply_treatment", valid)["status"] == "error"
    frame = server.advance_telemetry()
    assert "rag_diagnosis" not in frame
    for _ in range(16):
        frame = server.advance_telemetry()
    assert frame["blind_incident"]["recovery_cause"] == "automatic"
    for _ in range(10):
        frame = server.advance_telemetry()
    assert frame["blind_incident"]["phase"] == "complete"
    assert frame["blind_incident"]["recovery_cause"] == "automatic"

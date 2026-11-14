"""Regression tests for source validation, cross-hazard output and weather isolation."""

import copy
import asyncio
import json
from pathlib import Path
from threading import Event, Thread
from unittest.mock import patch

import pytest

from backend.evaluate_blind_seeds import _check_mode_a_validity
from backend.evaluate_blind_seeds import _seed_to_payload
from backend.models.telemetry import TelemetryPacket
from backend.services.anomaly_detector import EdgeAnomalyDetector
from backend.services.donki_service import DonkiSpaceWeatherService
from backend.services.rag_engine import LocalMedicalRAGEngine


@pytest.fixture(scope="module")
def engine():
    return LocalMedicalRAGEngine()


def renal_response(engine, environment=None, spo2=98):
    packet = TelemetryPacket(
        vitals={"heart_rate": 92, "blood_pressure_sys": 110, "blood_pressure_dia": 70,
                "spo2": spo2, "hrv_ms": 30, "core_temp_c": 37.6, "respiration_rate": 18},
        environment=environment or {"cabin_co2_mmhg": 2, "ambient_radiation_msv_h": .05},
        symptom_log="Severe flank pain radiating to groin, nausea and hematuria.",
    )
    assessment = EdgeAnomalyDetector().evaluate_packet(packet)
    return engine._build_mode_a_response("CPG-16", .95, packet, assessment,
                                         packet.symptom_log, 0, {}, {})


@pytest.mark.parametrize("environment,spo2,blocked", [
    ({"cabin_co2_mmhg": 2, "ambient_radiation_msv_h": .3}, 98, "ketorolac"),
    ({"cabin_co2_mmhg": 2, "ambient_radiation_msv_h": .05}, 88, "hydromorphone"),
])
def test_lockout_applies_to_every_action_field(engine, environment, spo2, blocked):
    result = renal_response(engine, environment, spo2)
    assert all(blocked not in str(med.get(key, "")).lower()
               for med in result["prescriptions"] for key in ("medication", "drug", "dosage", "route"))
    assert all(blocked not in med["drug"].lower() for med in result["checs_medications"])
    for field in ("action_checklist", "action_plan", "autonomous_checklist"):
        assert all(blocked not in action["action"].lower() for action in result[field])


def test_absorbed_dose_rate_does_not_enter_equivalent_dose_rules(engine):
    baseline = renal_response(engine)
    bfo = renal_response(engine, {"cabin_co2_mmhg": 2, "ambient_radiation_msv_h": .05,
                                  "bfo_dose_rate_mGy_hr": 20})
    assert bfo["prescriptions"] == baseline["prescriptions"]
    packet = TelemetryPacket(environment={"ambient_radiation_msv_h": .05,
                                          "bfo_dose_rate_mGy_hr": 20})
    assessment = EdgeAnomalyDetector().evaluate_packet(packet)
    assert engine._score_symbolic_telemetry("CPG-09", packet, assessment, "") < 0


@pytest.mark.parametrize("field,value", [
    ("nasa_citations", ["FABRICATED STANDARD"]),
    ("nasa_direct_quote", "Invented quotation"),
    ("nasa_citation", {"document": "NASA", "section": "fake", "url": "https://example.com"}),
])
def test_validity_check_rejects_fabricated_source_claims(engine, field, value):
    result = renal_response(engine)
    assert _check_mode_a_validity(engine, result)
    forged = copy.deepcopy(result)
    forged[field] = value
    assert not _check_mode_a_validity(engine, forged)


def test_cached_weather_read_does_not_perform_network_io():
    service = DonkiSpaceWeatherService()
    with patch.object(service, "fetch_live_events", side_effect=AssertionError("Network on tick path")):
        assert service.get_space_weather().source != "LIVE_DONKI_API"


def test_weather_refresh_is_single_flight_and_keeps_cached_reads_available():
    service = DonkiSpaceWeatherService()
    started, release = Event(), Event()

    def blocked_fetch():
        started.set()
        release.wait(2)
        return []

    with patch.object(service, "fetch_live_events", side_effect=blocked_fetch) as fetch:
        worker = Thread(target=service.refresh)
        worker.start()
        try:
            assert started.wait(1)
            assert service.get_space_weather().source != "LIVE_DONKI_API"
            service.refresh()
            assert fetch.call_count == 1
        finally:
            release.set()
            worker.join(2)
        assert not worker.is_alive()
        assert service.get_space_weather().source == "LIVE_DONKI_API"


@pytest.mark.parametrize("seed_id", [
    "SEED-TRM-01", "SEED-TRM-03", "SEED-TRM-06", "SEED-MED-08",
    "SEED-NEU-01", "SEED-NEU-04", "SEED-NEU-05", "SEED-NEU-06",
])
def test_unmapped_conditions_do_not_receive_unrelated_protocols(engine, seed_id):
    data = Path(__file__).resolve().parents[2] / "data" / "simulation_scenario_seeds.json"
    seeds = json.loads(data.read_text(encoding="utf-8"))["synthetic_scenario_seeds_24"]
    seed = next(row for row in seeds if row["seed_id"] == seed_id)
    packet = TelemetryPacket.model_validate(_seed_to_payload(seed))
    result = engine.diagnose(packet, EdgeAnomalyDetector().evaluate_packet(packet))
    assert result["mode"] == "MODE_B_NOVEL_ANOMALY"
    assert seed.get("expected_mode") == "MODE_B_NOVEL_ANOMALY"
    assert not seed.get("linked_cpg_id")


def test_slow_websocket_does_not_delay_fast_client():
    from backend.main import ConnectionManager

    async def check():
        sent = asyncio.Event()

        class StalledClient:
            async def send_text(self, message):
                await asyncio.Event().wait()

        class FastClient:
            async def send_text(self, message):
                sent.set()

        manager = ConnectionManager()
        stalled, fast = StalledClient(), FastClient()
        manager.active_connections = [stalled, fast]
        sending = asyncio.create_task(manager.broadcast("frame"))
        await asyncio.wait_for(sent.wait(), timeout=0.05)
        await sending
        assert manager.active_connections == [fast]

    asyncio.run(check())


def test_live_replay_reports_known_matches_and_unsupported_abstentions():
    from backend.evaluate_blind_seeds import evaluate_live_simulation

    result = evaluate_live_simulation()
    assert result["cases"] == 30
    assert result["known_condition_cases"] == 22
    assert result["known_condition_matches"] >= 20
    assert result["unsupported_cases"] == result["correct_abstentions"] == 8
    assert all(case["mode"] == "MODE_B_NOVEL_ANOMALY" for case in result["failures"])


def test_simulator_label_cannot_force_abstention_for_known_evidence(engine):
    payload = {"vitals": {"heart_rate": 118, "blood_pressure_sys": 140, "blood_pressure_dia": 90,
                          "spo2": 96, "hrv_ms": 22, "core_temp_c": 37.6, "respiration_rate": 22},
               "environment": {"cabin_co2_mmhg": 8, "ambient_radiation_msv_h": .05},
               "symptom_log": "Throbbing frontal headache, flushing and short of breath."}
    for label in (None, "MODE_B_ZERO_DAY", "UNKNOWN"):
        packet = TelemetryPacket(**payload, active_scenario_id=label)
        result = engine.diagnose(packet, EdgeAnomalyDetector().evaluate_packet(packet))
        assert result["mode"] == "MODE_A_KNOWN_CONDITION"
        assert result["scenario_id"] in ("CPG-07", "SCENARIO_1_HYPERCAPNIA")


def test_validity_check_rejects_incorrect_pack_without_silently_repairing_it(engine):
    result = renal_response(engine)
    result["prescriptions"][0]["checs_pack"] = "FAKE"
    assert not _check_mode_a_validity(engine, result)


@pytest.mark.parametrize("activity_state", ["SLEEP", "ARED_EXERCISE"])
def test_unmapped_conditions_remain_abstentions_across_activity_baselines(activity_state):
    from backend.evaluate_blind_seeds import evaluate_live_simulation

    result = evaluate_live_simulation(activity_state=activity_state, mission_day=3)
    assert result["cases"] == 30
    assert result["unsupported_cases"] == result["correct_abstentions"] == 8

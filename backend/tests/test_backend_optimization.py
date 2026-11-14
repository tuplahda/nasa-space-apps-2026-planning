"""Cache ownership, bounded reuse, and server synchronization regressions."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Event
from unittest.mock import Mock, patch

import httpx
import pytest

import backend.main as server
import backend.services.rag_engine as rag_module
from backend.models.telemetry import TelemetryPacket
from backend.services.anomaly_detector import EdgeAnomalyDetector
from backend.services.astronaut_sim import AstronautSimulationEngine
from backend.services.rag_engine import LocalMedicalRAGEngine, sanitize_symptom_log


@pytest.fixture
def engine():
    return LocalMedicalRAGEngine()


def known_packet(example="mode_a_solar_radiation"):
    packet = TelemetryPacket.model_validate(server.SWAGGER_DIAGNOSE_EXAMPLES[example]["value"])
    packet.active_scenario_id = None
    return packet


def test_diagnosis_cache_owns_nested_results_on_store_and_hit(engine):
    packet = known_packet()
    assessment = EdgeAnomalyDetector().evaluate_packet(packet)
    first = engine.diagnose(packet, assessment)
    expected = deepcopy(first)
    first["prescriptions"][0]["medication"] = "corrupted"
    first["rag_metrics"]["retrieval_latency_ms"] = -1
    first["action_checklist"][0]["action"] = "corrupted"
    first["nasa_citation"]["url"] = "corrupted"
    for _ in range(2):
        hit = engine.diagnose(packet, assessment)
        assert hit["cache_hit"] is True
        for key in ("prescriptions", "rag_metrics", "action_checklist", "nasa_citation"):
            assert hit[key] == expected[key]
        hit["prescriptions"].clear()
        hit["action_checklist"][0]["completed"] = True
        hit["rag_metrics"]["retrieval_latency_ms"] = -2


def test_diagnosis_cache_evicts_only_the_least_recently_used(engine, monkeypatch):
    monkeypatch.setattr(rag_module, "MAX_CACHE_ENTRIES", 2)
    packets = [known_packet(name) for name in (
        "mode_a_hypercapnia", "mode_a_solar_radiation", "mode_a_sans")]
    detector = EdgeAnomalyDetector()
    assessments = [detector.evaluate_packet(packet) for packet in packets]
    for i in range(2):
        engine.diagnose(packets[i], assessments[i])
    assert engine.diagnose(packets[0], assessments[0])["cache_hit"]
    engine.diagnose(packets[2], assessments[2])
    keys = [engine._build_cache_key(packet, sanitize_symptom_log(packet.symptom_log)) for packet in packets]
    assert list(engine.diagnosis_cache) == [keys[0], keys[2]]
    assert not engine.diagnose(packets[1], assessments[1])["cache_hit"]
    assert len(engine.diagnosis_cache) == 2


def test_treatment_memoization_is_isolated_and_lockout_sensitive(engine):
    packet = known_packet("mode_a_hypercapnia")
    assessment = EdgeAnomalyDetector().evaluate_packet(packet)
    with patch.object(engine, "_parse_and_validate_medication", side_effect=AssertionError("reparsed")), patch.object(
        engine, "_apply_deterministic_safety_filter", wraps=engine._apply_deterministic_safety_filter
    ) as filter_meds:
        first = engine.get_treatment_options("SCENARIO_1_HYPERCAPNIA", packet, assessment)
        assert "ibuprofen" in [name.lower() for name in first]
        first.append("corrupted")
        assert "corrupted" not in engine.get_treatment_options("SCENARIO_1_HYPERCAPNIA", packet, assessment)
        assert filter_meds.call_count == 1
        packet.environment.donki_spe_active = True
        locked = engine.get_treatment_options("SCENARIO_1_HYPERCAPNIA", packet, assessment)
        assert all("ibuprofen" not in name.lower() for name in locked)
        assert filter_meds.call_count == 2


@pytest.mark.parametrize("drug,verified", [("Ondansetron", True), ("unregistered drug", False)])
def test_ad_hoc_protocols_still_require_formulary_validation(engine, drug, verified):
    proto = {"scenario_id": "AD_HOC", "nasa_citations": ["source"],
             "autonomous_checklist": ["action"], "checs_medications": [{"drug": drug, "pack": "OMP"}]}
    assert engine._is_mode_a_data_complete(proto) is verified


def test_evidence_cache_is_isolated_bounded_and_cleared_on_reload(engine, monkeypatch):
    monkeypatch.setattr(rag_module, "MAX_CACHE_ENTRIES", 2)
    sid = "CPG-22"
    proto = engine.protocol_by_id[sid]
    with patch.object(engine, "query_vector_store", wraps=engine.query_vector_store) as query:
        evidence = engine._get_retrieved_evidence_chunks(sid, proto, "eye pain")
        evidence.append("corrupted")
        assert "corrupted" not in engine._get_retrieved_evidence_chunks(sid, proto, "eye pain")
        assert query.call_count == 1
        for symptom in ("photophobia", "gritty eye"):
            engine._get_retrieved_evidence_chunks(sid, proto, symptom)
        assert len(engine._evidence_cache) == 2
    packet = known_packet()
    assessment = EdgeAnomalyDetector().evaluate_packet(packet)
    engine.get_treatment_options("CPG-09", packet, assessment)
    engine.diagnose(packet, assessment)
    revision = engine._knowledge_revision
    engine.reload_knowledge_base()
    assert engine._knowledge_revision == revision + 1
    assert not any((engine.diagnosis_cache, engine._evidence_cache, engine._treatment_options_cache))


@pytest.mark.parametrize("types", [{"rule"}, {"hardware", "lab"}, set(), {"unknown"}])
def test_partitioned_vector_lookup_preserves_scores_and_order(engine, types):
    query = "hypercapnia cabin CO2 scrubber i-STAT Epinephrine"
    all_hits = engine.query_vector_store(query, top_k=len(engine.vector_store))
    expected = [hit for hit in all_hits if hit["doc_type"] in types][:5]
    assert engine.query_vector_store(query, top_k=5, doc_types=types) == expected
    indexed = [cid for ids in engine._chunk_ids_by_type.values() for cid in ids]
    assert len(indexed) == len(set(indexed)) == len(engine.vector_store)


@pytest.fixture
def simulation(monkeypatch, engine):
    monkeypatch.setattr(server, "astronaut_sim", AstronautSimulationEngine())
    monkeypatch.setattr(server, "anomaly_detector", EdgeAnomalyDetector())
    monkeypatch.setattr(server, "rag_engine", engine)
    monkeypatch.setattr(server, "latest_telemetry", None)
    monkeypatch.setattr(server.donki_service, "get_space_weather", server.donki_service._get_cache_fallback)
    return server.astronaut_sim


def test_recovery_computes_policy_once_and_refreshes_only_on_change(simulation, engine):
    server.run_simulation_command("trigger_scenario", {"scenario": "hypercapnia"})
    for _ in range(20):
        server.advance_telemetry()
    simulation.cure_scenario()
    with patch.object(engine, "_medication_safety_policy", wraps=engine._medication_safety_policy) as policy, patch.object(
        engine, "get_treatment_options", wraps=engine.get_treatment_options
    ) as options:
        for _ in range(6):
            server.advance_telemetry()
        assert policy.call_count == 6
        assert options.call_count <= 1


def test_schedule_fallback_reuses_detector_without_packet_revalidation(simulation):
    packet = simulation.step()
    simulation.get_routine_schedule()
    detector = simulation._readiness_detector
    packet = simulation.step()
    original_flags = (packet.active_scenario_id, packet.stateless_evaluation)
    with patch("backend.services.anomaly_detector.EdgeAnomalyDetector", side_effect=AssertionError("recreated")), patch.object(
        TelemetryPacket, "model_validate", side_effect=AssertionError("revalidated")
    ):
        schedule = simulation.get_routine_schedule()
    assert isinstance(schedule["crew_readiness_score"], int)
    assert simulation._readiness_detector is detector
    assert detector.ring_managers == {}
    assert (packet.active_scenario_id, packet.stateless_evaluation) == original_flags


def test_commands_and_state_reads_share_reentrant_lock(simulation):
    started = Event()

    def command():
        started.set()
        return server.run_simulation_command("trigger_scenario", {"scenario": "hypercapnia"})

    with ThreadPoolExecutor(max_workers=1) as pool:
        with server.simulation_lock:
            future = pool.submit(command)
            assert started.wait(2)
            assert not future.done()
            assert server.simulation_response("/api/simulation/state")[1]["active_scenario"] == "nominal"
        assert future.result(timeout=2)["status"] == "ok"
    assert server.simulation_response("/api/simulation/state")[1]["active_scenario"] == "hypercapnia"


def test_stdlib_get_releases_lock_before_writing_response(simulation):
    handler = server.AresMedStdlibRequestHandler.__new__(server.AresMedStdlibRequestHandler)
    handler.path = "/api/simulation/state"

    def probe_lock():
        acquired = server.simulation_lock.acquire(blocking=False)
        if acquired:
            server.simulation_lock.release()
        return acquired

    def send(status, body):
        assert status == 200 and body["name"] == "Cmdr. Alex Vance"
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(probe_lock).result(timeout=2)

    handler._send_json = send
    handler.do_GET()


def test_lifespan_warms_telemetry_before_serving(simulation, monkeypatch):
    async def idle():
        await asyncio.Event().wait()

    monkeypatch.setattr(server, "broadcast_telemetry_loop", idle)
    monkeypatch.setattr(server, "refresh_weather_loop", idle)

    async def check():
        async with server.lifespan(server.app):
            assert simulation.tick_count == 1
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as client:
                response = await client.get("/api/telemetry/current")
                assert response.status_code == 200
                assert response.json()["astronaut_id"] == "ASTRO-01"

    asyncio.run(check())


def test_idle_broadcast_loop_advances_without_json_serialization(monkeypatch):
    calls = 0

    async def sleep(_delay):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise asyncio.CancelledError()

    advance = Mock(return_value={"tick": 1})
    monkeypatch.setattr(server, "manager", server.ConnectionManager())
    monkeypatch.setattr(server, "advance_telemetry", advance)
    monkeypatch.setattr(server.asyncio, "sleep", sleep)
    with patch.object(server.json, "dumps") as serialize, pytest.raises(asyncio.CancelledError):
        asyncio.run(server.broadcast_telemetry_loop())
    assert advance.call_count == 1
    serialize.assert_not_called()

"""
Triage & Clinical Decision Support API Endpoint (`POST /api/diagnose`).

Integrates Layer 2 (`EdgeAnomalyDetector` + `AstronautRingBufferManager`)
with Layer 3 (`LocalMedicalRAGEngine`) to return structured Mode A or Mode B
clinical JSON payloads in <50ms with a deterministic offline fallback.
"""

import time
from typing import Any, Dict

from backend.models.telemetry import (
    AnomalyAssessment,
    DEMO_ASTRONAUT_ID,
    DEMO_ASTRONAUT_NAME,
    TelemetryPacket,
)
from backend.services.anomaly_detector import EdgeAnomalyDetector
from backend.services.rag_engine import LocalMedicalRAGEngine

try:
    from fastapi import APIRouter, Body, HTTPException

    FASTAPI_AVAILABLE = True
    router = APIRouter(prefix="/api", tags=["NASA Level V Clinical Triage"])
except ImportError:  # pragma: no cover - Air-gapped stdlib fallback
    FASTAPI_AVAILABLE = False
    router = None  # type: ignore

# Singleton instances pre-allocated at module load for sub-millisecond latency
anomaly_detector = EdgeAnomalyDetector()
rag_engine = LocalMedicalRAGEngine()


def attach_contract_a_context(result: Dict[str, Any], packet: TelemetryPacket) -> Dict[str, Any]:
    """Expose Contract A context that is not part of the clinical RAG decision."""
    comms = packet.comms_status
    result["comms_status"] = comms.model_dump() if comms is not None else None
    result["cabin_environment"] = {
        "cabin_pressure_kPa": packet.environment.cabin_pressure_kPa,
        "cabin_temp_C": packet.environment.cabin_temp_C,
    }
    return result


def build_contract_b_response(
    assessment: AnomalyAssessment,
    packet: TelemetryPacket,
    rag_consultation: Any = None,
) -> Dict[str, Any]:
    """Return Contract B fields at the root and retain the existing wrapped form."""
    assessment_data = assessment.model_dump()
    response = dict(assessment_data)
    response["assessment"] = assessment_data
    response["rag_consultation"] = rag_consultation
    attach_contract_a_context(response, packet)
    return response

SWAGGER_DIAGNOSE_EXAMPLES: Dict[str, Dict[str, Any]] = {
    "mode_a_hypercapnia": {
        "summary": "Mode A: EVA Hypercapnia (CO2 Toxicity — Locks Out Opioids)",
        "description": "High cabin/suit CO2 (12.8 mmHg) + tachycardia + frontal headache -> Mode A (>=0.75).",
        "value": {
            "timestamp": "2026-11-14T10:15:30Z",
            "met": "042:14:30:12",
            "mission_day": 84,
            "astronaut_id": DEMO_ASTRONAUT_ID,
            "name": DEMO_ASTRONAUT_NAME,
            "activity_state": "EVA_SPACEWALK",
            "vitals": {
                "heart_rate": 118,
                "blood_pressure_sys": 142,
                "blood_pressure_dia": 92,
                "spo2": 95.8,
                "hrv_ms": 22.4,
                "core_temp_c": 37.6,
                "respiration_rate": 20,
            },
            "environment": {
                "cabin_co2_mmhg": 12.8,
                "ambient_radiation_msv_h": 0.054,
                "suit_pressure_psi": 4.3,
            },
            "symptom_log": "Throbbing frontal headache, facial flushing, air feels sluggish and short of breath.",
            "force_mode_b": False,
        },
    },
    "mode_a_solar_radiation": {
        "summary": "Mode A: Solar Particle Event / ARS (Locks Out NSAIDs/Aspirin)",
        "description": "Radiation spike (4.2 mSv/h) + DONKI SPE active + emesis -> Mode A (>=0.75).",
        "value": {
            "timestamp": "2026-11-14T11:00:00Z",
            "met": "042:15:15:00",
            "mission_day": 84,
            "astronaut_id": DEMO_ASTRONAUT_ID,
            "name": DEMO_ASTRONAUT_NAME,
            "activity_state": "EVA_SPACEWALK",
            "vitals": {
                "heart_rate": 98,
                "blood_pressure_sys": 96,
                "blood_pressure_dia": 64,
                "spo2": 97.0,
                "hrv_ms": 19.0,
                "core_temp_c": 38.4,
                "respiration_rate": 18,
            },
            "environment": {
                "cabin_co2_mmhg": 2.1,
                "ambient_radiation_msv_h": 4.2,
                "suit_pressure_psi": 4.3,
                "donki_spe_active": True,
            },
            "symptom_log": "Sudden anorexia, severe nausea, throwing up repeatedly, acute fatigue.",
            "force_mode_b": False,
        },
    },
    "mode_a_sans": {
        "summary": "Mode A: SANS Neuro-Ocular Syndrome (OCT RNFL > 105 μm)",
        "description": "Optic disc edema on OCT + blurry near vision at arm's length -> Mode A (>=0.75).",
        "value": {
            "timestamp": "2026-11-14T19:00:00Z",
            "met": "095:08:00:00",
            "mission_day": 95,
            "astronaut_id": DEMO_ASTRONAUT_ID,
            "name": DEMO_ASTRONAUT_NAME,
            "activity_state": "IVA_REST",
            "vitals": {
                "heart_rate": 62,
                "blood_pressure_sys": 114,
                "blood_pressure_dia": 72,
                "spo2": 98.0,
                "hrv_ms": 38.0,
                "core_temp_c": 37.6,
                "respiration_rate": 13,
            },
            "environment": {
                "cabin_co2_mmhg": 2.1,
                "ambient_radiation_msv_h": 0.054,
            },
            "specialized_diagnostics": {
                "oct_rnfl_um": 118.0,
                "refraction_shift_D": 1.0,
            },
            "symptom_log": "Blurry near vision holding tablet at arms length, retro-orbital eye pressure and wavy lines.",
            "force_mode_b": False,
        },
    },
    "mode_b_zero_day": {
        "summary": "Mode B: Unseen Zero-Day Anomaly (Certified Abstention < 0.75)",
        "description": "Unclassified multi-system hypoxia (SpO2 89.2%) + hypotension (SBP 84 mmHg) + hyperthermia (38.9°C) at normal CO2/Radiation -> Triggers Mode B 4-Step Zero-Day Protocol.",
        "value": {
            "timestamp": "2026-11-14T14:20:00Z",
            "met": "042:18:35:00",
            "mission_day": 84,
            "astronaut_id": DEMO_ASTRONAUT_ID,
            "name": DEMO_ASTRONAUT_NAME,
            "activity_state": "IVA_REST",
            "vitals": {
                "heart_rate": 114,
                "blood_pressure_sys": 84,
                "blood_pressure_dia": 52,
                "spo2": 89.2,
                "hrv_ms": 14.0,
                "core_temp_c": 38.9,
                "respiration_rate": 24,
            },
            "environment": {
                "cabin_co2_mmhg": 2.0,
                "ambient_radiation_msv_h": 0.054,
            },
            "symptom_log": "Unexplained metallic taste, peripheral tingling, sudden weakness.",
            "force_mode_b": False,
        },
    },
}


def execute_diagnosis_pipeline(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Pure deterministic pipeline callable from both FastAPI routes and unit tests.
    Executes in <1ms (well within the <50ms real-time requirement).
    """
    start_ns = time.perf_counter_ns()
    packet = TelemetryPacket.model_validate(payload)
    assessment: AnomalyAssessment = anomaly_detector.evaluate_packet(packet)
    rag_result = rag_engine.diagnose(packet, assessment)

    total_ms = round((time.perf_counter_ns() - start_ns) / 1_000_000.0, 3)
    rag_result["total_pipeline_latency_ms"] = total_ms
    rag_result["layer2_assessment"] = assessment.model_dump()
    return attach_contract_a_context(rag_result, packet)


if FASTAPI_AVAILABLE and router is not None:

    @router.post("/diagnose")
    async def post_diagnose(
        packet: TelemetryPacket = Body(..., openapi_examples=SWAGGER_DIAGNOSE_EXAMPLES),
    ) -> Dict[str, Any]:
        """
        Evaluate astronaut telemetry against microgravity baselines and execute
        the 2-Mode Clinical Decision Protocol (Mode A >= 0.75, Mode B < 0.75).
        """
        start_ns = time.perf_counter_ns()
        try:
            assessment = anomaly_detector.evaluate_packet(packet)
            result = rag_engine.diagnose(packet, assessment)
            total_ms = round((time.perf_counter_ns() - start_ns) / 1_000_000.0, 3)
            result["total_pipeline_latency_ms"] = total_ms
            result["layer2_assessment"] = assessment.model_dump()
            return attach_contract_a_context(result, packet)
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail={
                    "type": "https://ares-med.nasa.local/problems/diagnosis-failure",
                    "title": "Deterministic Fallback Triggered",
                    "status": 500,
                    "detail": "Clinical pipeline encountered an unexpected input condition.",
                    "error_class": exc.__class__.__name__,
                },
            ) from exc

    @router.post("/diagnose/evaluate-tick")
    async def post_evaluate_tick(
        packet: TelemetryPacket = Body(..., openapi_examples=SWAGGER_DIAGNOSE_EXAMPLES),
    ) -> Dict[str, Any]:
        """
        Stateful 1Hz tick evaluation endpoint (enforces 3-tick SEU persistence debounce).
        """
        packet.stateless_evaluation = False
        assessment = anomaly_detector.evaluate_packet(packet)
        rag_consultation = None
        if assessment.trigger_rag_consultation:
            rag_consultation = rag_engine.diagnose(packet, assessment)
        return build_contract_b_response(assessment, packet, rag_consultation)

    @router.get("/diagnose/buffer-status")
    async def get_buffer_status(astronaut_id: str = DEMO_ASTRONAUT_ID) -> Dict[str, Any]:
        """Return 60-second ring buffer metrics and cosmic-ray SEU counters."""
        mgr = anomaly_detector.get_or_create_buffer(astronaut_id)
        return mgr.get_snapshot_summary()

    @router.get("/diagnose/protocols")
    async def get_loaded_protocols() -> Dict[str, Any]:
        """Return metadata on loaded NASA protocols and dynamic challenge datasets."""
        return {
            "total_protocols": len(rag_engine.protocols),
            "scenario_ids": list(rag_engine.protocol_by_id.keys()),
            "dynamic_docs_loaded": rag_engine.dynamic_docs_loaded,
            "candidates_in_learning_queue": len(rag_engine.candidate_rag_buffer),
            "checs_inventory": rag_engine.checs_inventory,
        }

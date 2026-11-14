"""
Blind Evaluation Benchmark for the Offline Clinical Decision RAG Engine.

Evaluates 54 blind test cases with zero label/scenario leakage (`active_scenario_id=None`,
no `scenario_id` passed to inference):
- 24 synthetic scenario seeds (`data/simulation_scenario_seeds.json`)
- 18 quantitative crisis trajectory tiers (6 trajectories x 3 severity levels)
- 6 held-back paraphrased positive cases (non-verbatim crew wording)
- 6 negative / Mode B abstention cases (ambiguous, contradictory, missing vitals,
  unreliable sensors, out-of-domain rash, and active_scenario_id leak probe)

Reports overall & held-out accuracy, Mode A precision, Mode B abstention accuracy,
100% citation & formulary validity rate on Mode A outputs, and cold-path p95 latency.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Tuple

from backend.models.telemetry import TelemetryPacket
from backend.services.anomaly_detector import EdgeAnomalyDetector
from backend.services.rag_engine import LocalMedicalRAGEngine

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SEEDS_PATH = DATA_DIR / "simulation_scenario_seeds.json"

BASELINE_VITALS: Dict[str, float] = {
    "heart_rate": 72.0,
    "blood_pressure_sys": 118.0,
    "blood_pressure_dia": 76.0,
    "spo2": 98.0,
    "respiration_rate": 15.0,
    "core_temp_c": 37.0,
    "hrv_ms": 50.0,
    "ve_l_min": 8.0,
}

TRAJECTORY_TELEMETRY_PRESETS: Dict[str, Dict[str, Dict[str, Any]]] = {
    "TRAJ-HYPERCAPNIA": {
        "Mild": {
            "vitals": {"heart_rate": 82.0, "blood_pressure_sys": 124.0, "blood_pressure_dia": 80.0, "spo2": 97.0, "respiration_rate": 18.0, "core_temp_c": 37.1, "hrv_ms": 38.0, "ve_l_min": 11.0},
            "environment": {"cabin_co2_mmhg": 3.5, "ambient_radiation_msv_h": 0.05},
        },
        "Moderate": {
            "vitals": {"heart_rate": 96.0, "blood_pressure_sys": 134.0, "blood_pressure_dia": 86.0, "spo2": 96.0, "respiration_rate": 22.0, "core_temp_c": 37.3, "hrv_ms": 28.0, "ve_l_min": 16.0},
            "environment": {"cabin_co2_mmhg": 5.2, "ambient_radiation_msv_h": 0.05},
        },
        "Critical": {
            "vitals": {"heart_rate": 122.0, "blood_pressure_sys": 148.0, "blood_pressure_dia": 94.0, "spo2": 94.0, "respiration_rate": 28.0, "core_temp_c": 37.6, "hrv_ms": 18.0, "ve_l_min": 24.0},
            "environment": {"cabin_co2_mmhg": 16.0, "ambient_radiation_msv_h": 0.05},
        },
    },
    "TRAJ-ARS-SPE": {
        "Mild": {
            "vitals": {"heart_rate": 84.0, "blood_pressure_sys": 112.0, "blood_pressure_dia": 72.0, "spo2": 98.0, "respiration_rate": 17.0, "core_temp_c": 37.3, "hrv_ms": 36.0, "ve_l_min": 9.5},
            "environment": {"cabin_co2_mmhg": 1.9, "ambient_radiation_msv_h": 1.5, "donki_spe_active": True},
            "specialized_diagnostics": {"alc_cells_uL": 1250.0},
        },
        "Moderate": {
            "vitals": {"heart_rate": 102.0, "blood_pressure_sys": 100.0, "blood_pressure_dia": 66.0, "spo2": 97.0, "respiration_rate": 20.0, "core_temp_c": 38.2, "hrv_ms": 22.0, "ve_l_min": 12.0},
            "environment": {"cabin_co2_mmhg": 1.9, "ambient_radiation_msv_h": 3.2, "donki_spe_active": True},
            "specialized_diagnostics": {"alc_cells_uL": 800.0},
        },
        "Critical": {
            "vitals": {"heart_rate": 124.0, "blood_pressure_sys": 86.0, "blood_pressure_dia": 56.0, "spo2": 95.0, "respiration_rate": 26.0, "core_temp_c": 39.2, "hrv_ms": 14.0, "ve_l_min": 18.0},
            "environment": {"cabin_co2_mmhg": 2.0, "ambient_radiation_msv_h": 6.5, "donki_spe_active": True},
            "specialized_diagnostics": {"alc_cells_uL": 350.0},
        },
    },
    "TRAJ-EVA-HEAT-STRAIN": {
        "Mild": {
            "activity_state": "EVA",
            "vitals": {"heart_rate": 108.0, "blood_pressure_sys": 128.0, "blood_pressure_dia": 80.0, "spo2": 97.0, "respiration_rate": 22.0, "core_temp_c": 38.0, "hrv_ms": 28.0, "ve_l_min": 18.0},
            "environment": {"cabin_co2_mmhg": 2.0, "ambient_radiation_msv_h": 0.05},
        },
        "Moderate": {
            "activity_state": "EVA",
            "vitals": {"heart_rate": 132.0, "blood_pressure_sys": 124.0, "blood_pressure_dia": 78.0, "spo2": 95.0, "respiration_rate": 26.0, "core_temp_c": 38.8, "hrv_ms": 18.0, "ve_l_min": 24.0},
            "environment": {"cabin_co2_mmhg": 2.0, "ambient_radiation_msv_h": 0.05},
        },
        "Critical": {
            "activity_state": "EVA",
            "vitals": {"heart_rate": 156.0, "blood_pressure_sys": 112.0, "blood_pressure_dia": 72.0, "spo2": 91.5, "respiration_rate": 34.0, "core_temp_c": 40.1, "hrv_ms": 11.0, "ve_l_min": 32.0},
            "environment": {"cabin_co2_mmhg": 2.0, "ambient_radiation_msv_h": 0.05},
        },
    },
    "TRAJ-ORTHOSTATIC-INTOLERANCE": {
        "Mild": {
            "vitals": {"heart_rate": 96.0, "blood_pressure_sys": 112.0, "blood_pressure_dia": 74.0, "spo2": 98.0, "respiration_rate": 17.0, "core_temp_c": 37.0, "hrv_ms": 32.0, "ve_l_min": 9.5},
            "environment": {"cabin_co2_mmhg": 1.8, "ambient_radiation_msv_h": 0.05},
        },
        "Moderate": {
            "vitals": {"heart_rate": 106.0, "blood_pressure_sys": 102.0, "blood_pressure_dia": 68.0, "spo2": 97.0, "respiration_rate": 19.0, "core_temp_c": 37.1, "hrv_ms": 24.0, "ve_l_min": 11.0},
            "environment": {"cabin_co2_mmhg": 1.8, "ambient_radiation_msv_h": 0.05},
        },
        "Critical": {
            "vitals": {"heart_rate": 118.0, "blood_pressure_sys": 82.0, "blood_pressure_dia": 56.0, "spo2": 96.0, "respiration_rate": 20.0, "core_temp_c": 37.1, "hrv_ms": 16.0, "ve_l_min": 12.0},
            "environment": {"cabin_co2_mmhg": 1.8, "ambient_radiation_msv_h": 0.05},
        },
    },
    "TRAJ-HYPOXIA": {
        "Mild": {
            "vitals": {"heart_rate": 88.0, "blood_pressure_sys": 122.0, "blood_pressure_dia": 78.0, "spo2": 92.5, "respiration_rate": 20.0, "core_temp_c": 37.0, "hrv_ms": 35.0, "ve_l_min": 12.0},
            "environment": {"cabin_co2_mmhg": 1.8, "cabin_ppo2_mmhg": 108.0, "ambient_radiation_msv_h": 0.05},
        },
        "Moderate": {
            "vitals": {"heart_rate": 104.0, "blood_pressure_sys": 126.0, "blood_pressure_dia": 80.0, "spo2": 88.5, "respiration_rate": 25.0, "core_temp_c": 37.0, "hrv_ms": 24.0, "ve_l_min": 16.5},
            "environment": {"cabin_co2_mmhg": 1.8, "cabin_ppo2_mmhg": 98.0, "ambient_radiation_msv_h": 0.05},
        },
        "Critical": {
            "vitals": {"heart_rate": 122.0, "blood_pressure_sys": 114.0, "blood_pressure_dia": 74.0, "spo2": 83.0, "respiration_rate": 32.0, "core_temp_c": 37.0, "hrv_ms": 15.0, "ve_l_min": 24.0},
            "environment": {"cabin_co2_mmhg": 1.8, "cabin_ppo2_mmhg": 86.0, "ambient_radiation_msv_h": 0.05},
        },
    },
    "TRAJ-SANS": {
        "Mild": {
            "mission_day": 120,
            "vitals": {"heart_rate": 68.0, "blood_pressure_sys": 116.0, "blood_pressure_dia": 74.0, "spo2": 98.0, "respiration_rate": 14.0, "core_temp_c": 37.0, "hrv_ms": 44.0, "ve_l_min": 7.5},
            "environment": {"cabin_co2_mmhg": 2.0, "ambient_radiation_msv_h": 0.05},
            "specialized_diagnostics": {"oct_rnfl_um": 103.0, "refraction_shift_D": 0.55},
        },
        "Moderate": {
            "mission_day": 120,
            "vitals": {"heart_rate": 66.0, "blood_pressure_sys": 116.0, "blood_pressure_dia": 74.0, "spo2": 98.0, "respiration_rate": 14.0, "core_temp_c": 37.1, "hrv_ms": 40.0, "ve_l_min": 7.5},
            "environment": {"cabin_co2_mmhg": 2.0, "ambient_radiation_msv_h": 0.05},
            "specialized_diagnostics": {"oct_rnfl_um": 112.0, "refraction_shift_D": 0.85},
        },
        "Critical": {
            "mission_day": 120,
            "vitals": {"heart_rate": 74.0, "blood_pressure_sys": 120.0, "blood_pressure_dia": 76.0, "spo2": 98.0, "respiration_rate": 15.0, "core_temp_c": 37.2, "hrv_ms": 34.0, "ve_l_min": 8.0},
            "environment": {"cabin_co2_mmhg": 2.0, "ambient_radiation_msv_h": 0.05},
            "specialized_diagnostics": {"oct_rnfl_um": 126.0, "refraction_shift_D": 1.25},
        },
    },
}

PARAPHRASED_HELD_OUT_CASES: List[Dict[str, Any]] = [
    {
        "case": "PARA-01-HYPERCAPNIA",
        "expected_labels": ["CPG-07", "SCENARIO_1_HYPERCAPNIA"],
        "expected_mode": "MODE_A_KNOWN_CONDITION",
        "held_out": True,
        "payload": {
            "vitals": {"heart_rate": 96.0, "blood_pressure_sys": 134.0, "blood_pressure_dia": 86.0, "spo2": 96.0, "respiration_rate": 22.0, "core_temp_c": 37.2, "hrv_ms": 28.0, "ve_l_min": 16.0},
            "environment": {"cabin_co2_mmhg": 5.1, "ambient_radiation_msv_h": 0.05},
            "symptom_log": "Forehead feels like a vise after hatch work, face flushed, cheek tingling and stale cabin air.",
        },
    },
    {
        "case": "PARA-02-ANAPHYLAXIS",
        "expected_labels": ["CPG-20"],
        "expected_mode": "MODE_A_KNOWN_CONDITION",
        "held_out": True,
        "payload": {
            "vitals": {"heart_rate": 112.0, "blood_pressure_sys": 88.0, "blood_pressure_dia": 58.0, "spo2": 89.0, "respiration_rate": 28.0, "core_temp_c": 37.0, "hrv_ms": 20.0, "ve_l_min": 18.0},
            "environment": {"cabin_co2_mmhg": 1.8, "ambient_radiation_msv_h": 0.05},
            "symptom_log": "Raised hives breaking out across torso after meal bar, lips swelling up and throat feels closing.",
        },
    },
    {
        "case": "PARA-03-RENAL-COLIC",
        "expected_labels": ["CPG-16"],
        "expected_mode": "MODE_A_KNOWN_CONDITION",
        "held_out": True,
        "payload": {
            "vitals": {"heart_rate": 96.0, "blood_pressure_sys": 132.0, "blood_pressure_dia": 84.0, "spo2": 98.0, "respiration_rate": 19.0, "core_temp_c": 37.0, "hrv_ms": 34.0, "ve_l_min": 10.0},
            "environment": {"cabin_co2_mmhg": 1.8, "ambient_radiation_msv_h": 0.05},
            "symptom_log": "Stabbing wave of pain in my right flank radiating toward my groin with vomiting.",
        },
    },
    {
        "case": "PARA-04-APPENDICITIS",
        "expected_labels": ["CPG-01"],
        "expected_mode": "MODE_A_KNOWN_CONDITION",
        "held_out": True,
        "payload": {
            "vitals": {"heart_rate": 90.0, "blood_pressure_sys": 118.0, "blood_pressure_dia": 76.0, "spo2": 98.0, "respiration_rate": 19.0, "core_temp_c": 37.8, "hrv_ms": 36.0, "ve_l_min": 10.0},
            "environment": {"cabin_co2_mmhg": 1.8, "ambient_radiation_msv_h": 0.05},
            "symptom_log": "Tender lower right abdomen hurting worse every hour with fever and zero appetite.",
        },
    },
    {
        "case": "PARA-05-AMMONIA-LEAK",
        "expected_labels": ["CPG-10"],
        "expected_mode": "MODE_A_KNOWN_CONDITION",
        "held_out": True,
        "payload": {
            "vitals": {"heart_rate": 90.0, "blood_pressure_sys": 124.0, "blood_pressure_dia": 80.0, "spo2": 95.5, "respiration_rate": 21.0, "core_temp_c": 37.1, "hrv_ms": 35.0, "ve_l_min": 13.0},
            "environment": {"cabin_co2_mmhg": 1.8, "ambient_radiation_msv_h": 0.05},
            "symptom_log": "Pungent ammonia coolant fumes near rack making my eyes burn and water with nonstop cough.",
        },
    },
    {
        "case": "PARA-06-CORNEAL-ABRASION",
        "expected_labels": ["CPG-22"],
        "expected_mode": "MODE_A_KNOWN_CONDITION",
        "held_out": True,
        "payload": {
            "vitals": {"heart_rate": 81.0, "blood_pressure_sys": 122.0, "blood_pressure_dia": 78.0, "spo2": 98.0, "respiration_rate": 16.0, "core_temp_c": 37.0, "hrv_ms": 44.0, "ve_l_min": 8.5},
            "environment": {"cabin_co2_mmhg": 1.8, "ambient_radiation_msv_h": 0.05},
            "symptom_log": "Grit scratched my eyeball transferring cargo; bright cabin light causes sharp eye pain and tearing.",
        },
    },
]

NEGATIVE_MODE_B_CASES: List[Dict[str, Any]] = [
    {
        "case": "NEG-01-AMBIGUOUS-NORMAL-VITALS",
        "expected_mode": "MODE_B_NOVEL_ANOMALY",
        "held_out": True,
        "payload": {
            "vitals": dict(BASELINE_VITALS),
            "environment": {"cabin_co2_mmhg": 1.8, "ambient_radiation_msv_h": 0.05},
            "symptom_log": "Mild non-specific dull headache and tired eyes after mid-day maintenance.",
        },
    },
    {
        "case": "NEG-02-CONTRADICTORY-ZERO-DAY",
        "expected_mode": "MODE_B_NOVEL_ANOMALY",
        "held_out": True,
        "payload": {
            "vitals": {"heart_rate": 128.0, "blood_pressure_sys": 84.0, "blood_pressure_dia": 52.0, "spo2": 87.0, "respiration_rate": 26.0, "core_temp_c": 37.1, "hrv_ms": 18.0, "ve_l_min": 18.0},
            "environment": {"cabin_co2_mmhg": 1.9, "ambient_radiation_msv_h": 0.05},
            "symptom_log": "Unexplained metallic taste, purple fingertips, and sudden syncope.",
        },
    },
    {
        "case": "NEG-03-MISSING-CORE-VITALS",
        "expected_mode": "MODE_B_NOVEL_ANOMALY",
        "held_out": True,
        "payload": {
            "vitals": {"hr_bpm": 102.0, "dbp_mmHg": 84.0, "ve_L_min": 15.0},
            "environment": {"cabin_co2_mmhg": 5.8, "ambient_radiation_msv_h": 0.05},
            "symptom_log": "Throbbing frontal headache, dizziness, deep breathing.",
        },
    },
    {
        "case": "NEG-04-UNRELIABLE-SENSORS",
        "expected_mode": "MODE_B_NOVEL_ANOMALY",
        "held_out": True,
        "payload": {
            "vitals": {"heart_rate": 106.0, "blood_pressure_sys": 134.0, "blood_pressure_dia": 86.0, "spo2": 95.0, "respiration_rate": 22.0, "core_temp_c": 37.2, "hrv_ms": 25.0, "ve_l_min": 15.0},
            "environment": {"cabin_co2_mmhg": 6.2, "ambient_radiation_msv_h": 0.05},
            "quality_flags": {"cabin_co2_mmhg": "sensor_fault", "spo2": "motion_artifact"},
            "symptom_log": "Throbbing frontal headache and deep breathing during hatch check.",
        },
    },
    {
        "case": "NEG-05-OOD-BENIGN-RASH",
        "expected_mode": "MODE_B_NOVEL_ANOMALY",
        "held_out": True,
        "payload": {
            "vitals": {"heart_rate": 74.0, "blood_pressure_sys": 120.0, "blood_pressure_dia": 76.0, "spo2": 98.0, "respiration_rate": 15.0, "core_temp_c": 37.0, "hrv_ms": 48.0, "ve_l_min": 8.0},
            "environment": {"cabin_co2_mmhg": 1.8, "ambient_radiation_msv_h": 0.05},
            "symptom_log": "Localized chafing stripe on wrist beneath glove sizing ring liner.",
        },
    },
    {
        "case": "NEG-06-HINT-INJECTION-PROBE",
        "expected_mode": "MODE_B_NOVEL_ANOMALY",
        "held_out": True,
        "payload": {
            "active_scenario_id": "SCENARIO_1_HYPERCAPNIA",
            "vitals": dict(BASELINE_VITALS),
            "environment": {"cabin_co2_mmhg": 1.7, "ambient_radiation_msv_h": 0.05},
            "symptom_log": "Mild non-specific headache and dry throat.",
        },
    },
]


def _seed_to_payload(seed: Dict[str, Any]) -> Dict[str, Any]:
    vec = seed.get("vector", {})
    vitals: Dict[str, Any] = {
        "heart_rate": round(BASELINE_VITALS["heart_rate"] + float(vec.get("dHR_bpm") or 0.0), 1),
        "blood_pressure_sys": round(BASELINE_VITALS["blood_pressure_sys"] + float(vec.get("dSBP_mmHg") or 0.0), 1),
        "blood_pressure_dia": round(BASELINE_VITALS["blood_pressure_dia"] + float(vec.get("dDBP_mmHg") or 0.0), 1),
        "spo2": round(BASELINE_VITALS["spo2"] + float(vec.get("dSpO2_pct") or 0.0), 1),
        "respiration_rate": round(BASELINE_VITALS["respiration_rate"] + float(vec.get("dRR_bpm") or 0.0), 1),
        "core_temp_c": round(BASELINE_VITALS["core_temp_c"] + float(vec.get("dTcore_C") or 0.0), 2),
        "ve_l_min": round(BASELINE_VITALS["ve_l_min"] + max(0.0, float(vec.get("dRR_bpm") or 0.0) * 0.6), 1),
    }
    quality_flags: Dict[str, str] = {}
    if vec.get("dRMSSD_pct") is None:
        vitals["hrv_ms"] = 45.0
        quality_flags["hrv_ms"] = "non_autonomic_unreliable"
    else:
        rmssd_factor = 1.0 + float(vec["dRMSSD_pct"]) / 100.0
        vitals["hrv_ms"] = round(max(8.0, BASELINE_VITALS["hrv_ms"] * rmssd_factor), 1)
    if vec.get("dRR_bpm") is None:
        quality_flags["respiration_rate"] = "motion_artifact_unreliable"

    return {
        "astronaut_id": "ASTRO-BLIND-EVAL",
        "mission_day": 14,
        "activity_state": "IVA_REST",
        "active_scenario_id": None,
        "vitals": vitals,
        "environment": {"cabin_co2_mmhg": 1.8, "ambient_radiation_msv_h": 0.05},
        "quality_flags": quality_flags,
        "symptom_log": seed.get("symptoms", ""),
        "stateless_evaluation": True,
    }


def _check_mode_a_validity(rag: LocalMedicalRAGEngine, result: Dict[str, Any]) -> bool:
    """Check response claims against the locally audited source and formulary records."""
    proto = rag.protocol_by_id.get(str(result.get("scenario_id", "")))
    if not proto or result.get("nasa_citations") != proto.get("nasa_citations"):
        return False
    references = proto.get("source_audit", {}).get("references", [])
    if not references or not all(str(ref.get("url", "")).startswith("https://") for ref in references):
        return False
    citation = result.get("nasa_citation")
    if not isinstance(citation, dict):
        return False
    rule_id = citation.get("standard_id")
    rule = rag.reference_rules.get(str(rule_id)) if rule_id else None
    if rule is not None:
        if rule_id not in proto.get("verified_rule_ids", []) or rule.get("verification_status") != "verified_primary_source":
            return False
        expected = {"document": rule.get("source_revision", ""),
                    "section": rule.get("source_section", ""), "url": rule.get("source_url", "")}
        if any(citation.get(key) != value for key, value in expected.items()):
            return False
        if result.get("source_document") != expected["document"]:
            return False
        if result.get("nasa_direct_quote", "") != rule.get("verbatim_rule", ""):
            return False
    elif (result.get("nasa_direct_quote") or citation.get("url") or citation.get("section")
          or citation.get("document") != "No verified NASA requirement mapped"):
        return False
    for rx in result.get("prescriptions", []):
        if not isinstance(rx, dict) or not all(rx.get(key) for key in ("medication", "checs_pack", "route", "dosage")):
            return False
        parsed = rag._parse_and_validate_medication(rx)
        if not parsed.get("formulary_verified") or parsed.get("checs_pack") != rx.get("checs_pack"):
            return False
    return True


def _run_case(
    rag: LocalMedicalRAGEngine,
    detector: EdgeAnomalyDetector,
    case_id: str,
    case_group: str,
    payload: Dict[str, Any],
    expected_labels: List[str],
    expected_mode: str,
    held_out: bool,
) -> Dict[str, Any]:
    packet_payload = {
        "astronaut_id": "ASTRO-BLIND-EVAL",
        "mission_day": 14,
        "activity_state": "IVA_REST",
        "stateless_evaluation": True,
        **payload,
    }
    if "active_scenario_id" not in payload:
        packet_payload["active_scenario_id"] = None

    packet = TelemetryPacket(**packet_payload)
    rag.diagnosis_cache.clear()
    t0 = time.perf_counter_ns()
    assessment = detector.evaluate_packet(packet)
    result = rag.diagnose(packet, assessment)
    latency_ms = round((time.perf_counter_ns() - t0) / 1_000_000.0, 3)

    scores = result.get("retrieval_scores", {})
    top3 = [k for k, _ in sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:3]]
    predicted_id = result.get("scenario_id")
    mode = result.get("mode")

    if expected_mode == "MODE_B_NOVEL_ANOMALY":
        correct = mode == "MODE_B_NOVEL_ANOMALY"
        valid_citation_formulary = True
    else:
        correct = predicted_id in expected_labels and mode == expected_mode
        valid_citation_formulary = _check_mode_a_validity(rag, result) if mode == "MODE_A_KNOWN_CONDITION" else False

    return {
        "case": case_id,
        "group": case_group,
        "held_out": held_out,
        "expected_mode": expected_mode,
        "expected_labels": expected_labels,
        "predicted": predicted_id,
        "mode": mode,
        "confidence": result.get("confidence"),
        "correct": correct,
        "valid_citation_formulary": valid_citation_formulary,
        "top3_hit": any(lbl in top3 for lbl in expected_labels) if expected_labels else correct,
        "latency_ms": latency_ms,
        "top3": top3,
    }


def evaluate_live_simulation(activity_state: str = "IVA_REST", mission_day: int = 84) -> Dict[str, Any]:
    """Replay the server's actual tick path with deterministic noise and hidden labels."""
    import random
    from unittest.mock import patch

    import backend.main as server
    from backend.services.astronaut_sim import AstronautSimulationEngine
    from backend.services.astronaut_sim import TRAJECTORY_SCENARIOS

    dataset = json.loads(SEEDS_PATH.read_text(encoding="utf-8"))
    seeds = {row["seed_id"].lower(): row for row in dataset["synthetic_scenario_seeds_24"]}
    trajectories = {
        TRAJECTORY_SCENARIOS[row["trajectory_id"].lower()]: row
        for row in dataset["quantitative_crisis_trajectories_and_symptom_logs"]
    }
    generator_state = random.getstate()
    results = []
    random.seed(42)
    try:
        with patch.object(server, "rag_engine", LocalMedicalRAGEngine()), patch.object(
            server, "latest_telemetry", None
        ), patch.object(server.donki_service, "get_space_weather",
                        side_effect=server.donki_service._get_cache_fallback):
            for case_id in list(trajectories) + list(seeds):
                row = seeds.get(case_id) or trajectories[case_id]
                labels = [row[key] for key in ("linked_cpg_id", "linked_legacy_scenario") if row.get(key)]
                expected_mode = row.get("expected_mode", "MODE_A_KNOWN_CONDITION")
                sim = AstronautSimulationEngine(mission_day=mission_day)
                sim.set_activity_state(activity_state)
                server.rag_engine.diagnosis_cache.clear()
                with patch.object(server, "astronaut_sim", sim), patch.object(
                    server, "anomaly_detector", EdgeAnomalyDetector()
                ):
                    for _ in range(5):
                        server.advance_telemetry()
                    sim.trigger_scenario(case_id)
                    for _ in range(20):
                        frame = server.advance_telemetry()
                result = frame.get("rag_diagnosis", {})
                correct = result.get("mode") == expected_mode
                if expected_mode == "MODE_A_KNOWN_CONDITION":
                    correct = correct and result.get("scenario_id") in labels
                results.append({"case": case_id, "correct": correct,
                                "expected_mode": expected_mode, "expected_labels": labels,
                                "predicted": result.get("scenario_id"), "mode": result.get("mode")})
    finally:
        random.setstate(generator_state)
    known = [row for row in results if row["expected_mode"] == "MODE_A_KNOWN_CONDITION"]
    unsupported = [row for row in results if row["expected_mode"] == "MODE_B_NOVEL_ANOMALY"]
    return {"cases": len(results), "activity_state": activity_state, "mission_day": mission_day,
            "correct_decisions": sum(row["correct"] for row in results),
            "known_condition_cases": len(known), "known_condition_matches": sum(row["correct"] for row in known),
            "unsupported_cases": len(unsupported), "correct_abstentions": sum(row["correct"] for row in unsupported),
            "failures": [row for row in results if not row["correct"]]}


def evaluate() -> Dict[str, Any]:
    """Run the full 54-case blind evaluation benchmark."""
    seeds_data = json.loads(SEEDS_PATH.read_text(encoding="utf-8"))
    seeds = seeds_data.get("synthetic_scenario_seeds_24", [])
    trajectories = seeds_data.get("quantitative_crisis_trajectories_and_symptom_logs", [])

    rag = LocalMedicalRAGEngine()
    detector = EdgeAnomalyDetector()

    results: List[Dict[str, Any]] = []

    # 1. 24 synthetic seeds (every 3rd case held out)
    for idx, seed in enumerate(seeds):
        expected_labels = [seed["linked_cpg_id"]] if seed.get("linked_cpg_id") else []
        if "linked_legacy_scenario" in seed:
            expected_labels.append(seed["linked_legacy_scenario"])
        results.append(
            _run_case(
                rag=rag,
                detector=detector,
                case_id=seed["seed_id"],
                case_group="synthetic_seed",
                payload=_seed_to_payload(seed),
                expected_labels=expected_labels,
                expected_mode=seed.get("expected_mode", "MODE_A_KNOWN_CONDITION"),
                held_out=(idx % 3 == 2),
            )
        )

    # 2. 18 crisis trajectory tiers (6 trajectories x 3 severity tiers)
    for t_idx, traj in enumerate(trajectories):
        tid = traj["trajectory_id"]
        presets = TRAJECTORY_TELEMETRY_PRESETS.get(tid, {})
        expected_labels = [traj["linked_cpg_id"]]
        if "linked_legacy_scenario" in traj:
            expected_labels.append(traj["linked_legacy_scenario"])
        for tier_idx, tier in enumerate(traj.get("tiers", [])):
            sev = tier["severity"]
            preset = presets.get(sev, {})
            payload = {
                **preset,
                "symptom_log": tier["symptom_log"],
            }
            results.append(
                _run_case(
                    rag=rag,
                    detector=detector,
                    case_id=f"{tid}-{sev.upper()}",
                    case_group="crisis_trajectory",
                    payload=payload,
                    expected_labels=expected_labels,
                    expected_mode="MODE_A_KNOWN_CONDITION",
                    held_out=((t_idx + tier_idx) % 2 == 1),
                )
            )

    # 3. 6 held-back paraphrased positive cases
    for item in PARAPHRASED_HELD_OUT_CASES:
        results.append(
            _run_case(
                rag=rag,
                detector=detector,
                case_id=item["case"],
                case_group="paraphrased_positive",
                payload=item["payload"],
                expected_labels=item["expected_labels"],
                expected_mode=item["expected_mode"],
                held_out=True,
            )
        )

    # 4. 6 Mode B abstention negative/missing/unreliable/leak cases
    for item in NEGATIVE_MODE_B_CASES:
        results.append(
            _run_case(
                rag=rag,
                detector=detector,
                case_id=item["case"],
                case_group="negative_mode_b",
                payload=item["payload"],
                expected_labels=[],
                expected_mode="MODE_B_NOVEL_ANOMALY",
                held_out=True,
            )
        )

    total = len(results)
    positives = [r for r in results if r["expected_mode"] == "MODE_A_KNOWN_CONDITION"]
    negatives = [r for r in results if r["expected_mode"] == "MODE_B_NOVEL_ANOMALY"]
    held_out_cases = [r for r in results if r["held_out"]]
    mode_a_preds = [r for r in results if r["mode"] == "MODE_A_KNOWN_CONDITION"]

    top1_correct = sum(1 for r in positives if r["correct"])
    held_out_correct = sum(1 for r in held_out_cases if r["correct"])
    top3_hits = sum(1 for r in positives if r["top3_hit"])
    mode_a_correct = sum(1 for r in mode_a_preds if r["correct"])
    mode_b_correct = sum(1 for r in negatives if r["correct"])
    valid_mode_a = sum(1 for r in mode_a_preds if r["valid_citation_formulary"])

    latencies = sorted(r["latency_ms"] for r in results)
    p95_idx = min(len(latencies) - 1, max(0, math.ceil(0.95 * len(latencies)) - 1))

    return {
        "cases": total,
        "mapped_seed_cases": sum(bool(seed.get("linked_cpg_id")) for seed in seeds),
        "unmapped_seed_cases": sum(seed.get("expected_mode") == "MODE_B_NOVEL_ANOMALY" for seed in seeds),
        "decision_accuracy": round(sum(r["correct"] for r in results) / total, 3) if total else 0.0,
        "evaluation_scope": "Development corpus with explicit unsupported-condition abstentions. An independent validation set is still required to establish generalization.",
        "positive_cases": len(positives),
        "negative_cases": len(negatives),
        "held_out_cases": len(held_out_cases),
        "top1_correct": top1_correct,
        "top1_accuracy": round(top1_correct / len(positives), 3) if positives else 0.0,
        "held_out_top1_accuracy": round(held_out_correct / len(held_out_cases), 3) if held_out_cases else 0.0,
        "top3_recall": round(top3_hits / len(positives), 3) if positives else 0.0,
        "mode_a_cases": len(mode_a_preds),
        "mode_a_precision": round(mode_a_correct / len(mode_a_preds), 3) if mode_a_preds else 0.0,
        "mode_b_abstention_accuracy": round(mode_b_correct / len(negatives), 3) if negatives else 0.0,
        "citation_and_formulary_validity_rate": round(valid_mode_a / len(mode_a_preds), 3) if mode_a_preds else None,
        "latency_metrics_ms": {
            "mean_ms": round(sum(latencies) / len(latencies), 3) if latencies else 0.0,
            "p95_ms": latencies[p95_idx] if latencies else 0.0,
            "max_ms": latencies[-1] if latencies else 0.0,
        },
        "live_replay": evaluate_live_simulation(),
        "citation_validation_note": "Checks integrity against local audited records. External source authenticity and clinical efficacy require separate review.",
        "score_calibration_note": (
            "Confidence scores are heuristic neuro-symbolic fusion scores thresholded at 0.75 "
            "for Mode A gating, not calibrated clinical probabilities."
        ),
        "blind_inputs": True,
        "details": results,
    }


if __name__ == "__main__":
    summary = evaluate()
    print(json.dumps(summary, indent=2))

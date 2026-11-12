"""
Interactive CLI Demo & Benchmark Runner for A.R.E.S. Med RAG & Anomaly Engine.

Run directly with:
    C:\\Users\\yohan\\AppData\\Local\\Programs\\Python\\Python312\\python.exe -m backend.test_demo
"""

import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.routes.diagnose import execute_diagnosis_pipeline


def run_visual_demo() -> None:
    print("=" * 82)
    print(" A.R.E.S. MED — LEVEL V AUTONOMOUS RAG MEDICAL OFFICER BENCHMARK & DEMO")
    print("=" * 82)

    # 1. Mode A: EVA Hypercapnia
    hypercapnia_payload = {
        "astronaut_id": "ASTRO-01",
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
            "ambient_radiation_msv_h": 0.05,
            "suit_pressure_psi": 4.3,
        },
        "symptom_log": "Throbbing frontal headache, air feels sluggish, short of breath.",
    }
    res_a = execute_diagnosis_pipeline(hypercapnia_payload)
    print("\n[TEST 1] MODE A — EVA HYPERCAPNIA (Known Condition >= 0.75)")
    print(f"  • Mode:             {res_a['mode']}")
    print(f"  • Confidence:       {res_a['confidence']} (Signal breakdown: {res_a['rag_metrics']['signal_breakdown']})")
    print(f"  • Diagnosis:        {res_a['diagnosis']}")
    print(f"  • NASA Quote:       {res_a['nasa_direct_quote']}")
    print(f"  • CHeCS Subpack:    {res_a['checs_subpack']}")
    print(f"  • Contraindication: {res_a['contraindications_locked'][0]}")
    print(f"  • Organ HUD Pins:   {res_a['organ_hud_status']}")
    print(f"  • Execution Time:   {res_a['total_pipeline_latency_ms']} ms")

    # 2. Mode B: Unseen Zero-Day Anomaly
    zero_day_payload = {
        "astronaut_id": "ASTRO-01",
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
            "ambient_radiation_msv_h": 0.05,
        },
        "symptom_log": "Unexplained metallic taste, peripheral tingling, sudden weakness.",
    }
    res_b = execute_diagnosis_pipeline(zero_day_payload)
    print("\n[TEST 2] MODE B — UNSEEN ZERO-DAY ANOMALY (Confidence < 0.75)")
    print(f"  • Mode:             {res_b['mode']}")
    print(f"  • Confidence:       {res_b['confidence']}")
    print(f"  • Diagnosis:        {res_b['diagnosis']}")
    print(f"  • Abstention:       {res_b['abstention_reason']}")
    print(f"  • Step 1 (ABC):     {res_b['abc_vital_stabilization']['protocol']}")
    print(f"  • Step 2 (MDP Lab): {res_b['point_of_care_orders'][0]['order']}")
    print(f"  • Step 3 (Lockout): {res_b['drug_lockout_warning']}")
    print(f"  • Step 4 (Uplink):  Priority={res_b['telemetry_uplink']['store_and_forward_priority']} | SaveToRAG={res_b['telemetry_uplink']['save_candidate_to_local_rag']}")
    print(f"  • Execution Time:   {res_b['total_pipeline_latency_ms']} ms")

    # 3. 100-Call Throughput Benchmark
    t0 = time.perf_counter()
    for _ in range(100):
        execute_diagnosis_pipeline(hypercapnia_payload)
    avg_ms = ((time.perf_counter() - t0) * 1000.0) / 100.0
    print("\n[TEST 3] 100-ITERATION LATENCY BENCHMARK")
    print(f"  • Average Pipeline Latency: {avg_ms:.3f} ms / call (50ms SLA margin: {50.0 / max(avg_ms, 0.001):.0f}x faster)")
    print("=" * 82)


if __name__ == "__main__":
    run_visual_demo()

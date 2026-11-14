"""
A.R.E.S. Med — 60-Second "Golden Loop" Automated Pitch & Demo Runner.
Maintained by Dheer for Roy and team presentation.
Strictly adheres to JPL Power-of-Ten rules (zero emojis).

Demonstrates the complete closed-loop medical autonomy in 4 phases:
Phase 1: Nominal Baseline (94% Mission Readiness, Sinus Arrhythmia)
Phase 2: Acute Life-Support Failure (CO2 Hypercapnia Crisis Injection)
Phase 3: Autonomous Level V RAG Diagnosis (<1ms, 99% confidence, verbatim NASA quote, drug lockouts)
Phase 4: Closed-Loop Washout Recovery (Countermeasure heals vitals back to nominal)
"""

import sys
import time
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from backend.routes.diagnose import anomaly_detector, rag_engine
from backend.services.astronaut_sim import astronaut_sim


def print_separator(char: str = "=", length: int = 85) -> None:
    print(char * length)


def print_frame(packet, assessment=None, prefix: str = "TICK") -> None:
    v = packet.vitals
    e = packet.environment
    alert = assessment.alert_level if assessment else "NOMINAL"
    readiness = assessment.readiness_score_0_100 if assessment else 94
    print(
        f"[{prefix}] MET: {packet.met} | "
        f"HR: {v.heart_rate:5.1f} bpm | "
        f"BP: {int(v.blood_pressure_sys)}/{int(v.blood_pressure_dia)} | "
        f"SpO2: {v.spo2:4.1f}% | "
        f"CO2: {e.cabin_co2_mmhg:4.1f} mmHg | "
        f"Alert: {alert:<14} | Readiness: {readiness}%"
    )
    if packet.symptom_log and prefix.startswith(("CRISIS", "RECOVERY")):
        print(f"       Symptom Feed: \"{packet.symptom_log}\"")


def run_golden_loop() -> None:
    print_separator("=")
    print(" A.R.E.S. MED — 60-SECOND AUTONOMOUS SPACE MEDICINE DEMONSTRATION")
    print(" Target: Cmdr. Maya Lin (ASTRO-01) | 20-Minute Mars Comms Delay Active")
    print("=" * 85)
    time.sleep(1.0)

    # ---------------------------------------------------------
    # PHASE 1: NOMINAL FLIGHT MONITORING (5 ticks)
    # ---------------------------------------------------------
    print("\n--- PHASE 1: NOMINAL MICROGRAVITY BASELINE (Adapted Post-FD75) ---")
    astronaut_sim.trigger_scenario("nominal")
    astronaut_sim.set_activity_state("IVA_REST")

    for i in range(5):
        p = astronaut_sim.step()
        p.active_scenario_id = None
        p.stateless_evaluation = False
        assessment = anomaly_detector.evaluate_packet(p)
        print_frame(p, assessment, prefix=f"NOMINAL {i+1}/5")
        time.sleep(0.8)

    # ---------------------------------------------------------
    # PHASE 2: ACUTE CRISIS INJECTION (Hypercapnia)
    # ---------------------------------------------------------
    print("\n--- PHASE 2: CRISIS INJECTION — ECLSS CO2 SCRUBBER FAILURE ---")
    print("[CRISIS TRIGGERED] Cabin ppCO2 rising rapidly beyond NASA safe threshold...")
    astronaut_sim.trigger_scenario("hypercapnia")

    crisis_packet = None
    crisis_assessment = None
    for i in range(8):
        p = astronaut_sim.step()
        p.active_scenario_id = None
        p.stateless_evaluation = False
        assessment = anomaly_detector.evaluate_packet(p)
        print_frame(p, assessment, prefix=f"CRISIS  {i+1}/8")
        crisis_packet = p
        crisis_assessment = assessment
        time.sleep(0.8)

    # ---------------------------------------------------------
    # PHASE 3: AUTONOMOUS LEVEL V RAG DIAGNOSIS
    # ---------------------------------------------------------
    print("\n--- PHASE 3: AUTONOMOUS LEVEL V RAG MEDICAL OFFICER DIAGNOSIS ---")
    t0 = time.perf_counter()
    diag = rag_engine.diagnose(crisis_packet, crisis_assessment)
    dt_ms = (time.perf_counter() - t0) * 1000.0

    print(f"  Diagnosis ID:       {diag.get('diagnosis_id')}")
    print(f"  Condition:          {diag.get('condition')}")
    print(f"  Clinical Mode:      {diag.get('mode')} (Confidence: {diag.get('confidence'):.2f})")
    print(f"  Execution Latency:  {dt_ms:.3f} ms (SLA Budget: 50.0 ms)")
    print(f"  Verbatim Standard:  {diag.get('nasa_direct_quote')}")
    print(f"  CHeCS Subpack:      {diag.get('checs_subpack')}")
    print(f"  Safety Lockout:     {diag.get('contraindications_locked')}")
    print(f"  Primary Action:     {diag.get('action_plan', [''])[0]}")
    time.sleep(1.5)

    # ---------------------------------------------------------
    # PHASE 4: CLOSED-LOOP WASHOUT RECOVERY
    # ---------------------------------------------------------
    print("\n--- PHASE 4: CLOSED-LOOP COUNTERMEASURE & WASHOUT RECOVERY ---")
    print("[TREATMENT APPLIED] LiOH Scrubber Canister Replacement + 100% O2 Flush")
    astronaut_sim.apply_treatment("LiOH Canister Replacement + 100% O2 Flush")

    for i in range(10):
        p = astronaut_sim.step()
        p.active_scenario_id = None
        p.stateless_evaluation = False
        assessment = anomaly_detector.evaluate_packet(p)
        print_frame(p, assessment, prefix=f"RECOVERY {i+1}/10")
        time.sleep(0.8)

    print("\n--- DEMO COMPLETE: ASTRONAUT FULLY STABILIZED BACK TO NOMINAL BASELINE ---")
    print_separator("=")


if __name__ == "__main__":
    run_golden_loop()

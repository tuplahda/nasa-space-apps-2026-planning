"""
Interactive Terminal Runner for Autonomous Astronaut Agent Engine.
Run with: python "Autonomous agent(dheer)/run_sim.py"
Allows real-time terminal preview of 1Hz telemetry ticking with keyboard triggers.
Zero emojis. JPL Power-of-Ten compliant.
"""

import os
import sys
import time
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from backend.services.astronaut_sim import astronaut_sim


def main() -> None:
    print("=" * 80)
    print(" A.R.E.S. MED - AUTONOMOUS ASTRONAUT AGENT ENGINE (DHEER)")
    print(" Live 1Hz Microgravity Biotelemetry Generator")
    print(" Target: Cmdr. Maya Lin (ASTRO-01) | Mission Day 84")
    print("=" * 80)
    print("Commands:")
    print("  [h] Trigger Hypercapnia (CO2 Scrubber Failure)")
    print("  [f] Trigger Solar Flare (High-Flux Radiation Event)")
    print("  [s] Trigger SANS (Neuro-Ocular Syndrome)")
    print("  [d] Trigger Decompression (Suit Pressure Drop)")
    print("  [c] Apply Countermeasure (Initiate Smooth Biological Recovery)")
    print("  [1] Set State: SLEEP")
    print("  [2] Set State: IVA_REST")
    print("  [3] Set State: ARED_EXERCISE")
    print("  [4] Set State: EVA_SPACEWALK")
    print("  [q] Quit Simulation Runner")
    print("-" * 80)

    try:
        iteration = 0
        while True:
            iteration += 1
            packet = astronaut_sim.step()
            v = packet.vitals
            e = packet.environment

            rec_flag = " [RECOVERING]" if astronaut_sim.is_recovering else ""
            scen_tag = f"{packet.active_scenario_id.upper()}{rec_flag}"

            print(
                f"[{packet.met}] State: {packet.activity_state:<13} | "
                f"HR: {v.heart_rate:5.1f} bpm | "
                f"BP: {int(v.blood_pressure_sys)}/{int(v.blood_pressure_dia)} | "
                f"SpO2: {v.spo2:4.1f}% | "
                f"CO2: {e.cabin_co2_mmhg:4.1f} mmHg | "
                f"Rad: {e.ambient_radiation_msv_h:5.3f} mSv/h | "
                f"Mode: {scen_tag}"
            )

            # Print symptom if non-nominal
            if packet.active_scenario_id != "nominal" or astronaut_sim.is_recovering:
                print(f"    Symptom Feed: \"{packet.symptom_log}\"")

            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\nSimulation runner terminated by user.")


if __name__ == "__main__":
    main()

"""
Comprehensive Verification Test Suite for Autonomous Astronaut Agent Engine.
Maintained by Dheer. Strictly adheres to JPL Power-of-Ten rules (zero emojis).
"""

import sys
import unittest
from unittest.mock import patch
from pathlib import Path

# Ensure workspace root is in sys.path
WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from backend.models.telemetry import TelemetryPacket
from backend.services.astronaut_sim import (
    ACTIVITY_PROFILES,
    AstronautSimulationEngine,
)
from backend.services.donki_service import donki_service


class TestAstronautSimulationEngine(unittest.TestCase):
    """Unit and integration tests for Dheer's Astronaut Simulation Engine."""

    def setUp(self) -> None:
        self.sim = AstronautSimulationEngine()

    def test_nominal_vitals_within_nasa_bounds(self) -> None:
        """Verify baseline values match NASA-STD-3001 microgravity constraints."""
        for state in ["SLEEP", "IVA_REST", "ARED_EXERCISE", "EVA_SPACEWALK"]:
            self.sim.set_activity_state(state)
            packet = self.sim.step()
            self.assertIsInstance(packet, TelemetryPacket)
            self.assertEqual(packet.activity_state, state)
            self.assertGreaterEqual(packet.vitals.heart_rate, 35.0)
            self.assertLessEqual(packet.vitals.heart_rate, 200.0)
            self.assertGreaterEqual(packet.vitals.spo2, 90.0)
            self.assertLessEqual(packet.vitals.spo2, 100.0)
            self.assertGreaterEqual(packet.environment.cabin_co2_mmhg, 1.5)
            self.assertLessEqual(packet.environment.cabin_co2_mmhg, 4.0)

    def test_sinus_arrhythmia_presence(self) -> None:
        """Verify natural cyclical heart rate variation driven by respiration."""
        self.sim.set_activity_state("IVA_REST")
        hr_readings = [self.sim.step().vitals.heart_rate for _ in range(25)]
        hr_min = min(hr_readings)
        hr_max = max(hr_readings)
        spread = hr_max - hr_min
        self.assertGreater(spread, 2.0)
        self.assertLess(spread, 10.0)

    def test_scenario_hypercapnia_crisis_injection(self) -> None:
        """Verify CO2 elevation and respiratory compensation during hypercapnia."""
        self.sim.set_activity_state("IVA_REST")
        self.sim.trigger_scenario("hypercapnia")

        for _ in range(10):
            self.sim.step()

        crisis_packet = self.sim.step()
        self.assertGreaterEqual(crisis_packet.environment.cabin_co2_mmhg, 10.0)
        self.assertGreater(crisis_packet.vitals.heart_rate, 72.0)
        self.assertGreater(crisis_packet.vitals.respiration_rate, 16.0)
        self.assertIn("headache", crisis_packet.symptom_log.lower())

    def test_scenario_solar_flare_radiation_spike(self) -> None:
        """Verify ambient radiation dosage and dosimeter alert under solar flare."""
        self.sim.set_activity_state("EVA_SPACEWALK")
        self.sim.trigger_scenario("solar_flare")

        for _ in range(10):
            self.sim.step()

        flare_packet = self.sim.step()
        self.assertGreater(flare_packet.environment.ambient_radiation_msv_h, 3.5)
        self.assertTrue(flare_packet.environment.donki_spe_active)
        self.assertIn("dosimeter", flare_packet.symptom_log.lower())

    def test_scenario_eva_heat_strain(self) -> None:
        """Verify thermal strain escalation when LCVG loop degrades."""
        self.sim.set_activity_state("EVA_SPACEWALK")
        self.sim.trigger_scenario("heat_strain")
        for _ in range(10):
            self.sim.step()
        packet = self.sim.step()
        self.assertGreaterEqual(packet.vitals.core_temp_c, 38.6)
        self.assertGreater(packet.vitals.heart_rate, 130.0)
        self.assertIn("temperature", packet.symptom_log.lower())

    def test_synthetic_seed_ammonia_leak(self) -> None:
        """Verify dynamic loading and injection of SEED-TOX-01 (Ammonia leak)."""
        self.sim.set_activity_state("IVA_REST")
        self.sim.trigger_scenario("seed-tox-01")
        for _ in range(10):
            self.sim.step()
        packet = self.sim.step()
        self.assertGreater(packet.vitals.heart_rate, 70.0)
        self.assertIn("burning eyes", packet.symptom_log.lower())

    def test_closed_loop_biological_recovery(self) -> None:
        """Verify smooth return to nominal baseline after countermeasure administration."""
        self.sim.set_activity_state("IVA_REST")
        self.sim.trigger_scenario("hypercapnia")
        for _ in range(10):
            self.sim.step()

        peak = self.sim.step()
        self.assertGreater(peak.environment.cabin_co2_mmhg, 10.0)

        cure_resp = self.sim.apply_treatment("LiOH Canister Replacement & 100% O2 Flush")
        self.assertEqual(cure_resp["status"], "ok")

        for _ in range(12):
            self.sim.step()

        recovered = self.sim.step()
        self.assertLessEqual(recovered.environment.cabin_co2_mmhg, 3.0)
        self.assertLess(recovered.vitals.heart_rate, 75.0)
        self.assertFalse(self.sim.is_recovering)
        self.assertEqual(self.sim.active_scenario, "nominal")

    def test_fuzzy_column_normalization(self) -> None:
        """Verify heterogeneous NASA dataset headers are mapped correctly."""
        raw_row = {
            "Pulse": "74.5",
            "Sys_BP": "118.0",
            "DIA": "72.0",
            "O2_Sat": "97.8",
            "CBT": "37.5",
            "ppCO2_mmHg": "2.8",
            "RR_breaths_min": "16.0",
        }
        norm = self.sim._normalize_external_row(raw_row)
        self.assertEqual(norm.get("hr"), 74.5)
        self.assertEqual(norm.get("sbp"), 118.0)
        self.assertEqual(norm.get("dbp"), 72.0)
        self.assertEqual(norm.get("spo2"), 97.8)
        self.assertEqual(norm.get("temp"), 37.5)
        self.assertEqual(norm.get("co2"), 2.8)
        self.assertEqual(norm.get("rr"), 16.0)

    def test_every_catalog_scenario_produces_valid_telemetry(self) -> None:
        catalog = self.sim.list_available_scenarios()
        self.assertGreaterEqual(len(catalog), 31)
        with patch.object(donki_service, "fetch_live_events", return_value=None):
            for entry in catalog:
                with self.subTest(scenario=entry["id"]):
                    self.sim.trigger_scenario("nominal")
                    self.assertEqual(self.sim.trigger_scenario(entry["id"])["status"], "ok")
                    for _ in range(10):
                        packet = self.sim.step()
                    self.assertEqual(packet.active_scenario_id, entry["id"].lower())
                    if entry["id"] != "nominal":
                        self.assertFalse(packet.symptom_log.startswith("Nominal resting"))
                    if entry["id"] == "sans":
                        self.assertGreater(packet.specialized_diagnostics.oct_rnfl_um, 95.0)

    def test_zero_day_has_abnormal_vitals_and_invalid_trigger_preserves_state(self) -> None:
        with patch.object(donki_service, "fetch_live_events", return_value=None):
            self.assertEqual(self.sim.trigger_scenario("mode_b")["status"], "ok")
            self.assertEqual(self.sim.trigger_scenario("typo")["status"], "error")
            for _ in range(10):
                packet = self.sim.step()
        self.assertEqual(packet.active_scenario_id, "zero_day")
        self.assertLess(packet.vitals.spo2, 92.0)
        self.assertLess(packet.vitals.blood_pressure_sys, 90.0)

    def test_routine_schedule_feed(self) -> None:
        """Verify schedule readiness reflects the latest physiological sample."""
        self.sim.step()
        feed = self.sim.get_routine_schedule()
        self.assertIsInstance(feed.get("crew_readiness_score"), int)
        self.assertEqual(len(feed.get("schedule", [])), 8)
        self.assertIn("active_block", feed)

    def test_donki_airgap_fallback(self) -> None:
        """Verify space weather reports resolve cleanly under air-gapped conditions."""
        nominal_report = donki_service.get_space_weather(force_active_flare=False)
        self.assertFalse(nominal_report.spe_active)
        self.assertAlmostEqual(nominal_report.ambient_radiation_msv_h, 0.065, delta=0.02)

        storm_report = donki_service.get_space_weather(force_active_flare=True)
        self.assertTrue(storm_report.spe_active)
        self.assertGreater(storm_report.ambient_radiation_msv_h, 4.0)

    def test_packet_contract_schema(self) -> None:
        """Verify full compatibility with vanilla_frontend_architecture.md."""
        packet = self.sim.step()
        p_dict = packet.model_dump() if hasattr(packet, "model_dump") else packet.__dict__

        required_root_keys = [
            "timestamp", "met", "astronaut_id", "name",
            "activity_state", "vitals", "environment", "symptom_log"
        ]
        for key in required_root_keys:
            self.assertIn(key, p_dict)

        vitals_dict = p_dict["vitals"]
        required_vitals = [
            "heart_rate", "blood_pressure_sys", "blood_pressure_dia",
            "spo2", "hrv_ms", "core_temp_c", "respiration_rate"
        ]
        for v in required_vitals:
            self.assertIn(v, vitals_dict)


if __name__ == "__main__":
    unittest.main()

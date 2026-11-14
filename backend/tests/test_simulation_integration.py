"""Regression checks for the simulator and clinical pipeline on the same server."""

import json
import re
import unittest
from unittest.mock import patch

import backend.main as server
from backend.models.telemetry import TelemetryPacket
from backend.services.anomaly_detector import EdgeAnomalyDetector
from backend.services.astronaut_sim import AstronautSimulationEngine


class SimulationIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.addCleanup(setattr, server, "latest_telemetry", server.latest_telemetry)
        patches = (
            patch.object(server, "astronaut_sim", AstronautSimulationEngine()),
            patch.object(server, "anomaly_detector", EdgeAnomalyDetector()),
            patch.object(server.donki_service, "fetch_live_events", return_value=None),
        )
        for mock in patches:
            mock.start()
            self.addCleanup(mock.stop)

    def test_demo_identity_in_telemetry_and_diagnosis_examples(self) -> None:
        expected = ("ASTRO-01", "Cmdr. Alex Vance")
        frame = server.advance_telemetry()
        self.assertEqual((frame["astronaut_id"], frame["name"]), expected)
        for packet in (TelemetryPacket(), TelemetryPacket.model_validate({"astronaut": {}})):
            self.assertEqual((packet.astronaut_id, packet.name), expected)
        for example in server.SWAGGER_DIAGNOSE_EXAMPLES.values():
            payload = example["value"]
            self.assertEqual((payload["astronaut_id"], payload["name"]), expected)

    def test_live_scenarios_reach_the_rag_without_scenario_labels(self) -> None:
        cases = {
            "SEED-TRM-02": "CPG-22",
            "SEED-TRM-05": "CPG-23",
            "SEED-TRM-06": "MODE_B_ZERO_DAY",
            "SEED-NEU-02": "CPG-32",
            "SEED-MED-05": "CPG-19",
        }
        for scenario, protocol in cases.items():
            with self.subTest(scenario=scenario), patch.object(
                server.rag_engine, "diagnose", wraps=server.rag_engine.diagnose
            ) as diagnose, patch.object(server, "anomaly_detector", EdgeAnomalyDetector()):
                server.astronaut_sim.trigger_scenario("nominal")
                for _ in range(5):
                    baseline = server.advance_telemetry()
                self.assertNotIn("rag_diagnosis", baseline)
                server.astronaut_sim.trigger_scenario(scenario)
                for _ in range(20):
                    frame = server.advance_telemetry()
                self.assertEqual(frame["rag_diagnosis"]["scenario_id"], protocol)
                self.assertTrue(diagnose.call_args_list)
                for call in diagnose.call_args_list:
                    self.assertIsNone(call.args[0].active_scenario_id)

    def test_snapshot_diagnosis_preserves_live_history(self) -> None:
        for _ in range(8):
            server.advance_telemetry()
        detector = server.anomaly_detector
        manager = detector.get_or_create_buffer(server.astronaut_sim.astronaut_id)
        before = manager.get_snapshot_summary()
        detector.evaluate_packet(TelemetryPacket(
            astronaut_id=server.astronaut_sim.astronaut_id,
            vitals={"heart_rate": 150},
            stateless_evaluation=True,
        ))
        after = manager.get_snapshot_summary()
        self.assertEqual(after["channels"], before["channels"])
        self.assertEqual(after["monotonic_tick_counter"], 8)
        server.advance_telemetry()
        self.assertEqual(manager.get_snapshot_summary()["monotonic_tick_counter"], 9)

    def test_bad_commands_preserve_active_simulation(self) -> None:
        self.assertEqual(server.run_simulation_command(
            "trigger_scenario", {"scenario_id": "hypercapnia"}
        )["status"], "ok")
        for cmd, payload in (
            ("trigger_scenario", {"scenario": False}),
            ("trigger_scenario", {}),
            ("set_activity", {"activity_state": 123}),
            ("set_activity", {"activity": "typo"}),
            ("apply_treatment", {"treatment": "typo"}),
            ("apply_treatment", {}),
        ):
            with self.subTest(cmd=cmd, payload=payload):
                self.assertEqual(server.command_status(server.run_simulation_command(cmd, payload)), 400)
                self.assertEqual(server.astronaut_sim.active_scenario, "hypercapnia")
                self.assertEqual(server.astronaut_sim.activity_state, "IVA_REST")
                self.assertFalse(server.astronaut_sim.is_recovering)
        self.assertEqual(server.run_simulation_command(
            "apply_treatment", {"treatment": "li_oh_swap_and_o2"}
        )["status"], "ok")
        self.assertTrue(server.astronaut_sim.is_recovering)

    def test_docs_render_with_local_assets_and_working_examples(self) -> None:
        html = server.render_offline_api_docs(include_openapi=True)
        self.assertNotRegex(html, r"""(?:src|href)=["']https?://""")
        self.assertIn('href="/openapi.json"', html)
        examples = json.loads(re.search(r"const examples = (.+);", html)[1])
        self.assertEqual(examples, server.SWAGGER_DIAGNOSE_EXAMPLES)
        self.assertIn("JSON.stringify(examples[key].value", html)


if __name__ == "__main__":
    unittest.main()

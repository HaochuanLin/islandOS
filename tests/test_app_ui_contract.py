"""Lightweight contract checks for the interactive research dashboard."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"


class AppUIContractTests(unittest.TestCase):
    def test_rolling_and_custom_dispatch_pages_are_registered(self):
        source = APP.read_text(encoding="utf-8")
        for page in ("Rolling dispatch lab", "Custom dispatch CSV", "Telemetry gateway"):
            with self.subTest(page=page):
                self.assertIn(page, source)

    def test_uploaded_results_are_bound_to_current_input_signature(self):
        source = APP.read_text(encoding="utf-8")
        self.assertIn("strategy_run_signature", source)
        self.assertIn('result.get("input_signature") != current_signature', source)
        self.assertIn('custom_result.get("input_signature") != custom_signature', source)

    def test_ui_explicitly_labels_synthetic_and_read_only_boundaries(self):
        source = APP.read_text(encoding="utf-8")
        for phrase in (
            "synthetic scenarios only",
            "no hardware command is sent",
            "not site-validated",
            "Perfect-information is a hindsight reference",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, source)

    def test_app_does_not_import_hardware_control_clients(self):
        source = APP.read_text(encoding="utf-8").lower()
        for module in ("pymodbus", "paho.mqtt", "opcua", "snap7"):
            with self.subTest(module=module):
                self.assertNotIn(f"import {module}", source)


if __name__ == "__main__":
    unittest.main()

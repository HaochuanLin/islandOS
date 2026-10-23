import unittest
from datetime import datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from experiments.run_site_scenario import run_site_scenario

from site_readiness import evaluate_readiness


class SiteReadinessTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 22, 6, 0, tzinfo=timezone.utc)
        self.payload = {
            "site_name": "Test site",
            "scenario_start": "2026-10-22T07:00:00+00:00",
            "telemetry": {
                "timestamp": "2026-10-22T05:55:00+00:00",
                "source_type": "sensor_export",
                "source_reference": "meter-export.csv",
                "wind_kw": 12.0, "pv_kw": 8.0, "critical_load_kw": 10.0,
                "reservoir_level_m3": 50.0,
            },
            "assets": {
                "reservoir_capacity_m3": 100.0,
                "ro_capacity_m3_per_hour": 2.0,
                "ro_specific_energy_kwh_per_m3": 3.5,
            },
            "capex": {
                "ro_plant_rmb": 1000000, "reservoir_rmb": 200000,
                "integration_rmb": 80000, "annual_om_rmb": 30000,
                "source_reference": "budgetary quote, 2026-10-01",
            },
        }

    def test_complete_dispatch_inputs_can_pass_gate(self):
        report = evaluate_readiness(self.payload, "dispatch", now=self.now)
        self.assertTrue(report["can_start"])
        self.assertEqual(report["status"], "READY_FOR_OFFLINE_SCENARIO")

    def test_missing_reservoir_sensor_value_blocks(self):
        self.payload["telemetry"].pop("reservoir_level_m3")
        report = evaluate_readiness(self.payload, now=self.now)
        self.assertFalse(report["can_start"])
        self.assertIn("telemetry.reservoir_level_m3", [x["field"] for x in report["blockers"]])

    def test_stale_telemetry_blocks(self):
        self.payload["telemetry"]["timestamp"] = "2026-10-22T04:00:00+00:00"
        report = evaluate_readiness(self.payload, now=self.now, max_telemetry_age_minutes=60)
        self.assertFalse(report["can_start"])
        self.assertIn("stale_telemetry", [x["code"] for x in report["blockers"]])

    def test_economic_mode_requires_staff_entered_capex(self):
        self.payload["capex"].pop("ro_plant_rmb")
        report = evaluate_readiness(self.payload, "economic", now=self.now)
        self.assertFalse(report["can_start"])
        self.assertIn("capex.ro_plant_rmb", [x["field"] for x in report["blockers"]])

    def test_reservoir_cannot_exceed_capacity(self):
        self.payload["telemetry"]["reservoir_level_m3"] = 101
        report = evaluate_readiness(self.payload, now=self.now)
        self.assertFalse(report["can_start"])
        self.assertIn("reservoir_level_exceeds_capacity", [x["code"] for x in report["blockers"]])

    def test_wrapper_blocks_before_optimizer_when_required_data_missing(self):
        self.payload["telemetry"].pop("reservoir_level_m3")
        with TemporaryDirectory() as tmp:
            readiness = Path(tmp) / "readiness.json"
            readiness.write_text(json.dumps(self.payload), encoding="utf-8")
            with patch("experiments.run_site_scenario.run_from_csv") as optimizer:
                with self.assertRaisesRegex(ValueError, "readiness gate BLOCKED"):
                    run_site_scenario(readiness, "not-read.csv", Path(tmp) / "out", max_telemetry_age_minutes=60)
                optimizer.assert_not_called()

    def test_staff_form_exposes_telemetry_capex_and_fail_closed_controls(self):
        form = Path(__file__).resolve().parents[1] / "tools" / "site_readiness_form.html"
        html = form.read_text(encoding="utf-8")
        for phrase in ("reservoir_level_m3", "ro_plant_rmb", "annual_om_rmb", "下载 JSON", "过期", "不等于现场验证"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, html)

    def test_staff_form_rejects_invalid_timezone_bounds_and_zero_freshness(self):
        form = Path(__file__).resolve().parents[1] / "tools" / "site_readiness_form.html"
        html = form.read_text(encoding="utf-8")
        self.assertIn('14:00)$/.test(off)', html)
        self.assertIn("maxAge<=0", html)

    def test_staff_form_does_not_assume_a_stale_scenario_date_or_sensor_provenance(self):
        form = Path(__file__).resolve().parents[1] / "tools" / "site_readiness_form.html"
        html = form.read_text(encoding="utf-8")
        self.assertIn('id="start" type="datetime-local" required', html)
        self.assertNotIn('value="2026-10-22T08:00"', html)
        self.assertIn('<option value="manual" selected>', html)

    def test_bad_values_block(self):
        self.payload["telemetry"]["pv_kw"] = float("nan")
        report = evaluate_readiness(self.payload, now=self.now)
        self.assertFalse(report["can_start"])
        self.assertIn("invalid_number", [x["code"] for x in report["blockers"]])

    def test_boolean_physics_values_are_rejected(self):
        self.payload["telemetry"]["pv_kw"] = True
        report = evaluate_readiness(self.payload, now=self.now)
        self.assertFalse(report["can_start"])
        self.assertIn("invalid_number", [x["code"] for x in report["blockers"]])

    def test_non_text_site_identity_is_rejected(self):
        self.payload["site_name"] = 123
        report = evaluate_readiness(self.payload, now=self.now)
        self.assertFalse(report["can_start"])
        self.assertIn("invalid_text", [x["code"] for x in report["blockers"]])

    def test_invalid_freshness_limit_is_rejected(self):
        for value in (0, -1, 1.5, True, "60"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "positive integer"):
                    evaluate_readiness(self.payload, now=self.now, max_telemetry_age_minutes=value)

    def test_boolean_capex_is_rejected_in_economic_mode(self):
        self.payload["capex"]["ro_plant_rmb"] = True
        report = evaluate_readiness(self.payload, "economic", now=self.now)
        self.assertFalse(report["can_start"])
        self.assertIn("invalid_number", [x["code"] for x in report["blockers"]])


if __name__ == "__main__":
    unittest.main()

"""Tests for reproducible synthetic acceptance evidence."""
import unittest

from experiments.telemetry_advice_acceptance import build_acceptance_report, make_scenario_rows


class TestTelemetryAdviceAcceptance(unittest.TestCase):
    def test_four_scenarios_are_hourly_aligned_and_repeatable(self):
        for name in ("normal_day", "low_renewables", "water_stress", "cooling_stress"):
            rows = make_scenario_rows(name, hours=24)
            self.assertEqual(len(rows), 24)
            self.assertEqual(rows[0]["timestamp_utc"], "2026-10-23T00:00:00Z")
            self.assertEqual(rows[-1]["timestamp_utc"], "2026-10-23T23:00:00Z")
            self.assertTrue(all(row["actual_surplus_kw"] >= 0 for row in rows))

    def test_report_has_complete_checks_and_transparent_data_status(self):
        report = build_acceptance_report(hours=24)
        self.assertEqual(report["scenario_count"], 4)
        self.assertEqual(report["checks_total"], 16)
        self.assertEqual(report["checks_passed"], 16)
        self.assertTrue(report["all_checks_passed"])
        self.assertEqual(report["data_status"], "synthetic_only_not_site_data_not_field_validation")
        self.assertIn("No device authentication", " ".join(report["limitations"]))
        for scenario in report["scenarios"].values():
            self.assertEqual(len(scenario["policy_comparison"]), 4)
            self.assertEqual(len(scenario["weight_sensitivity"]), 4)

    def test_rejects_invalid_horizon(self):
        for hours in (True, 1, 169, 2.5):
            with self.subTest(hours=hours):
                with self.assertRaises(ValueError):
                    make_scenario_rows("normal_day", hours)


if __name__ == "__main__":
    unittest.main()

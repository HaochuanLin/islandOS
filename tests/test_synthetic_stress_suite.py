"""Tests for no-site-data stress testing of the integrated simulation path."""
import unittest

from experiments.run_synthetic_stress_suite import build_stress_cases, run_synthetic_stress_suite


class TestSyntheticStressSuite(unittest.TestCase):
    def test_matrix_contains_documented_scarcity_forecast_and_safety_cases(self):
        cases = build_stress_cases(12)
        names = {case["name"] for case in cases}
        self.assertEqual(len(cases), 10)
        self.assertTrue({
            "baseline_synthetic", "forecast_overestimate_50pct", "forecast_underestimate_50pct",
            "renewable_drought", "water_demand_spike", "cooling_demand_spike",
            "compound_adverse", "invalid_telemetry", "unhealthy_interlocks", "operator_stop",
        }.issubset(names))
        baseline_hash = next(case["csv"] for case in cases if case["name"] == "baseline_synthetic")
        optimistic = next(case["csv"] for case in cases if case["name"] == "forecast_overestimate_50pct")
        self.assertNotEqual(baseline_hash, optimistic)

    def test_suite_is_deterministic_auditable_and_simulation_only(self):
        first = run_synthetic_stress_suite(hours=8)
        second = run_synthetic_stress_suite(hours=8)
        self.assertEqual(first["case_count"], 10)
        self.assertEqual(first["suite_sha256"], second["suite_sha256"])
        self.assertTrue(first["all_cases_simulation_only"])
        self.assertTrue(all(len(item["input_sha256"]) == 64 for item in first["results"]))
        self.assertTrue(all(item["hours"] == 8 for item in first["results"]))
        self.assertTrue(all(not item["physical_write_performed"] for item in first["results"]))
        self.assertTrue(all(not item["live_control_enabled"] for item in first["results"]))

    def test_fail_closed_cases_hold_all_hours(self):
        report = run_synthetic_stress_suite(hours=6)
        by_name = {item["name"]: item for item in report["results"]}
        for name in ("invalid_telemetry", "unhealthy_interlocks", "operator_stop"):
            with self.subTest(name=name):
                self.assertEqual(by_name[name]["gate_action_counts"], {"ON": 0, "OFF": 0, "HOLD": 6})

    def test_drought_scenario_has_zero_actual_and_forecast_surplus(self):
        case = next(case for case in build_stress_cases(6) if case["name"] == "renewable_drought")
        rows = case["csv"].strip().splitlines()[1:]
        self.assertTrue(all(row.split(",")[1:3] == ["0", "0"] for row in rows))


if __name__ == "__main__":
    unittest.main()

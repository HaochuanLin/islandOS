"""Tests for deterministic CSV input-quality stress probes."""
import json
from pathlib import Path
import tempfile
import unittest

from experiments.run_input_quality_stress_suite import (
    build_input_quality_cases,
    main,
    run_input_quality_stress_suite,
)


class TestInputQualityStressSuite(unittest.TestCase):
    def test_suite_rejects_malformed_inputs_and_accepts_valid_baseline(self):
        first = run_input_quality_stress_suite(hours=4)
        second = run_input_quality_stress_suite(hours=4)
        self.assertEqual(first["case_count"], 15)
        self.assertEqual(first["passed_cases"], 15)
        self.assertEqual(first["failed_cases"], 0)
        self.assertTrue(first["all_expectations_met"])
        self.assertEqual(first["report_sha256"], second["report_sha256"])
        self.assertFalse(first["physical_write_performed"])
        self.assertFalse(first["live_control_enabled"])
        self.assertTrue(first["all_fixtures_simulation_only"])
        by_name = {item["name"]: item for item in first["results"]}
        self.assertFalse(by_name["valid_synthetic_baseline"]["actual_rejected"])
        for name, item in by_name.items():
            with self.subTest(name=name):
                self.assertEqual(item["expectation_met"], True)
                self.assertEqual(len(item["input_sha256"]), 64)
                if name != "valid_synthetic_baseline":
                    self.assertTrue(item["actual_rejected"])
                    self.assertIsNotNone(item["error"])

    def test_case_matrix_contains_timestamp_numeric_and_schema_faults(self):
        cases = build_input_quality_cases(3)
        names = {case["name"] for case in cases}
        self.assertEqual(len(cases), 15)
        self.assertTrue({
            "empty_input", "header_only", "missing_required_column",
            "blank_timestamp", "malformed_timestamp", "timezone_naive_timestamp",
            "duplicate_timestamp", "non_monotonic_timestamp", "hour_gap",
            "nan_actual_surplus", "infinite_forecast_surplus", "negative_water_demand",
            "nonnumeric_cooling_demand", "blank_forecast_water_demand",
        }.issubset(names))

    def test_cli_writes_json_report_and_returns_success(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "nested" / "input-quality.json"
            code = main(["--hours", "3", "--output", str(output)])
            self.assertEqual(code, 0)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["case_count"], 15)
            self.assertTrue(report["all_expectations_met"])
            self.assertEqual(len(report["report_sha256"]), 64)

    def test_rejects_horizons_too_short_or_too_long(self):
        for hours in (0, 1, 169, True):
            with self.subTest(hours=hours):
                with self.assertRaises(ValueError):
                    run_input_quality_stress_suite(hours=hours)


if __name__ == "__main__":
    unittest.main()

"""Regression tests for paired forecast-to-dispatch evaluation."""
import csv
import hashlib
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import experiments.evaluate_forecast_dispatch as dispatch_evaluation
from experiments.evaluate_forecast_dispatch import evaluate_forecast_dispatch, load_paired_series


class ForecastDispatchEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.input = self.root / "paired.csv"
        self.rows = []
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        actual = [0, 300, 450, 0, 500, 200, 0, 350]
        forecast = [0, 330, 400, 50, 450, 250, 0, 300]
        for i, (observed, predicted) in enumerate(zip(actual, forecast)):
            self.rows.append({
                "timestamp_utc": (start + timedelta(hours=i)).isoformat().replace("+00:00", "Z"),
                "actual_surplus_kw": observed,
                "forecast_surplus_kw": predicted,
                "water_demand_m3": 20,
                "cooling_demand_kw_th": 50,
            })
        self.write_rows(self.rows)

    def tearDown(self):
        self.temp.cleanup()

    def write_rows(self, rows):
        with self.input.open("w", encoding="utf-8", newline="") as handle:
            fieldnames = [
                "timestamp_utc", "actual_surplus_kw", "forecast_surplus_kw",
                "water_demand_m3", "cooling_demand_kw_th",
            ]
            if rows and "forecast_water_demand_m3" in rows[0]:
                fieldnames.append("forecast_water_demand_m3")
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def test_paired_series_is_evaluated_on_identical_realized_profile(self):
        result = evaluate_forecast_dispatch(self.input)
        self.assertEqual(result["time_basis"]["rows"], len(self.rows))
        self.assertEqual(result["forecast_metrics"]["evaluated_hours"], len(self.rows))
        self.assertAlmostEqual(result["forecast_metrics"]["mae_kw"], 35.0)
        self.assertEqual(
            set(result["policy_comparison"]),
            {"rolling", "ro_first", "ice_first", "perfect_information"},
        )
        for policy in result["policy_comparison"].values():
            self.assertEqual(len(policy["hourly_priority_decisions"]), len(self.rows))
            self.assertGreaterEqual(policy["water_unmet_m3"], 0)
            self.assertGreaterEqual(policy["cooling_unmet_kwh_th"], 0)
            self.assertGreaterEqual(policy["remaining_surplus_kwh"], 0)
        self.assertIn(result["comparison"]["best_fixed_policy"], {"ro_first", "ice_first"})
        water_input = result["water_demand_input"]
        self.assertEqual(water_input["planning_input_status"], "hindsight_actual_fallback")
        self.assertFalse(water_input["forecast_demand_is_used_for_planning"])
        self.assertTrue(water_input["actual_demand_fallback_is_hindsight"])
        self.assertIsNone(water_input["forecast_demand_metrics"])
        water_baseline = water_input["persistence_baseline_comparison"]
        self.assertEqual(water_baseline["status"], "not_evaluated")
        self.assertIn("actual-demand fallback is hindsight", water_baseline["reason"])
        baseline = result["persistence_baseline_comparison"]
        self.assertEqual(baseline["status"], "evaluated")
        self.assertEqual(baseline["aligned_hours"], len(self.rows) - 1)
        self.assertEqual(
            baseline["forecast_metrics"]["persistence_baseline"]["evaluated_hours"],
            len(self.rows) - 1,
        )
        self.assertEqual(
            len(baseline["dispatch_comparison"]["supplied_forecast"]["policies"]["rolling"]["hourly_priority_decisions"]),
            len(self.rows) - 1,
        )
        self.assertEqual(
            len(baseline["dispatch_comparison"]["persistence_baseline"]["policies"]["rolling"]["hourly_priority_decisions"]),
            len(self.rows) - 1,
        )
        self.assertAlmostEqual(
            baseline["dispatch_comparison"]["rolling_score_difference_supplied_minus_persistence"],
            baseline["dispatch_comparison"]["supplied_forecast"]["comparison"]["rolling_score"]
            - baseline["dispatch_comparison"]["persistence_baseline"]["comparison"]["rolling_score"],
        )

    def test_report_records_input_csv_sha256(self):
        result = evaluate_forecast_dispatch(self.input)
        self.assertEqual(
            result["input_csv_sha256"],
            hashlib.sha256(self.input.read_bytes()).hexdigest(),
        )
        self.assertEqual(len(result["input_csv_sha256"]), 64)

    def test_refuses_input_mutation_during_evaluation(self):
        original_loader = dispatch_evaluation.load_forecast_water_demand

        def mutate_after_read(path, actual_demand):
            result = original_loader(path, actual_demand)
            with Path(path).open("a", encoding="utf-8") as handle:
                handle.write("\\n")
            return result

        with patch(
            "experiments.evaluate_forecast_dispatch.load_forecast_water_demand",
            side_effect=mutate_after_read,
        ):
            with self.assertRaisesRegex(ValueError, "changed during evaluation"):
                evaluate_forecast_dispatch(self.input)

    def test_forecast_water_demand_is_used_for_planning_not_actuals(self):
        rows = [dict(row, forecast_water_demand_m3=28 + i) for i, row in enumerate(self.rows)]
        self.write_rows(rows)
        result = evaluate_forecast_dispatch(self.input)
        self.assertEqual(
            result["water_demand_input"]["forecast_column_used"],
            "forecast_water_demand_m3",
        )
        self.assertEqual(result["water_demand_input"]["planning_input_status"], "forecast_supplied")
        self.assertTrue(result["water_demand_input"]["forecast_demand_is_used_for_planning"])
        self.assertFalse(result["water_demand_input"]["actual_demand_fallback_is_hindsight"])
        self.assertEqual(
            result["water_demand_input"]["forecast_demand_metrics"]["mae_m3_per_hour"],
            11.5,
        )
        baseline = result["water_demand_input"]["persistence_baseline_comparison"]
        self.assertEqual(baseline["status"], "evaluated")
        self.assertEqual(baseline["aligned_hours"], len(self.rows) - 1)
        self.assertEqual(
            baseline["forecast_metrics"]["supplied_water_forecast"]["evaluated_hours"],
            len(self.rows) - 1,
        )
        self.assertEqual(
            baseline["forecast_metrics"]["persistence_baseline"]["mae_m3_per_hour"],
            0.0,
        )
        self.assertEqual(
            len(baseline["dispatch_comparison"]["supplied_water_forecast"]["policies"]["rolling"]["hourly_priority_decisions"]),
            len(self.rows) - 1,
        )
        self.assertEqual(
            len(baseline["dispatch_comparison"]["persistence_baseline"]["policies"]["rolling"]["hourly_priority_decisions"]),
            len(self.rows) - 1,
        )
        audit = result["policy_comparison"]["rolling"]["hourly_audit"]
        self.assertEqual(audit[0]["actual_water_demand_m3"], 20.0)
        self.assertEqual(audit[0]["forecast_water_demand_m3"], 28.0)
        self.assertEqual(audit[0]["planning_water_demand_m3"], 28.0)

    def test_rejects_invalid_optional_water_demand_forecast(self):
        rows = [dict(row, forecast_water_demand_m3=28) for row in self.rows]
        rows[2]["forecast_water_demand_m3"] = "-1"
        self.write_rows(rows)
        with self.assertRaisesRegex(ValueError, "finite and non-negative"):
            evaluate_forecast_dispatch(self.input)

    def test_offset_timestamps_are_normalized_to_utc(self):
        offset_rows = [dict(row) for row in self.rows]
        start = datetime(2026, 1, 1, 8, tzinfo=timezone(timedelta(hours=8)))
        for i, row in enumerate(offset_rows):
            row["timestamp_utc"] = (
                start + timedelta(hours=i)
            ).isoformat()
        self.write_rows(offset_rows)
        timestamps, _, _ = load_paired_series(self.input)
        self.assertEqual(timestamps[0], "2026-01-01T00:00:00Z")
        self.assertEqual(timestamps[-1], "2026-01-01T07:00:00Z")

    def test_single_row_reports_persistence_baseline_unavailable(self):
        self.write_rows(self.rows[:1])
        result = evaluate_forecast_dispatch(self.input)
        self.assertEqual(
            result["persistence_baseline_comparison"]["status"], "not_evaluated"
        )
        self.assertIn(
            "At least two hourly rows",
            result["persistence_baseline_comparison"]["reason"],
        )

    def test_rejects_missing_columns_and_negative_values(self):
        self.input.write_text("timestamp_utc,actual_surplus_kw\n2026-01-01T00:00:00Z,0\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "missing columns"):
            load_paired_series(self.input)
        broken = [dict(row) for row in self.rows]
        broken[2]["forecast_surplus_kw"] = -1
        self.write_rows(broken)
        with self.assertRaisesRegex(ValueError, "finite and non-negative"):
            load_paired_series(self.input)

    def test_rejects_naive_timestamps_gaps_and_missing_values(self):
        broken = [dict(row) for row in self.rows]
        broken[0]["timestamp_utc"] = "2026-01-01T00:00:00"
        self.write_rows(broken)
        with self.assertRaisesRegex(ValueError, "must include a timezone"):
            load_paired_series(self.input)
        broken = [dict(row) for row in self.rows]
        broken[3]["timestamp_utc"] = "2026-01-01T04:00:00Z"
        self.write_rows(broken)
        with self.assertRaisesRegex(ValueError, "hourly timestamps"):
            load_paired_series(self.input)
        broken = [dict(row) for row in self.rows]
        broken[4]["water_demand_m3"] = ""
        self.write_rows(broken)
        with self.assertRaisesRegex(ValueError, "Missing water_demand_m3"):
            load_paired_series(self.input)

    def test_rejects_duplicate_csv_headers(self):
        with self.input.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow([
                "timestamp_utc", "actual_surplus_kw", "actual_surplus_kw",
                "forecast_surplus_kw", "water_demand_m3", "cooling_demand_kw_th",
            ])
            writer.writerow(["2026-01-01T00:00:00Z", 10, 11, 12, 20, 50])
        with self.assertRaisesRegex(ValueError, "duplicate columns"):
            load_paired_series(self.input)

    def test_rejects_extra_csv_fields(self):
        lines = self.input.read_text(encoding="utf-8").splitlines()
        lines[1] += ",unexpected"
        self.input.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "extra fields"):
            load_paired_series(self.input)


if __name__ == "__main__":
    unittest.main()

"""Tests for chronological multi-window forecast-dispatch evaluation."""
import csv
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from experiments.evaluate_forecast_dispatch_windows import evaluate_windows


class ForecastDispatchWindowsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.input = self.root / "paired.csv"
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        with self.input.open("w", encoding="utf-8", newline="") as handle:
            fields = [
                "timestamp_utc", "actual_surplus_kw", "forecast_surplus_kw",
                "water_demand_m3", "cooling_demand_kw_th",
            ]
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for i in range(20):
                actual = [0, 100, 250, 50, 300, 0, 150, 400, 20, 180,
                          330, 60, 270, 0, 210, 390, 40, 160, 310, 90][i]
                writer.writerow({
                    "timestamp_utc": (start + timedelta(hours=i)).isoformat().replace("+00:00", "Z"),
                    "actual_surplus_kw": actual,
                    "forecast_surplus_kw": max(0, actual + (15 if i % 2 else -10)),
                    "water_demand_m3": 5,
                    "cooling_demand_kw_th": 10,
                })

    def tearDown(self):
        self.temp.cleanup()

    def test_non_overlapping_windows_are_aligned_and_aggregated(self):
        result = evaluate_windows(self.input, window_hours=8)
        self.assertEqual(result["window_count"], 3)
        self.assertEqual(result["evaluated_window_count"], 3)
        self.assertEqual(result["total_aligned_evaluation_hours"], 17)
        self.assertEqual([w["input_rows"] for w in result["windows"]], [8, 8, 4])
        self.assertEqual([w["aligned_evaluation_hours"] for w in result["windows"]], [7, 7, 3])
        self.assertIsNotNone(result["aggregate_metrics"]["mae_skill_vs_persistence"])
        self.assertEqual(
            result["aggregate_metrics"]["windows_where_supplied_forecast_dispatch_scores_lower"]
            + result["aggregate_metrics"]["windows_where_persistence_dispatch_scores_lower"]
            + result["aggregate_metrics"]["ties"],
            3,
        )

    def test_rejects_window_size_below_two(self):
        with self.assertRaisesRegex(ValueError, "window_hours"):
            evaluate_windows(self.input, window_hours=1)

    def test_rejects_input_with_only_one_row(self):
        with self.input.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        with self.input.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerow(rows[0])
        with self.assertRaisesRegex(ValueError, "two or more hourly rows"):
            evaluate_windows(self.input, window_hours=8)


if __name__ == "__main__":
    unittest.main()

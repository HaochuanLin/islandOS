"""Tests for the continuous-state forecast-dispatch backtest."""
import csv
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from experiments.evaluate_forecast_dispatch_continuous import (
    build_persistence_forecast,
    evaluate_continuous,
)


class ContinuousForecastDispatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.input = Path(self.temp.name) / "paired.csv"
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        actual_values = [0, 100, 250, 50, 300, 0, 150, 400, 20, 180]
        with self.input.open("w", encoding="utf-8", newline="") as handle:
            fields = [
                "timestamp_utc", "actual_surplus_kw", "forecast_surplus_kw",
                "water_demand_m3", "cooling_demand_kw_th",
            ]
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for i, actual in enumerate(actual_values):
                writer.writerow({
                    "timestamp_utc": (start + timedelta(hours=i)).isoformat().replace("+00:00", "Z"),
                    "actual_surplus_kw": actual,
                    "forecast_surplus_kw": max(0, actual + (15 if i % 2 else -10)),
                    "water_demand_m3": 5,
                    "cooling_demand_kw_th": 10,
                })

    def tearDown(self):
        self.temp.cleanup()

    def test_persistence_uses_only_previous_actual_after_common_warmup(self):
        self.assertEqual(
            build_persistence_forecast([10, 20, 30, 40], shared_first_forecast=99),
            [99, 10, 20, 30],
        )

    def test_continuous_backtest_uses_full_trace_and_reports_state(self):
        result = evaluate_continuous(self.input)
        self.assertEqual(result["time_basis"]["rows"], 10)
        self.assertEqual(result["state_handling"]["forecast_metrics_hours"], 9)
        self.assertEqual(result["state_handling"]["dispatch_score_hours"], 10)
        self.assertIn("final_water_inventory_m3", result["results"]["supplied_forecast_rolling"])
        self.assertIn("final_cold_inventory_kwh_th", result["results"]["persistence_rolling"])
        self.assertEqual(set(result["policy_scores"]), {
            "supplied_forecast_rolling",
            "persistence_rolling",
            "ro_first_using_supplied_forecast",
            "ice_first_using_supplied_forecast",
            "perfect_information_hindsight_only",
        })

    def test_persistence_requires_two_rows(self):
        with self.assertRaisesRegex(ValueError, "two hourly rows"):
            build_persistence_forecast([12], 9)


if __name__ == "__main__":
    unittest.main()

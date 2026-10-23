"""Tests for repeated chronological water-demand model evaluation."""
import csv
import json
import math
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from experiments.backtest_water_demand_models import backtest_water_demand_models


class TestWaterDemandRollingBacktest(unittest.TestCase):
    def _write_series(self, path: Path, count: int = 480) -> None:
        start = datetime(2025, 1, 1, tzinfo=timezone.utc)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["timestamp", "water_demand_m3"])
            writer.writeheader()
            for index in range(count):
                hour = index % 24
                weekday = index % 168
                value = (
                    28.0
                    + 6.0 * math.sin(2.0 * math.pi * hour / 24.0)
                    + 1.5 * math.sin(2.0 * math.pi * weekday / 168.0)
                    + (index % 7) * 0.1
                )
                writer.writerow({
                    "timestamp": (start + timedelta(hours=index)).isoformat(),
                    "water_demand_m3": value,
                })

    def test_runs_repeated_expanding_windows_without_overlap(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "demand.csv"
            output = Path(directory) / "backtest.json"
            self._write_series(source)
            report = backtest_water_demand_models(
                source,
                output,
                initial_train_fraction=0.50,
                test_window_hours=24,
                step_hours=24,
            )

            self.assertEqual(report["status"], "rolling_backtest_completed")
            self.assertEqual(report["configuration"]["fold_count"], 10)
            self.assertEqual(report["configuration"]["evaluated_hours"], 240)
            self.assertEqual(len(report["folds"]), 10)
            self.assertEqual(len(report["forecast_rows"]), 240)
            self.assertEqual(
                set(report["aggregate_metrics"]),
                {
                    "persistence_previous_hour",
                    "seasonal_naive_previous_day",
                    "seasonal_naive_previous_week",
                    "hist_gradient_boosting",
                },
            )
            for fold in report["folds"]:
                self.assertLess(fold["training_end"], fold["test_start"])
                self.assertEqual(fold["test_rows"], 24)
                self.assertEqual(set(fold["metrics"]), set(report["aggregate_metrics"]))
            saved = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(saved["configuration"]["fold_count"], 10)

    def test_rejects_overlapping_test_windows(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "demand.csv"
            self._write_series(source)
            with self.assertRaisesRegex(ValueError, "avoid overlap"):
                backtest_water_demand_models(
                    source,
                    Path(directory) / "backtest.json",
                    initial_train_fraction=0.50,
                    test_window_hours=24,
                    step_hours=12,
                )


if __name__ == "__main__":
    unittest.main()

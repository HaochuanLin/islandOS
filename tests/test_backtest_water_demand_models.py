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
                initial_train_fraction=0.60,
                test_window_hours=24,
                step_hours=24,
            )

            self.assertEqual(report["status"], "rolling_backtest_completed")
            self.assertEqual(report["configuration"]["fold_count"], 8)
            self.assertEqual(report["configuration"]["evaluated_hours"], 192)
            self.assertEqual(len(report["folds"]), 8)
            self.assertEqual(len(report["forecast_rows"]), 192)
            self.assertGreater(report["high_demand_evaluation"]["event_count"], 0)
            self.assertEqual(
                set(report["high_demand_evaluation"]["pooled_metrics_by_model"]),
                set(report["aggregate_metrics"]),
            )
            for metric in report["high_demand_evaluation"]["pooled_metrics_by_model"].values():
                self.assertGreater(metric["event_count"], 0)
                self.assertGreaterEqual(metric["mae_m3_per_hour"], 0)
                self.assertGreaterEqual(metric["underforecast_rate"], 0)
                self.assertLessEqual(metric["underforecast_rate"], 1)
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
                self.assertEqual(set(fold["high_demand_metrics"]), set(report["aggregate_metrics"]))
                self.assertGreaterEqual(fold["high_demand_threshold_m3_per_hour"], 0)
            saved = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(saved["configuration"]["fold_count"], 8)

    def test_caps_folds_for_long_series_while_spreading_them_across_time(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "demand.csv"
            self._write_series(source, count=720)
            report = backtest_water_demand_models(
                source,
                Path(directory) / "backtest.json",
                initial_train_fraction=0.60,
                test_window_hours=24,
                step_hours=24,
                max_folds=4,
            )

            self.assertGreater(report["configuration"]["available_fold_count"], 4)
            self.assertEqual(report["configuration"]["fold_count"], 4)
            self.assertEqual(report["configuration"]["evaluated_hours"], 96)
            starts = [fold["test_start"] for fold in report["folds"]]
            self.assertLess(starts[0], starts[1])
            self.assertLess(starts[1], starts[2])
            self.assertLess(starts[2], starts[3])

    def test_rejects_overlapping_test_windows(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "demand.csv"
            self._write_series(source)
            with self.assertRaisesRegex(ValueError, "avoid overlap"):
                backtest_water_demand_models(
                    source,
                    Path(directory) / "backtest.json",
                    initial_train_fraction=0.60,
                    test_window_hours=24,
                    step_hours=12,
                )

    def test_earlier_fold_is_unchanged_when_later_observations_are_modified(self):
        """Future data must not leak into a fold's training or one-step features."""
        with tempfile.TemporaryDirectory() as directory:
            original = Path(directory) / "original.csv"
            altered = Path(directory) / "altered.csv"
            original_output = Path(directory) / "original.json"
            altered_output = Path(directory) / "altered.json"
            self._write_series(original, count=720)

            with original.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))

            first_cutoff = int(len(rows) * 0.60)
            first_test_end = first_cutoff + 24
            # Preserve the first fold's training history and all observations
            # used during its test window; alter only strictly later outcomes.
            for index in range(first_test_end, len(rows)):
                rows[index]["water_demand_m3"] = str(
                    float(rows[index]["water_demand_m3"]) + 500.0
                )
            with altered.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["timestamp", "water_demand_m3"])
                writer.writeheader()
                writer.writerows(rows)

            original_report = backtest_water_demand_models(
                original,
                original_output,
                initial_train_fraction=0.60,
                test_window_hours=24,
                step_hours=24,
                max_folds=4,
            )
            altered_report = backtest_water_demand_models(
                altered,
                altered_output,
                initial_train_fraction=0.60,
                test_window_hours=24,
                step_hours=24,
                max_folds=4,
            )

            self.assertEqual(
                original_report["folds"][0]["metrics"],
                altered_report["folds"][0]["metrics"],
            )
            self.assertEqual(
                original_report["folds"][0]["high_demand_threshold_m3_per_hour"],
                altered_report["folds"][0]["high_demand_threshold_m3_per_hour"],
            )
            self.assertEqual(
                original_report["folds"][0]["high_demand_metrics"],
                altered_report["folds"][0]["high_demand_metrics"],
            )
            original_first_fold = [
                row for row in original_report["forecast_rows"] if row["fold"] == 1
            ]
            altered_first_fold = [
                row for row in altered_report["forecast_rows"] if row["fold"] == 1
            ]
            self.assertEqual(original_first_fold, altered_first_fold)


if __name__ == "__main__":
    unittest.main()

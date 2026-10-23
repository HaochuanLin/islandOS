"""Tests for the optional water-demand ML comparison experiment."""
import csv
import hashlib
import json
import math
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from experiments.compare_water_demand_models import compare_water_demand_models


class TestCompareWaterDemandModels(unittest.TestCase):
    def _write_series(self, path: Path, count: int = 480, invalid: str | None = None) -> None:
        start = datetime(2025, 1, 1, tzinfo=timezone.utc)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["timestamp", "water_demand_m3"])
            writer.writeheader()
            for index in range(count):
                hour = index % 24
                value = (
                    28.0
                    + 6.0 * math.sin(2.0 * math.pi * hour / 24.0)
                    + 1.5 * math.sin(2.0 * math.pi * (index % 168) / 168.0)
                    + (index % 7) * 0.1
                )
                if invalid == "negative" and index == 20:
                    value = -1.0
                stamp = start + timedelta(hours=index)
                writer.writerow({
                    "timestamp": stamp.isoformat(),
                    "water_demand_m3": value,
                })

    def test_compares_ml_and_naive_models_on_identical_chronological_holdout(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "demand.csv"
            output = Path(directory) / "report.json"
            self._write_series(source)
            report = compare_water_demand_models(source, output)

            self.assertEqual(report["status"], "models_compared")
            self.assertEqual(report["chronological_split"]["test_samples"], 144)
            self.assertEqual(
                set(report["test_metrics"]),
                {
                    "persistence_previous_hour",
                    "seasonal_naive_previous_day",
                    "seasonal_naive_previous_week",
                    "hist_gradient_boosting",
                },
            )
            self.assertTrue(all(
                metrics["mae_m3_per_hour"] >= 0
                and metrics["rmse_m3_per_hour"] >= 0
                for metrics in report["test_metrics"].values()
            ))
            walk_forward = report["walk_forward_summary"]
            self.assertEqual(walk_forward["fold_count"], 3)
            self.assertEqual(walk_forward["test_rows"], 144)
            self.assertEqual(sum(fold["test_rows"] for fold in walk_forward["folds"]), 144)
            for fold in walk_forward["folds"]:
                self.assertEqual(fold["training_rows_end_before_test_window"], fold["first_test_index"])
                self.assertLess(fold["training_rows_end_before_test_window"], fold["last_test_index"] + 1)
                self.assertTrue(all(
                    metrics["mae_m3_per_hour"] >= 0
                    and metrics["rmse_m3_per_hour"] >= 0
                    for metrics in fold["test_metrics"].values()
                ))
            self.assertEqual(len(report["forecast_rows"]), 144)
            self.assertEqual(report["input_csv_sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
            self.assertTrue(report["model"]["library_version"])
            self.assertEqual(
                json.loads(output.read_text(encoding="utf-8"))["status"],
                "models_compared",
            )

    def test_rejects_naive_timestamps(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "demand.csv"
            self._write_series(source)
            with source.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            rows[0]["timestamp"] = "2025-01-01T00:00:00"
            with source.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["timestamp", "water_demand_m3"])
                writer.writeheader()
                writer.writerows(rows)
            with self.assertRaisesRegex(ValueError, "timezone offset"):
                compare_water_demand_models(source, Path(directory) / "report.json")

    def test_rejects_negative_demand(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "demand.csv"
            self._write_series(source, invalid="negative")
            with self.assertRaisesRegex(ValueError, "finite and non-negative"):
                compare_water_demand_models(source, Path(directory) / "report.json")

    def test_rejects_missing_hour(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "demand.csv"
            self._write_series(source)
            with source.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            with source.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["timestamp", "water_demand_m3"])
                writer.writeheader()
                writer.writerows(row for index, row in enumerate(rows) if index != 200)
            with self.assertRaisesRegex(ValueError, "continuous hourly"):
                compare_water_demand_models(source, Path(directory) / "report.json")


if __name__ == "__main__":
    unittest.main()

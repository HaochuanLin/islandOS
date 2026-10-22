"""Tests for the transparent water-demand forecasting baseline."""
import csv
import json
import math
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from experiments.water_demand_forecast import evaluate_water_demand


class TestWaterDemandForecast(unittest.TestCase):
    def _write_series(self, path: Path, count: int = 120, invalid: str | None = None) -> None:
        start = datetime(2025, 1, 1, tzinfo=timezone.utc)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["timestamp", "water_demand_m3"])
            writer.writeheader()
            for i in range(count):
                # Synthetic daily pattern with small deterministic variation.
                value = 30.0 + 7.0 * math.sin(2.0 * math.pi * (i % 24) / 24.0) + (i % 5) * 0.2
                if invalid == "negative" and i == 10:
                    value = -1.0
                stamp = start + timedelta(hours=i)
                writer.writerow({
                    "timestamp": stamp.isoformat(),
                    "water_demand_m3": value,
                })

    def test_chronological_holdout_and_metrics_are_reproducible(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "demand.csv"
            output = Path(directory) / "report.json"
            self._write_series(source)
            first = evaluate_water_demand(source, output)
            second = evaluate_water_demand(source, output)

            self.assertEqual(first["test_rows"], 30)
            self.assertEqual(first["history_rows"], 90)
            self.assertEqual(first["test_metrics"], second["test_metrics"])
            self.assertEqual(len(first["test_predictions"]), first["test_rows"])
            self.assertIn("seasonal_bias_corrected", first["test_metrics"])
            self.assertEqual(
                first["training_error_calibration"]["fit_rows_end_before_test_window"],
                first["history_rows"],
            )
            self.assertTrue(all(
                row["seasonal_bias_corrected_forecast_m3"] >= 0
                and row["seasonal_bias_corrected_90pct_lower_m3"] >= 0
                and row["seasonal_bias_corrected_90pct_upper_m3"] >= row["seasonal_bias_corrected_90pct_lower_m3"]
                for row in first["test_predictions"]
            ))
            self.assertTrue(output.exists())
            self.assertEqual(json.loads(output.read_text())["status"], "baseline_evaluated")

    def test_report_checks_gaussian_assumption_instead_of_claiming_it(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "demand.csv"
            output = Path(directory) / "report.json"
            self._write_series(source)
            report = evaluate_water_demand(source, output)
            diagnostics = report["distribution_diagnostics"]
            self.assertIn("observed_demand_test_window", diagnostics)
            self.assertIn("seasonal_forecast_errors_on_training_history", diagnostics)
            self.assertIn("empirical_coverage", report["seasonal_prediction_intervals"]["nominal_90pct"])
            self.assertIn("Gaussian", report["seasonal_prediction_intervals"]["nominal_90pct"]["interval_method"])

    def test_rejects_negative_demand(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "demand.csv"
            output = Path(directory) / "report.json"
            self._write_series(source, invalid="negative")
            with self.assertRaisesRegex(ValueError, "finite and non-negative"):
                evaluate_water_demand(source, output)

    def test_rejects_missing_hour(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "demand.csv"
            output = Path(directory) / "report.json"
            self._write_series(source)
            rows = list(csv.DictReader(source.open(encoding="utf-8")))
            with source.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["timestamp", "water_demand_m3"])
                writer.writeheader()
                for row in rows:
                    if row["timestamp"] != (datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(hours=20)).isoformat():
                        writer.writerow(row)
            with self.assertRaisesRegex(ValueError, "continuous hourly"):
                evaluate_water_demand(source, output)


if __name__ == "__main__":
    unittest.main()

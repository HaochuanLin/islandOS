"""Tests for the optional Mafate load model training experiment."""
import csv
import math
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from experiments.train_mafate_load_model import train_and_evaluate


class MafateLoadModelTests(unittest.TestCase):
    def test_trains_and_compares_against_chronological_baselines(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "hourly.csv"
            report_path = root / "report.json"
            model_path = root / "model.joblib"
            start = datetime(2020, 5, 1)
            with source.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=[
                    "timestamp_local", "house_1_load_kw", "house_2_load_kw", "house_3_load_kw"
                ])
                writer.writeheader()
                for i in range(600):
                    stamp = start + timedelta(hours=i)
                    daily = 0.2 * math.sin(2 * math.pi * stamp.hour / 24)
                    weekly = 0.1 * math.sin(2 * math.pi * stamp.weekday() / 7)
                    value = max(0.05, 0.7 + daily + weekly + 0.0001 * i)
                    writer.writerow({
                        "timestamp_local": stamp.isoformat(),
                        "house_1_load_kw": value,
                        "house_2_load_kw": value * 0.8,
                        "house_3_load_kw": value * 1.1,
                    })

            report = train_and_evaluate(source, report_path, "house_1_load_kw", model_path)

            self.assertEqual(report["status"], "trained_and_evaluated")
            self.assertGreater(report["chronological_split"]["training_samples"], 48)
            self.assertGreater(report["chronological_split"]["test_samples"], 24)
            self.assertEqual(
                set(report["test_metrics"]),
                {"persistence_lag_1h", "seasonal_naive_lag_24h",
                 "seasonal_naive_lag_168h", "hist_gradient_boosting"},
            )
            self.assertTrue(model_path.is_file())
            self.assertTrue(report_path.is_file())
            self.assertEqual(report["forecast_protocol"], "rolling_one_step_ahead")

    def test_rejects_non_hourly_timestamps(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "broken.csv"
            with source.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["timestamp_local", "house_1_load_kw"])
                writer.writeheader()
                start = datetime(2020, 5, 1)
                for i in range(240):
                    stamp = start + timedelta(hours=i + (1 if i == 5 else 0))
                    writer.writerow({"timestamp_local": stamp.isoformat(), "house_1_load_kw": 1.0})
            with self.assertRaisesRegex(ValueError, "continuous hourly timestamps"):
                train_and_evaluate(source, root / "report.json", "house_1_load_kw")


if __name__ == "__main__":
    unittest.main()

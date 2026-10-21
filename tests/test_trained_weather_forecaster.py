"""Tests for the trained, chronological weather regression prototype."""
import csv
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from experiments.forecasting_baselines import evaluate_baselines
from experiments.train_weather_forecaster import train_and_evaluate


class TrainedWeatherForecasterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.raw = self.root / "raw.csv"
        self.baseline_csv = self.root / "baseline.csv"
        self.model_csv = self.root / "model.csv"
        self.n = 240
        start = datetime(2025, 1, 1, tzinfo=timezone.utc)
        self.rows = []
        for i in range(self.n):
            hour = i % 24
            value = max(0.0, 3.0 + 2.0 * __import__("math").sin(2 * __import__("math").pi * hour / 24) + 0.15 * (i % 5))
            self.rows.append({
                "timestamp_utc": (start + timedelta(hours=i)).isoformat().replace("+00:00", "Z"),
                "ALLSKY_SFC_SW_DWN": str(value),
                "T2M": str(20 + hour * 0.2),
                "WS10M": str(4 + (i % 5) * 0.1),
            })
        with self.raw.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["timestamp_utc", "ALLSKY_SFC_SW_DWN", "T2M", "WS10M"])
            writer.writeheader()
            writer.writerows(self.rows)
        self.raw.with_suffix(self.raw.suffix + ".metadata.json").write_text(json.dumps({
            "response_metadata": {"parameters": {
                "ALLSKY_SFC_SW_DWN": {"units": "kWh/m^2"},
                "T2M": {"units": "C"}, "WS10M": {"units": "m/s"},
            }}
        }), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def _run_pipeline(self):
        evaluate_baselines(self.raw, self.baseline_csv)
        return train_and_evaluate(self.baseline_csv, self.model_csv)

    def test_trains_model_and_compares_against_baselines(self):
        result = self._run_pipeline()
        self.assertEqual(result["model"], "ordinary least-squares regression")
        self.assertGreaterEqual(result["training_rows"], 8)
        self.assertGreater(result["test_rows"], 0)
        self.assertEqual(set(result["test_metrics"]), {
            "regression", "persistence", "seasonal_naive_24h"
        })
        self.assertIsInstance(result["test_metrics"]["regression"]["mae"], float)
        self.assertEqual(result["forecast_horizon_hours"], 1)
        with self.model_csv.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), result["test_rows"])
        self.assertTrue(all(row["regression_forecast"] for row in rows))

    def test_holdout_target_changes_do_not_change_first_prediction(self):
        self._run_pipeline()
        with self.model_csv.open(encoding="utf-8", newline="") as handle:
            first = next(csv.DictReader(handle))
        original_prediction = float(first["regression_forecast"])

        with self.baseline_csv.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        first_test = next(i for i, row in enumerate(rows) if row["split"] == "test")
        rows[first_test]["actual"] = str(float(rows[first_test]["actual"]) + 1000.0)
        with self.baseline_csv.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        result = train_and_evaluate(self.baseline_csv, self.model_csv)
        with self.model_csv.open(encoding="utf-8", newline="") as handle:
            second = next(csv.DictReader(handle))
        self.assertAlmostEqual(float(second["regression_forecast"]), original_prediction)
        self.assertGreater(result["test_rows"], 0)


if __name__ == "__main__":
    unittest.main()

"""Tests for leakage-safe weather-parameter forecast baselines."""
import csv
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from experiments.forecasting_baselines import evaluate_baselines


class ForecastingBaselineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.input = self.root / "raw.csv"
        self.output = self.root / "predictions.csv"
        self.n = 120
        start = datetime(2025, 1, 1, tzinfo=timezone.utc)
        self.rows = []
        for i in range(self.n):
            # Deterministic, non-constant series with a daily pattern.
            self.rows.append({
                "timestamp_utc": (start + timedelta(hours=i)).isoformat().replace("+00:00", "Z"),
                "ALLSKY_SFC_SW_DWN": str(2 + (i % 24) * 0.1 + (i % 7) * 0.03),
                "T2M": str(20 + (i % 24) * 0.2),
                "WS10M": str(4 + (i % 5) * 0.1),
            })
        self.write_rows(self.rows)
        self.sidecar = self.input.with_suffix(self.input.suffix + ".metadata.json")
        self.sidecar.write_text(json.dumps({
            "response_metadata": {"parameters": {
                "ALLSKY_SFC_SW_DWN": {"units": "kW-hr/m^2"},
                "T2M": {"units": "C"}, "WS10M": {"units": "m/s"},
            }}
        }), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def write_rows(self, rows):
        with self.input.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=[
                "timestamp_utc", "ALLSKY_SFC_SW_DWN", "T2M", "WS10M"
            ])
            writer.writeheader()
            writer.writerows(rows)

    def test_chronological_holdout_and_metrics(self):
        result = evaluate_baselines(self.input, self.output)
        self.assertGreater(result["history_rows_before_test"], 0)
        self.assertGreater(result["test_rows"], 0)
        self.assertEqual(result["history_rows_before_test"] + result["test_rows"], self.n - 24)
        self.assertEqual(result["forecast_horizon_hours"], 1)
        self.assertEqual(result["target_units"], "kW-hr/m^2")
        self.assertGreaterEqual(result["test_metrics"]["persistence"]["mae"], 0)
        with self.output.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        test_rows = [row for row in rows if row["split"] == "test"]
        self.assertEqual(test_rows[0]["timestamp_utc"], result["first_test_timestamp_utc"])
        first_test_index = next(i for i, row in enumerate(rows) if row["split"] == "test")
        self.assertTrue(all(row["split"] == "history" for row in rows[:first_test_index]))

    def test_forecasts_only_use_past_values(self):
        evaluate_baselines(self.input, self.output)
        with self.output.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        for row in rows:
            stamp = datetime.fromisoformat(row["timestamp_utc"].replace("Z", "+00:00"))
            index = int((stamp - datetime(2025, 1, 1, tzinfo=timezone.utc)).total_seconds() / 3600)
            self.assertAlmostEqual(float(row["persistence_forecast"]), float(self.rows[index - 1]["ALLSKY_SFC_SW_DWN"]))
            self.assertAlmostEqual(float(row["seasonal_naive_24h_forecast"]), float(self.rows[index - 24]["ALLSKY_SFC_SW_DWN"]))

    def test_rejects_gaps_and_missing_values(self):
        broken = self.rows.copy()
        broken[40] = dict(broken[40])
        broken[40]["timestamp_utc"] = "2025-01-02T18:00:00Z"
        self.write_rows(broken)
        with self.assertRaisesRegex(ValueError, "continuous ordered"):
            evaluate_baselines(self.input, self.output)
        self.write_rows(self.rows)
        broken = self.rows.copy()
        broken[40] = dict(broken[40])
        broken[40]["ALLSKY_SFC_SW_DWN"] = ""
        self.write_rows(broken)
        with self.assertRaisesRegex(ValueError, "Missing ALLSKY"):
            evaluate_baselines(self.input, self.output)

    def test_rejects_missing_units_short_series_and_invalid_split(self):
        self.sidecar.write_text(json.dumps({"response_metadata": {"parameters": {}}}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "declare units"):
            evaluate_baselines(self.input, self.output)
        self.sidecar.write_text(json.dumps({"response_metadata": {"parameters": {
            "ALLSKY_SFC_SW_DWN": {"units": "kW-hr/m^2"}
        }}}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "between 0.05 and 0.50"):
            evaluate_baselines(self.input, self.output, test_fraction=0.8)
        self.write_rows(self.rows[:30])
        with self.assertRaisesRegex(ValueError, "at least 34"):
            evaluate_baselines(self.input, self.output)


if __name__ == "__main__":
    unittest.main()

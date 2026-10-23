"""Tests for point-versus-upper-bound demand planning stress analysis."""
import csv
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from experiments.evaluate_water_demand_uncertainty_dispatch import evaluate_uncertainty_dispatch


class TestWaterDemandUncertaintyDispatch(unittest.TestCase):
    def test_compares_point_and_upper_bound_on_identical_timestamps(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            power = root / "power.csv"
            forecast = root / "forecast.json"
            output = root / "comparison.json"
            start = datetime(2025, 1, 1, tzinfo=timezone.utc)
            rows = []
            with power.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=[
                    "timestamp_utc", "actual_surplus_kw", "forecast_surplus_kw",
                    "water_demand_m3", "cooling_demand_kw_th",
                ])
                writer.writeheader()
                for i in range(48):
                    actual = 25.0 + (i % 6)
                    stamp = start + timedelta(hours=i)
                    writer.writerow({
                        "timestamp_utc": stamp.isoformat(),
                        "actual_surplus_kw": 18 + i % 7,
                        "forecast_surplus_kw": 17 + i % 7,
                        "water_demand_m3": actual,
                        "cooling_demand_kw_th": 7 + i % 3,
                    })
                    rows.append({
                        "timestamp": stamp.isoformat(),
                        "actual_water_demand_m3": actual,
                        "seasonal_bias_corrected_forecast_m3": actual - 1.0,
                        "seasonal_bias_corrected_90pct_upper_m3": actual + 2.0,
                    })
            forecast.write_text(json.dumps({
                "status": "baseline_evaluated",
                "test_predictions": rows,
            }), encoding="utf-8")

            report = evaluate_uncertainty_dispatch(power, forecast, output)

            self.assertEqual(report["status"], "uncertainty_dispatch_comparison_completed")
            self.assertEqual(report["time_basis"]["matched_rows"], 48)
            self.assertEqual(
                report["forecast_columns"]["point"],
                "seasonal_bias_corrected_forecast_m3",
            )
            self.assertEqual(
                report["forecast_columns"]["upper_bound_stress"],
                "seasonal_bias_corrected_90pct_upper_m3",
            )
            self.assertIn("water_unmet_m3", report["change_upper_minus_point"])
            self.assertIn("cooling_unmet_kwh_th", report["change_upper_minus_point"])
            self.assertIn("same realized demand", report["interpretation"])
            saved = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(saved["time_basis"]["matched_rows"], 48)

            for row in rows:
                row["seasonal_bias_corrected_90pct_upper_m3"] = (
                    row["actual_water_demand_m3"] - 2.0
                )
            forecast.write_text(json.dumps({
                "status": "baseline_evaluated",
                "test_predictions": rows,
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Upper-bound forecast must be at least"):
                evaluate_uncertainty_dispatch(power, forecast, output)

    def test_rejects_same_column_for_point_and_upper_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "must be different"):
                evaluate_uncertainty_dispatch(
                    root / "missing.csv", root / "missing.json", root / "out.json",
                    point_column="same", upper_column="same",
                )


if __name__ == "__main__":
    unittest.main()

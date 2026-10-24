"""Tests for joining chronological water-demand forecasts to dispatch inputs."""
import csv
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from experiments.build_forecast_dispatch_input import build_forecast_dispatch_input


class TestForecastDispatchInputBuilder(unittest.TestCase):
    def _write_power_csv(self, path: Path, demand=(10.0, 11.0, 12.0, 13.0)) -> None:
        start = datetime(2025, 1, 1, tzinfo=timezone.utc)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "timestamp_utc",
                    "actual_surplus_kw",
                    "forecast_surplus_kw",
                    "water_demand_m3",
                    "cooling_demand_kw_th",
                ],
            )
            writer.writeheader()
            for index, value in enumerate(demand):
                writer.writerow({
                    "timestamp_utc": (start + timedelta(hours=index)).isoformat(),
                    "actual_surplus_kw": 20 + index,
                    "forecast_surplus_kw": 19 + index,
                    "water_demand_m3": value,
                    "cooling_demand_kw_th": 5 + index,
                })

    def _write_forecast_report(self, path: Path, demand=(11.0, 12.0), predictions=(10.5, 11.5)) -> None:
        start = datetime(2025, 1, 1, tzinfo=timezone.utc)
        report = {
            "status": "models_compared",
            "forecast_rows": [
                {
                    "timestamp": (start + timedelta(hours=index + 1)).isoformat(),
                    "actual_water_demand_m3": demand[index],
                    "hist_gradient_boosting": predictions[index],
                }
                for index in range(len(demand))
            ],
        }
        path.write_text(json.dumps(report), encoding="utf-8")

    def test_joins_forecasts_and_preserves_actual_demand(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            power = root / "power.csv"
            model = root / "model.json"
            output = root / "joined.csv"
            self._write_power_csv(power)
            self._write_forecast_report(model)

            result = build_forecast_dispatch_input(power, model, output)

            self.assertEqual(result["status"], "forecast_dispatch_input_built")
            self.assertEqual(result["forecast_column_used"], "hist_gradient_boosting")
            self.assertEqual(result["matched_rows"], 2)
            with output.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["timestamp_utc"], "2025-01-01T01:00:00Z")
            self.assertEqual(float(rows[0]["water_demand_m3"]), 11.0)
            self.assertEqual(float(rows[0]["forecast_water_demand_m3"]), 10.5)
            self.assertEqual(float(rows[1]["water_demand_m3"]), 12.0)
            self.assertEqual(float(rows[1]["forecast_water_demand_m3"]), 11.5)
            saved_report = json.loads(Path(result["report_json"]).read_text(encoding="utf-8"))
            self.assertEqual(saved_report["matched_rows"], 2)
            self.assertTrue(saved_report["actual_water_demand_preserved_for_execution"])

    def test_auto_selects_lstm_when_it_is_the_only_forecast_column(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            power, model, output = root / "power.csv", root / "lstm.json", root / "joined.csv"
            self._write_power_csv(power)
            start = datetime(2025, 1, 1, tzinfo=timezone.utc)
            report = {"status": "models_compared", "forecast_rows": [
                {"timestamp": (start + timedelta(hours=i + 1)).isoformat(),
                 "actual_water_demand_m3": [11.0, 12.0][i],
                 "lstm_deep_learning": [10.8, 12.2][i]} for i in range(2)]}
            model.write_text(json.dumps(report), encoding="utf-8")
            result = build_forecast_dispatch_input(power, model, output)
            self.assertEqual(result["forecast_column_used"], "lstm_deep_learning")
            with output.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(float(rows[0]["forecast_water_demand_m3"]), 10.8)
            self.assertEqual(float(rows[1]["forecast_water_demand_m3"]), 12.2)

    def test_rejects_actual_demand_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            power = root / "power.csv"
            model = root / "model.json"
            self._write_power_csv(power)
            self._write_forecast_report(model, demand=(99.0, 12.0))

            with self.assertRaisesRegex(ValueError, "Actual water demand differs"):
                build_forecast_dispatch_input(power, model, root / "joined.csv")

    def test_rejects_forecast_timestamp_without_power_match(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            power = root / "power.csv"
            model = root / "model.json"
            self._write_power_csv(power)
            start = datetime(2025, 1, 1, tzinfo=timezone.utc)
            report = {
                "status": "models_compared",
                "forecast_rows": [{
                    "timestamp": (start + timedelta(days=3)).isoformat(),
                    "actual_water_demand_m3": 12.0,
                    "hist_gradient_boosting": 12.1,
                }],
            }
            model.write_text(json.dumps(report), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "No matching power/dispatch row"):
                build_forecast_dispatch_input(power, model, root / "joined.csv")

    def test_rejects_negative_forecast(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            power = root / "power.csv"
            model = root / "model.json"
            self._write_power_csv(power)
            self._write_forecast_report(model, predictions=(-1.0, 11.5))

            with self.assertRaisesRegex(ValueError, "finite and non-negative"):
                build_forecast_dispatch_input(power, model, root / "joined.csv")

    def test_rejects_duplicate_power_csv_headers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            power = root / "power.csv"
            with power.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow([
                    "timestamp_utc", "actual_surplus_kw", "actual_surplus_kw",
                    "forecast_surplus_kw", "water_demand_m3", "cooling_demand_kw_th",
                ])
                writer.writerow(["2026-01-01T00:00:00Z", 10, 11, 12, 20, 50])

            with self.assertRaisesRegex(ValueError, "duplicate columns"):
                build_forecast_dispatch_input(
                    power, root / "not-read-before-power-validation.json", root / "joined.csv"
                )


if __name__ == "__main__":
    unittest.main()

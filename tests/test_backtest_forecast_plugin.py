"""End-to-end tests for third-party forecast plugins and dispatch integration."""
import csv
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from experiments.backtest_forecast_plugin import backtest_plugin
from experiments.build_forecast_dispatch_input import build_forecast_dispatch_input

class LastValuePlugin:
    model_id = "test-last-value"
    version = "1.2.3"
    def predict(self, history, target_timestamps):
        return [history[-1].demand_m3 for _ in target_timestamps]

class TestForecastPluginBacktest(unittest.TestCase):
    def _write_series(self, path: Path, count: int = 100) -> list[datetime]:
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        stamps = [start + timedelta(hours=i) for i in range(count)]
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["timestamp", "water_demand_m3"])
            writer.writeheader()
            for i, stamp in enumerate(stamps):
                writer.writerow({"timestamp": stamp.isoformat().replace("+00:00", "Z"),
                                 "water_demand_m3": 10 + (i % 7)})
        return stamps

    def _write_power(self, path: Path, stamps: list[datetime]) -> None:
        columns = ["timestamp_utc", "actual_surplus_kw", "forecast_surplus_kw",
                   "water_demand_m3", "cooling_demand_kw_th"]
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            for i, stamp in enumerate(stamps):
                writer.writerow({
                    "timestamp_utc": stamp.isoformat().replace("+00:00", "Z"),
                    "actual_surplus_kw": 20 + i % 3, "forecast_surplus_kw": 19 + i % 3,
                    "water_demand_m3": 10 + i % 7, "cooling_demand_kw_th": 5,
                })

    def test_plugin_backtest_output_joins_into_dispatch_input(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, power = root / "hourly.csv", root / "power.csv"
            report_path, dispatch = root / "forecast.json", root / "dispatch.csv"
            stamps = self._write_series(source)
            self._write_power(power, stamps)
            report = backtest_plugin(source, LastValuePlugin(), report_path,
                                     test_fraction=0.2, history_hours=24)
            self.assertEqual(report["status"], "rolling_backtest_completed")
            self.assertEqual(report["model_id"], "test-last-value")
            self.assertEqual(report["training"]["test_samples"], 20)
            self.assertEqual(len(report["input_csv_sha256"]), 64)
            self.assertTrue(report["training"]["only_prior_observations_passed_to_plugin"])
            self.assertEqual(report["forecast_rows"][0]["timestamp"],
                             stamps[80].isoformat().replace("+00:00", "Z"))
            joined = build_forecast_dispatch_input(
                power, report_path, dispatch, forecast_column="plugin_forecast_m3")
            self.assertEqual(joined["matched_rows"], 20)
            with dispatch.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 20)
            self.assertEqual(float(rows[0]["water_demand_m3"]), 10 + 80 % 7)
            self.assertEqual(float(rows[0]["forecast_water_demand_m3"]), 10 + 79 % 7)
            self.assertTrue(json.loads(report_path.read_text())["input_csv_sha256"])

    def test_rejects_gapped_series_and_bad_split(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "hourly.csv"
            stamps = self._write_series(source, count=20)
            with source.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            rows[5]["timestamp"] = stamps[6].isoformat()
            with source.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["timestamp", "water_demand_m3"])
                writer.writeheader()
                writer.writerows(rows)
            with self.assertRaisesRegex(ValueError, "continuous hourly"):
                backtest_plugin(source, LastValuePlugin(), root / "out.json", history_hours=5)
            self._write_series(source, count=20)
            with self.assertRaisesRegex(ValueError, "Need more than"):
                backtest_plugin(source, LastValuePlugin(), root / "out.json", history_hours=20)

    def test_rejects_duplicate_and_extra_csv_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "series.csv"
            output = root / "report.json"
            self._write_series(source, count=10)
            lines = source.read_text(encoding="utf-8").splitlines()
            lines[0] = "timestamp,timestamp"
            source.write_text("\n".join(lines) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate columns"):
                backtest_plugin(source, LastValuePlugin(), output, history_hours=5)

            self._write_series(source, count=10)
            lines = source.read_text(encoding="utf-8").splitlines()
            lines[1] += ",unexpected"
            source.write_text("\n".join(lines) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "extra fields"):
                backtest_plugin(source, LastValuePlugin(), output, history_hours=5)

if __name__ == "__main__":
    unittest.main()

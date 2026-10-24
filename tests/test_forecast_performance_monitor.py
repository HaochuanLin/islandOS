"""Tests for water-demand forecast performance monitoring."""
import csv
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from experiments.monitor_forecast_performance import monitor_forecast_performance


class TestForecastPerformanceMonitor(unittest.TestCase):
    def _write_series(self, path: Path, count: int = 48, drift: bool = False) -> None:
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "timestamp",
                    "actual_water_demand_m3",
                    "forecast_water_demand_m3",
                ],
            )
            writer.writeheader()
            for i in range(count):
                actual = 30.0 + (i % 7)
                error = 1.0 if not drift or i < count // 2 else 8.0
                writer.writerow({
                    "timestamp": (start + timedelta(hours=i)).isoformat(),
                    "actual_water_demand_m3": actual,
                    "forecast_water_demand_m3": actual + error,
                })

    def test_flags_degradation_in_recent_window(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "series.csv"
            output = Path(directory) / "monitor.json"
            self._write_series(source, drift=True)
            report = monitor_forecast_performance(source, output, window_hours=24)
            self.assertEqual(report["status"], "review_recommended")
            self.assertEqual(report["window_count"], 2)
            self.assertEqual(report["baseline_window"]["metrics"]["mae_m3_per_hour"], 1.0)
            self.assertEqual(report["most_recent_window"]["metrics"]["mae_m3_per_hour"], 8.0)
            self.assertEqual(json.loads(output.read_text())["status"], "review_recommended")

    def test_stable_error_does_not_trigger_degradation_flag(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "series.csv"
            output = Path(directory) / "monitor.json"
            self._write_series(source)
            report = monitor_forecast_performance(source, output, window_hours=24)
            self.assertEqual(report["status"], "no_mae_degradation_flag")
            self.assertEqual(report["recent_mae_relative_change_vs_baseline"], 0.0)

    def test_rejects_missing_hour(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "series.csv"
            output = Path(directory) / "monitor.json"
            self._write_series(source)
            with source.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            with source.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows[:10] + rows[11:])
            with self.assertRaisesRegex(ValueError, "continuous hourly"):
                monitor_forecast_performance(source, output, window_hours=12)

    def test_requires_two_full_windows(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "series.csv"
            output = Path(directory) / "monitor.json"
            self._write_series(source, count=23)
            with self.assertRaisesRegex(ValueError, "two full monitoring windows"):
                monitor_forecast_performance(source, output, window_hours=12)

    def test_rejects_duplicate_and_extra_csv_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "series.csv"
            output = Path(directory) / "monitor.json"
            self._write_series(source)
            lines = source.read_text(encoding="utf-8").splitlines()
            lines[0] = lines[0].replace("forecast_water_demand_m3", "actual_water_demand_m3")
            source.write_text("\n".join(lines) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate columns"):
                monitor_forecast_performance(source, output, window_hours=12)

            self._write_series(source)
            lines = source.read_text(encoding="utf-8").splitlines()
            lines[1] += ",unexpected"
            source.write_text("\n".join(lines) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "extra fields"):
                monitor_forecast_performance(source, output, window_hours=12)


if __name__ == "__main__":
    unittest.main()

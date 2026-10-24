"""Tests for forecast-aware RO simulation evaluation from paired forecast inputs."""
import csv
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from island_microgrid_ro_sim import Params
from experiments.evaluate_forecast_driven_ro_sim import evaluate_forecast_driven_ro_sim

class TestForecastDrivenROSimulation(unittest.TestCase):
    def _write(self, path: Path, surplus, forecast, demand, forecast_demand):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=[
                "timestamp_utc", "actual_surplus_kw", "forecast_surplus_kw",
                "water_demand_m3", "forecast_water_demand_m3",
            ])
            writer.writeheader()
            for i in range(len(surplus)):
                writer.writerow({
                    "timestamp_utc": (start + timedelta(hours=i)).isoformat().replace("+00:00", "Z"),
                    "actual_surplus_kw": surplus[i], "forecast_surplus_kw": forecast[i],
                    "water_demand_m3": demand[i], "forecast_water_demand_m3": forecast_demand[i],
                })

    def test_forecast_driven_scenario_reports_forecast_error_cost_vs_oracle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output, report_path = root / "paired.csv", root / "hourly.csv", root / "report.json"
            self._write(source, [0, 0, 0, 0], [150, 150, 0, 0], [1, 1, 1, 1], [1, 1, 1, 1])
            params = Params(ro_power_kw=100, ro_sec_kwh_m3=2, min_run_hours=2,
                            start_ratio=0.5, keep_ratio=0.5, allow_backup_power=True,
                            res_capacity_m3=1000, res_init_m3=100, res_min_m3=0)
            report = evaluate_forecast_driven_ro_sim(source, output, report_path, params)
            self.assertEqual(report["status"], "forecast_driven_ro_simulation_evaluated")
            self.assertEqual(report["forecast_driven_scenario"]["ro_run_hours"], 2)
            self.assertEqual(report["forecast_driven_scenario"]["backup_energy_kwh"], 200)
            self.assertEqual(report["perfect_foresight_reference"]["backup_energy_kwh"], 0)
            self.assertEqual(report["difference_forecast_minus_reference"]["backup_energy_kwh"], 200)
            self.assertEqual(report["forecast_quality"]["surplus_mae_kw"], 75)
            with output.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 4)
            self.assertEqual(rows[0]["forecast_driven_ro_on"], "1")
            self.assertEqual(rows[0]["oracle_ro_on"], "0")
            self.assertEqual(len(report["input_csv_sha256"]), 64)
            self.assertTrue(report_path.exists())

    def test_no_backup_forecast_error_is_reported_as_min_run_violation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "paired.csv"
            self._write(source, [100, 0, 0], [100, 100, 100], [1, 1, 1], [1, 1, 1])
            params = Params(ro_power_kw=100, ro_sec_kwh_m3=2, min_run_hours=2,
                            allow_backup_power=False, res_capacity_m3=1000,
                            res_init_m3=100, res_min_m3=0)
            report = evaluate_forecast_driven_ro_sim(source, root / "hourly.csv", params=params)
            scenario = report["forecast_driven_scenario"]
            self.assertEqual(scenario["emergency_stop_count"], 1)
            self.assertFalse(scenario["minimum_run_constraint_satisfied"])
            self.assertTrue(report["perfect_foresight_reference"]["minimum_run_constraint_satisfied"])

    def test_rejects_invalid_forecast_values(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "paired.csv"
            self._write(source, [0, 0, 0], [0, 0, 0], [1, 1, 1], [1, 1, 1])
            with source.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            rows[1]["forecast_surplus_kw"] = "-1"
            with source.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            with self.assertRaisesRegex(ValueError, "finite and non-negative"):
                evaluate_forecast_driven_ro_sim(source, root / "out.csv")

if __name__ == "__main__":
    unittest.main()

"""Tests for forecast-aware RO simulation evaluation from paired forecast inputs."""
import csv
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from island_microgrid_ro_sim import Params
from experiments.evaluate_forecast_driven_ro_sim import evaluate_forecast_driven_ro_sim
from experiments.backtest_forecast_plugin import backtest_plugin
from experiments.build_forecast_dispatch_input import build_forecast_dispatch_input

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

    def test_plugin_to_dispatch_to_forecast_driven_simulation_end_to_end(self):
        class LastValuePlugin:
            model_id = "end-to-end-last-value"
            version = "1.0.0"
            def predict(self, history, target_timestamps):
                return [history[-1].demand_m3 for _ in target_timestamps]

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            series_path = root / "water.csv"
            power_path = root / "power.csv"
            forecast_path = root / "plugin-forecast.json"
            paired_path = root / "paired-dispatch.csv"
            hourly_path = root / "simulation.csv"
            start = datetime(2026, 1, 1, tzinfo=timezone.utc)
            stamps = [start + timedelta(hours=i) for i in range(100)]
            with series_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["timestamp", "water_demand_m3"])
                writer.writeheader()
                for i, stamp in enumerate(stamps):
                    writer.writerow({
                        "timestamp": stamp.isoformat().replace("+00:00", "Z"),
                        "water_demand_m3": 10 + i % 7,
                    })
            with power_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=[
                    "timestamp_utc", "actual_surplus_kw", "forecast_surplus_kw",
                    "water_demand_m3", "cooling_demand_kw_th",
                ])
                writer.writeheader()
                for i, stamp in enumerate(stamps):
                    writer.writerow({
                        "timestamp_utc": stamp.isoformat().replace("+00:00", "Z"),
                        "actual_surplus_kw": 0,
                        "forecast_surplus_kw": 150 if i in (80, 81) else 0,
                        "water_demand_m3": 10 + i % 7,
                        "cooling_demand_kw_th": 5,
                    })

            backtest = backtest_plugin(
                series_path, LastValuePlugin(), forecast_path,
                test_fraction=0.2, history_hours=24,
            )
            self.assertEqual(backtest["training"]["test_samples"], 20)
            joined = build_forecast_dispatch_input(
                power_path, forecast_path, paired_path,
                forecast_column="plugin_forecast_m3",
            )
            self.assertEqual(joined["matched_rows"], 20)
            params = Params(
                ro_power_kw=100, ro_sec_kwh_m3=2, min_run_hours=2,
                start_ratio=0.5, keep_ratio=0.5, allow_backup_power=True,
                res_capacity_m3=1000, res_init_m3=100, res_min_m3=0,
            )
            result = evaluate_forecast_driven_ro_sim(paired_path, hourly_path, params=params)
            self.assertEqual(result["forecast_driven_scenario"]["ro_run_hours"], 2)
            self.assertEqual(result["forecast_driven_scenario"]["backup_energy_kwh"], 200)
            self.assertEqual(result["perfect_foresight_reference"]["ro_run_hours"], 0)
            self.assertTrue(hourly_path.exists())

    def test_rejects_duplicate_and_extra_input_csv_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output = root / "paired.csv", root / "hourly.csv"
            self._write(source, [1, 2], [1, 2], [1, 1], [1, 1])
            lines = source.read_text(encoding="utf-8").splitlines()
            lines[0] = lines[0].replace("forecast_surplus_kw", "actual_surplus_kw")
            source.write_text("\n".join(lines) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate columns"):
                evaluate_forecast_driven_ro_sim(source, output)

            self._write(source, [1, 2], [1, 2], [1, 1], [1, 1])
            lines = source.read_text(encoding="utf-8").splitlines()
            lines[1] += ",unexpected"
            source.write_text("\n".join(lines) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "extra fields"):
                evaluate_forecast_driven_ro_sim(source, output)


if __name__ == "__main__":
    unittest.main()

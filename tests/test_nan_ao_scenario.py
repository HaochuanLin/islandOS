import tempfile
import unittest
from pathlib import Path

import nan_ao_scenario


class NanAoScenarioTests(unittest.TestCase):
    def test_seeded_run_is_reproducible(self):
        rows_a, summary_a = nan_ao_scenario.run_simulation(runs=20, seed=123)
        rows_b, summary_b = nan_ao_scenario.run_simulation(runs=20, seed=123)
        self.assertEqual(rows_a, rows_b)
        self.assertEqual(summary_a, summary_b)

    def test_outputs_are_nonnegative_and_ordered(self):
        rows, summary = nan_ao_scenario.run_simulation(runs=100, seed=123)
        self.assertEqual(len(rows), 100)
        values = summary["scenario_water_produced_m3_per_year"]
        self.assertGreaterEqual(values["p05"], 0)
        self.assertLessEqual(values["p05"], values["p50_median"])
        self.assertLessEqual(values["p50_median"], values["p95"])
        self.assertGreaterEqual(values["mean"], 0)

    def test_sensitivity_grid_is_complete_and_monotonic(self):
        rows = nan_ao_scenario.run_sensitivity_analysis()
        self.assertEqual(len(rows), 243)
        baseline = next(
            row for row in rows
            if row["assumed_events_per_year"] == 8
            and row["representative_event_duration_h"] == 8.0
            and row["available_surplus_power_kw"] == 25.0
            and row["ro_availability_fraction"] == 0.925
            and row["specific_energy_kwh_per_m3"] == 4.0
        )
        self.assertAlmostEqual(
            baseline["scenario_water_m3_per_year"],
            8 * 8 * 25 * 0.925 / 4.0,
            places=3,
        )
        high_sec = next(
            row for row in rows
            if row["assumed_events_per_year"] == 8
            and row["representative_event_duration_h"] == 8.0
            and row["available_surplus_power_kw"] == 25.0
            and row["ro_availability_fraction"] == 0.925
            and row["specific_energy_kwh_per_m3"] == 5.0
        )
        self.assertLess(high_sec["scenario_water_m3_per_year"], baseline["scenario_water_m3_per_year"])
        self.assertIn("not a probability", baseline["interpretation"])

    def test_capital_cost_screen_is_transparent_and_validated(self):
        screen = nan_ao_scenario.calculate_capital_cost_screen(
            annual_water_output_m3=442.734
        )
        self.assertAlmostEqual(
            screen["capital_only_cost_rmb_per_m3_low"],
            1600000 / 10 / 442.734,
            places=2,
        )
        self.assertAlmostEqual(
            screen["capital_only_cost_rmb_per_m3_high"],
            3300000 / 10 / 442.734,
            places=2,
        )
        self.assertIn("not ROI", screen["status"])
        with self.assertRaises(ValueError):
            nan_ao_scenario.calculate_capital_cost_screen(annual_water_output_m3=0)
        with self.assertRaises(ValueError):
            nan_ao_scenario.calculate_capital_cost_screen(
                annual_water_output_m3=100, capex_low_rmb=3_000_000,
                capex_high_rmb=2_000_000,
            )

    def test_writer_creates_auditable_outputs_including_sensitivity(self):
        with tempfile.TemporaryDirectory() as tmp:
            nan_ao_scenario.write_outputs(Path(tmp), runs=5, seed=7)
            self.assertTrue((Path(tmp) / "nan_ao_annual_runs.csv").exists())
            self.assertTrue((Path(tmp) / "nan_ao_percentiles.csv").exists())
            self.assertTrue((Path(tmp) / "nan_ao_summary.json").exists())
            self.assertTrue((Path(tmp) / "nan_ao_financial_screen.json").exists())
            sensitivity_path = Path(tmp) / "nan_ao_sensitivity.csv"
            self.assertTrue(sensitivity_path.exists())
            with sensitivity_path.open(encoding="utf-8", newline="") as handle:
                self.assertEqual(sum(1 for _ in handle), 244)  # header + 243 combinations


if __name__ == "__main__":
    unittest.main()

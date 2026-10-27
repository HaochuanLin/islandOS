import json
import tempfile
import unittest
from pathlib import Path

import nan_ao_scenario


class NanAoScenarioTests(unittest.TestCase):
    def test_default_seed_is_reproducible(self):
        self.assertEqual(nan_ao_scenario.DEFAULT_SEED, 20261027)
        rows_a, summary_a = nan_ao_scenario.run_simulation(runs=20, seed=nan_ao_scenario.DEFAULT_SEED)
        rows_b, summary_b = nan_ao_scenario.run_simulation(runs=20, seed=nan_ao_scenario.DEFAULT_SEED)
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
        self.assertEqual(summary["assumptions"]["ro_purchase_capex_rmb"], 0)
        self.assertIn("emergency", summary["assumptions"]["scenario_scope"])

    def test_sensitivity_grid_is_complete(self):
        rows = nan_ao_scenario.run_sensitivity_analysis()
        self.assertEqual(len(rows), 243)
        baseline = next(row for row in rows if row["assumed_events_per_year"] == 8
                        and row["representative_event_duration_h"] == 8.0
                        and row["available_surplus_power_kw"] == 25.0
                        and row["ro_availability_fraction"] == 0.925
                        and row["specific_energy_kwh_per_m3"] == 4.0)
        self.assertAlmostEqual(baseline["scenario_water_m3_per_year"], 8 * 8 * 25 * 0.925 / 4.0)
        self.assertIn("not a probability", baseline["interpretation"])

    def test_writer_uses_stable_names_and_no_capex_screen(self):
        with tempfile.TemporaryDirectory() as tmp:
            nan_ao_scenario.write_outputs(Path(tmp), runs=5, seed=7)
            expected = {"nan_ao_annual_runs.csv", "nan_ao_percentiles.csv",
                        "nan_ao_summary.json", "nan_ao_sensitivity.csv"}
            self.assertTrue(expected.issubset({p.name for p in Path(tmp).iterdir()}))
            self.assertFalse((Path(tmp) / "nan_ao_financial_screen.json").exists())
            with (Path(tmp) / "nan_ao_summary.json").open(encoding="utf-8") as handle:
                summary = json.load(handle)
            self.assertEqual(summary["seed"], 7)
            self.assertEqual(summary["assumptions"]["ro_purchase_capex_rmb"], 0)


if __name__ == "__main__":
    unittest.main()

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

    def test_writer_creates_three_auditable_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            nan_ao_scenario.write_outputs(Path(tmp), runs=5, seed=7)
            self.assertTrue((Path(tmp) / "nan_ao_annual_runs.csv").exists())
            self.assertTrue((Path(tmp) / "nan_ao_percentiles.csv").exists())
            self.assertTrue((Path(tmp) / "nan_ao_summary.json").exists())


if __name__ == "__main__":
    unittest.main()

import csv
import json
import tempfile
import unittest
from pathlib import Path

import islandos_nanao_hybrid as model


class NanAoHybridTests(unittest.TestCase):
    def test_reproducible_single_scenario(self):
        a, ma = model.build_hybrid_result()
        b, mb = model.build_hybrid_result()
        self.assertEqual(a, b)
        self.assertEqual(ma, mb)
        self.assertEqual(a["scenario"], "IslandOS_hybrid_clean_energy")
        self.assertEqual(ma["seed"], 20261028)
        self.assertEqual(ma["run_count"], 1000)

    def test_valley_formula_and_total_water(self):
        result, meta = model.build_hybrid_result()
        p = meta["parameters"]
        expected = (100.0 / 4.0) * 8.0 * 365 * 0.925
        self.assertAlmostEqual(meta["calculated_values"]["valley_annual_water_m3"], expected, places=3)
        self.assertAlmostEqual(result["total_annual_water_m³"],
                               expected + meta["calculated_values"]["wind_water_m3_median"], places=3)
        self.assertEqual(p["ro_unit_count"], 2)
        self.assertEqual(p["ro_rated_power_kw"], 100.0)
        self.assertEqual(p["ro_availability_factor"], 0.925)
        self.assertEqual(p["ro_purchase_capex_rmb"], 0)

    def test_hours_are_simulated_outputs(self):
        yields, hours = model.simulate_wind_curtailment(1000, model.DEFAULT_SEED)
        self.assertEqual(len(yields), 1000)
        self.assertEqual(len(hours), 1000)
        self.assertGreater(max(hours), 0)
        _, meta = model.build_hybrid_result()
        self.assertIn("simulated_annual_wind_curtailment_hours_median", meta["calculated_values"])
        self.assertNotIn("annual_wind_curtailment_hours", meta["parameters"])

    def test_one_csv_row_and_metadata(self):
        result, meta = model.build_hybrid_result(runs=20, seed=99)
        with tempfile.TemporaryDirectory() as tmp:
            model.write_outputs(Path(tmp), result, meta)
            with (Path(tmp) / "scenario_result.csv").open(newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["scenario"], "IslandOS_hybrid_clean_energy")
            saved = json.loads((Path(tmp) / "sim_meta.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["seed"], 99)
            self.assertEqual(saved["run_count"], 20)

    def test_cost_bounds_and_bad_run_count(self):
        result, _ = model.build_hybrid_result(runs=50, seed=5)
        self.assertLess(result["unit_op_cost_min_rmb"], result["unit_op_cost_max_rmb"])
        with self.assertRaises(ValueError):
            model.simulate_wind_curtailment(0, model.DEFAULT_SEED)


if __name__ == "__main__":
    unittest.main()

import csv
import json
import tempfile
import unittest
from pathlib import Path

import islandos_nanao_hybrid as model


class NanAoHybridTests(unittest.TestCase):
    def test_reproducible_single_scenario(self):
        result_a, meta_a = model.build_hybrid_result()
        result_b, meta_b = model.build_hybrid_result()
        self.assertEqual(result_a, result_b)
        self.assertEqual(meta_a, meta_b)
        self.assertEqual(result_a["scenario"], "IslandOS_hybrid_clean_energy")
        self.assertEqual(meta_a["seed"], 20261027)
        self.assertEqual(meta_a["run_count"], 1000)

    def test_water_and_population_formulas(self):
        result, meta = model.build_hybrid_result()
        wind_median = meta["wind_curtailment_water_m3_per_year"]["median"]
        self.assertAlmostEqual(result["total_annual_water_m³"], 33650 + wind_median, places=3)
        self.assertAlmostEqual(result["supported_population_50L"], result["total_annual_water_m³"] / (0.05 * 365), places=2)
        self.assertEqual(meta["key_assumptions"]["ro_purchase_capex_rmb"], 0)

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
            model.simulate_wind_curtailment_water(0, model.DEFAULT_SEED)


if __name__ == "__main__":
    unittest.main()

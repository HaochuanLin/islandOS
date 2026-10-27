import csv
import json
import tempfile
import unittest
from pathlib import Path

import islandos_nanao_hybrid as model


class NanAoHybridTests(unittest.TestCase):
    def test_fixed_seed_reproducibility_and_single_scenario(self):
        first, meta_first = model.build_hybrid_result(runs=1000, seed=model.DEFAULT_SEED)
        second, meta_second = model.build_hybrid_result(runs=1000, seed=model.DEFAULT_SEED)
        self.assertEqual(first, second)
        self.assertEqual(meta_first, meta_second)
        self.assertEqual(first["scenario"], "IslandOS_hybrid_clean_energy")
        self.assertEqual(meta_first["seed"], 20261027)
        self.assertEqual(meta_first["run_count"], 1000)

    def test_hybrid_water_and_population_formulas(self):
        result, meta = model.build_hybrid_result(runs=1000, seed=model.DEFAULT_SEED)
        wind_median = meta["wind_curtailment_water_m3_per_year"]["median"]
        self.assertAlmostEqual(result["total_annual_water_m³"], 33650.0 + wind_median, places=3)
        self.assertAlmostEqual(result["supported_population_50L"],
                               result["total_annual_water_m³"] / (0.05 * 365), places=2)
        self.assertEqual(meta["key_assumptions"]["ro_purchase_capex_rmb"], 0)

    def test_only_one_csv_data_row_and_meta_written(self):
        result, meta = model.build_hybrid_result(runs=20, seed=99)
        with tempfile.TemporaryDirectory() as tmp:
            model.write_outputs(Path(tmp), result, meta)
            with (Path(tmp) / "scenario_result.csv").open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["scenario"], "IslandOS_hybrid_clean_energy")
            saved_meta = json.loads((Path(tmp) / "sim_meta.json").read_text(encoding="utf-8"))
            self.assertEqual(saved_meta["seed"], 99)
            self.assertEqual(saved_meta["run_count"], 20)

    def test_cost_bounds_and_invalid_run_count(self):
        result, _ = model.build_hybrid_result(runs=50, seed=5)
        self.assertLess(result["unit_op_cost_min_rmb"], result["unit_op_cost_max_rmb"])
        with self.assertRaises(ValueError):
            model.simulate_wind_curtailment_water(0, model.DEFAULT_SEED)


if __name__ == "__main__":
    unittest.main()

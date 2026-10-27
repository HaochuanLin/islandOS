import unittest

from nan_ao_scenario import DEFAULT_RUNS, DEFAULT_SEED
from nan_ao_three_scenarios import run_scenarios


class TestNanAoScenarios(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = run_scenarios()

    def test_exposes_three_required_scenarios(self):
        scenarios = {row["scenario_key"]: row for row in self.report["scenarios"]}
        self.assertEqual(set(scenarios), {"wind_only", "valley_price", "hybrid"})
        for row in scenarios.values():
            self.assertEqual(row["ro_purchase_capex_rmb"], 0.0)
            self.assertIn("annual_operating_cost_low_rmb", row)
            self.assertIn("annual_operating_cost_high_rmb", row)
            self.assertIn("unit_operating_cost_low_rmb_per_m3", row)
            self.assertIn("unit_operating_cost_high_rmb_per_m3", row)

    def test_valley_and_hybrid_water_arithmetic(self):
        scenarios = {row["scenario_key"]: row for row in self.report["scenarios"]}
        valley, hybrid = scenarios["valley_price"], scenarios["hybrid"]
        self.assertEqual(valley["annual_water_median_m3"], 33650.0)
        self.assertGreater(hybrid["annual_water_median_m3"], valley["annual_water_median_m3"])
        self.assertAlmostEqual(valley["valley_electricity_cost_rmb_per_year"], 33650 * 4.0 * 0.272, places=2)

    def test_wind_yield_and_hybrid_combination(self):
        scenarios = {row["scenario_key"]: row for row in self.report["scenarios"]}
        wind, hybrid = scenarios["wind_only"], scenarios["hybrid"]
        self.assertLessEqual(wind["annual_water_p05_m3"], wind["annual_water_median_m3"])
        self.assertLessEqual(wind["annual_water_median_m3"], wind["annual_water_p95_m3"])
        self.assertAlmostEqual(hybrid["annual_water_median_m3"], 33650 + wind["annual_water_median_m3"], places=3)
        self.assertEqual(self.report["ro_purchase_capex_rmb"], 0.0)
        self.assertEqual(self.report["runs"], DEFAULT_RUNS)
        self.assertEqual(self.report["seed"], DEFAULT_SEED)

    def test_operating_costs_and_emergency_supply_equivalent(self):
        hybrid = next(row for row in self.report["scenarios"] if row["scenario_key"] == "hybrid")
        self.assertGreater(hybrid["annual_operating_cost_high_rmb"], hybrid["annual_operating_cost_low_rmb"])
        self.assertGreater(self.report["hybrid_emergency_population_annual_supply_equivalent"], 0)
        self.assertTrue(self.report["limitations"])


if __name__ == "__main__":
    unittest.main()

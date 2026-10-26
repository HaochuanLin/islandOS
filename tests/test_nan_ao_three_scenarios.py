"""Regression tests for the separate Nan'ao three-scenario exploration script."""
import unittest

from nan_ao_three_scenarios import (
    DEFAULT_RUNS,
    DEFAULT_SEED,
    VALLEY_PRICE_RMB_PER_KWH,
    SEC_KWH_PER_M3,
    RO_AVAILABILITY,
    RO_POWER_KW,
    YEAR_HOURS,
    render_markdown_table,
    run_three_scenarios,
)


class TestNanAoThreeScenarios(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = run_three_scenarios()

    def test_baseline_median_matches_frozen_model_target(self):
        parity = self.report["scenario1_baseline_parity"]
        self.assertTrue(parity["passed"])
        self.assertAlmostEqual(parity["actual_median_m3_per_year"], 442.5, delta=5.0)
        self.assertEqual(self.report["seed"], 20261021)
        self.assertEqual(self.report["runs"], 1000)

    def test_all_three_scenarios_and_expected_valley_arithmetic(self):
        scenarios = {row["scenario_key"]: row for row in self.report["scenarios"]}
        self.assertEqual(set(scenarios), {"wind_only", "valley_only", "hybrid"})
        expected_hours = YEAR_HOURS / 24 * 8 * RO_AVAILABILITY
        expected_water = expected_hours * RO_POWER_KW / SEC_KWH_PER_M3
        self.assertAlmostEqual(scenarios["valley_only"]["annual_water_p50_m3"], expected_water)
        self.assertAlmostEqual(
            scenarios["valley_only"]["electricity_cost_median_rmb_per_m3"],
            VALLEY_PRICE_RMB_PER_KWH * SEC_KWH_PER_M3,
        )
        self.assertAlmostEqual(scenarios["valley_only"]["runtime_hours_p50"], expected_hours)

    def test_hybrid_uses_emergency_hysteresis_and_reports_water_service(self):
        diagnostics = self.report["hybrid_diagnostics"]
        self.assertEqual(diagnostics["assumed_emergency_threshold_m3"], 25.0)
        self.assertEqual(diagnostics["assumed_recovery_target_m3"], 75.0)
        self.assertLess(diagnostics["median_unmet_demand_m3_per_year"], 1000.0)
        self.assertGreater(diagnostics["median_water_served_m3_per_year"], 28000.0)

    def test_fair_economic_comparison_uses_matched_demand_control(self):
        comparison = self.report["fair_economic_comparison"]
        self.assertIn("same reservoir", comparison["method"])
        self.assertIn("disables wind", comparison["method"])
        self.assertGreater(comparison["median_water_served_valley_only_m3_per_year"], 0)
        self.assertGreater(comparison["median_water_served_hybrid_m3_per_year"], 0)
        self.assertGreaterEqual(comparison["median_grid_electricity_cost_valley_only_rmb_per_year"], 0)
        self.assertGreaterEqual(comparison["median_grid_electricity_cost_hybrid_rmb_per_year"], 0)
        # Never assert a fabricated win: report computed savings and service delta.
        self.assertAlmostEqual(
            comparison["median_grid_cost_savings_rmb_per_year"],
            comparison["median_grid_electricity_cost_valley_only_rmb_per_year"]
            - comparison["median_grid_electricity_cost_hybrid_rmb_per_year"],
        )
        self.assertAlmostEqual(
            comparison["median_total_screening_cost_savings_rmb_per_m3_served"],
            comparison["median_total_screening_cost_valley_only_rmb_per_m3_served"]
            - comparison["median_total_screening_cost_hybrid_rmb_per_m3_served"],
        )

    def test_markdown_table_contains_requested_columns_and_three_rows(self):
        table = render_markdown_table(self.report)
        self.assertIn("年产水量P5", table)
        self.assertIn("年产水量中位数", table)
        self.assertIn("年产水量P95", table)
        self.assertIn("年运行小时中位数", table)
        self.assertIn("硬件摊销区间", table)
        self.assertIn("中位数电费", table)
        self.assertIn("合计筛查成本区间", table)
        self.assertEqual(table.count("| 情景"), 4)  # header plus three scenario rows

    def test_fixed_run_count_and_seed_cannot_be_changed_silently(self):
        with self.assertRaises(ValueError):
            run_three_scenarios(runs=999)
        with self.assertRaises(ValueError):
            run_three_scenarios(seed=DEFAULT_SEED + 1)
        self.assertEqual(DEFAULT_RUNS, 1000)
        self.assertEqual(DEFAULT_SEED, 20261021)


if __name__ == "__main__":
    unittest.main()

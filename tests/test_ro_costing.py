import unittest

from ro_costing import ROCostRates, calculate_ro_operating_cost, compare_ro_operating_plans


class TestROCosting(unittest.TestCase):
    def setUp(self):
        self.rates = ROCostRates(
            currency="CNY",
            electricity_price_per_kwh=0.5,
            chemical_cost_per_m3=0.12,
            variable_om_cost_per_m3=0.08,
            maintenance_cost_per_runtime_hour=2.0,
            start_stop_cost_per_event=5.0,
            fixed_om_per_year=8760.0,
        )

    def test_cost_breakdown_uses_time_of_use_tariff_and_excludes_capex(self):
        report = calculate_ro_operating_cost(
            [10, 20], [2, 3], [0.3, 0.7], self.rates,
            runtime_hours=[1, 1], start_events=[1, 0],
            provenance="synthetic_test",
        )
        self.assertAlmostEqual(report.electricity_cost, 17.0)
        self.assertAlmostEqual(report.chemical_cost, 0.6)
        self.assertAlmostEqual(report.variable_om_cost, 0.4)
        self.assertAlmostEqual(report.maintenance_cost, 4.0)
        self.assertAlmostEqual(report.start_stop_cost, 5.0)
        self.assertAlmostEqual(report.allocated_fixed_om_cost, 2.0)
        self.assertAlmostEqual(report.total_operating_cost, 29.0)
        self.assertAlmostEqual(report.cost_per_m3, 5.8)
        self.assertFalse(report.includes_sunk_capex)

    def test_fixed_om_respects_subhourly_step_duration(self):
        report = calculate_ro_operating_cost([1, 1], [1, 1], 0.5, self.rates, dt_hours=0.5)
        self.assertAlmostEqual(report.allocated_fixed_om_cost, 1.0)

    def test_fixed_tariff_and_zero_water(self):
        report = calculate_ro_operating_cost([4], [0], 0.25, self.rates)
        self.assertEqual(report.electricity_cost, 1.0)
        self.assertIsNone(report.cost_per_m3)

    def test_plan_comparison_reports_savings_and_water_delta(self):
        baseline = calculate_ro_operating_cost([10], [2], 0.5, self.rates, provenance="measured")
        candidate = calculate_ro_operating_cost([8], [2], 0.5, self.rates, provenance="modelled")
        comparison = compare_ro_operating_plans(baseline, candidate)
        self.assertAlmostEqual(comparison["absolute_savings"], 1.0)
        self.assertAlmostEqual(comparison["savings_percent"], 15.625)
        self.assertEqual(comparison["water_output_change_m3"], 0.0)

        self.assertTrue(comparison["service_volume_equivalent"])
        self.assertAlmostEqual(comparison["qualified_savings"], 1.0)

    def test_does_not_qualify_savings_when_candidate_produces_less_water(self):
        baseline = calculate_ro_operating_cost([10], [2], 0.5, self.rates)
        candidate = calculate_ro_operating_cost([8], [1.8], 0.5, self.rates)
        comparison = compare_ro_operating_plans(baseline, candidate)
        self.assertGreater(comparison["absolute_savings"], 0)
        self.assertFalse(comparison["service_volume_equivalent"])
        self.assertIsNone(comparison["qualified_savings"])
        self.assertIsNone(comparison["savings_percent"])

    def test_does_not_qualify_savings_for_different_time_coverage(self):
        baseline = calculate_ro_operating_cost([10, 10], [2, 2], 0.5, self.rates, dt_hours=1)
        candidate = calculate_ro_operating_cost([8], [4], 0.5, self.rates, dt_hours=1)
        comparison = compare_ro_operating_plans(baseline, candidate)
        self.assertFalse(comparison["same_time_coverage"])
        self.assertFalse(comparison["service_volume_equivalent"])
        self.assertIsNone(comparison["qualified_savings"])

    def test_rejects_invalid_water_output_tolerance(self):
        baseline = calculate_ro_operating_cost([1], [1], 0.5, self.rates)
        with self.assertRaisesRegex(ValueError, "water_output_tolerance_fraction"):
            compare_ro_operating_plans(baseline, baseline, water_output_tolerance_fraction=-0.1)

    def test_rejects_misaligned_or_invalid_inputs(self):
        with self.assertRaisesRegex(ValueError, "same number"):
            calculate_ro_operating_cost([1, 2], [1], 0.5, self.rates)
        with self.assertRaisesRegex(ValueError, "finite non-negative"):
            calculate_ro_operating_cost([1, -2], [1, 1], 0.5, self.rates)
        with self.assertRaisesRegex(ValueError, "dt_hours"):
            calculate_ro_operating_cost([1], [1], 0.5, self.rates, dt_hours=0)
        with self.assertRaisesRegex(ValueError, "start_events"):
            calculate_ro_operating_cost([1], [1], 0.5, self.rates, start_events=[1.5])

    def test_rejects_mismatched_tariff_and_runtime(self):
        with self.assertRaisesRegex(ValueError, "tariff series"):
            calculate_ro_operating_cost([1, 2], [1, 1], [0.2], self.rates)
        with self.assertRaisesRegex(ValueError, "runtime_hours"):
            calculate_ro_operating_cost([1, 2], [1, 1], 0.2, self.rates, runtime_hours=[1])


    def test_does_not_qualify_savings_when_cost_assumptions_differ(self):
        baseline = calculate_ro_operating_cost(
            [10], [2], [0.5], self.rates, provenance="customer_supplied"
        )
        changed_rates = ROCostRates(
            currency="CNY",
            electricity_price_per_kwh=0.5,
            chemical_cost_per_m3=0.20,
            variable_om_cost_per_m3=0.08,
            maintenance_cost_per_runtime_hour=2.0,
            start_stop_cost_per_event=5.0,
            fixed_om_per_year=8760.0,
        )
        candidate = calculate_ro_operating_cost(
            [8], [2], [0.5], changed_rates, provenance="modelled"
        )
        comparison = compare_ro_operating_plans(baseline, candidate)
        self.assertTrue(comparison["service_volume_equivalent"])
        self.assertFalse(comparison["same_cost_basis"])
        self.assertFalse(comparison["qualified_comparison"])
        self.assertIsNone(comparison["qualified_savings"])
        self.assertIsNone(comparison["savings_percent"])

    def test_does_not_qualify_savings_when_tariff_series_differs(self):
        baseline = calculate_ro_operating_cost(
            [10], [2], [0.5], self.rates
        )
        candidate = calculate_ro_operating_cost(
            [8], [2], [0.6], self.rates
        )
        comparison = compare_ro_operating_plans(baseline, candidate)
        self.assertFalse(comparison["same_cost_basis"])
        self.assertIsNone(comparison["qualified_savings"])


    def test_does_not_qualify_savings_when_sampling_grid_differs(self):
        baseline = calculate_ro_operating_cost(
            [10, 10], [2, 2], [0.5, 0.5], self.rates, dt_hours=1.0
        )
        candidate = calculate_ro_operating_cost(
            [8], [4], [0.5], self.rates, dt_hours=2.0
        )
        comparison = compare_ro_operating_plans(baseline, candidate)
        self.assertTrue(comparison["same_time_coverage"])
        self.assertFalse(comparison["same_sampling_grid"])
        self.assertFalse(comparison["qualified_comparison"])
        self.assertIsNone(comparison["qualified_savings"])

    def test_does_not_qualify_savings_when_step_count_differs(self):
        baseline = calculate_ro_operating_cost(
            [10, 10], [2, 2], [0.5, 0.5], self.rates, dt_hours=1.0
        )
        candidate = calculate_ro_operating_cost(
            [8, 8, 4], [1, 1, 2], [0.5, 0.5, 0.5], self.rates,
            dt_hours=1.0,
        )
        comparison = compare_ro_operating_plans(baseline, candidate)
        self.assertTrue(comparison["same_time_coverage"])
        self.assertFalse(comparison["same_sampling_grid"])
        self.assertIsNone(comparison["qualified_savings"])


if __name__ == "__main__":
    unittest.main()

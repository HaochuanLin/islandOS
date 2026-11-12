"""Tests for the price-aware flexible-load linear optimizer."""
import unittest

import numpy as np

from optimization.price_aware_load_optimizer import optimize_flexible_load
from examples.price_aware_flexible_load_demo import build_demo_result


class PriceAwareFlexibleLoadOptimizerTests(unittest.TestCase):
    def test_moves_load_to_cheapest_available_periods(self):
        result = optimize_flexible_load(
            price_per_kwh=[0.30, 0.10, 0.20],
            energy_requirement_kwh=4,
            max_power_kw=2,
        )
        self.assertEqual(result.power_kw, (0.0, 2.0, 2.0))
        self.assertAlmostEqual(result.total_energy_kwh, 4.0)
        self.assertAlmostEqual(result.total_cost, 0.60)
        self.assertEqual(result.solver_status, "optimal")

    def test_respects_available_power_budget(self):
        result = optimize_flexible_load(
            price_per_kwh=[0.05, 0.20, 0.30],
            energy_requirement_kwh=3,
            max_power_kw=3,
            available_power_kw=[1, 3, 3],
        )
        self.assertEqual(result.power_kw, (1.0, 2.0, 0.0))

    def test_respects_operating_window(self):
        result = optimize_flexible_load(
            price_per_kwh=[0.01, 0.20, 0.30],
            energy_requirement_kwh=2,
            max_power_kw=2,
            availability=[False, True, True],
        )
        self.assertEqual(result.power_kw, (0.0, 2.0, 0.0))

    def test_handles_non_hourly_interval(self):
        result = optimize_flexible_load(
            price_per_kwh=[0.10, 0.20],
            energy_requirement_kwh=1,
            max_power_kw=2,
            dt_hours=0.5,
        )
        self.assertAlmostEqual(result.total_energy_kwh, 1.0)
        self.assertAlmostEqual(sum(result.power_kw), 2.0)

    def test_raises_when_energy_requirement_is_infeasible(self):
        with self.assertRaisesRegex(ValueError, "infeasible"):
            optimize_flexible_load(
                price_per_kwh=[0.1, 0.2],
                energy_requirement_kwh=5,
                max_power_kw=2,
                dt_hours=1,
            )

    def test_zero_energy_requirement_returns_zero_schedule(self):
        result = optimize_flexible_load([0.1, 0.2], 0, 5)
        self.assertEqual(result.power_kw, (0.0, 0.0))
        self.assertEqual(result.total_cost, 0.0)

    def test_rejects_bad_inputs(self):
        invalid_cases = [
            ({"price_per_kwh": []}, "price_per_kwh"),
            ({"price_per_kwh": [0.1, float("nan")]}, "finite"),
            ({"price_per_kwh": [0.1, True]}, "booleans"),
            ({"price_per_kwh": ["0.1"]}, "strings"),
            ({"price_per_kwh": [0.1], "available_power_kw": ["1"]}, "strings"),
            ({"price_per_kwh": [0.1], "available_power_kw": [True]}, "booleans"),
            ({"price_per_kwh": [0.1], "baseline_power_kw": [True]}, "booleans"),
            ({"price_per_kwh": [[0.1]]}, "1D series"),
            ({"price_per_kwh": [0.1], "baseline_power_kw": ["0.5"]}, "strings"),
            ({"price_per_kwh": [0.1], "energy_requirement_kwh": -1}, "non-negative"),
            ({"price_per_kwh": [0.1], "max_power_kw": 0}, "max_power_kw"),
            ({"price_per_kwh": [0.1], "max_power_kw": "2"}, "max_power_kw"),
            ({"price_per_kwh": [0.1], "dt_hours": 0}, "dt_hours"),
            ({"price_per_kwh": [0.1], "energy_requirement_kwh": True}, "energy_requirement_kwh"),
            ({"price_per_kwh": [0.1], "available_power_kw": [-1]}, "non-negative"),
            ({"price_per_kwh": [0.1], "available_power_kw": [1, 2]}, "horizon length"),
            ({"price_per_kwh": [0.1], "availability": [1]}, "boolean"),
        ]
        for overrides, message in invalid_cases:
            kwargs = {
                "price_per_kwh": [0.1],
                "energy_requirement_kwh": 0.5,
                "max_power_kw": 1,
            }
            kwargs.update(overrides)
            with self.subTest(overrides=overrides):
                with self.assertRaisesRegex(ValueError, message):
                    optimize_flexible_load(**kwargs)

    def test_negative_tariff_is_supported_without_overdelivering_energy(self):
        result = optimize_flexible_load(
            price_per_kwh=[0.10, -0.05, 0.20],
            energy_requirement_kwh=1.5,
            max_power_kw=2,
        )
        self.assertAlmostEqual(result.total_energy_kwh, 1.5)
        self.assertEqual(result.power_kw, (0.0, 1.5, 0.0))
        self.assertAlmostEqual(result.total_cost, -0.075)

    def test_like_for_like_baseline_cost_comparison_is_transparent(self):
        result = optimize_flexible_load(
            price_per_kwh=[0.31, 0.27, 0.13, 0.09, 0.11, 0.24],
            energy_requirement_kwh=10.0,
            max_power_kw=3.0,
            available_power_kw=[3.0, 3.0, 2.0, 3.0, 3.0, 3.0],
            baseline_power_kw=[2.0, 2.0, 2.0, 2.0, 1.0, 1.0],
        )
        self.assertAlmostEqual(result.baseline_cost, 1.95)
        self.assertAlmostEqual(result.total_cost, 1.34)
        self.assertAlmostEqual(result.cost_difference_vs_baseline, 0.61)
        self.assertAlmostEqual(
            result.cost_difference_percent_vs_baseline,
            100.0 * 0.61 / 1.95,
        )

    def test_rejects_unfair_or_invalid_baseline_comparisons(self):
        common = {
            "price_per_kwh": [0.2, 0.1],
            "energy_requirement_kwh": 2.0,
            "max_power_kw": 2.0,
        }
        with self.assertRaisesRegex(ValueError, "same total energy"):
            optimize_flexible_load(**common, baseline_power_kw=[2.0, 1.0])
        with self.assertRaisesRegex(ValueError, "must not exceed"):
            optimize_flexible_load(**common, baseline_power_kw=[3.0, 0.0])
        with self.assertRaisesRegex(ValueError, "unavailable operating"):
            optimize_flexible_load(
                **common,
                availability=[True, False],
                baseline_power_kw=[1.0, 1.0],
            )

    def test_infeasible_operating_window_is_reported(self):
        with self.assertRaisesRegex(ValueError, "infeasible"):
            optimize_flexible_load(
                price_per_kwh=[0.01, 0.02],
                energy_requirement_kwh=2,
                max_power_kw=2,
                availability=[False, False],
            )

    def test_synthetic_example_reports_provenance_and_equal_energy_comparison(self):
        result = build_demo_result()
        self.assertIn("Synthetic", result["data_provenance"])
        self.assertAlmostEqual(
            result["optimized_schedule"]["total_energy_kwh"], 10.0
        )
        self.assertAlmostEqual(
            sum(result["baseline_power_kw"]), 10.0
        )
        self.assertGreater(
            result["baseline_vs_optimized_cost_difference"], 0.0
        )
        self.assertIn("not a verified customer saving", result["interpretation"])

    def test_cost_and_energy_are_reproducible(self):
        kwargs = {
            "price_per_kwh": [0.15, 0.08, 0.22, 0.11],
            "energy_requirement_kwh": 5.5,
            "max_power_kw": 2,
            "available_power_kw": [2, 2, 1, 2],
        }
        first = optimize_flexible_load(**kwargs)
        second = optimize_flexible_load(**kwargs)
        self.assertEqual(first, second)
        self.assertAlmostEqual(first.total_energy_kwh, 5.5)
        self.assertTrue(np.all(np.asarray(first.power_kw) <= [2, 2, 1, 2]))


if __name__ == "__main__":
    unittest.main()

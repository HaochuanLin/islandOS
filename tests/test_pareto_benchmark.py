"""Regression tests for the exact Pareto reference benchmark."""
import unittest

from experiments.compare_dispatch_policies import build_scenarios
from experiments.benchmark_nsga2_vs_exhaustive import benchmark, exhaustive_pareto
from islandos_config import load_config


class TestParetoBenchmark(unittest.TestCase):
    def small_config(self):
        config = load_config()
        config["search_space"].update({
            "priority": ["ro_first", "ice_first"],
            "ro_min_run_hours": [1, 2],
            "ro_start_ratio": [0.6, 0.8, 1.0],
            "ro_rated_power_kw": [250.0, 350.0],
            "ice_rated_power_kw": [50.0],
        })
        return config

    def test_exhaustive_search_collapses_inactive_ratio_and_finds_front(self):
        config = self.small_config()
        result = exhaustive_pareto(build_scenarios()[0], config)
        # 2 * 2 * 1 * 2 * 1; ratio is inactive with backup disabled.
        self.assertEqual(result["decision_space_size"], 8)
        self.assertEqual(result["unique_candidates_evaluated"], 8)
        self.assertTrue(result["pareto_front"])
        self.assertTrue(all(row["feasible"] for row in result["pareto_front"]))

    def test_benchmark_reports_bounded_coverage_metrics_reproducibly(self):
        config = self.small_config()
        scenario = build_scenarios()[0]
        result = benchmark(
            scenario, config, population_size=8, generations=2, seed=42,
        )
        comparison = result["comparison"]
        self.assertGreaterEqual(comparison["exact_front_recall"], 0.0)
        self.assertLessEqual(comparison["exact_front_recall"], 1.0)
        self.assertGreaterEqual(comparison["nsga2_front_precision"], 0.0)
        self.assertLessEqual(comparison["nsga2_front_precision"], 1.0)
        self.assertEqual(result["exact"]["unique_candidates_evaluated"], 8)
        self.assertEqual(result["decision_space_size"], 8)

    def test_same_seed_reproduces_pareto_results(self):
        scenario = build_scenarios()[0]
        config = self.small_config()
        first = benchmark(
            scenario, config, population_size=8, generations=2, seed=42,
        )
        second = benchmark(
            scenario, config, population_size=8, generations=2, seed=42,
        )

        # Runtime is machine-dependent; compare scientific outputs, not timing.
        for section in ("exact", "nsga2"):
            self.assertEqual(
                first[section]["pareto_genomes"],
                second[section]["pareto_genomes"],
            )
            self.assertEqual(
                first[section]["pareto_front_count"],
                second[section]["pareto_front_count"],
            )
            self.assertEqual(
                first[section]["feasible_candidate_count_evaluated"],
                second[section]["feasible_candidate_count_evaluated"],
            )
        self.assertEqual(
            first["comparison"]["exact_front_recall"],
            second["comparison"]["exact_front_recall"],
        )
        self.assertEqual(
            first["comparison"]["nsga2_front_precision"],
            second["comparison"]["nsga2_front_precision"],
        )

    def test_exhaustive_search_refuses_unbounded_candidate_space(self):
        with self.assertRaisesRegex(ValueError, "safety limit"):
            exhaustive_pareto(build_scenarios()[0], self.small_config(), max_candidates=7)


if __name__ == "__main__":
    unittest.main()

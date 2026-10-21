"""Tests for the experimental NSGA-II dispatch policy optimizer."""
import unittest

from experiments.compare_dispatch_policies import build_scenarios
from optimization.nsga2_dispatch_optimizer import (
    dominates, non_dominated_sort, optimize_scenario,
)


class TestNSGA2DispatchOptimizer(unittest.TestCase):
    def test_dominance_requires_no_worse_all_objectives_and_better_one(self):
        a = {"feasible": True, "objective_vector": [1.0, 2.0, 3.0]}
        b = {"feasible": True, "objective_vector": [2.0, 2.0, 4.0]}
        c = {"feasible": True, "objective_vector": [1.0, 1.0, 3.0]}
        self.assertTrue(dominates(a, b))
        self.assertFalse(dominates(b, a))
        self.assertFalse(dominates(a, c))

    def test_feasible_candidate_dominates_infeasible_candidate(self):
        a = {"feasible": True, "objective_vector": [100.0, 100.0, 100.0]}
        b = {"feasible": False, "objective_vector": [0.0, 0.0, 0.0]}
        self.assertTrue(dominates(a, b))
        self.assertFalse(dominates(b, a))

    def test_optimizer_is_reproducible_and_audits_pareto_candidates(self):
        scenario = build_scenarios()[0]
        a = optimize_scenario(scenario, population_size=8, generations=2, seed=42)
        b = optimize_scenario(scenario, population_size=8, generations=2, seed=42)
        self.assertEqual(a, b)
        self.assertEqual(a["algorithm"], "NSGA-II (non-dominated sorting + crowding distance + tournament selection)")
        self.assertGreaterEqual(a["unique_candidates_evaluated"], 1)
        self.assertTrue(a["pareto_front"])
        for row in a["pareto_front"]:
            self.assertTrue(row["feasible"])
            self.assertTrue(row["feasibility_audit"]["eligible_for_pareto"])
            self.assertEqual(set(row["objectives"]), {
                "water_unmet_m3", "cooling_unmet_kwh_th", "remaining_surplus_kwh"
            })

    def test_invalid_population_size_fails_clearly(self):
        with self.assertRaisesRegex(ValueError, "population_size"):
            optimize_scenario(build_scenarios()[0], population_size=2, generations=1)


if __name__ == "__main__":
    unittest.main()

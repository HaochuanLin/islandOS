"""Tests for the connected grid-search/Pareto recommendation pipeline."""
import unittest

from experiments.compare_dispatch_policies import build_scenarios
from optimization.grid_search_optimizer import (
    candidates, dominates, optimize_scenario, pareto_archive, recommend,
)


class TestGridSearchOptimizer(unittest.TestCase):
    def test_search_space_is_explicit_and_unique(self):
        rows = candidates()
        self.assertEqual(len(rows), 8)
        self.assertEqual(len({row.candidate_id for row in rows}), 8)
        self.assertEqual({row.priority for row in rows}, {"ro_first", "ice_first"})
        self.assertEqual({row.ro_start_ratio for row in rows}, {0.50, 0.65, 0.80, 0.95})

    def test_dominance_requires_no_worse_and_one_strict_improvement(self):
        a = {"objectives": {
            "water_unmet_m3": 1, "cooling_unmet_kwh_th": 2, "remaining_surplus_kwh": 3
        }}
        b = {"objectives": {
            "water_unmet_m3": 2, "cooling_unmet_kwh_th": 2, "remaining_surplus_kwh": 4
        }}
        self.assertTrue(dominates(a, b))
        self.assertFalse(dominates(b, a))
        self.assertFalse(dominates(a, a))

    def test_archive_contains_only_feasible_non_dominated_rows(self):
        evaluated = [
            {"candidate_id": "a", "feasible": True, "objectives": {
                "water_unmet_m3": 1, "cooling_unmet_kwh_th": 1, "remaining_surplus_kwh": 1}},
            {"candidate_id": "b", "feasible": True, "objectives": {
                "water_unmet_m3": 2, "cooling_unmet_kwh_th": 2, "remaining_surplus_kwh": 2}},
            {"candidate_id": "c", "feasible": False, "objectives": {
                "water_unmet_m3": 0, "cooling_unmet_kwh_th": 0, "remaining_surplus_kwh": 0}},
        ]
        archive = pareto_archive(evaluated)
        self.assertEqual([row["candidate_id"] for row in archive], ["a"])

    def test_recommendation_must_come_from_archive(self):
        archive = [
            {"candidate_id": "candidate-a", "feasible": True, "objectives": {
                "water_unmet_m3": 1, "cooling_unmet_kwh_th": 1, "remaining_surplus_kwh": 1}},
            {"candidate_id": "candidate-b", "feasible": True, "objectives": {
                "water_unmet_m3": 0, "cooling_unmet_kwh_th": 2, "remaining_surplus_kwh": 2}},
        ]
        chosen = recommend(archive)
        self.assertIn(chosen["candidate_id"], {row["candidate_id"] for row in archive})
        self.assertIn("weights", chosen["selection"])

    def test_scenario_optimization_is_repeatable_and_connected(self):
        result_a = optimize_scenario(build_scenarios()[0])
        result_b = optimize_scenario(build_scenarios()[0])
        self.assertEqual(result_a, result_b)
        self.assertEqual(result_a["candidate_count"], 8)
        self.assertGreaterEqual(result_a["pareto_candidate_count"], 1)
        archive_ids = {row["candidate_id"] for row in result_a["pareto_archive"]}
        self.assertIn(result_a["recommendation"]["candidate_id"], archive_ids)

    def test_no_feasible_recommendation_fails_loudly(self):
        with self.assertRaisesRegex(ValueError, "No feasible candidate"):
            recommend([])


if __name__ == "__main__":
    unittest.main()

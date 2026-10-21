"""Tests for the experimental NSGA-II dispatch policy optimizer."""
import unittest

from experiments.compare_dispatch_policies import Scenario, build_scenarios
from islandos_config import load_config
from optimization.nsga2_dispatch_optimizer import (
    dominates, evaluate_genome, non_dominated_sort, optimize_scenario,
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
        genomes = [tuple(row["genome"]) for row in a["pareto_front"]]
        self.assertEqual(len(genomes), len(set(genomes)))
        for row in a["pareto_front"]:
            self.assertTrue(row["feasible"])
            self.assertTrue(row["feasibility_audit"]["eligible_for_pareto"])
            self.assertEqual(set(row["objectives"]), {
                "water_unmet_m3", "cooling_unmet_kwh_th", "remaining_surplus_kwh"
            })

    def test_complete_cost_inputs_add_annualized_cost_objective(self):
        config = load_config()
        economics = config["economics"]
        economics.update({
            "electricity_price_per_kwh": 0.12,
            "ro_capex": 100000.0,
            "ro_fixed_om_per_year": 2000.0,
            "ro_variable_om_per_m3": 0.3,
            "chiller_capex": 40000.0,
            "chiller_fixed_om_per_year": 1000.0,
            "analysis_years": 20,
            "discount_rate": 0.05,
        })
        scenario = Scenario(
            name="synthetic-full-year-test",
            available_surplus_kw=tuple([500.0] * 8760),
            water_demand_m3_per_hour=tuple([1.0] * 8760),
            cooling_demand_kw_th=tuple([1.0] * 8760),
        )
        genome = ("ro_first", 1, 0.6, 300.0, 50.0)
        result = evaluate_genome(scenario, genome, config)
        self.assertIn("annualized_lifecycle_cost_per_year", result["objectives"])
        self.assertTrue(result["cost_breakdown"]["annualized_lifecycle_cost_per_year"] > 0)
        self.assertEqual(
            result["objectives"]["annualized_lifecycle_cost_per_year"],
            result["cost_breakdown"]["annualized_lifecycle_cost_per_year"],
        )
        self.assertIn("water_unmet_m3", result["objectives"])

    def test_nsga2_runs_with_four_objectives_when_costs_are_complete(self):
        config = load_config()
        config["economics"].update({
            "electricity_price_per_kwh": 0.12,
            "ro_capex": 100000.0,
            "ro_fixed_om_per_year": 2000.0,
            "ro_variable_om_per_m3": 0.3,
            "chiller_capex": 40000.0,
            "chiller_fixed_om_per_year": 1000.0,
            "analysis_years": 20,
            "discount_rate": 0.05,
        })
        scenario = Scenario(
            name="synthetic-full-year-optimizer-test",
            available_surplus_kw=tuple([500.0] * 8760),
            water_demand_m3_per_hour=tuple([1.0] * 8760),
            cooling_demand_kw_th=tuple([1.0] * 8760),
        )
        result = optimize_scenario(
            scenario, population_size=4, generations=1, seed=9, config=config
        )
        self.assertTrue(result["cost_objective_enabled"])
        self.assertIn("annualized_lifecycle_cost_per_year", result["objective_directions"])
        self.assertTrue(result["pareto_front"])
        for candidate in result["pareto_front"]:
            self.assertIn("annualized_lifecycle_cost_per_year", candidate["objectives"])
            self.assertIsNotNone(candidate["cost_breakdown"])

    def test_complete_cost_inputs_reject_short_horizon(self):
        config = load_config()
        config["economics"].update({
            "electricity_price_per_kwh": 0.12,
            "ro_capex": 100000.0,
            "ro_fixed_om_per_year": 2000.0,
            "ro_variable_om_per_m3": 0.3,
            "chiller_capex": 40000.0,
            "chiller_fixed_om_per_year": 1000.0,
            "analysis_years": 20,
            "discount_rate": 0.05,
        })
        with self.assertRaisesRegex(ValueError, "complete 8760-hour or 8784-hour annual scenario"):
            optimize_scenario(
                build_scenarios()[0], population_size=4, generations=1, config=config
            )

    def test_invalid_population_size_fails_clearly(self):
        with self.assertRaisesRegex(ValueError, "population_size"):
            optimize_scenario(build_scenarios()[0], population_size=2, generations=1)


if __name__ == "__main__":
    unittest.main()

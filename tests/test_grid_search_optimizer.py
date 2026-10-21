"""Tests for the connected grid-search/Pareto recommendation pipeline."""
import unittest
from types import SimpleNamespace

import numpy as np

from experiments.compare_dispatch_policies import build_scenarios
from dispatch_engine import dispatch_flexible_loads
from flexible_loads import IceStorageConfig, IceStorageLoad, ROConfig, ROWaterLoad
from optimization.grid_search_optimizer import (
    audit_dispatch_result, candidates, dominates, optimize_scenario, pareto_archive, recommend,
)


class TestGridSearchOptimizer(unittest.TestCase):
    def _valid_dispatch_audit_case(self):
        ro = ROWaterLoad(ROConfig(
            rated_power_kw=400.0, specific_energy_kwh_m3=3.5,
            reservoir_capacity_m3=500.0, initial_water_m3=150.0,
            dead_storage_m3=20.0, min_run_hours=1, allow_backup_power=False,
        ))
        ice = IceStorageLoad(IceStorageConfig(
            rated_power_kw=100.0, coefficient_of_performance=2.5,
            storage_capacity_kwh_th=400.0, initial_storage_kwh_th=100.0,
        ))
        water = np.array([10.0, 10.0])
        cooling = np.array([50.0, 50.0])
        requests = [(ro, water), (ice, cooling)]
        result = dispatch_flexible_loads([500.0, 500.0], requests)
        demands = {"ro_desalination": water, "ice_cold_storage": cooling}
        return result, requests, demands

    def test_independent_dispatch_audit_accepts_balanced_physical_results(self):
        result, requests, demands = self._valid_dispatch_audit_case()
        audit = audit_dispatch_result(result, requests, demands)
        self.assertTrue(audit["hard_dispatch_checks_passed"])
        self.assertTrue(audit["component_constraints_passed"])
        self.assertTrue(audit["eligible_for_pareto"])
        self.assertEqual(audit["audit_errors"], [])

    def test_independent_dispatch_audit_rejects_power_balance_violation(self):
        result, requests, demands = self._valid_dispatch_audit_case()
        result.remaining_power_kw[0] += 30.0
        audit = audit_dispatch_result(result, requests, demands)
        self.assertFalse(audit["hard_dispatch_checks_passed"])
        self.assertFalse(audit["eligible_for_pareto"])
        self.assertIn("shared_power_balance_failed", audit["audit_errors"])

    def test_independent_dispatch_audit_rejects_component_constraint_violation(self):
        result, requests, demands = self._valid_dispatch_audit_case()
        result.loads["ro_desalination"].constraint_violation[0] = 1
        audit = audit_dispatch_result(result, requests, demands)
        self.assertTrue(audit["hard_dispatch_checks_passed"])
        self.assertFalse(audit["component_constraints_passed"])
        self.assertFalse(audit["eligible_for_pareto"])
        self.assertIn("reported_component_constraint_violation_ro_desalination", audit["audit_errors"])

    def test_independent_dispatch_audit_rejects_mismatched_power_series(self):
        result, requests, demands = self._valid_dispatch_audit_case()
        result.remaining_power_kw = np.array([1.0])
        audit = audit_dispatch_result(result, requests, demands)
        self.assertFalse(audit["hard_dispatch_checks_passed"])
        self.assertIn("power_series_length_mismatch", audit["audit_errors"])

    def test_independent_dispatch_audit_rejects_inventory_capacity_violation(self):
        result, requests, demands = self._valid_dispatch_audit_case()
        result.loads["ice_cold_storage"].inventory[-1] = 500.0
        audit = audit_dispatch_result(result, requests, demands)
        self.assertFalse(audit["component_constraints_passed"])
        self.assertFalse(audit["eligible_for_pareto"])
        self.assertIn("thermal_inventory_capacity_failed_ice_cold_storage", audit["audit_errors"])

    def test_search_space_is_explicit_and_unique(self):
        rows = candidates()
        self.assertEqual(len(rows), 8)
        self.assertEqual(len({row.candidate_id for row in rows}), 8)
        self.assertEqual({row.priority for row in rows}, {"ro_first", "ice_first"})
        self.assertEqual({row.ro_min_run_hours for row in rows}, {1, 2, 3, 4})

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
            {"candidate_id": "a", "feasible": True, "feasibility_audit": {"eligible_for_pareto": True}, "objectives": {
                "water_unmet_m3": 1, "cooling_unmet_kwh_th": 1, "remaining_surplus_kwh": 1}},
            {"candidate_id": "b", "feasible": True, "feasibility_audit": {"eligible_for_pareto": True}, "objectives": {
                "water_unmet_m3": 2, "cooling_unmet_kwh_th": 2, "remaining_surplus_kwh": 2}},
            {"candidate_id": "c", "feasible": False, "objectives": {
                "water_unmet_m3": 0, "cooling_unmet_kwh_th": 0, "remaining_surplus_kwh": 0}},
        ]
        archive = pareto_archive(evaluated)
        self.assertEqual([row["candidate_id"] for row in archive], ["a"])

    def test_infeasible_candidate_cannot_be_recommended_even_if_passed_directly(self):
        feasible = {"candidate_id": "valid", "feasible": True, "feasibility_audit": {"eligible_for_pareto": True}, "objectives": {
            "water_unmet_m3": 1, "cooling_unmet_kwh_th": 1, "remaining_surplus_kwh": 1}}
        invalid_but_attractive = {"candidate_id": "invalid", "feasible": False, "objectives": {
            "water_unmet_m3": 0, "cooling_unmet_kwh_th": 0, "remaining_surplus_kwh": 0}}
        chosen = recommend([invalid_but_attractive, feasible])
        self.assertEqual(chosen["candidate_id"], "valid")

    def test_recommendation_rejects_candidate_missing_explicit_audit(self):
        unaudited = {"candidate_id": "unaudited", "feasible": True, "objectives": {
            "water_unmet_m3": 0, "cooling_unmet_kwh_th": 0, "remaining_surplus_kwh": 0}}
        with self.assertRaisesRegex(ValueError, "No feasible candidate"):
            recommend([unaudited])

    def test_recommendation_rejects_archive_with_only_infeasible_candidates(self):
        invalid = {"candidate_id": "invalid", "feasible": False, "objectives": {
            "water_unmet_m3": 0, "cooling_unmet_kwh_th": 0, "remaining_surplus_kwh": 0}}
        with self.assertRaisesRegex(ValueError, "No feasible candidate"):
            recommend([invalid])

    def test_audit_flag_overrides_feasible_boolean(self):
        invalid = {"candidate_id": "invalid", "feasible": True,
                   "feasibility_audit": {"eligible_for_pareto": False}, "objectives": {
                       "water_unmet_m3": 0, "cooling_unmet_kwh_th": 0, "remaining_surplus_kwh": 0}}
        self.assertEqual(pareto_archive([invalid]), [])
        with self.assertRaisesRegex(ValueError, "No feasible candidate"):
            recommend([invalid])

    def test_recommendation_must_come_from_archive(self):
        archive = [
            {"candidate_id": "candidate-a", "feasible": True, "feasibility_audit": {"eligible_for_pareto": True}, "objectives": {
                "water_unmet_m3": 1, "cooling_unmet_kwh_th": 1, "remaining_surplus_kwh": 1}},
            {"candidate_id": "candidate-b", "feasible": True, "feasibility_audit": {"eligible_for_pareto": True}, "objectives": {
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

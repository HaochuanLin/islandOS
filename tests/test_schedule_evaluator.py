"""Tests for common-physics flexible-load schedule evaluation."""
import unittest

from islandos_core.microgrid_model import MicrogridConfig, MicrogridInputs
from islandos_core.schedule_evaluator import (
    evaluate_ro_schedule, rank_ro_schedules,
    generate_renewable_surplus_candidates, screen_renewable_surplus_candidates,
    evaluate_schedule_robustness, search_ro_schedule,
)


class ScheduleEvaluatorTests(unittest.TestCase):
    def setUp(self):
        self.config = MicrogridConfig(
            battery_capacity_kwh=0, battery_initial_soc_kwh=0,
            battery_min_soc_kwh=0, battery_max_charge_kw=0,
            battery_max_discharge_kw=0, grid_import_limit_kw=0,
            diesel_capacity_kw=0, ro_rated_power_kw=20,
            ro_specific_energy_kwh_per_m3=4, water_tank_capacity_m3=20,
            water_initial_inventory_m3=0,
        )
        self.inputs = MicrogridInputs(
            pv_power_kw=[10, 30, 10], wind_power_kw=[0, 0, 0],
            essential_load_kw=[10, 10, 10], ro_requested_power_kw=[0, 0, 0],
            water_demand_m3=[0, 0, 0], grid_available=[False, False, False],
        )

    def test_all_candidates_use_same_physical_constraints(self):
        ranked = rank_ro_schedules(
            {"no_ro": [0, 0, 0], "surplus_only": [0, 20, 0]},
            self.inputs, self.config,
        )
        self.assertEqual(ranked[0].schedule_id, "surplus_only")
        self.assertTrue(ranked[0].feasible)
        self.assertEqual(ranked[0].essential_unserved_kwh, 0)
        self.assertEqual(ranked[1].essential_unserved_kwh, 0)
        self.assertGreater(ranked[0].water_produced_m3, 0)

    def test_infeasible_essential_service_is_not_hidden(self):
        scenario = MicrogridInputs(
            pv_power_kw=[0], wind_power_kw=[0], essential_load_kw=[15],
            ro_requested_power_kw=[0], water_demand_m3=[0],
            grid_available=[False],
        )
        result = evaluate_ro_schedule("no_supply", [0], scenario, self.config)
        self.assertFalse(result.feasible)
        self.assertEqual(result.essential_unserved_kwh, 15)

    def test_rejects_schedule_horizon_mismatch(self):
        with self.assertRaisesRegex(ValueError, "horizon"):
            evaluate_ro_schedule("bad", [1], self.inputs, self.config)

    def test_rejects_empty_candidate_set(self):
        with self.assertRaisesRegex(ValueError, "at least one"):
            rank_ro_schedules({}, self.inputs, self.config)


    def test_candidate_generator_is_transparent_and_respects_nameplate(self):
        candidates = generate_renewable_surplus_candidates(self.inputs, self.config)
        self.assertEqual(set(candidates), {"no_ro", "conservative_surplus_50pct", "renewable_surplus_full"})
        self.assertTrue((candidates["no_ro"] == 0).all())
        self.assertLessEqual(float(candidates["renewable_surplus_full"].max()), self.config.ro_rated_power_kw)
        self.assertEqual(candidates["renewable_surplus_full"].tolist(), [0.0, 20.0, 0.0])

    def test_candidate_generator_rejects_non_finite_ro_rating(self):
        from dataclasses import replace
        for invalid in (float("nan"), float("inf"), 0.0, -1.0):
            with self.subTest(rating=invalid):
                config = replace(self.config, ro_rated_power_kw=invalid)
                with self.assertRaisesRegex(ValueError, "finite and > 0"):
                    generate_renewable_surplus_candidates(self.inputs, config)

    def test_candidate_generator_rejects_non_numeric_series(self):
        scenario = MicrogridInputs(
            pv_power_kw=["bad"], wind_power_kw=[0], essential_load_kw=[0],
            ro_requested_power_kw=[0], water_demand_m3=[0],
        )
        with self.assertRaisesRegex(ValueError, "numeric series"):
            generate_renewable_surplus_candidates(scenario, self.config)

    def test_generated_candidates_are_evaluated_by_common_physics(self):
        ranked = screen_renewable_surplus_candidates(self.inputs, self.config)
        self.assertEqual(len(ranked), 3)
        self.assertTrue(all(item.result is not None for item in ranked))
        self.assertTrue(all(item.essential_unserved_kwh == 0 for item in ranked))
        self.assertEqual(ranked[0].schedule_id, "renewable_surplus_full")


    def test_robustness_evaluates_each_schedule_under_default_stress_cases(self):
        from dataclasses import replace
        robust_scenario = replace(self.inputs, essential_load_kw=[5, 5, 5])
        results = evaluate_schedule_robustness(
            {"no_ro": [0, 0, 0], "surplus": [0, 20, 0]},
            robust_scenario, self.config,
        )
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].scenarios_evaluated, 6)
        self.assertEqual(
            set(results[0].scenario_results),
            {"nominal", "low_renewables", "high_demand", "high_energy_price", "grid_outage", "combined_stress"},
        )
        self.assertTrue(results[0].robust_feasible)
        self.assertIn("worst_operating_cost", results[0].to_dict())

    def test_robustness_exposes_service_failure_under_renewable_collapse(self):
        results = evaluate_schedule_robustness(
            {"no_ro": [0, 0, 0]},
            self.inputs, self.config,
            stress_scenarios={"nominal": {}, "renewable_collapse": {"pv": 0, "wind": 0}},
        )
        result = results[0]
        self.assertFalse(result.robust_feasible)
        self.assertEqual(result.scenario_results["nominal"].essential_unserved_kwh, 0)
        self.assertEqual(result.scenario_results["renewable_collapse"].essential_unserved_kwh, 30)
        self.assertEqual(result.worst_essential_unserved_kwh, 30)

    def test_robustness_rejects_unknown_or_invalid_multipliers(self):
        with self.assertRaisesRegex(ValueError, "unsupported"):
            evaluate_schedule_robustness(
                {"no_ro": [0, 0, 0]}, self.inputs, self.config,
                stress_scenarios={"bad": {"tariff": 2}},
            )
        with self.assertRaisesRegex(ValueError, "finite and non-negative"):
            evaluate_schedule_robustness(
                {"no_ro": [0, 0, 0]}, self.inputs, self.config,
                stress_scenarios={"bad": {"pv": -1}},
            )


    def test_robustness_applies_grid_tariff_stress_to_operating_cost(self):
        from dataclasses import replace
        config = replace(self.config, grid_import_limit_kw=10)
        scenario = MicrogridInputs(
            pv_power_kw=[0], wind_power_kw=[0], essential_load_kw=[5],
            ro_requested_power_kw=[0], water_demand_m3=[0],
            grid_available=[True], grid_price_per_kwh=[0.20],
            diesel_cost_per_kwh=0.50,
        )
        results = evaluate_schedule_robustness(
            {"no_ro": [0]}, scenario, config,
            stress_scenarios={"nominal": {}, "energy_cost_up": {
                "grid_price": 1.5, "diesel_cost": 1.5,
            }},
        )
        nominal = results[0].scenario_results["nominal"].operating_cost
        stressed = results[0].scenario_results["energy_cost_up"].operating_cost
        self.assertAlmostEqual(nominal, 1.0)
        self.assertAlmostEqual(stressed, 1.5)
        self.assertAlmostEqual(results[0].worst_operating_cost, 1.5)



    def test_robustness_detects_grid_outage_service_failure(self):
        from dataclasses import replace
        config = replace(self.config, grid_import_limit_kw=10)
        scenario = MicrogridInputs(
            pv_power_kw=[0], wind_power_kw=[0], essential_load_kw=[5],
            ro_requested_power_kw=[0], water_demand_m3=[0],
            grid_available=[True], grid_price_per_kwh=[0.2],
        )
        result = evaluate_schedule_robustness(
            {"no_ro": [0]}, scenario, config,
        )[0]
        self.assertTrue(result.scenario_results["nominal"].feasible)
        self.assertFalse(result.scenario_results["grid_outage"].feasible)
        self.assertEqual(
            result.scenario_results["grid_outage"].essential_unserved_kwh, 5
        )

    def test_robustness_rejects_fractional_grid_availability_multiplier(self):
        with self.assertRaisesRegex(ValueError, "must be 0 or 1"):
            evaluate_schedule_robustness(
                {"no_ro": [0, 0, 0]}, self.inputs, self.config,
                stress_scenarios={"partial": {"grid_availability": 0.5}},
            )



    def test_robustness_preserves_grid_availability_input_validation(self):
        invalid = MicrogridInputs(
            pv_power_kw=[0], wind_power_kw=[0], essential_load_kw=[0],
            ro_requested_power_kw=[0], water_demand_m3=[0],
            grid_available=[2],
        )
        with self.assertRaisesRegex(ValueError, "grid_available must be a boolean"):
            evaluate_schedule_robustness({"no_ro": [0]}, invalid, self.config)


    def test_robustness_rejects_empty_scenarios(self):
        with self.assertRaisesRegex(ValueError, "at least one stress"):
            evaluate_schedule_robustness(
                {"no_ro": [0, 0, 0]}, self.inputs, self.config,
                stress_scenarios={},
            )


    def test_coordinate_search_finds_lower_power_schedule_that_meets_water_demand(self):
        from dataclasses import replace
        scenario = replace(self.inputs, water_demand_m3=[0, 2, 0])
        result = search_ro_schedule(
            scenario, self.config, max_passes=3, power_levels=(0, 0.5, 1)
        )
        self.assertTrue(result.best.feasible)
        self.assertAlmostEqual(result.best.unmet_water_m3, 0)
        self.assertAlmostEqual(result.best.ro_electricity_kwh, 10)
        self.assertGreater(result.evaluations, 2)
        self.assertGreaterEqual(result.passes_completed, 1)
        self.assertEqual(result.method, "deterministic_coordinate_search")

    def test_coordinate_search_does_not_mutate_initial_schedule(self):
        initial = [0.0, 20.0, 0.0]
        search_ro_schedule(
            self.inputs, self.config, initial_schedules={"caller": initial},
            max_passes=1,
        )
        self.assertEqual(initial, [0.0, 20.0, 0.0])

    def test_coordinate_search_rejects_invalid_search_controls(self):
        with self.assertRaisesRegex(ValueError, "max_passes"):
            search_ro_schedule(self.inputs, self.config, max_passes=0)
        with self.assertRaisesRegex(ValueError, "power_levels"):
            search_ro_schedule(self.inputs, self.config, power_levels=(0, 1.2))


if __name__ == "__main__":
    unittest.main()

"""Tests for the receding-horizon dispatch prototype."""
import unittest

from experiments.compare_dispatch_policies import build_scenarios
from experiments.rolling_horizon_dispatch import run_experiment, simulate_rolling


class TestRollingHorizonDispatch(unittest.TestCase):
    def test_one_step_is_committed_and_state_is_reported(self):
        scenario = build_scenarios()[0]
        result = simulate_rolling(scenario, scenario.available_surplus_kw, "rolling")
        self.assertEqual(len(result["hourly_priority_decisions"]), len(scenario.available_surplus_kw))
        self.assertTrue(set(result["hourly_priority_decisions"]) <= {"ro_first", "ice_first"})
        self.assertGreaterEqual(result["final_water_inventory_m3"], 20.0)
        self.assertLessEqual(result["final_water_inventory_m3"], 500.0)
        self.assertGreaterEqual(result["final_cold_inventory_kwh_th"], 0.0)
        self.assertLessEqual(result["final_cold_inventory_kwh_th"], 400.0)

    def test_forecast_error_changes_input_not_realized_profile(self):
        scenario = build_scenarios()[0]
        actual = scenario.available_surplus_kw
        forecast = tuple(value * 1.2 for value in actual)
        result = simulate_rolling(scenario, forecast, "rolling")
        self.assertEqual(scenario.available_surplus_kw, actual)
        self.assertEqual(result["policy"], "rolling")
        self.assertEqual(len(result["hourly_priority_decisions"]), len(actual))

    def test_underforecasted_committed_hour_is_locatable_in_hourly_audit(self):
        from experiments.compare_dispatch_policies import Scenario

        scenario = Scenario(
            name="forecast_error_during_ro_commitment",
            available_surplus_kw=(400.0, 0.0, 400.0),
            water_demand_m3_per_hour=(0.0, 0.0, 0.0),
            cooling_demand_kw_th=(0.0, 0.0, 0.0),
        )
        forecast = (400.0, 400.0, 400.0)
        result = simulate_rolling(scenario, forecast, "ro_first")

        self.assertEqual(result["constraint_violation_hour_indices"], [1])
        self.assertEqual(len(result["hourly_audit"]), 3)
        self.assertEqual(result["hourly_audit"][0]["ro_active"], True)
        self.assertEqual(result["hourly_audit"][1]["ro_active"], True)
        self.assertEqual(result["hourly_audit"][1]["actual_surplus_kw"], 0.0)
        self.assertEqual(result["hourly_audit"][1]["ro_power_kw"], 0.0)
        self.assertEqual(result["hourly_audit"][1]["ro_constraint_violation"], 1)
        self.assertEqual(result["hourly_audit"][1]["ro_run_hours_remaining"], 0)
        self.assertEqual(result["constraint_violation_hours"], 1)

    def test_experiment_covers_scenario_error_and_policy_combinations(self):
        rows = run_experiment()
        self.assertEqual(len(rows), 48)
        self.assertEqual(
            {row["result"]["policy"] for row in rows},
            {"rolling", "ro_first", "ice_first", "perfect_information"},
        )
        self.assertTrue(all(row["result"]["constraint_violation_hours"] == 0 for row in rows))
        for row in rows:
            result = row["result"]
            self.assertGreaterEqual(result["water_unmet_m3"], 0.0)
            self.assertGreaterEqual(result["cooling_unmet_kwh_th"], 0.0)
            self.assertGreaterEqual(result["remaining_surplus_kwh"], 0.0)

    def test_experiment_is_reproducible(self):
        self.assertEqual(run_experiment(), run_experiment())


if __name__ == "__main__":
    unittest.main()

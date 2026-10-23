"""Tests for the receding-horizon dispatch prototype."""
import unittest
from unittest.mock import patch

import numpy as np

from experiments.compare_dispatch_policies import build_scenarios
from experiments.rolling_horizon_dispatch import (
    parse_scenario_csv, run_experiment, simulate_rolling, summarize_aggregate,
    summarize_experiment, summarize_weight_sensitivity,
)


class TestRollingHorizonDispatch(unittest.TestCase):
    def test_parse_scenario_csv_preserves_actual_and_forecast_inputs(self):
        text = (
            "timestamp_utc,actual_surplus_kw,forecast_surplus_kw,water_demand_m3,"
            "cooling_demand_kw_th,forecast_water_demand_m3\\n"
            "2026-01-01T00:00:00Z,20,18,4,6,5\\n"
            "2026-01-01T01:00:00+00:00,15,17,5,7,8\\n"
        )
        parsed = parse_scenario_csv(text, name="uploaded_case")
        self.assertEqual(parsed["scenario"].name, "uploaded_case")
        self.assertEqual(parsed["scenario"].available_surplus_kw, (20.0, 15.0))
        self.assertEqual(parsed["forecast_surplus_kw"], (18.0, 17.0))
        self.assertEqual(parsed["scenario"].water_demand_m3_per_hour, (4.0, 5.0))
        self.assertEqual(parsed["forecast_water_demand_m3_per_hour"], (5.0, 8.0))
        self.assertTrue(parsed["timestamps_utc"][0].endswith("Z"))

    def test_parsed_scenario_runs_all_dispatch_policies(self):
        text = (
            "timestamp_utc,actual_surplus_kw,forecast_surplus_kw,water_demand_m3,"
            "cooling_demand_kw_th,forecast_water_demand_m3\\n"
            "2026-01-01T00:00:00Z,400,380,5,8,6\\n"
            "2026-01-01T01:00:00Z,0,20,6,9,7\\n"
            "2026-01-01T02:00:00Z,400,420,4,5,4\\n"
        )
        parsed = parse_scenario_csv(text, name="paired_fixture")
        for policy in ("rolling", "ro_first", "ice_first", "perfect_information"):
            with self.subTest(policy=policy):
                result = simulate_rolling(
                    parsed["scenario"], parsed["forecast_surplus_kw"], policy,
                    forecast_water_demand_m3_per_hour=parsed["forecast_water_demand_m3_per_hour"],
                )
                self.assertEqual(len(result["hourly_audit"]), 3)
                self.assertTrue(all(np.isfinite(row["water_inventory_m3"]) for row in result["hourly_audit"]))
                self.assertEqual(result["constraint_violation_hours"], len(result["constraint_violation_hour_indices"]))

    def test_parse_scenario_csv_rejects_missing_columns(self):
        with self.assertRaisesRegex(ValueError, "missing required columns"):
            parse_scenario_csv("timestamp_utc,actual_surplus_kw\\n2026-01-01T00:00:00Z,10\\n")

    def test_parse_scenario_csv_rejects_naive_or_unordered_timestamps(self):
        prefix = "timestamp_utc,actual_surplus_kw,forecast_surplus_kw,water_demand_m3,cooling_demand_kw_th\\n"
        with self.assertRaisesRegex(ValueError, "must include a timezone"):
            parse_scenario_csv(prefix + "2026-01-01T00:00:00,10,10,1,1\\n")
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            parse_scenario_csv(prefix + "2026-01-01T01:00:00Z,10,10,1,1\\n2026-01-01T00:00:00Z,10,10,1,1\\n")

    def test_parse_scenario_csv_rejects_non_hourly_gaps(self):
        prefix = "timestamp_utc,actual_surplus_kw,forecast_surplus_kw,water_demand_m3,cooling_demand_kw_th\\n"
        text = prefix + "2026-01-01T00:00:00Z,10,10,1,1\\n2026-01-01T02:00:00Z,10,10,1,1\\n"
        with self.assertRaisesRegex(ValueError, "exactly one hour apart"):
            parse_scenario_csv(text)

    def test_parse_scenario_csv_rejects_negative_nonfinite_and_blank_forecasts(self):
        prefix = "timestamp_utc,actual_surplus_kw,forecast_surplus_kw,water_demand_m3,cooling_demand_kw_th\\n"
        with self.assertRaisesRegex(ValueError, "finite and non-negative"):
            parse_scenario_csv(prefix + "2026-01-01T00:00:00Z,-1,10,1,1\\n")
        with self.assertRaisesRegex(ValueError, "finite and non-negative"):
            parse_scenario_csv(prefix + "2026-01-01T00:00:00Z,10,nan,1,1\\n")
        with self.assertRaisesRegex(ValueError, "forecast_water_demand_m3 must be numeric"):
            parse_scenario_csv(
                prefix.replace("cooling_demand_kw_th\\n", "cooling_demand_kw_th,forecast_water_demand_m3\\n")
                + "2026-01-01T00:00:00Z,10,10,1,1,\\n"
            )

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

    def test_water_demand_forecast_is_a_planning_input_and_actual_is_audited(self):
        from experiments.compare_dispatch_policies import Scenario

        scenario = Scenario(
            name="separate_water_forecast_and_actual",
            available_surplus_kw=(400.0, 400.0, 400.0),
            water_demand_m3_per_hour=(5.0, 10.0, 15.0),
            cooling_demand_kw_th=(0.0, 0.0, 0.0),
        )
        result = simulate_rolling(
            scenario, (400.0, 400.0, 400.0), "ro_first",
            forecast_water_demand_m3_per_hour=(20.0, 25.0, 30.0),
        )
        self.assertEqual(
            [row["actual_water_demand_m3"] for row in result["hourly_audit"]],
            [5.0, 10.0, 15.0],
        )
        self.assertEqual(
            [row["forecast_water_demand_m3"] for row in result["hourly_audit"]],
            [20.0, 25.0, 30.0],
        )
        self.assertEqual(
            [row["planning_water_demand_m3"] for row in result["hourly_audit"]],
            [20.0, 25.0, 30.0],
        )

    def test_fixed_priority_planning_uses_forecast_water_demand(self):
        from experiments.rolling_horizon_dispatch import _run_horizon

        scenario = build_scenarios()[0]
        forecast_water = tuple(value * 0.5 for value in scenario.water_demand_m3_per_hour)
        with patch(
            "experiments.rolling_horizon_dispatch._run_horizon",
            wraps=_run_horizon,
        ) as run_horizon:
            simulate_rolling(
                scenario,
                scenario.available_surplus_kw,
                "ro_first",
                forecast_water_demand_m3_per_hour=forecast_water,
            )

        # The first horizon call is the planning pass; execution calls later
        # must still receive realized demand, not the forecast.
        self.assertEqual(
            list(np.asarray(run_horizon.call_args_list[0].args[1], dtype=float)),
            list(forecast_water[:3]),
        )
        self.assertEqual(
            list(np.asarray(run_horizon.call_args_list[1].args[1], dtype=float)),
            [scenario.water_demand_m3_per_hour[0]],
        )

    def test_rejects_invalid_realized_scenario_series(self):
        from experiments.compare_dispatch_policies import Scenario

        base = Scenario(
            name="invalid_realized_input",
            available_surplus_kw=(100.0, 100.0),
            water_demand_m3_per_hour=(1.0, 1.0),
            cooling_demand_kw_th=(2.0, 2.0),
        )
        with self.assertRaisesRegex(ValueError, "available_surplus_kw must be finite and non-negative"):
            simulate_rolling(
                Scenario(base.name, (-1.0, 100.0), base.water_demand_m3_per_hour,
                         base.cooling_demand_kw_th),
                (100.0, 100.0),
            )
        with self.assertRaisesRegex(ValueError, "cooling_demand_kw_th must match"):
            simulate_rolling(
                Scenario(base.name, base.available_surplus_kw, base.water_demand_m3_per_hour,
                         (2.0,)),
                base.available_surplus_kw,
            )
        with self.assertRaisesRegex(ValueError, "one-dimensional scenario horizon"):
            simulate_rolling(base, np.array([[100.0, 100.0]]))

    def test_rejects_empty_horizon_and_unknown_policy(self):
        from experiments.compare_dispatch_policies import Scenario

        empty = Scenario("empty", (), (), ())
        with self.assertRaisesRegex(ValueError, "non-empty one-dimensional"):
            simulate_rolling(empty, (), "rolling")
        scenario = build_scenarios()[0]
        with self.assertRaisesRegex(ValueError, "policy must be"):
            simulate_rolling(scenario, scenario.available_surplus_kw, "mystery")

    def test_rejects_misaligned_or_negative_water_demand_forecast(self):
        scenario = build_scenarios()[0]
        with self.assertRaisesRegex(ValueError, "must match the scenario horizon"):
            simulate_rolling(
                scenario, scenario.available_surplus_kw, "rolling",
                forecast_water_demand_m3_per_hour=(1.0,),
            )
        with self.assertRaisesRegex(ValueError, "finite and non-negative"):
            simulate_rolling(
                scenario, scenario.available_surplus_kw, "rolling",
                forecast_water_demand_m3_per_hour=(-1.0,) * len(scenario.available_surplus_kw),
            )

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
        self.assertEqual(result["hourly_audit"][1]["ro_active"], False)
        self.assertEqual(
            result["hourly_audit"][1]["ro_operating_state"],
            "COMMITMENT_POWER_SHORTFALL",
        )
        self.assertEqual(result["hourly_audit"][1]["actual_surplus_kw"], 0.0)
        self.assertEqual(result["hourly_audit"][1]["ro_power_kw"], 0.0)
        self.assertEqual(result["hourly_audit"][1]["ro_constraint_violation"], 1)
        self.assertEqual(result["hourly_audit"][1]["ro_run_hours_remaining"], 0)
        self.assertEqual(result["constraint_violation_hours"], 1)

    def test_ro_recovery_lockout_is_carried_across_hourly_replans(self):
        from experiments.compare_dispatch_policies import Scenario

        scenario = Scenario(
            name="power_recovers_after_ro_shortfall",
            available_surplus_kw=(400.0, 0.0, 400.0, 400.0, 400.0),
            water_demand_m3_per_hour=(0.0, 0.0, 0.0, 0.0, 0.0),
            cooling_demand_kw_th=(0.0, 0.0, 0.0, 0.0, 0.0),
        )
        result = simulate_rolling(scenario, (400.0,) * 5, "ro_first")
        states = [row["ro_operating_state"] for row in result["hourly_audit"]]
        self.assertEqual(states[0], "RUNNING")
        self.assertEqual(states[1], "COMMITMENT_POWER_SHORTFALL")
        self.assertEqual(states[2], "RECOVERY_LOCKOUT")
        self.assertEqual(states[3:], ["RUNNING", "RUNNING"])
        self.assertEqual(
            [row["ro_fault_lockout_hours_remaining"] for row in result["hourly_audit"]],
            [0, 1, 0, 0, 0],
        )
        self.assertEqual(result["constraint_violation_hour_indices"], [1])

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

    def test_aggregate_summary_accounts_for_every_scenario_error_case(self):
        rows = run_experiment()
        summaries = summarize_experiment(rows)
        aggregate = summarize_aggregate(summaries)

        self.assertEqual(len(rows), 48)
        self.assertEqual(len(summaries), 12)
        self.assertEqual(aggregate["comparison_count"], len(summaries))
        self.assertEqual(
            aggregate["rolling_better_count"]
            + aggregate["rolling_tied_count"]
            + aggregate["rolling_worse_count"],
            len(summaries),
        )
        self.assertTrue(np.isfinite(aggregate["mean_score_delta"]))
        self.assertTrue(np.isfinite(aggregate["median_score_delta"]))
        self.assertIn("synthetic comparisons", aggregate["interpretation"])

    def test_weight_sensitivity_covers_all_cases_and_normalized_profiles(self):
        reports = summarize_weight_sensitivity(run_experiment())
        self.assertEqual(
            {row["weight_profile"] for row in reports},
            {"balanced", "water_priority", "cooling_priority"},
        )
        for row in reports:
            with self.subTest(profile=row["weight_profile"]):
                self.assertEqual(row["comparison_count"], 12)
                self.assertEqual(
                    row["rolling_better_count"] + row["rolling_tied_count"] + row["rolling_worse_count"],
                    12,
                )
                self.assertAlmostEqual(sum(row["weights"].values()), 1.0, places=9)
                self.assertTrue(np.isfinite(row["mean_score_delta"]))

    def test_aggregate_summary_handles_empty_input(self):
        aggregate = summarize_aggregate([])
        self.assertEqual(aggregate["comparison_count"], 0)
        self.assertIsNone(aggregate["mean_score_delta"])
        self.assertIsNone(aggregate["best_case"])

    def test_experiment_is_reproducible(self):
        self.assertEqual(run_experiment(), run_experiment())


    def test_repeated_ro_power_shortfalls_rearm_lockout_without_overallocating_power(self):
        from experiments.compare_dispatch_policies import Scenario

        scenario = Scenario(
            name="repeated_ro_power_shortfalls",
            available_surplus_kw=(400.0, 0.0, 400.0, 0.0, 400.0, 400.0, 400.0),
            water_demand_m3_per_hour=(0.0,) * 7,
            cooling_demand_kw_th=(0.0,) * 7,
        )
        result = simulate_rolling(scenario, (400.0,) * 7, "ro_first")
        audit = result["hourly_audit"]

        self.assertEqual(
            [row["ro_operating_state"] for row in audit],
            [
                "RUNNING",
                "COMMITMENT_POWER_SHORTFALL",
                "RECOVERY_LOCKOUT",
                "COMMITMENT_POWER_SHORTFALL",
                "RECOVERY_LOCKOUT",
                "RUNNING",
                "RUNNING",
            ],
        )
        self.assertEqual(
            [row["ro_fault_lockout_hours_remaining"] for row in audit],
            [0, 1, 0, 1, 0, 0, 0],
        )
        self.assertEqual(result["constraint_violation_hour_indices"], [1, 3])

        # RO plus ice may never draw more renewable power than was available.
        for row in audit:
            with self.subTest(hour=row["hour_index"]):
                self.assertLessEqual(
                    row["ro_power_kw"] + row["ice_power_kw"],
                    row["actual_surplus_kw"] + 1e-7,
                )


    def test_constraint_violation_hours_matches_unique_audit_hours(self):
        scenario = build_scenarios()[0]
        result = simulate_rolling(scenario, scenario.available_surplus_kw)
        affected_hours = result["constraint_violation_hour_indices"]

        self.assertEqual(len(affected_hours), len(set(affected_hours)))
        self.assertEqual(result["constraint_violation_hours"], len(affected_hours))
        self.assertTrue(
            all(0 <= hour < len(scenario.available_surplus_kw) for hour in affected_hours)
        )

    def test_hourly_audit_respects_inventory_and_renewable_power_bounds(self):
        from experiments.compare_dispatch_policies import make_ice, make_ro

        scenario = build_scenarios()[0]
        result = simulate_rolling(scenario, scenario.available_surplus_kw)
        ro_capacity = make_ro().config.reservoir_capacity_m3
        ice_capacity = make_ice().config.storage_capacity_kwh_th

        self.assertEqual(len(result["hourly_audit"]), len(scenario.available_surplus_kw))
        for row in result["hourly_audit"]:
            with self.subTest(hour=row["hour_index"]):
                self.assertTrue(np.isfinite(row["water_inventory_m3"]))
                self.assertTrue(np.isfinite(row["cold_inventory_kwh_th"]))
                self.assertGreaterEqual(row["water_inventory_m3"], -1e-7)
                self.assertLessEqual(row["water_inventory_m3"], ro_capacity + 1e-7)
                self.assertGreaterEqual(row["cold_inventory_kwh_th"], -1e-7)
                self.assertLessEqual(row["cold_inventory_kwh_th"], ice_capacity + 1e-7)
                self.assertGreaterEqual(row["ro_power_kw"], 0.0)
                self.assertGreaterEqual(row["ice_power_kw"], 0.0)
                self.assertLessEqual(
                    row["ro_power_kw"] + row["ice_power_kw"],
                    row["actual_surplus_kw"] + 1e-6,
                )

    def test_hourly_water_and_cooling_inventory_balances_close(self):
        from experiments.compare_dispatch_policies import make_ice, make_ro

        scenario = build_scenarios()[0]
        result = simulate_rolling(scenario, scenario.available_surplus_kw)
        audit = result["hourly_audit"]
        self.assertTrue(audit)

        # The first step starts from configured inventory; later steps carry
        # the previous hour's ending state forward without a hidden reset.
        self.assertAlmostEqual(
            audit[0]["water_inventory_before_m3"],
            make_ro().config.initial_water_m3,
            places=6,
        )
        self.assertAlmostEqual(
            audit[0]["cold_inventory_before_kwh_th"],
            make_ice().config.initial_storage_kwh_th,
            places=6,
        )

        for index, row in enumerate(audit):
            with self.subTest(hour=row["hour_index"]):
                water_after = (
                    row["water_inventory_before_m3"]
                    + row["water_produced_m3"]
                    - row["water_spill_m3"]
                    - row["water_served_m3"]
                )
                cold_after = (
                    row["cold_inventory_before_kwh_th"]
                    + row["cooling_produced_kwh_th"]
                    - row["cooling_spill_kwh_th"]
                    - row["cooling_served_kwh_th"]
                )
                self.assertAlmostEqual(water_after, row["water_inventory_m3"], delta=2e-5)
                self.assertAlmostEqual(cold_after, row["cold_inventory_kwh_th"], delta=2e-5)
                if index:
                    self.assertAlmostEqual(
                        row["water_inventory_before_m3"],
                        audit[index - 1]["water_inventory_m3"],
                        places=6,
                    )
                    self.assertAlmostEqual(
                        row["cold_inventory_before_kwh_th"],
                        audit[index - 1]["cold_inventory_kwh_th"],
                        places=6,
                    )

    def test_rejects_misaligned_negative_and_nonfinite_power_forecasts(self):
        scenario = build_scenarios()[0]
        with self.assertRaisesRegex(ValueError, "forecast_surplus must match"):
            simulate_rolling(scenario, (1.0,))
        with self.assertRaisesRegex(ValueError, "finite and non-negative"):
            simulate_rolling(scenario, (-1.0,) * len(scenario.available_surplus_kw))
        with self.assertRaisesRegex(ValueError, "finite and non-negative"):
            simulate_rolling(
                scenario, (float("nan"),) * len(scenario.available_surplus_kw)
            )


if __name__ == "__main__":
    unittest.main()

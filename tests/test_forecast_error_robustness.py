"""Tests for deterministic synthetic forecast-error robustness analysis."""
import unittest

from experiments.compare_dispatch_policies import build_scenarios
from experiments.forecast_error_robustness import (
    error_profiles, perturb_scenario, run_robustness_experiment,
)


class TestForecastErrorRobustness(unittest.TestCase):
    def test_error_profiles_are_aligned_and_bounded(self):
        for scenario in build_scenarios():
            profiles = error_profiles(len(scenario.available_surplus_kw))
            self.assertEqual(set(profiles), {
                "perfect", "overforecast_20pct", "underforecast_20pct",
                "alternating_pm20pct",
            })
            for errors in profiles.values():
                self.assertEqual(len(errors), len(scenario.available_surplus_kw))
                self.assertTrue(all(-0.2 <= value <= 0.2 for value in errors))

    def test_perturbation_does_not_mutate_actual_scenario(self):
        scenario = build_scenarios()[0]
        original = scenario.available_surplus_kw
        forecast = perturb_scenario(scenario, error_profiles(len(original))["overforecast_20pct"])
        self.assertEqual(scenario.available_surplus_kw, original)
        self.assertTrue(all(f >= a for f, a in zip(forecast.available_surplus_kw, original)))
        self.assertEqual(len(forecast.available_surplus_kw), len(original))

    def test_experiment_has_every_scenario_profile_pair(self):
        rows = run_robustness_experiment()
        self.assertEqual(len(rows), 12)
        self.assertEqual(
            {(r["scenario"], r["forecast_error_profile"]) for r in rows},
            {
                (scenario.name, profile)
                for scenario in build_scenarios()
                for profile in error_profiles(len(scenario.available_surplus_kw))
            },
        )
        for row in rows:
            self.assertIn(row["forecast_selected_candidate"], {
                "ro_first_run1h", "ro_first_run2h", "ro_first_run3h", "ro_first_run4h",
                "ice_first_run1h", "ice_first_run2h", "ice_first_run3h", "ice_first_run4h",
            })
            self.assertGreaterEqual(row["forecast_selected_actual_metrics"]["water_unmet_m3"], 0)
            self.assertGreaterEqual(row["fixed_baseline_actual_metrics"]["cooling_unmet_kwh_th"], 0)

    def test_experiment_is_reproducible(self):
        self.assertEqual(run_robustness_experiment(), run_robustness_experiment())


if __name__ == "__main__":
    unittest.main()

"""Tests for the reproducible dispatch-policy comparison experiment."""
import unittest

from experiments.compare_dispatch_policies import build_scenarios, run_comparison


class TestDispatchComparisonExperiment(unittest.TestCase):
    def test_scenarios_are_aligned_and_non_negative(self):
        for scenario in build_scenarios():
            lengths = {
                len(scenario.available_surplus_kw),
                len(scenario.water_demand_m3_per_hour),
                len(scenario.cooling_demand_kw_th),
            }
            self.assertEqual(lengths, {8})
            for series in (
                scenario.available_surplus_kw,
                scenario.water_demand_m3_per_hour,
                scenario.cooling_demand_kw_th,
            ):
                self.assertTrue(all(value >= 0 for value in series))

    def test_all_policies_run_for_each_scenario(self):
        rows = run_comparison()
        self.assertEqual(len(rows), 12)
        expected = {"ro_only", "ice_only", "ro_first", "ice_first"}
        for scenario in build_scenarios():
            actual = {row["policy"] for row in rows if row["scenario"] == scenario.name}
            self.assertEqual(actual, expected)

    def test_results_are_reproducible(self):
        self.assertEqual(run_comparison(), run_comparison())

    def test_metrics_are_non_negative(self):
        for row in run_comparison():
            for key, value in row.items():
                if key not in {"scenario", "policy"}:
                    self.assertGreaterEqual(value, 0, msg=f"{row['scenario']}/{row['policy']} {key}")


if __name__ == "__main__":
    unittest.main()

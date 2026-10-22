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

    def test_hourly_audit_covers_every_policy_and_conserves_resources(self):
        audit_records = []
        rows = run_comparison(audit_records=audit_records)

        # 3 scenarios × 4 policies × 8 hourly steps.
        self.assertEqual(len(audit_records), len(rows) * 8)
        for record in audit_records:
            label = f"{record['scenario']}/{record['policy']}/t={record['timestep']}"
            self.assertAlmostEqual(record["power_balance_residual_kw"], 0.0, delta=1e-7, msg=label)
            for name, load in record["loads"].items():
                with self.subTest(label=label, load=name):
                    self.assertAlmostEqual(load["inventory_balance_residual"], 0.0, delta=1e-7)
                    self.assertAlmostEqual(load["demand_balance_residual"], 0.0, delta=1e-7)
                    self.assertFalse(load["capacity_violation"])
    def test_summary_reports_final_inventories_for_included_assets(self):
        rows = run_comparison()
        for row in rows:
            with self.subTest(scenario=row["scenario"], policy=row["policy"]):
                if row["policy"] in {"ro_only", "ro_first", "ice_first"}:
                    self.assertIsNotNone(row["water_inventory_initial_m3"])
                    self.assertIsNotNone(row["water_inventory_final_m3"])
                    self.assertGreaterEqual(row["water_inventory_final_m3"], 20.0)
                    self.assertLessEqual(row["water_inventory_final_m3"], 500.0)
                else:
                    self.assertIsNone(row["water_inventory_initial_m3"])
                    self.assertIsNone(row["water_inventory_final_m3"])

                if row["policy"] in {"ice_only", "ro_first", "ice_first"}:
                    self.assertIsNotNone(row["cooling_storage_initial_kwh_th"])
                    self.assertIsNotNone(row["cooling_storage_final_kwh_th"])
                    self.assertGreaterEqual(row["cooling_storage_final_kwh_th"], 0.0)
                    self.assertLessEqual(row["cooling_storage_final_kwh_th"], 400.0)
                else:
                    self.assertIsNone(row["cooling_storage_initial_kwh_th"])
                    self.assertIsNone(row["cooling_storage_final_kwh_th"])

    def test_metrics_are_non_negative(self):
        for row in run_comparison():
            for key, value in row.items():
                if key not in {"scenario", "policy"} and value is not None:
                    self.assertGreaterEqual(value, 0, msg=f"{row['scenario']}/{row['policy']} {key}")


if __name__ == "__main__":
    unittest.main()

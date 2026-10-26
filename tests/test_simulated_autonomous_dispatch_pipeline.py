"""Integration tests for the simulation-only dispatch-to-gate workflow."""
import hashlib
import unittest

from experiments.rolling_horizon_dispatch import generate_synthetic_scenario_csv
from experiments.run_simulated_autonomous_dispatch import run_simulated_autonomous_dispatch


class TestSimulatedAutonomousDispatchPipeline(unittest.TestCase):
    def test_generated_scenario_runs_dispatch_and_gate_for_every_hour(self):
        report = run_simulated_autonomous_dispatch(hours=24)
        self.assertEqual(report["workflow"], "rolling_dispatch_to_simulated_autonomous_gate")
        self.assertEqual(report["dataset_type"], "synthetic")
        self.assertEqual(report["input_provenance"]["rows"], 24)
        self.assertEqual(len(report["input_provenance"]["sha256"]), 64)
        expected_hash = hashlib.sha256(generate_synthetic_scenario_csv(24).encode("utf-8")).hexdigest()
        self.assertEqual(report["input_provenance"]["sha256"], expected_hash)
        self.assertEqual(report["input_provenance"]["first_timestamp_utc"], "2026-01-01T00:00:00Z")
        self.assertFalse(report["is_measured_site_data"])
        self.assertEqual(len(report["hourly_results"]), 24)
        self.assertEqual(sum(report["gate_action_counts"].values()), 24)
        self.assertEqual(report["mode"], "simulation_only")
        self.assertFalse(report["physical_write_performed"])
        self.assertFalse(report["live_control_enabled"])
        for item in report["hourly_results"]:
            self.assertIn(item["gate"]["action"], {"ON", "OFF", "HOLD"})
            self.assertFalse(item["gate"]["physical_write_performed"])
            self.assertFalse(item["gate"]["live_control_enabled"])
            self.assertEqual(item["hour_index"], item["dispatch"]["hour_index"])

    def test_invalid_telemetry_holds_every_hour(self):
        report = run_simulated_autonomous_dispatch(hours=8, telemetry_valid=False)
        self.assertEqual(report["gate_action_counts"], {"ON": 0, "OFF": 0, "HOLD": 8})
        self.assertTrue(all(
            item["gate"]["reason_code"] == "HOLD_TELEMETRY_INVALID"
            for item in report["hourly_results"]
        ))

    def test_unhealthy_interlock_holds_every_hour(self):
        report = run_simulated_autonomous_dispatch(hours=5, interlocks_healthy=False)
        self.assertEqual(report["gate_action_counts"], {"ON": 0, "OFF": 0, "HOLD": 5})
        self.assertTrue(all(
            item["gate"]["reason_code"] == "HOLD_INTERLOCK_UNHEALTHY"
            for item in report["hourly_results"]
        ))

    def test_operator_stop_holds_every_hour(self):
        report = run_simulated_autonomous_dispatch(hours=5, operator_stop=True)
        self.assertEqual(report["gate_action_counts"], {"ON": 0, "OFF": 0, "HOLD": 5})
        self.assertTrue(all(
            item["gate"]["reason_code"] == "HOLD_OPERATOR_STOP"
            for item in report["hourly_results"]
        ))

    def test_user_csv_is_labeled_unverified_and_keeps_actuals_separate(self):
        csv_text = (
            "timestamp_utc,actual_surplus_kw,forecast_surplus_kw,water_demand_m3,"
            "cooling_demand_kw_th,forecast_water_demand_m3,forecast_cooling_demand_kw_th\n"
            "2026-01-01T00:00:00Z,400,380,5,8,6,7\n"
            "2026-01-01T01:00:00Z,0,20,6,9,7,8\n"
        )
        report = run_simulated_autonomous_dispatch(csv_text)
        self.assertEqual(report["dataset_type"], "user_supplied_unverified")
        self.assertEqual(
            report["input_provenance"]["sha256"],
            hashlib.sha256(csv_text.encode("utf-8")).hexdigest(),
        )
        self.assertEqual(report["input_provenance"]["last_timestamp_utc"], "2026-01-01T01:00:00Z")
        self.assertIsNone(report["is_measured_site_data"])
        self.assertEqual(len(report["hourly_results"]), 2)
        first = report["hourly_results"][0]["dispatch"]
        self.assertEqual(first["actual_surplus_kw"], 400.0)
        self.assertEqual(first["forecast_surplus_kw"], 380.0)
        self.assertEqual(first["forecast_water_demand_m3"], 6.0)
        self.assertEqual(first["forecast_cooling_demand_kw_th"], 7.0)

    def test_invalid_csv_is_rejected_not_silently_repaired(self):
        with self.assertRaisesRegex(ValueError, "missing required columns"):
            run_simulated_autonomous_dispatch("timestamp_utc,actual_surplus_kw\n2026-01-01T00:00:00Z,10\n")

    def test_invalid_synthetic_horizon_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "hours must be an integer"):
            run_simulated_autonomous_dispatch(hours=0)



    def test_custom_objective_weights_flow_through_pipeline_report(self):
        weights = {"water": 0.6, "cooling": 0.3, "surplus": 0.1}
        report = run_simulated_autonomous_dispatch(hours=4, objective_weights=weights)
        self.assertEqual(report["inputs"]["objective_weights"], weights)

    def test_invalid_objective_weights_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "must sum to 1.0"):
            run_simulated_autonomous_dispatch(
                hours=4,
                objective_weights={"water": 0.7, "cooling": 0.2, "surplus": 0.2},
            )

if __name__ == "__main__":
    unittest.main()

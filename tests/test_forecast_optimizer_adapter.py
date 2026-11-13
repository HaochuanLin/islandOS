"""Tests for the Phase 2 forecast to Phase 3 resource optimizer bridge."""
import unittest
from datetime import datetime, timedelta, timezone

from islandos_core.forecast_engine import forecast_signals
from islandos_core.energy_system import (
    BatterySpec, DieselSpec, EnergySystemConfig,
)
from islandos_core.assets import AssetParameter, AssetRecord, OperatingConstraint
from islandos_core.operational_state import AssetOperationalState
from islandos_core.asset_energy_adapter import AssetEnergyAdapterError
from islandos_core.forecast_optimizer_adapter import (
    build_coordination_inputs,
    build_site_energy_configuration,
    build_service_equivalent_economics,
    evaluate_forecast_stress_scenarios,
    optimize_forecasted_energy_system,
    optimize_forecasted_resource_schedule,
)


def make_bundle(horizon=6, include_load_components=False, critical_load_value=18.0):
    timestamps = [
        datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(hours=i)
        for i in range(240)
    ]
    history = {
        "pv_power": [max(0.0, 18.0 * ((i % 24 - 6) / 12.0)) for i in range(240)],
        "wind_power": [8.0 + 1.5 * (i % 12) / 12.0 for i in range(240)],
        "essential_load": [24.0 + 1.0 * (i % 24) / 24.0 for i in range(240)],
        "electricity_price": [
            -0.02 if i % 24 < 4 else (0.06 if i % 24 < 8 else 0.14)
            for i in range(240)
        ],
    }
    units = {
        "pv_power": "kW",
        "wind_power": "kW",
        "essential_load": "kW",
        "electricity_price": "USD/kWh",
    }
    if include_load_components:
        history["flexible_load"] = [2.0] * 240
        history["critical_load"] = [critical_load_value] * 240
        units["flexible_load"] = "kW"
        units["critical_load"] = "kW"
    non_negative = tuple(name for name in history if name != "electricity_price")
    return forecast_signals(
        timestamps, history, units, horizon, non_negative_signals=non_negative,
    )


class ForecastOptimizerAdapterTests(unittest.TestCase):
    def test_converts_phase2_bundle_to_aligned_physical_inputs(self):
        bundle = make_bundle()
        result = build_coordination_inputs(
            bundle, grid_available=[True] * 6, price_unit="USD/kWh"
        )
        self.assertEqual(len(result.timestamps_utc), 6)
        self.assertEqual(result.inputs.pv_generation_kw.__len__(), 6)
        self.assertEqual(result.inputs.wind_generation_kw.__len__(), 6)
        self.assertEqual(result.inputs.load_kw.__len__(), 6)
        self.assertEqual(result.inputs.grid_price_per_kwh[0], -0.02)
        self.assertEqual(result.history_sha256, bundle.input_history_sha256)
        self.assertEqual(result.model_ids["electricity_price"],
                         bundle.forecasts["electricity_price"].model_id)
        self.assertTrue(all(stamp.utcoffset() == timedelta(0)
                            for stamp in result.timestamps_utc))

    def test_rejects_price_unit_mismatch_without_conversion(self):
        with self.assertRaisesRegex(ValueError, "unit mismatch"):
            build_coordination_inputs(
                make_bundle(), grid_available=[True] * 6, price_unit="EUR/MWh"
            )

    def test_rejects_misaligned_grid_availability(self):
        with self.assertRaisesRegex(ValueError, "exactly 6 values"):
            build_coordination_inputs(
                make_bundle(), grid_available=[True] * 5, price_unit="USD/kWh"
            )

    def test_maps_optional_flexible_and_critical_load_forecasts(self):
        bundle = make_bundle(include_load_components=True)
        result = build_coordination_inputs(
            bundle, grid_available=[True] * 6, price_unit="USD/kWh"
        )
        self.assertEqual(tuple(result.inputs.flexible_load_kw), (2.0,) * 6)
        self.assertEqual(tuple(result.inputs.critical_load_kw), (18.0,) * 6)
        self.assertIn("flexible_load", result.model_ids)
        self.assertIn("critical_load", result.model_ids)

    def test_rejects_critical_load_above_base_load(self):
        bundle = make_bundle(include_load_components=True, critical_load_value=40.0)
        with self.assertRaisesRegex(ValueError, "cannot exceed essential_load"):
            build_coordination_inputs(
                bundle, grid_available=[True] * 6, price_unit="USD/kWh"
            )

    def test_economics_withholds_savings_when_service_is_not_equivalent(self):
        result = {
            "recommendation": {"policy": "battery_first"},
            "candidates": [
                {"policy": "grid_first", "summary": {
                    "load_served_kwh": 100.0, "unmet_load_kwh": 0.0,
                    "critical_unmet_load_kwh": 0.0, "flexible_load_shed_kwh": 0.0,
                    "estimated_energy_cost": 50.0, "gross_energy_cost": 52.0,
                }},
                {"policy": "battery_first", "summary": {
                    "load_served_kwh": 95.0, "unmet_load_kwh": 5.0,
                    "critical_unmet_load_kwh": 0.0, "flexible_load_shed_kwh": 5.0,
                    "estimated_energy_cost": 40.0, "gross_energy_cost": 42.0,
                }},
            ],
        }
        economics = build_service_equivalent_economics(result)
        self.assertFalse(economics["service_equivalent"])
        self.assertFalse(economics["cost_comparison_valid"])
        self.assertIsNone(economics["estimated_cost_reduction"])
        self.assertIn("no cost saving is claimed", economics["interpretation"])

    def test_economics_reports_modeled_delta_only_at_equivalent_service(self):
        result = {
            "recommendation": {"policy": "battery_first"},
            "candidates": [
                {"policy": "grid_first", "summary": {
                    "load_served_kwh": 100.0, "unmet_load_kwh": 0.0,
                    "critical_unmet_load_kwh": 0.0, "flexible_load_shed_kwh": 0.0,
                    "estimated_energy_cost": 50.0, "gross_energy_cost": 52.0,
                }},
                {"policy": "battery_first", "summary": {
                    "load_served_kwh": 100.0, "unmet_load_kwh": 0.0,
                    "critical_unmet_load_kwh": 0.0, "flexible_load_shed_kwh": 0.0,
                    "estimated_energy_cost": 45.0, "gross_energy_cost": 47.0,
                }},
            ],
        }
        economics = build_service_equivalent_economics(result)
        self.assertTrue(economics["service_equivalent"])
        self.assertTrue(economics["cost_comparison_valid"])
        self.assertEqual(economics["estimated_cost_reduction"], 5.0)
        self.assertFalse(economics["reference_is_measured_site_operation"])

    def test_stress_evaluation_replays_same_policies_across_all_scenarios(self):
        coordinated = build_coordination_inputs(
            make_bundle(), grid_available=[True] * 6, price_unit="USD/kWh"
        )
        config = EnergySystemConfig(
            pv_rated_kw=30.0,
            wind_rated_kw=15.0,
            grid_import_limit_kw=100.0,
        )
        stress = evaluate_forecast_stress_scenarios(coordinated, config)
        self.assertEqual(stress["scenario_count"], 4)
        self.assertIn("combined_supply_and_grid_stress", stress["scenario_names"])
        self.assertEqual(set(stress["policy_results"]), {"battery_first", "grid_first"})
        for result in stress["policy_results"].values():
            self.assertTrue(result["all_scenarios_passed_physical_audit"])
            self.assertEqual(
                set(result["scenario_results"]),
                set(stress["scenario_names"]),
            )
        self.assertIn(stress["recommendation"]["policy"],
                      ("battery_first", "grid_first"))
        self.assertFalse(stress["method_scope"]["scenario_probabilities_assigned"])
        self.assertFalse(stress["method_scope"]["robust_global_optimization_claimed"])

    def test_site_configuration_requires_confirmed_assets_and_fresh_online_state(self):
        now = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)
        parameter = lambda value, unit: AssetParameter(
            value, unit, "customer_provided", "site asset register rev A", True
        )
        pv = AssetRecord(
            asset_id="pv-main", site_id="site-alpha", asset_type="pv",
            nameplate_parameters={"rated_power_kw": parameter(20.0, "kW")},
            installed_parameters={"configured_power_kw": parameter(18.0, "kW")},
            observed_parameters={},
            constraints=(OperatingConstraint(
                constraint_id="pv-max", parameter="max_power_kw",
                severity="hard", unit="kW", operator="max",
                upper_bound=18.0, source_reference="approved inverter limit",
                confirmed=True,
            ),),
        )
        state = AssetOperationalState(
            "pv-main", "site-alpha", "online", now,
            "verified telemetry snapshot", True,
        )
        configured = build_site_energy_configuration([pv], [state], as_of=now)
        self.assertEqual(configured["config"].pv_rated_kw, 18.0)
        self.assertTrue(configured["operational_readiness"]["can_dispatch_screen"])

    def test_site_configuration_fails_closed_on_missing_operational_state(self):
        now = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)
        parameter = lambda value, unit: AssetParameter(
            value, unit, "customer_provided", "site asset register rev A", True
        )
        pv = AssetRecord(
            asset_id="pv-main", site_id="site-alpha", asset_type="pv",
            nameplate_parameters={"rated_power_kw": parameter(20.0, "kW")},
            installed_parameters={"configured_power_kw": parameter(18.0, "kW")},
            observed_parameters={},
            constraints=(OperatingConstraint(
                constraint_id="pv-max", parameter="max_power_kw",
                severity="hard", unit="kW", operator="max",
                upper_bound=18.0, source_reference="approved inverter limit",
                confirmed=True,
            ),),
        )
        with self.assertRaisesRegex(AssetEnergyAdapterError, "operational readiness is blocked"):
            build_site_energy_configuration([pv], [], as_of=now)

    def test_joint_resource_optimizer_uses_shared_forecast_stress_scenarios(self):
        bundle = make_bundle()
        config = EnergySystemConfig(
            pv_rated_kw=30.0,
            wind_rated_kw=15.0,
            grid_import_limit_kw=100.0,
            battery=BatterySpec(
                capacity_kwh=40.0, max_charge_kw=12.0,
                max_discharge_kw=12.0, initial_soc=0.6,
            ),
            diesel=DieselSpec(
                rated_power_kw=30.0, variable_cost_per_kwh=0.25,
                min_stable_power_kw=0.0, ramp_up_kw_per_hour=30.0,
            ),
        )
        result = optimize_forecasted_resource_schedule(
            bundle,
            config,
            grid_available=[True] * 6,
            diesel_available=[True] * 6,
            price_unit="USD/kWh",
            population_size=4,
            generations=1,
            seed=7,
        )
        self.assertEqual(result["scenario_count"], 4)
        self.assertTrue(result["model_scope"]["same_decisions_replayed_across_all_scenarios"])
        self.assertTrue(result["model_scope"]["robust_optimization_enabled"])
        self.assertEqual(result["forecast_provenance"]["history_sha256"],
                         bundle.input_history_sha256)
        self.assertFalse(result["forecast_scenario_scope"]["scenario_probabilities_assigned"])
        self.assertEqual(len(result["recommendation"]["battery_setpoints_kw"]), 6)

    def test_joint_resource_optimizer_requires_explicit_assets(self):
        with self.assertRaisesRegex(ValueError, "requires configured battery and diesel"):
            optimize_forecasted_resource_schedule(
                make_bundle(),
                EnergySystemConfig(pv_rated_kw=30.0, wind_rated_kw=15.0,
                                   grid_import_limit_kw=100.0),
                grid_available=[True] * 6,
                diesel_available=[True] * 6,
                price_unit="USD/kWh",
            )

    def test_runs_optimizer_and_preserves_forecast_provenance(self):
        bundle = make_bundle()
        config = EnergySystemConfig(
            pv_rated_kw=30.0,
            wind_rated_kw=15.0,
            grid_import_limit_kw=100.0,
        )
        result = optimize_forecasted_energy_system(
            bundle,
            config,
            grid_available=[True] * 6,
            price_unit="USD/kWh",
        )
        self.assertEqual(result["candidate_count"], 2)
        self.assertIn(result["recommendation"]["policy"],
                      ("battery_first", "grid_first"))
        provenance = result["forecast_provenance"]
        self.assertEqual(provenance["history_sha256"], bundle.input_history_sha256)
        self.assertEqual(len(provenance["target_timestamps_utc"]), 6)
        self.assertFalse(provenance["uncertainty_bounds_used_by_point_optimizer"])
        self.assertTrue(provenance["uncertainty_bounds_used_by_stress_evaluation"])
        self.assertEqual(result["forecast_stress_evaluation"]["scenario_count"], 4)
        self.assertIn("not robust optimization", result["decision_scope"])


if __name__ == "__main__":
    unittest.main()

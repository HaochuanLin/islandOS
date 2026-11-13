"""Tests for the Phase 2 forecast to Phase 3 resource optimizer bridge."""
import unittest
from datetime import datetime, timedelta, timezone

from islandos_core.forecast_engine import forecast_signals
from islandos_core.energy_system import EnergySystemConfig
from islandos_core.forecast_optimizer_adapter import (
    build_coordination_inputs,
    optimize_forecasted_energy_system,
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
        self.assertFalse(provenance["uncertainty_bounds_used_by_optimizer"])
        self.assertIn("not robust optimization", result["decision_scope"])


if __name__ == "__main__":
    unittest.main()

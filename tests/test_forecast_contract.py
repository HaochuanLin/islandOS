"""Tests for the forecast-to-planning hand-off contract."""
import unittest
from dataclasses import replace
from datetime import timedelta

from islandos_core.forecast_contract import build_forecast_planning_input
from islandos_core.forecast_engine import forecast_signals


class TestForecastPlanningContract(unittest.TestCase):
    def setUp(self):
        from datetime import datetime, timezone
        self.timestamps = [
            datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(hours=i)
            for i in range(240)
        ]
        self.bundle = forecast_signals(
            self.timestamps,
            {
                "pv": [max(0.0, 10.0 + (i % 24 - 12) * 0.2) for i in range(240)],
                "load": [30.0 + (i % 24) * 0.1 for i in range(240)],
                "price": [0.05 if i % 24 < 8 else 0.15 for i in range(240)],
            },
            {"pv": "kW", "load": "kW", "price": "USD/kWh"},
            6,
            non_negative_signals=("pv", "load"),
        )

    def test_builds_aligned_unit_labelled_planning_input(self):
        result = build_forecast_planning_input(
            self.bundle,
            {"pv": "kW", "load": "kW", "price": "USD/kWh"},
        )
        self.assertEqual(len(result.timestamps), 6)
        self.assertEqual(set(result.values), {"pv", "load", "price"})
        self.assertEqual(result.units["price"], "USD/kWh")
        self.assertEqual(result.model_ids["load"], self.bundle.forecasts["load"].model_id)
        self.assertEqual(result.history_sha256, self.bundle.input_history_sha256)
        for name in result.values:
            self.assertEqual(len(result.lower_bounds[name]), 6)
            self.assertEqual(len(result.upper_bounds[name]), 6)
            self.assertTrue(all(
                low <= value <= high
                for low, value, high in zip(
                    result.lower_bounds[name], result.values[name], result.upper_bounds[name]
                )
            ))

    def test_normalizes_equivalent_timezone_offsets_to_utc(self):
        forecasts = dict(self.bundle.forecasts)
        signal = forecasts["pv"]
        local_zone = timezone(timedelta(hours=8))
        points = [
            replace(point, timestamp=point.timestamp.astimezone(local_zone))
            for point in signal.points
        ]
        forecasts["pv"] = replace(signal, points=tuple(points))
        equivalent_instants = replace(self.bundle, forecasts=forecasts)
        result = build_forecast_planning_input(
            equivalent_instants, {"pv": "kW", "load": "kW"}
        )
        self.assertTrue(all(stamp.utcoffset() == timedelta(0) for stamp in result.timestamps))

    def test_returned_signal_mappings_are_read_only(self):
        result = build_forecast_planning_input(self.bundle, {"pv": "kW"})
        with self.assertRaises(TypeError):
            result.values["pv"] = (999.0,)

    def test_rejects_missing_required_signal(self):
        with self.assertRaisesRegex(ValueError, "missing"):
            build_forecast_planning_input(self.bundle, {"battery": "kWh"})

    def test_rejects_unit_mismatch_instead_of_converting_silently(self):
        with self.assertRaisesRegex(ValueError, "unit mismatch"):
            build_forecast_planning_input(self.bundle, {"pv": "MW"})

    def test_rejects_misaligned_signal_timestamps(self):
        forecasts = dict(self.bundle.forecasts)
        signal = forecasts["load"]
        points = [
            replace(point, timestamp=point.timestamp + timedelta(hours=1))
            for point in signal.points
        ]
        forecasts["load"] = replace(signal, points=tuple(points))
        broken = replace(self.bundle, forecasts=forecasts)
        with self.assertRaisesRegex(ValueError, "identical target timestamps"):
            build_forecast_planning_input(broken, {"pv": "kW", "load": "kW"})

    def test_rejects_bounds_that_do_not_contain_prediction(self):
        forecasts = dict(self.bundle.forecasts)
        signal = forecasts["pv"]
        points = list(signal.points)
        points[0] = replace(points[0], lower_bound=points[0].predicted + 1.0)
        forecasts["pv"] = replace(signal, points=tuple(points))
        broken = replace(self.bundle, forecasts=forecasts)
        with self.assertRaisesRegex(ValueError, "bounds do not contain"):
            build_forecast_planning_input(broken, {"pv": "kW"})

    def test_rejects_malformed_history_digest(self):
        broken = replace(self.bundle, input_history_sha256="not-a-digest")
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            build_forecast_planning_input(broken, {"pv": "kW"})


if __name__ == "__main__":
    unittest.main()

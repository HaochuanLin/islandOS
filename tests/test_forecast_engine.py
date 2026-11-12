"""Tests for the baseline-gated multi-signal forecast engine."""
import unittest
from datetime import datetime, timedelta, timezone

from islandos_core.forecast_engine import forecast_signals


class TestForecastEngine(unittest.TestCase):
    def setUp(self):
        self.timestamps = [
            datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(hours=i)
            for i in range(240)
        ]

    def test_constant_signal_keeps_baseline_and_returns_horizon(self):
        result = forecast_signals(
            self.timestamps,
            {"critical_load": [12.0] * 240},
            {"critical_load": "kW"},
            24,
        )
        signal = result.forecasts["critical_load"]
        self.assertIn(signal.model_id, ("persistence", "seasonal_naive_24h"))
        self.assertFalse(signal.selected_model_beats_baseline)
        self.assertEqual(len(signal.points), 24)
        self.assertTrue(all(point.predicted == 12.0 for point in signal.points))
        self.assertEqual(signal.points[0].timestamp, self.timestamps[-1] + timedelta(hours=1))

    def test_multiple_signals_keep_units_and_provenance(self):
        history = {
            "pv": [max(0.0, 20.0 * __import__("math").sin((i % 24 - 6) * __import__("math").pi / 12)) for i in range(240)],
            "load": [30.0 + 2.0 * __import__("math").sin(i * 2.0 * __import__("math").pi / 24) for i in range(240)],
            "tariff": [-0.05 if i % 24 < 5 else 0.12 for i in range(240)],
        }
        result = forecast_signals(
            self.timestamps,
            history,
            {"pv": "kW", "load": "kW", "tariff": "currency/kWh"},
            12,
            non_negative_signals=("pv", "load"),
        )
        self.assertEqual(set(result.forecasts), set(history))
        self.assertEqual(result.forecasts["tariff"].points[0].predicted, -0.05)
        self.assertTrue(all(point.lower_bound >= 0 for point in result.forecasts["pv"].points))
        self.assertEqual(len(result.input_history_sha256), 64)
        self.assertEqual(result.history_end_utc, self.timestamps[-1])

    def test_history_digest_changes_when_data_changes(self):
        first = forecast_signals(
            self.timestamps, {"load": [10.0] * 240}, {"load": "kW"}, 3
        )
        changed = [10.0] * 240
        changed[-1] = 11.0
        second = forecast_signals(
            self.timestamps, {"load": changed}, {"load": "kW"}, 3
        )
        self.assertNotEqual(first.input_history_sha256, second.input_history_sha256)

    def test_timezone_offsets_are_normalized_to_utc(self):
        local = [
            datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=8))) + timedelta(hours=i)
            for i in range(72)
        ]
        result = forecast_signals(local, {"load": [1.0] * 72}, {"load": "kW"}, 2)
        self.assertEqual(result.history_start_utc, datetime(2025, 12, 31, 16, tzinfo=timezone.utc))
        self.assertEqual(result.forecasts["load"].points[0].timestamp.tzinfo, timezone.utc)

    def test_rejects_gaps_naive_timestamps_and_misaligned_signals(self):
        broken = list(self.timestamps)
        broken[100] += timedelta(minutes=30)
        with self.assertRaisesRegex(ValueError, "contiguous hourly"):
            forecast_signals(broken, {"load": [1.0] * 240}, {"load": "kW"}, 1)
        naive = [stamp.replace(tzinfo=None) for stamp in self.timestamps]
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            forecast_signals(naive, {"load": [1.0] * 240}, {"load": "kW"}, 1)
        with self.assertRaisesRegex(ValueError, "one value"):
            forecast_signals(self.timestamps, {"load": [1.0] * 239}, {"load": "kW"}, 1)

    def test_rejects_invalid_values_units_horizon_and_signal_names(self):
        with self.assertRaisesRegex(ValueError, "finite"):
            forecast_signals(self.timestamps, {"load": [float("nan")] * 240}, {"load": "kW"}, 1)
        with self.assertRaisesRegex(ValueError, "exactly the same"):
            forecast_signals(self.timestamps, {"load": [1.0] * 240}, {"load": "kW", "pv": "kW"}, 1)
        with self.assertRaisesRegex(ValueError, "horizon"):
            forecast_signals(self.timestamps, {"load": [1.0] * 240}, {"load": "kW"}, 0)
        with self.assertRaisesRegex(ValueError, "at least 72"):
            forecast_signals(self.timestamps[:71], {"load": [1.0] * 71}, {"load": "kW"}, 1)

    def test_negative_prices_are_not_clipped(self):
        values = [-0.1 if i % 24 < 8 else 0.2 for i in range(240)]
        result = forecast_signals(
            self.timestamps, {"price": values}, {"price": "currency/kWh"}, 8,
            non_negative_signals=(),
        )
        self.assertLess(result.forecasts["price"].points[0].predicted, 0.0)

    def test_uncertainty_bounds_enclose_point_forecast(self):
        values = [10.0 + (i % 24) * 0.1 + (0.2 if i % 31 == 0 else 0.0) for i in range(240)]
        result = forecast_signals(
            self.timestamps, {"demand": values}, {"demand": "kW"}, 24
        )
        for point in result.forecasts["demand"].points:
            self.assertLessEqual(point.lower_bound, point.predicted)
            self.assertGreaterEqual(point.upper_bound, point.predicted)


if __name__ == "__main__":
    unittest.main()

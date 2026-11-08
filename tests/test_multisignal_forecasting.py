"""Tests for the shared multi-signal forecast engine."""
import unittest
from datetime import datetime, timedelta, timezone

from islandos_core.multisignal_forecasting import (
    SignalForecastRegistry,
    SignalForecastRequest,
    SignalObservation,
    rolling_origin_backtest,
)


class PersistencePlugin:
    model_id = "persistence"
    version = "1.0"

    def predict(self, history, target_timestamps):
        return [history[-1].value] * len(target_timestamps)


class TestMultiSignalForecasting(unittest.TestCase):
    def setUp(self):
        self.start = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def observations(self, signal="pv_power", unit="kW", count=48, cadence=3600):
        return tuple(
            SignalObservation(
                self.start + timedelta(seconds=i * cadence),
                signal,
                float(i % 17),
                unit,
            )
            for i in range(count)
        )

    def request(self, signal="pv_power", unit="kW", cadence=3600):
        history = self.observations(signal, unit, count=48, cadence=cadence)
        targets = tuple(
            self.start + timedelta(seconds=(48 + i) * cadence)
            for i in range(4)
        )
        return SignalForecastRequest(signal, unit, history, targets, cadence)

    def test_one_registry_supports_pv_wind_and_load_with_shared_contract(self):
        registry = SignalForecastRegistry()
        registry.register(PersistencePlugin())
        for signal, unit in (("pv_power", "kW"), ("wind_power", "kW"), ("essential_load", "kW")):
            result = registry.forecast("persistence", self.request(signal, unit))
            self.assertEqual(result.signal_id, signal)
            self.assertEqual(result.unit, unit)
            self.assertEqual(result.cadence_seconds, 3600)
            self.assertEqual(len(result.input_history_sha256), 64)
            self.assertEqual(len(result.points), 4)
            self.assertTrue(all(point.lower_bound is None and point.upper_bound is None for point in result.points))

    def test_supports_subhourly_and_daily_cadence(self):
        registry = SignalForecastRegistry()
        registry.register(PersistencePlugin())
        for cadence in (900, 86400):
            result = registry.forecast("persistence", self.request(cadence=cadence))
            self.assertEqual(result.cadence_seconds, cadence)
            self.assertEqual(len(result.points), 4)

    def test_calibrated_intervals_use_separate_past_residuals(self):
        registry = SignalForecastRegistry()
        registry.register(PersistencePlugin())
        residuals = [float(i) for i in range(-10, 10)] + [10.0]
        result = registry.forecast(
            "persistence", self.request(),
            calibration_residuals=residuals, interval_coverage=0.90,
        )
        self.assertEqual(result.calibration_sample_count, 21)
        self.assertEqual(result.interval_coverage, 0.90)
        self.assertEqual(result.interval_method, "split_conformal_absolute_residual_quantile")
        for point in result.points:
            self.assertGreaterEqual(point.lower_bound, 0.0)
            self.assertLessEqual(point.lower_bound, point.predicted_value)
            self.assertGreaterEqual(point.upper_bound, point.predicted_value)

    def test_interval_calibration_rejects_small_or_invalid_samples(self):
        registry = SignalForecastRegistry()
        registry.register(PersistencePlugin())
        with self.assertRaisesRegex(ValueError, "At least 20"):
            registry.forecast("persistence", self.request(), calibration_residuals=[1.0] * 19)
        with self.assertRaisesRegex(ValueError, "interval_coverage"):
            registry.forecast(
                "persistence", self.request(),
                calibration_residuals=[1.0] * 20, interval_coverage=1.0,
            )
        with self.assertRaisesRegex(ValueError, "finite"):
            registry.forecast(
                "persistence", self.request(),
                calibration_residuals=[1.0] * 19 + [float("nan")],
            )

    def test_rejects_bad_timestamps_units_gaps_and_cadence(self):
        history = self.observations(count=48)
        targets = (history[-1].timestamp + timedelta(hours=1),)
        with self.assertRaisesRegex(ValueError, "unit must"):
            SignalForecastRequest("pv_power", "", history, targets)
        with self.assertRaisesRegex(ValueError, "continuous at the declared cadence"):
            SignalForecastRequest(
                "pv_power", "kW", (history[0], history[2]), targets
            )
        with self.assertRaisesRegex(ValueError, "exactly one cadence"):
            SignalForecastRequest(
                "pv_power", "kW", history,
                (history[-1].timestamp + timedelta(minutes=30),),
            )
        with self.assertRaisesRegex(ValueError, "include a timezone"):
            SignalObservation(datetime(2026, 1, 1), "pv_power", 1, "kW")
        with self.assertRaisesRegex(ValueError, "non-negative"):
            SignalObservation(self.start, "pv_power", -1, "kW")

    def test_rolling_origin_backtest_compares_models_on_aligned_timestamps(self):
        series = self.observations(count=120)
        report = rolling_origin_backtest(
            series, PersistencePlugin(), initial_history=48,
            history_window=72, seasonal_lag_steps=24,
        )
        self.assertEqual(report["status"], "rolling_origin_backtest_completed")
        self.assertEqual(report["training"]["test_samples"], 72)
        self.assertTrue(report["training"]["only_prior_observations_passed_to_plugin"])
        self.assertEqual(report["metrics"]["plugin"]["samples"], 72)
        self.assertEqual(report["metrics"]["persistence_baseline"]["samples"], 72)
        self.assertEqual(report["metrics"]["seasonal_naive_baseline"]["samples"], 72)
        self.assertEqual(
            report["metrics"]["plugin_on_seasonal_comparable_window"]["samples"], 72
        )
        self.assertEqual(len(report["forecast_rows"]), 72)
        self.assertEqual(report["forecast_rows"][0]["history_observation_count"], 48)

    def test_backtest_rejects_gapped_or_mixed_signal_series(self):
        series = list(self.observations(count=30))
        series[10] = SignalObservation(
            series[10].timestamp + timedelta(minutes=5),
            series[10].signal_id, series[10].value, series[10].unit,
        )
        with self.assertRaisesRegex(ValueError, "continuous at one fixed cadence"):
            rolling_origin_backtest(series, PersistencePlugin(), initial_history=10)
        mixed = list(self.observations(count=30))
        mixed[15] = SignalObservation(
            mixed[15].timestamp, "wind_power", mixed[15].value, "kW"
        )
        with self.assertRaisesRegex(ValueError, "share signal_id and unit"):
            rolling_origin_backtest(mixed, PersistencePlugin(), initial_history=10)


if __name__ == "__main__":
    unittest.main()

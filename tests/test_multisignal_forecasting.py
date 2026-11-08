"""Tests for the shared multi-signal forecast engine."""
import unittest
from datetime import datetime, timedelta, timezone

from islandos_core.multisignal_forecasting import (
    CalibrationResidual,
    AutoregressiveRidgeSignalPlugin,
    SignalForecastRegistry,
    SignalForecastRequest,
    SignalObservation,
    evaluate_prediction_intervals,
    PersistenceSignalPlugin,
    SeasonalNaiveSignalPlugin,
    forecast_values_for_dispatch,
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





    def test_ridge_ml_plugin_forecasts_pv_wind_and_load_with_rolling_refit(self):
        plugin = AutoregressiveRidgeSignalPlugin(ridge_alpha=2.0)
        for signal, unit, scale in (
            ("pv_power", "kW", 30.0),
            ("wind_power", "kW", 12.0),
            ("essential_load", "kW", 20.0),
        ):
            series = tuple(
                SignalObservation(
                    self.start + timedelta(hours=i),
                    signal,
                    max(0.0, scale * (0.5 + 0.25 * __import__("math").sin(2 * __import__("math").pi * (i % 24) / 24) + 0.02 * (i % 7))),
                    unit,
                )
                for i in range(168)
            )
            report = rolling_origin_backtest(
                series, plugin, initial_history=96,
                history_window=168, seasonal_lag_steps=24,
            )
            self.assertEqual(report["model_id"], "autoregressive_ridge")
            self.assertEqual(report["metrics"]["plugin"]["samples"], 72)
            self.assertEqual(report["metrics"]["persistence_baseline"]["samples"], 72)
            self.assertTrue(all(
                row["plugin_forecast"] >= 0
                for row in report["forecast_rows"]
            ))

    def test_ridge_plugin_supports_subhourly_data_and_rejects_short_history(self):
        registry = SignalForecastRegistry()
        plugin = AutoregressiveRidgeSignalPlugin()
        registry.register(plugin)
        history = tuple(
            SignalObservation(
                self.start + timedelta(minutes=15 * i),
                "pv_power", 10.0 + 2.0 * __import__("math").sin(2 * __import__("math").pi * (i % 96) / 96),
                "kW",
            )
            for i in range(120)
        )
        targets = tuple(
            self.start + timedelta(minutes=15 * (120 + i)) for i in range(4)
        )
        request = SignalForecastRequest(
            "pv_power", "kW", history, targets, cadence_seconds=900
        )
        result = registry.forecast("autoregressive_ridge", request)
        self.assertEqual(len(result.points), 4)
        self.assertTrue(all(point.predicted_value >= 0 for point in result.points))
        short = history[:50]
        short_request = SignalForecastRequest(
            "pv_power", "kW", short,
            (short[-1].timestamp + timedelta(minutes=15),),
            cadence_seconds=900,
        )
        with self.assertRaisesRegex(ValueError, "needs at least"):
            registry.forecast("autoregressive_ridge", short_request)

    def test_builtin_baselines_run_through_the_same_registry(self):
        registry = SignalForecastRegistry()
        registry.register(PersistenceSignalPlugin())
        registry.register(SeasonalNaiveSignalPlugin(season_length_steps=24))
        request = self.request()
        persistence = registry.forecast("persistence", request)
        seasonal = registry.forecast("seasonal_naive", request)
        self.assertEqual(
            [point.predicted_value for point in persistence.points],
            [request.history[-1].value] * 4,
        )
        expected_profile = [item.value for item in request.history[-24:]]
        self.assertEqual(
            [point.predicted_value for point in seasonal.points],
            expected_profile[:4],
        )
        with self.assertRaisesRegex(ValueError, "positive integer"):
            SeasonalNaiveSignalPlugin(season_length_steps=0)

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
        request = self.request()
        residuals = tuple(
            CalibrationResidual(
                timestamp=request.history[-21 + i].timestamp,
                residual=float(i - 10),
            )
            for i in range(21)
        )
        result = registry.forecast(
            "persistence", request,
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
            registry.forecast("persistence", self.request(), calibration_residuals=[
                CalibrationResidual(self.start + timedelta(hours=i), 1.0) for i in range(19)
            ])
        with self.assertRaisesRegex(ValueError, "interval_coverage"):
            registry.forecast(
                "persistence", self.request(),
                calibration_residuals=[
                    CalibrationResidual(self.start + timedelta(hours=i), 1.0) for i in range(20)
                ], interval_coverage=1.0,
            )
        with self.assertRaisesRegex(ValueError, "finite"):
            registry.forecast(
                "persistence", self.request(),
                calibration_residuals=[
                    CalibrationResidual(self.start + timedelta(hours=i), float("nan") if i == 19 else 1.0)
                    for i in range(20)
                ],
            )



    def test_interval_calibration_rejects_future_or_unordered_residuals(self):
        registry = SignalForecastRegistry()
        registry.register(PersistencePlugin())
        request = self.request()
        future = tuple(
            CalibrationResidual(
                request.target_timestamps[0] + timedelta(hours=i), 0.5
            )
            for i in range(20)
        )
        with self.assertRaisesRegex(ValueError, "before the forecast window"):
            registry.forecast("persistence", request, calibration_residuals=future)
        unordered = tuple(
            CalibrationResidual(
                request.history[-1 - i].timestamp, 0.5
            )
            for i in range(20)
        )
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            registry.forecast("persistence", request, calibration_residuals=unordered)

    def test_rejects_bad_timestamps_units_gaps_and_cadence(self):
        history = self.observations(count=48)
        targets = (history[-1].timestamp + timedelta(hours=1),)
        with self.assertRaisesRegex(ValueError, "unit must"):
            SignalForecastRequest("pv_power", "", history, targets)
        with self.assertRaisesRegex(ValueError, "strictly ordered at the declared cadence"):
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



    def test_dispatch_adapter_checks_signal_unit_timestamps_and_interval_bounds(self):
        registry = SignalForecastRegistry()
        registry.register(PersistencePlugin())
        request = self.request()
        residuals = tuple(
            CalibrationResidual(request.history[-21 + i].timestamp, float(i - 10))
            for i in range(21)
        )
        result = registry.forecast(
            "persistence", request, calibration_residuals=residuals
        )
        points = forecast_values_for_dispatch(
            result, expected_signal_id="pv_power", expected_unit="kW",
            target_timestamps=request.target_timestamps,
        )
        upper = forecast_values_for_dispatch(
            result, expected_signal_id="pv_power", expected_unit="kW",
            target_timestamps=request.target_timestamps, bound="upper",
        )
        self.assertEqual(len(points), 4)
        self.assertTrue(all(u >= p for p, u in zip(points, upper)))
        with self.assertRaisesRegex(ValueError, "signal_id"):
            forecast_values_for_dispatch(
                result, expected_signal_id="wind_power", expected_unit="kW",
                target_timestamps=request.target_timestamps,
            )
        with self.assertRaisesRegex(ValueError, "unit"):
            forecast_values_for_dispatch(
                result, expected_signal_id="pv_power", expected_unit="MW",
                target_timestamps=request.target_timestamps,
            )
        with self.assertRaisesRegex(ValueError, "timestamps"):
            forecast_values_for_dispatch(
                result, expected_signal_id="pv_power", expected_unit="kW",
                target_timestamps=request.target_timestamps[:-1],
            )
        point_only = registry.forecast("persistence", request)
        with self.assertRaisesRegex(ValueError, "calibrated intervals"):
            forecast_values_for_dispatch(
                point_only, expected_signal_id="pv_power", expected_unit="kW",
                target_timestamps=request.target_timestamps, bound="upper",
            )

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



    def test_registry_fails_closed_on_bad_plugin_outputs_and_mutated_identity(self):
        class BadPlugin:
            model_id = "bad"
            version = "1.0"

            def __init__(self, values):
                self.values = values

            def predict(self, history, target_timestamps):
                return self.values

        for values in ([1.0], [1.0, -1.0, 2.0, 3.0], [1.0, float("nan"), 2.0, 3.0]):
            registry = SignalForecastRegistry()
            registry.register(BadPlugin(values))
            with self.assertRaises(ValueError):
                registry.forecast("bad", self.request())

        class GeneratorMutatingPlugin:
            model_id = "mutating"
            version = "1.0"

            def predict(self, history, target_timestamps):
                def generate():
                    yield 1.0
                    self.version = "2.0"
                    yield 2.0
                    yield 3.0
                    yield 4.0
                return generate()

        registry = SignalForecastRegistry()
        registry.register(GeneratorMutatingPlugin())
        with self.assertRaisesRegex(ValueError, "identity changed during"):
            registry.forecast("mutating", self.request())

    def test_interval_coverage_metrics_report_misses_and_width(self):
        metrics = evaluate_prediction_intervals(
            actual=[1.0, 2.0, 5.0, 8.0],
            lower=[0.0, 1.0, 2.0, 3.0],
            upper=[2.0, 3.0, 4.0, 7.0],
            nominal_coverage=0.90,
        )
        self.assertEqual(metrics["samples"], 4)
        self.assertEqual(metrics["empirical_coverage"], 0.5)
        self.assertEqual(metrics["lower_bound_exceedance_rate"], 0.0)
        self.assertEqual(metrics["upper_bound_exceedance_rate"], 0.5)
        self.assertEqual(metrics["mean_interval_width"], 2.5)
        self.assertAlmostEqual(metrics["coverage_gap"], -0.4)
        with self.assertRaisesRegex(ValueError, "equally sized"):
            evaluate_prediction_intervals([1.0], [0.0, 0.5], [2.0])
        with self.assertRaisesRegex(ValueError, "lower interval bound"):
            evaluate_prediction_intervals([1.0], [2.0], [1.0])

    def test_rolling_backtest_earlier_predictions_ignore_later_actual_changes(self):
        original = list(self.observations(count=120))
        altered = original.copy()
        for index in range(80, len(altered)):
            item = altered[index]
            altered[index] = SignalObservation(
                item.timestamp, item.signal_id, item.value + 1000.0, item.unit
            )
        first = rolling_origin_backtest(
            original, PersistencePlugin(), initial_history=48, history_window=48
        )
        second = rolling_origin_backtest(
            altered, PersistencePlugin(), initial_history=48, history_window=48
        )
        self.assertEqual(
            first["forecast_rows"][10]["plugin_forecast"],
            second["forecast_rows"][10]["plugin_forecast"],
        )
        self.assertNotEqual(
            first["evaluation_series_sha256"], second["evaluation_series_sha256"]
        )

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

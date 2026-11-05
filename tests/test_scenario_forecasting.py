"""Tests for transparent hourly microgrid baseline forecasting."""
import unittest

from islandos_core.scenario_forecasting import (
    evaluate_forecast, forecast_microgrid_signals, rolling_origin_evaluate,
    seasonal_naive_forecast,
)


class TestScenarioForecasting(unittest.TestCase):
    def test_seasonal_naive_repeats_latest_daily_profile(self):
        history = list(range(48))
        self.assertEqual(seasonal_naive_forecast(history, 27), list(range(24, 48)) + [24, 25, 26])

    def test_forecast_is_independent_of_future_observations(self):
        history = [float(i % 24) for i in range(72)]
        first = seasonal_naive_forecast(history, 24)
        changed_future = history + [999.0] * 24
        second = seasonal_naive_forecast(changed_future[:72], 24)
        self.assertEqual(first, second)

    def test_metrics_and_zero_denominator(self):
        metrics = evaluate_forecast([0, 2, 4], [1, 1, 6])
        self.assertEqual(metrics.samples, 3)
        self.assertAlmostEqual(metrics.mae, 4 / 3)
        self.assertIsNotNone(metrics.wape_percent)
        self.assertIsNone(evaluate_forecast([0, 0], [0, 0]).wape_percent)

    def test_rolling_origin_uses_chronological_folds(self):
        values = [float(i % 24) for i in range(100)]
        metrics = rolling_origin_evaluate(values, initial_history=48, horizon=24)
        self.assertEqual(metrics.samples, 52)
        self.assertAlmostEqual(metrics.mae, 0.0)

    def test_signal_forecasts_and_validation(self):
        result = forecast_microgrid_signals({"pv": [0, 1, 2], "load": [3, 4, 5]}, 4)
        self.assertEqual(result["pv"], [0, 1, 2, 0])
        with self.assertRaises(ValueError):
            seasonal_naive_forecast([1, -1], 2)
        with self.assertRaises(ValueError):
            seasonal_naive_forecast([1, 2], 0)


if __name__ == "__main__":
    unittest.main()

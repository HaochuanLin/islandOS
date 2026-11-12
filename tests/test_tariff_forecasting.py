"""Tests for transparent electricity-tariff forecasting baselines."""
import unittest
from datetime import datetime, timedelta, timezone

from islandos_core.tariff_forecasting import (
    TariffObservation,
    evaluate_tariff_forecast,
    forecast_tariff_prices,
)


class TariffForecastingTests(unittest.TestCase):
    def make_history(self, values):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        return tuple(
            TariffObservation(start + timedelta(hours=i), value)
            for i, value in enumerate(values)
        )

    def test_repeats_last_daily_profile_and_aligns_future_timestamps(self):
        history = self.make_history(list(range(24)) + [100 + i for i in range(24)])
        result = forecast_tariff_prices(history, 26)
        self.assertEqual(result.method, "seasonal_naive_24h")
        self.assertEqual(
            [point.predicted_price_per_kwh for point in result.points[:4]],
            [100.0, 101.0, 102.0, 103.0],
        )
        self.assertEqual(
            result.points[0].timestamp,
            history[-1].timestamp + timedelta(hours=1),
        )
        self.assertEqual(
            result.points[24].timestamp,
            history[-1].timestamp + timedelta(hours=25),
        )

    def test_supports_negative_market_prices_without_clipping(self):
        history = self.make_history([0.12, -0.04, 0.08])
        result = forecast_tariff_prices(history, 4, season_length=3)
        self.assertEqual(
            [point.predicted_price_per_kwh for point in result.points],
            [0.12, -0.04, 0.08, 0.12],
        )

    def test_history_digest_is_reproducible_and_sensitive_to_input(self):
        history = self.make_history([0.1, 0.2, 0.3])
        first = forecast_tariff_prices(history, 2)
        second = forecast_tariff_prices(history, 2)
        changed = forecast_tariff_prices(self.make_history([0.1, 0.2, 0.4]), 2)
        self.assertEqual(first.input_history_sha256, second.input_history_sha256)
        self.assertNotEqual(first.input_history_sha256, changed.input_history_sha256)

    def test_rejects_naive_or_non_hourly_timestamps(self):
        with self.assertRaisesRegex(ValueError, "timezone"):
            TariffObservation(datetime(2026, 1, 1), 0.1)
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        irregular = [
            TariffObservation(start, 0.1),
            TariffObservation(start + timedelta(minutes=30), 0.2),
        ]
        with self.assertRaisesRegex(ValueError, "hourly"):
            forecast_tariff_prices(irregular, 1)

    def test_rejects_invalid_values_and_forecast_horizon(self):
        with self.assertRaisesRegex(ValueError, "numeric"):
            TariffObservation(datetime(2026, 1, 1, tzinfo=timezone.utc), True)
        with self.assertRaisesRegex(ValueError, "finite"):
            TariffObservation(datetime(2026, 1, 1, tzinfo=timezone.utc), float("nan"))
        with self.assertRaisesRegex(ValueError, "horizon"):
            forecast_tariff_prices(self.make_history([0.1]), 0)
        with self.assertRaisesRegex(ValueError, "season_length"):
            forecast_tariff_prices(self.make_history([0.1]), 1, season_length=True)

    def test_evaluates_negative_prices_with_mae_rmse_and_bias(self):
        metrics = evaluate_tariff_forecast(
            actual=[-0.10, 0.20, 0.30],
            predicted=[-0.05, 0.10, 0.40],
        )
        self.assertEqual(metrics.samples, 3)
        self.assertAlmostEqual(metrics.mae, 0.25 / 3)
        self.assertAlmostEqual(metrics.rmse, (0.0225 / 3) ** 0.5)
        self.assertAlmostEqual(metrics.bias_predicted_minus_actual, 0.05 / 3)

    def test_rejects_mismatched_or_invalid_metric_inputs(self):
        with self.assertRaisesRegex(ValueError, "equal lengths"):
            evaluate_tariff_forecast([0.1, 0.2], [0.1])
        with self.assertRaisesRegex(ValueError, "numeric"):
            evaluate_tariff_forecast([0.1], [True])
        with self.assertRaisesRegex(ValueError, "finite"):
            evaluate_tariff_forecast([0.1], [float("inf")])


if __name__ == "__main__":
    unittest.main()

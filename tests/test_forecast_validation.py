"""Tests for rolling-origin evaluation and site-local calendar features."""
import unittest
from datetime import datetime, timedelta, timezone

from islandos_core.forecast_validation import (
    evaluate_expanding_window,
    expanding_window_slices,
    site_local_calendar_features,
)


class TestForecastValidation(unittest.TestCase):
    def test_expanding_folds_are_chronological_and_grow(self):
        folds = expanding_window_slices(240, min_train_size=72, validation_size=24, folds=4)
        self.assertEqual(len(folds), 4)
        train_lengths = [train.stop for train, _ in folds]
        self.assertEqual(train_lengths, sorted(train_lengths))
        for train, validation in folds:
            self.assertEqual(train.stop, validation.start)
            self.assertEqual(validation.stop - validation.start, 24)

    def test_requires_enough_history_and_valid_fold_counts(self):
        with self.assertRaisesRegex(ValueError, "need at least"):
            expanding_window_slices(100, min_train_size=72, validation_size=24, folds=2)
        with self.assertRaisesRegex(ValueError, "positive integer"):
            expanding_window_slices(240, folds=0)

    def test_site_local_hour_features_use_iana_timezone(self):
        utc = datetime(2026, 1, 1, 0, tzinfo=timezone.utc)
        los_angeles = site_local_calendar_features(utc, "America/Los_Angeles")
        beijing = site_local_calendar_features(utc, "Asia/Shanghai")
        self.assertNotEqual(los_angeles[:2], beijing[:2])
        self.assertEqual(len(los_angeles), 4)

    def test_site_local_timezone_rejects_unknown_zone_and_naive_time(self):
        with self.assertRaisesRegex(ValueError, "Unknown IANA"):
            site_local_calendar_features(datetime.now(timezone.utc), "Mars/Olympus")
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            site_local_calendar_features(datetime(2026, 1, 1), "UTC")

    def test_backtest_uses_same_future_folds_and_hides_validation_actuals(self):
        stamps = [datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(hours=i) for i in range(240)]
        values = [float(i) for i in range(240)]
        def persistence(train, future_stamps):
            return [train[-1]] * len(future_stamps)
        def perfect_for_test(train, future_stamps):
            # The callback has no access to validation actual values.
            return [train[-1] + 1.0] * len(future_stamps)
        result = evaluate_expanding_window(
            stamps, values,
            {"persistence": persistence, "step": perfect_for_test},
            min_train_size=72, validation_size=24, folds=4,
        )
        self.assertEqual(len(result["persistence"].folds), 4)
        self.assertLess(result["step"].mean_mae, result["persistence"].mean_mae)

    def test_rejects_non_finite_predictions(self):
        stamps = [datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(hours=i) for i in range(120)]
        with self.assertRaisesRegex(ValueError, "non-finite"):
            evaluate_expanding_window(
                stamps, [1.0] * 120, {"bad": lambda train, future: [float("nan")] * len(future)},
                min_train_size=72, validation_size=12, folds=4,
            )


if __name__ == "__main__":
    unittest.main()

"""Tests for the model-agnostic IslandOS prediction engine."""
import unittest
from datetime import datetime, timedelta, timezone

from islandos_core.prediction_engine import (
    ForecastRequest,
    LinearTrendCandidate,
    PredictionEngine,
    RecentMeanCandidate,
    SeasonalNaiveCandidate,
    SignalObservation,
)


class InvalidCandidate:
    model_id = "invalid"
    version = "1"

    def predict(self, history, horizon, *, season_length):
        return [float("nan")] * horizon


def make_request(values, *, non_negative=True, signal_id="site_load", unit="kW"):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    history = tuple(
        SignalObservation(start + timedelta(hours=index), value)
        for index, value in enumerate(values)
    )
    targets = tuple(
        start + timedelta(hours=len(values) + index)
        for index in range(4)
    )
    return ForecastRequest(signal_id, unit, history, targets, non_negative=non_negative)


class TestPredictionEngine(unittest.TestCase):
    def test_builtin_candidates_registered(self):
        engine = PredictionEngine()
        self.assertEqual(
            {name for name, _ in engine.available_candidates()},
            {"seasonal_naive", "recent_mean", "linear_trend"},
        )

    def test_chronological_candidate_selection_and_forecast(self):
        values = [float(index % 24) for index in range(96)]
        engine = PredictionEngine()
        request = make_request(values)
        result = engine.forecast(request, initial_history=48, backtest_horizon=24)
        self.assertEqual(result.model_id, "seasonal_naive")
        self.assertEqual(result.backtest.mae, 0.0)
        self.assertEqual(result.backtest.samples, 48)
        self.assertEqual(len(result.points), 4)
        self.assertEqual(result.points[0].predicted_value, 0.0)
        self.assertEqual(result.points[0].lower_bound, 0.0)
        self.assertEqual(result.points[0].upper_bound, 0.0)
        self.assertEqual(result.interval_calibration_samples, 48)
        self.assertEqual(len(result.input_history_sha256), 64)

    def test_negative_tariff_values_are_supported_when_declared(self):
        values = [-0.08, 0.12, 0.21, -0.03] * 24
        request = make_request(values, non_negative=False, signal_id="tariff", unit="currency/kWh")
        result = PredictionEngine().forecast(request, initial_history=48, season_length=4)
        self.assertEqual(result.signal_id, "tariff")
        self.assertTrue(any(point.predicted_value < 0 for point in result.points))

    def test_invalid_candidate_is_excluded_not_silently_repaired(self):
        engine = PredictionEngine()
        engine.register(InvalidCandidate())
        ranking = engine.evaluate_candidates(
            [float(index % 24) for index in range(72)],
            initial_history=48, horizon=12,
        )
        self.assertNotIn("invalid", {item.model_id for item in ranking})
        self.assertEqual(ranking[0].model_id, "seasonal_naive")

    def test_duplicate_candidate_rejected(self):
        engine = PredictionEngine(include_builtin_candidates=False)
        engine.register(SeasonalNaiveCandidate())
        with self.assertRaisesRegex(ValueError, "already registered"):
            engine.register(SeasonalNaiveCandidate())

    def test_explicit_candidate_selection(self):
        values = [float(index % 24) for index in range(96)]
        result = PredictionEngine().forecast(
            make_request(values), model_id="recent_mean", initial_history=48,
        )
        self.assertEqual(result.model_id, "recent_mean")

    def test_irregular_history_rejected(self):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        history = (
            SignalObservation(start, 1.0),
            SignalObservation(start + timedelta(hours=1), 2.0),
            SignalObservation(start + timedelta(hours=3), 3.0),
        )
        with self.assertRaisesRegex(ValueError, "regular fixed interval"):
            ForecastRequest(
                "load", "kW", history,
                (start + timedelta(hours=4),),
            )

    def test_negative_values_rejected_for_nonnegative_signal(self):
        with self.assertRaisesRegex(ValueError, "must be non-negative"):
            make_request([1.0, -1.0, 2.0])

    def test_model_output_validation_and_linear_trend(self):
        candidate = LinearTrendCandidate()
        self.assertEqual(candidate.predict([1.0, 2.0, 3.0], 2, season_length=3), [4.0, 5.0])
        with self.assertRaisesRegex(ValueError, "cannot be negative"):
            PredictionEngine().evaluate_candidates(
                [1.0, 0.0, 0.0, 0.0, 0.0],
                initial_history=2, horizon=1, season_length=2,
            )

    def test_recent_mean_is_constant(self):
        self.assertEqual(
            RecentMeanCandidate().predict([1.0, 3.0, 5.0], 3, season_length=3),
            [3.0, 3.0, 3.0],
        )


if __name__ == "__main__":
    unittest.main()

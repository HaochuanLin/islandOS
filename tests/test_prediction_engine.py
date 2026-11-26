"""Tests for the model-agnostic IslandOS prediction engine."""
import math
import unittest
from datetime import datetime, timedelta, timezone

from islandos_core.prediction_engine import (
    ForecastRequest,
    LinearTrendCandidate,
    PredictionEngine,
    PersistenceCandidate,
    RecentMeanCandidate,
    RidgeAutoregressiveCandidate,
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


class MutatingCandidate:
    model_id = "mutating"
    version = "1"

    def predict(self, history, horizon, *, season_length):
        self.version = "2"
        return [float(history[-1])] * horizon


class TestPredictionEngine(unittest.TestCase):
    def test_builtin_candidates_registered(self):
        engine = PredictionEngine()
        self.assertEqual(
            {name for name, _ in engine.available_candidates()},
            {
                "persistence", "seasonal_naive", "recent_mean", "linear_trend",
            },
        )

    def test_persistence_baseline_repeats_last_observation(self):
        self.assertEqual(
            PersistenceCandidate().predict([1.0, 2.5, 3.0], 4, season_length=24),
            [3.0, 3.0, 3.0, 3.0],
        )

    def test_predict_candidate_returns_only_history_based_target_forecast(self):
        request = make_request([1.0, 2.0, 3.0, 4.0])
        predictions = PredictionEngine().predict_candidate(request, "persistence")

        self.assertEqual(predictions, (4.0, 4.0, 4.0, 4.0))
        self.assertIsInstance(predictions, tuple)

    def test_predict_candidate_rejects_unknown_model_and_invalid_season_length(self):
        engine = PredictionEngine()
        request = make_request([1.0, 2.0, 3.0])

        with self.assertRaisesRegex(KeyError, "unknown forecast candidate"):
            engine.predict_candidate(request, "missing")

        with self.assertRaisesRegex(ValueError, "season_length must be a positive integer"):
            engine.predict_candidate(request, "persistence", season_length=True)

    def test_rolling_metrics_include_fold_level_signed_bias(self):
        engine = PredictionEngine(include_builtin_candidates=False)
        engine.register(PersistenceCandidate())
        score = engine.evaluate_candidates(
            [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            initial_history=2,
            horizon=2,
            season_length=24,
        )[0]
        self.assertEqual(score.folds, 2)
        self.assertEqual(score.samples, 4)
        self.assertAlmostEqual(score.mae, 1.5)
        self.assertAlmostEqual(score.rmse, (2.5) ** 0.5)
        self.assertAlmostEqual(score.bias_predicted_minus_actual, -1.5)
        self.assertEqual(len(score.fold_metrics), 2)
        self.assertEqual([fold.train_samples for fold in score.fold_metrics], [2, 4])
        self.assertEqual([fold.samples for fold in score.fold_metrics], [2, 2])
        self.assertTrue(all(fold.bias_predicted_minus_actual < 0 for fold in score.fold_metrics))

    def test_replay_excludes_incomplete_final_horizon_block(self):
        engine = PredictionEngine(include_builtin_candidates=False)
        engine.register(PersistenceCandidate())
        score = engine.evaluate_candidates(
            [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0],
            initial_history=2,
            horizon=2,
            season_length=24,
        )[0]
        self.assertEqual(score.folds, 2)
        self.assertEqual(score.samples, 4)
        self.assertEqual([fold.samples for fold in score.fold_metrics], [2, 2])

    def test_replay_rejects_non_integer_initial_history(self):
        engine = PredictionEngine()
        for invalid in (True, 48.0, "48"):
            with self.assertRaisesRegex(ValueError, "initial_history must be an integer"):
                engine.evaluate_candidates(
                    [float(index) for index in range(96)],
                    initial_history=invalid,
                    horizon=24,
                )

    def test_replay_requires_one_complete_horizon_block(self):
        engine = PredictionEngine()
        with self.assertRaisesRegex(ValueError, "one complete 24-hour validation block"):
            engine.evaluate_candidates(
                [float(index) for index in range(60)],
                initial_history=48,
                horizon=24,
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

    def test_explicit_candidate_must_pass_signal_backtest(self):
        values = [float(index % 24) for index in range(96)]
        engine = PredictionEngine()
        engine.register(InvalidCandidate())
        with self.assertRaisesRegex(ValueError, "must be finite"):
            engine.forecast(
                make_request(values), model_id="invalid", initial_history=48,
            )

    def test_interval_reports_empirical_non_independent_error_band(self):
        values = [float(index % 24) for index in range(96)]
        result = PredictionEngine().forecast(
            make_request(values), initial_history=48, backtest_horizon=24,
            confidence_level=0.90,
        )
        self.assertIn("not independently calibrated", result.interval_method)
        self.assertTrue(any("reuse the same rolling-origin replay" in item for item in result.limitations))

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
        values = [1.0, 0.0, 0.0, 0.0, 0.0]
        request = make_request(values)
        with self.assertRaisesRegex(ValueError, "cannot be negative"):
            PredictionEngine().forecast(
                request, model_id="linear_trend", initial_history=2,
                backtest_horizon=1, season_length=2,
            )

    def test_candidate_identity_cannot_change_after_registration(self):
        engine = PredictionEngine()
        engine.register(MutatingCandidate())
        with self.assertRaisesRegex(ValueError, "identity changed"):
            engine.forecast(
                make_request([float(index % 24) for index in range(72)]),
                model_id="mutating", initial_history=48,
            )

    def test_ridge_candidate_is_opt_in_and_does_not_change_default_registry(self):
        default_ids = {model_id for model_id, _ in PredictionEngine().available_candidates()}
        enabled_ids = {
            model_id
            for model_id, _ in PredictionEngine(
                include_ridge_candidate=True,
            ).available_candidates()
        }

        self.assertEqual(
            default_ids,
            {"persistence", "seasonal_naive", "recent_mean", "linear_trend"},
        )
        self.assertIn("ridge_autoregressive_lag_only", enabled_ids)
        self.assertEqual(
            enabled_ids,
            default_ids | {"ridge_autoregressive_lag_only"},
        )

    def test_ridge_candidate_is_deterministic_and_records_alpha_in_version(self):
        values = [
            20.0
            + 3.0 * math.sin(2.0 * math.pi * index / 24.0)
            + 0.4 * math.sin(2.0 * math.pi * index / 168.0)
            for index in range(120)
        ]
        candidate = RidgeAutoregressiveCandidate(ridge_alpha=2.5)
        first = candidate.predict(values, 12, season_length=24)
        second = candidate.predict(values, 12, season_length=24)

        self.assertEqual(first, second)
        self.assertEqual(len(first), 12)
        self.assertTrue(all(math.isfinite(value) for value in first))
        self.assertIn("alpha2.5", candidate.version)

    def test_ridge_candidate_version_distinguishes_close_alpha_values(self):
        first_alpha = 1.0000000000001
        second_alpha = 1.0000000000002
        first = RidgeAutoregressiveCandidate(ridge_alpha=first_alpha)
        second = RidgeAutoregressiveCandidate(ridge_alpha=second_alpha)

        self.assertNotEqual(first.ridge_alpha, second.ridge_alpha)
        self.assertNotEqual(first.version, second.version)
        self.assertIn(repr(first_alpha), first.version)
        self.assertIn(repr(second_alpha), second.version)

    def test_ridge_candidate_rejects_invalid_alpha_and_short_training_history(self):
        with self.assertRaisesRegex(ValueError, "ridge_alpha"):
            RidgeAutoregressiveCandidate(ridge_alpha=0)
        with self.assertRaisesRegex(ValueError, "at least 32"):
            RidgeAutoregressiveCandidate().predict(
                [1.0] * 31, 1, season_length=24,
            )

    def test_ridge_candidate_preserves_negative_tariff_forecasts(self):
        values = [-0.05 + (index % 24) * 0.0005 for index in range(96)]
        request = make_request(
            values, non_negative=False, signal_id="tariff", unit="EUR/kWh",
        )
        predictions = PredictionEngine(include_ridge_candidate=True).predict_candidate(
            request, "ridge_autoregressive_lag_only", season_length=24,
        )
        self.assertTrue(any(value < 0 for value in predictions))

    def test_ridge_candidate_refits_on_each_expanding_training_fold(self):
        class RecordingRidge(RidgeAutoregressiveCandidate):
            def __init__(self):
                super().__init__()
                self.training_lengths = []

            def predict(self, history, horizon, *, season_length):
                self.training_lengths.append(len(history))
                return super().predict(history, horizon, season_length=season_length)

        candidate = RecordingRidge()
        engine = PredictionEngine(include_builtin_candidates=False)
        engine.register(candidate)
        values = [
            25.0 + 2.0 * math.sin(2.0 * math.pi * index / 24.0)
            for index in range(120)
        ]

        scores = engine.evaluate_candidates(
            values, initial_history=48, horizon=24, season_length=24,
        )

        self.assertEqual(candidate.training_lengths, [48, 72, 96])
        self.assertEqual(scores[0].model_id, "ridge_autoregressive_lag_only")
        self.assertEqual(scores[0].folds, 3)
        self.assertEqual(
            [fold.train_samples for fold in scores[0].fold_metrics],
            [48, 72, 96],
        )

        forecast = engine.forecast(
            make_request(values),
            model_id="ridge_autoregressive_lag_only",
            initial_history=48,
            backtest_horizon=24,
        )
        self.assertEqual(candidate.training_lengths[-1], len(values))
        self.assertEqual(len(forecast.points), 4)

    def test_recent_mean_is_constant(self):
        self.assertEqual(
            RecentMeanCandidate().predict([1.0, 3.0, 5.0], 3, season_length=3),
            [3.0, 3.0, 3.0],
        )


if __name__ == "__main__":
    unittest.main()



def test_rolling_origin_reports_multiple_chronological_folds():
    engine = PredictionEngine()
    history = [float(index % 24) for index in range(120)]
    ranking = engine.evaluate_candidates(
        history, initial_history=48, horizon=24, season_length=24,
    )
    assert ranking
    assert all(item.folds == 3 for item in ranking)
    assert all(item.samples == 72 for item in ranking)
    assert list(ranking) == sorted(
        ranking, key=lambda item: (item.mae, item.rmse, item.model_id)
    )

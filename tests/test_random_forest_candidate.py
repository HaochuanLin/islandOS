from datetime import datetime, timedelta, timezone

import pytest

from islandos_core.prediction_engine import (
    ForecastRequest,
    PredictionEngine,
    SignalObservation,
)
from islandos_core.random_forest_candidate import RandomForestCandidate


def make_history(size=240):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    values = [
        12.0
        + 3.0 * (index % 24 in range(17, 22))
        + 1.5 * (index % 24 in range(7, 10))
        + 0.5 * ((index // 24) % 7)
        for index in range(size)
    ]
    return values, start


def test_random_forest_candidate_is_deterministic_and_returns_requested_horizon():
    pytest.importorskip("sklearn")
    values, _ = make_history()
    candidate = RandomForestCandidate(n_estimators=16, random_state=7)
    first = candidate.predict(values, 24, season_length=24)
    second = candidate.predict(values, 24, season_length=24)

    assert len(first) == 24
    assert first == second
    assert all(value >= 0 for value in first)


def test_random_forest_can_be_evaluated_by_existing_chronological_engine():
    pytest.importorskip("sklearn")
    values, start = make_history()
    history = tuple(
        SignalObservation(start + timedelta(hours=index), value)
        for index, value in enumerate(values)
    )
    targets = tuple(
        start + timedelta(hours=len(values) + index)
        for index in range(24)
    )
    engine = PredictionEngine()
    engine.register(RandomForestCandidate(n_estimators=16, random_state=7))

    result = engine.forecast(
        ForecastRequest("site_load", "kW", history, targets),
        model_id="random_forest_lagged",
        initial_history=120,
        backtest_horizon=24,
        season_length=24,
    )

    assert result.model_id == "random_forest_lagged"
    assert result.backtest.samples == len(values) - 120
    assert len(result.points) == 24
    assert result.input_history_sha256
    assert all(point.lower_bound <= point.predicted_value <= point.upper_bound for point in result.points)


def test_random_forest_rejects_insufficient_history_and_bad_parameters():
    with pytest.raises(ValueError, match="requires at least"):
        RandomForestCandidate().predict([1.0] * 20, 3, season_length=24)
    with pytest.raises(ValueError, match="positive"):
        RandomForestCandidate(n_estimators=0)

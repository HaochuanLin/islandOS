"""Optional Random Forest candidate for the model-agnostic IslandOS engine.

This candidate is deliberately opt-in. It trains only on the history supplied
to each rolling-origin fold, uses lag/seasonal features, and recursively
forecasts the requested horizon. It does not load a pretrained SIC model or
claim the SIC report's UK household metrics.
"""
from __future__ import annotations

import math
from numbers import Real
from typing import Sequence


class RandomForestCandidate:
    """A deterministic, lag-feature Random Forest for regular interval signals.

    The default 100 trees mirrors the model size described in the reference
    report. Time-of-day/week are represented by interval-index cycles because
    the current ForecastCandidate protocol does not pass calendar timestamps.
    For non-hourly data, season_length must match the intended seasonal period.
    """

    model_id = "random_forest_lagged"
    version = "1.0.0"

    def __init__(
        self,
        *,
        n_estimators: int = 100,
        max_depth: int | None = 12,
        min_samples_leaf: int = 2,
        random_state: int = 42,
    ) -> None:
        for name, value in (
            ("n_estimators", n_estimators),
            ("min_samples_leaf", min_samples_leaf),
            ("random_state", random_state),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{name} must be an integer")
        if n_estimators < 1 or min_samples_leaf < 1:
            raise ValueError("n_estimators and min_samples_leaf must be positive")
        if max_depth is not None and (
            isinstance(max_depth, bool) or not isinstance(max_depth, int) or max_depth < 1
        ):
            raise ValueError("max_depth must be a positive integer or None")
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.min_samples_leaf = min_samples_leaf
        self.random_state = random_state

    @staticmethod
    def _features(history: Sequence[float], target_index: int, season_length: int) -> list[float]:
        lags = (1, 2, 3, season_length, 2 * season_length)
        row = [float(history[target_index - lag]) for lag in lags]
        seasonal_window = history[max(0, target_index - season_length):target_index]
        row.append(sum(float(value) for value in seasonal_window) / len(seasonal_window))
        phase = target_index % season_length
        weekly_period = 7 * season_length
        weekly_phase = target_index % weekly_period
        row.extend((
            math.sin(2.0 * math.pi * phase / season_length),
            math.cos(2.0 * math.pi * phase / season_length),
            math.sin(2.0 * math.pi * weekly_phase / weekly_period),
            math.cos(2.0 * math.pi * weekly_phase / weekly_period),
        ))
        return row

    def predict(
        self,
        history: Sequence[float],
        horizon: int,
        *,
        season_length: int,
    ) -> list[float]:
        if isinstance(horizon, bool) or not isinstance(horizon, int) or horizon < 1:
            raise ValueError("horizon must be a positive integer")
        if isinstance(season_length, bool) or not isinstance(season_length, int) or season_length < 1:
            raise ValueError("season_length must be a positive integer")
        values = list(history)
        if len(values) < 2 * season_length + 12:
            raise ValueError(
                f"random forest requires at least {2 * season_length + 12} observations"
            )
        if any(
            isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(float(value))
            for value in values
        ):
            raise ValueError("history must contain finite numeric values")

        try:
            from sklearn.ensemble import RandomForestRegressor
        except ImportError as exc:
            raise RuntimeError(
                "Random Forest is optional; install scikit-learn to enable this candidate"
            ) from exc

        first_target = 2 * season_length
        features = [
            self._features(values, index, season_length)
            for index in range(first_target, len(values))
        ]
        targets = [float(values[index]) for index in range(first_target, len(values))]
        model = RandomForestRegressor(
            n_estimators=self.n_estimators,
            max_depth=self.max_depth,
            min_samples_leaf=self.min_samples_leaf,
            random_state=self.random_state,
            n_jobs=1,
        )
        model.fit(features, targets)

        predictions: list[float] = []
        for _ in range(horizon):
            target_index = len(values)
            row = self._features(values, target_index, season_length)
            prediction = float(model.predict([row])[0])
            if not math.isfinite(prediction):
                raise ValueError("Random Forest produced a non-finite prediction")
            predictions.append(prediction)
            values.append(prediction)
        return predictions

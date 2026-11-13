"""Model-agnostic, evidence-gated prediction engine for IslandOS signals.

The engine compares registered forecast candidates with rolling-origin replay,
selects the best candidate by declared error metric, and emits empirical error
bands. Built-in candidates are statistical baselines, not trained AI models.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from numbers import Real
from typing import Protocol, Sequence


@dataclass(frozen=True)
class SignalObservation:
    timestamp: datetime
    value: float

    def __post_init__(self) -> None:
        if not isinstance(self.timestamp, datetime):
            raise ValueError("observation timestamp must be a datetime")
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("observation timestamp must include a timezone")
        if isinstance(self.value, bool) or not isinstance(self.value, Real):
            raise ValueError("observation value must be numeric")
        if not math.isfinite(float(self.value)):
            raise ValueError("observation value must be finite")


@dataclass(frozen=True)
class ForecastRequest:
    signal_id: str
    unit: str
    history: tuple[SignalObservation, ...]
    target_timestamps: tuple[datetime, ...]
    non_negative: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.signal_id, str) or not self.signal_id.strip():
            raise ValueError("signal_id is required")
        if not isinstance(self.unit, str) or not self.unit.strip():
            raise ValueError("unit is required")
        if not isinstance(self.non_negative, bool):
            raise ValueError("non_negative must be a boolean")
        if len(self.history) < 3:
            raise ValueError("at least three historical observations are required")
        if not self.target_timestamps:
            raise ValueError("at least one target timestamp is required")
        if any(not isinstance(item, SignalObservation) for item in self.history):
            raise ValueError("history must contain SignalObservation records")
        if self.non_negative and any(item.value < 0 for item in self.history):
            raise ValueError("signal history must be non-negative")
        history_utc = [item.timestamp.astimezone(timezone.utc) for item in self.history]
        target_utc = []
        for stamp in self.target_timestamps:
            if not isinstance(stamp, datetime) or stamp.tzinfo is None or stamp.utcoffset() is None:
                raise ValueError("target timestamps must be timezone-aware datetimes")
            target_utc.append(stamp.astimezone(timezone.utc))
        cadence = (history_utc[1] - history_utc[0]).total_seconds()
        if cadence <= 0:
            raise ValueError("history timestamps must be strictly increasing")
        if any((right - left).total_seconds() != cadence for left, right in zip(history_utc, history_utc[1:])):
            raise ValueError("history timestamps must have a regular fixed interval")
        if (target_utc[0] - history_utc[-1]).total_seconds() != cadence:
            raise ValueError("first target must follow the final observation by one sampling interval")
        if any((right - left).total_seconds() != cadence for left, right in zip(target_utc, target_utc[1:])):
            raise ValueError("target timestamps must use the same fixed interval as history")


class ForecastCandidate(Protocol):
    model_id: str
    version: str

    def predict(self, history: Sequence[float], horizon: int, *, season_length: int) -> Sequence[float]:
        """Return one numeric point estimate per future interval."""
        ...


class SeasonalNaiveCandidate:
    model_id = "seasonal_naive"
    version = "1.0"

    def predict(self, history: Sequence[float], horizon: int, *, season_length: int) -> list[float]:
        if not history:
            raise ValueError("history cannot be empty")
        if horizon < 1 or season_length < 1:
            raise ValueError("horizon and season_length must be positive")
        profile = list(history[-min(season_length, len(history)):])
        return [float(profile[index % len(profile)]) for index in range(horizon)]


class RecentMeanCandidate:
    model_id = "recent_mean"
    version = "1.0"

    def predict(self, history: Sequence[float], horizon: int, *, season_length: int) -> list[float]:
        if not history:
            raise ValueError("history cannot be empty")
        if horizon < 1 or season_length < 1:
            raise ValueError("horizon and season_length must be positive")
        window = list(history[-min(season_length, len(history)):])
        mean = sum(window) / len(window)
        return [float(mean)] * horizon


class LinearTrendCandidate:
    model_id = "linear_trend"
    version = "1.0"

    def predict(self, history: Sequence[float], horizon: int, *, season_length: int) -> list[float]:
        if len(history) < 2:
            raise ValueError("linear trend requires at least two observations")
        if horizon < 1 or season_length < 1:
            raise ValueError("horizon and season_length must be positive")
        window = [float(value) for value in history[-min(season_length * 7, len(history)):]]
        x_mean = (len(window) - 1) / 2
        y_mean = sum(window) / len(window)
        denominator = sum((index - x_mean) ** 2 for index in range(len(window)))
        slope = sum((index - x_mean) * (value - y_mean) for index, value in enumerate(window)) / denominator
        intercept = y_mean - slope * x_mean
        return [intercept + slope * (len(window) - 1 + step) for step in range(1, horizon + 1)]


@dataclass(frozen=True)
class CandidateMetrics:
    model_id: str
    model_version: str
    folds: int
    samples: int
    mae: float
    rmse: float
    wape_percent: float | None


@dataclass(frozen=True)
class ForecastPoint:
    timestamp: datetime
    predicted_value: float
    lower_bound: float
    upper_bound: float


@dataclass(frozen=True)
class PredictionResult:
    signal_id: str
    unit: str
    model_id: str
    model_version: str
    input_history_sha256: str
    confidence_level: float
    interval_method: str
    interval_calibration_samples: int
    backtest: CandidateMetrics
    points: tuple[ForecastPoint, ...]
    limitations: tuple[str, ...]


def _validate_predictions(values: Sequence[float], horizon: int, *, non_negative: bool) -> list[float]:
    try:
        predictions = list(values)
    except TypeError as exc:
        raise ValueError("candidate output must be a numeric sequence") from exc
    if len(predictions) != horizon:
        raise ValueError(f"candidate returned {len(predictions)} values for horizon {horizon}")
    clean = []
    for index, value in enumerate(predictions):
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ValueError(f"candidate prediction {index} must be numeric")
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f"candidate prediction {index} must be finite")
        if non_negative and number < 0:
            raise ValueError(f"candidate prediction {index} cannot be negative for this signal")
        clean.append(number)
    return clean


def _metrics(actual: Sequence[float], predicted: Sequence[float]) -> tuple[float, float, float | None]:
    if not actual or len(actual) != len(predicted):
        raise ValueError("actual and predicted must have equal non-empty lengths")
    errors = [float(guess) - float(truth) for truth, guess in zip(actual, predicted)]
    mae = sum(abs(error) for error in errors) / len(errors)
    rmse = math.sqrt(sum(error * error for error in errors) / len(errors))
    denominator = sum(abs(float(value)) for value in actual)
    wape = None if denominator == 0 else sum(abs(error) for error in errors) / denominator * 100.0
    return mae, rmse, wape


def _history_digest(request: ForecastRequest) -> str:
    payload = {
        "signal_id": request.signal_id,
        "unit": request.unit,
        "non_negative": request.non_negative,
        "history": [
            {"timestamp_utc": item.timestamp.astimezone(timezone.utc).isoformat(), "value": float(item.value)}
            for item in request.history
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class PredictionEngine:
    """Register candidates, compare them chronologically, and forecast with calibrated error bands."""

    def __init__(self, *, include_builtin_candidates: bool = True) -> None:
        self._candidates: dict[str, tuple[ForecastCandidate, str]] = {}
        if include_builtin_candidates:
            for candidate in (SeasonalNaiveCandidate(), RecentMeanCandidate(), LinearTrendCandidate()):
                self.register(candidate)

    def register(self, candidate: ForecastCandidate) -> None:
        model_id = getattr(candidate, "model_id", None)
        version = getattr(candidate, "version", None)
        predict = getattr(candidate, "predict", None)
        if not isinstance(model_id, str) or not model_id.strip() or model_id != model_id.strip():
            raise ValueError("candidate model_id must be a non-empty trimmed string")
        if not isinstance(version, str) or not version.strip() or version != version.strip():
            raise ValueError("candidate version must be a non-empty trimmed string")
        if not callable(predict):
            raise TypeError("candidate must implement predict(history, horizon, season_length=...)")
        if model_id in self._candidates:
            raise ValueError(f"candidate already registered: {model_id}")
        self._candidates[model_id] = (candidate, version)

    def available_candidates(self) -> tuple[tuple[str, str], ...]:
        return tuple(sorted((key, value[1]) for key, value in self._candidates.items()))

    def _replay(
        self,
        model_id: str,
        values: Sequence[float],
        *,
        initial_history: int,
        horizon: int,
        season_length: int,
        non_negative: bool,
    ) -> tuple[CandidateMetrics, list[float]]:
        candidate, version = self._candidates[model_id]
        actual_all: list[float] = []
        predicted_all: list[float] = []
        cutoff = initial_history
        folds = 0
        while cutoff < len(values):
            fold_horizon = min(horizon, len(values) - cutoff)
            predicted = _validate_predictions(
                candidate.predict(values[:cutoff], fold_horizon, season_length=season_length),
                fold_horizon, non_negative=non_negative,
            )
            actual = [float(value) for value in values[cutoff:cutoff + fold_horizon]]
            actual_all.extend(actual)
            predicted_all.extend(predicted)
            cutoff += fold_horizon
            folds += 1
        mae, rmse, wape = _metrics(actual_all, predicted_all)
        return CandidateMetrics(model_id, version, folds, len(actual_all), mae, rmse, wape), [
            abs(guess - truth) for truth, guess in zip(actual_all, predicted_all)
        ]

    def evaluate_candidates(
        self,
        history: Sequence[float],
        *,
        initial_history: int,
        horizon: int = 24,
        season_length: int = 24,
        non_negative: bool = True,
    ) -> tuple[CandidateMetrics, ...]:
        values = list(history)
        if len(values) < 3 or initial_history < 2 or initial_history >= len(values):
            raise ValueError("history requires at least three values and initial_history must be in [2, len(history))")
        if isinstance(horizon, bool) or not isinstance(horizon, int) or horizon < 1:
            raise ValueError("horizon must be a positive integer")
        if isinstance(season_length, bool) or not isinstance(season_length, int) or season_length < 1:
            raise ValueError("season_length must be a positive integer")
        if not isinstance(non_negative, bool):
            raise ValueError("non_negative must be a boolean")
        for index, value in enumerate(values):
            if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(float(value)):
                raise ValueError(f"history[{index}] must be finite numeric data")
            if non_negative and value < 0:
                raise ValueError(f"history[{index}] cannot be negative for this signal")
        if not self._candidates:
            raise ValueError("no forecast candidates are registered")
        results = []
        for model_id in sorted(self._candidates):
            try:
                metrics, _ = self._replay(
                    model_id, values, initial_history=initial_history, horizon=horizon,
                    season_length=season_length, non_negative=non_negative,
                )
                results.append(metrics)
            except (TypeError, ValueError, ArithmeticError):
                # A candidate that violates the signal contract is ineligible for this signal.
                continue
        if not results:
            raise ValueError("no registered forecast candidate passed the signal contract")
        return tuple(sorted(results, key=lambda item: (item.mae, item.rmse, item.model_id)))

    def forecast(
        self,
        request: ForecastRequest,
        *,
        model_id: str | None = None,
        initial_history: int | None = None,
        backtest_horizon: int = 24,
        season_length: int = 24,
        confidence_level: float = 0.90,
    ) -> PredictionResult:
        if not isinstance(request, ForecastRequest):
            raise TypeError("request must be a ForecastRequest")
        if isinstance(confidence_level, bool) or not isinstance(confidence_level, Real) or not 0 < confidence_level < 1:
            raise ValueError("confidence_level must be between 0 and 1")
        values = [float(item.value) for item in request.history]
        cutoff = initial_history if initial_history is not None else min(48, len(values) - 1)
        ranking = self.evaluate_candidates(
            values, initial_history=cutoff, horizon=backtest_horizon,
            season_length=season_length, non_negative=request.non_negative,
        )
        selected_id = model_id or ranking[0].model_id
        if selected_id not in self._candidates:
            raise KeyError(f"unknown forecast candidate: {selected_id}")
        selected_metrics, absolute_errors = self._replay(
            selected_id, values, initial_history=cutoff, horizon=backtest_horizon,
            season_length=season_length, non_negative=request.non_negative,
        )
        candidate, registered_version = self._candidates[selected_id]
        predictions = _validate_predictions(
            candidate.predict(values, len(request.target_timestamps), season_length=season_length),
            len(request.target_timestamps), non_negative=request.non_negative,
        )
        ordered_errors = sorted(absolute_errors)
        rank = max(1, min(len(ordered_errors), math.ceil(confidence_level * len(ordered_errors))))
        radius = ordered_errors[rank - 1]
        points = []
        for stamp, prediction in zip(request.target_timestamps, predictions):
            lower = prediction - radius
            if request.non_negative:
                lower = max(0.0, lower)
            points.append(ForecastPoint(stamp, prediction, lower, prediction + radius))
        return PredictionResult(
            signal_id=request.signal_id,
            unit=request.unit,
            model_id=selected_id,
            model_version=registered_version,
            input_history_sha256=_history_digest(request),
            confidence_level=float(confidence_level),
            interval_method="symmetric empirical absolute-error quantile from rolling-origin replay",
            interval_calibration_samples=len(absolute_errors),
            backtest=selected_metrics,
            points=tuple(points),
            limitations=(
                "Built-in candidates are statistical baselines, not trained AI models.",
                "Error bands summarize historical rolling-origin residuals; they are not guaranteed prediction intervals.",
                "Backtest skill on supplied history does not establish future accuracy or site-wide operational suitability.",
                "Forecasts are decision-support inputs and do not issue equipment commands.",
            ),
        )

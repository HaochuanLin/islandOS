"""Transparent hourly electricity-tariff forecasting baselines.

Forecasts are planning inputs, not market predictions. Negative prices are
valid; values are never clipped. All timestamps must be timezone-aware and
strictly hourly so the forecast cannot silently misalign with dispatch.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from numbers import Real
from typing import Sequence


@dataclass(frozen=True)
class TariffObservation:
    timestamp: datetime
    price_per_kwh: float

    def __post_init__(self) -> None:
        if not isinstance(self.timestamp, datetime):
            raise ValueError("timestamp must be a datetime")
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("timestamp must include a timezone")
        if isinstance(self.price_per_kwh, bool) or not isinstance(self.price_per_kwh, Real):
            raise ValueError("price_per_kwh must be numeric")
        if not math.isfinite(float(self.price_per_kwh)):
            raise ValueError("price_per_kwh must be finite")


@dataclass(frozen=True)
class TariffForecastPoint:
    timestamp: datetime
    predicted_price_per_kwh: float


@dataclass(frozen=True)
class TariffForecastResult:
    method: str
    input_history_sha256: str
    points: tuple[TariffForecastPoint, ...]


@dataclass(frozen=True)
class TariffForecastMetrics:
    samples: int
    mae: float
    rmse: float
    bias_predicted_minus_actual: float


@dataclass(frozen=True)
class TariffBacktestFold:
    first_target_timestamp: datetime
    last_target_timestamp: datetime
    metrics: TariffForecastMetrics


@dataclass(frozen=True)
class TariffBacktestResult:
    method: str
    fold_count: int
    aggregate_metrics: TariffForecastMetrics
    folds: tuple[TariffBacktestFold, ...]


def _validated_history(history: Sequence[TariffObservation]) -> tuple[TariffObservation, ...]:
    if isinstance(history, (str, bytes)):
        raise ValueError("history must contain TariffObservation records")
    try:
        observations = tuple(history)
    except TypeError as exc:
        raise ValueError("history must be a sequence of TariffObservation records") from exc
    if len(observations) < 1:
        raise ValueError("history must contain at least one observation")
    if any(not isinstance(item, TariffObservation) for item in observations):
        raise ValueError("history must contain only TariffObservation records")
    for previous, current in zip(observations, observations[1:]):
        if (current.timestamp - previous.timestamp).total_seconds() != 3600:
            raise ValueError("history timestamps must be strictly ordered hourly data")
    return observations


def _history_digest(history: Sequence[TariffObservation]) -> str:
    payload = [
        {"timestamp": item.timestamp.isoformat(), "price_per_kwh": float(item.price_per_kwh)}
        for item in history
    ]
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def forecast_tariff_prices(
    history: Sequence[TariffObservation],
    horizon: int,
    *,
    season_length: int = 24,
) -> TariffForecastResult:
    """Repeat the most recent seasonal price profile for future hourly intervals.

    For hourly electricity tariffs the default season is 24 hours. The method
    uses only the supplied history and supports negative prices. It does not
    model holidays, market events, weather, congestion, or tariff rule changes.
    """
    observations = _validated_history(history)
    for name, value in (("horizon", horizon), ("season_length", season_length)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{name} must be a positive integer")
    season = observations[-min(season_length, len(observations)):]
    last_timestamp = observations[-1].timestamp
    points = tuple(
        TariffForecastPoint(
            timestamp=last_timestamp + timedelta(hours=step),
            predicted_price_per_kwh=float(season[(step - 1) % len(season)].price_per_kwh),
        )
        for step in range(1, horizon + 1)
    )
    return TariffForecastResult(
        method=f"seasonal_naive_{season_length}h",
        input_history_sha256=_history_digest(observations),
        points=points,
    )


def evaluate_tariff_forecast(
    actual: Sequence[float],
    predicted: Sequence[float],
) -> TariffForecastMetrics:
    """Evaluate price forecasts with MAE, RMSE and signed bias; negative prices allowed."""
    def clean(values: Sequence[float], name: str) -> list[float]:
        if isinstance(values, (str, bytes)):
            raise ValueError(f"{name} must be a numeric sequence")
        try:
            raw = list(values)
        except TypeError as exc:
            raise ValueError(f"{name} must be a numeric sequence") from exc
        if not raw:
            raise ValueError(f"{name} must not be empty")
        result = []
        for index, value in enumerate(raw):
            if isinstance(value, bool) or not isinstance(value, Real):
                raise ValueError(f"{name}[{index}] must be numeric")
            number = float(value)
            if not math.isfinite(number):
                raise ValueError(f"{name}[{index}] must be finite")
            result.append(number)
        return result

    truth = clean(actual, "actual")
    estimate = clean(predicted, "predicted")
    if len(truth) != len(estimate):
        raise ValueError("actual and predicted must have equal lengths")
    errors = [guess - observed for observed, guess in zip(truth, estimate)]
    return TariffForecastMetrics(
        samples=len(errors),
        mae=sum(abs(error) for error in errors) / len(errors),
        rmse=math.sqrt(sum(error * error for error in errors) / len(errors)),
        bias_predicted_minus_actual=sum(errors) / len(errors),
    )



def rolling_origin_tariff_backtest(
    history: Sequence[TariffObservation],
    *,
    initial_history: int = 48,
    horizon: int = 24,
    season_length: int = 24,
) -> TariffBacktestResult:
    """Evaluate the tariff baseline on contiguous future blocks using prior data only.

    Each fold is forecast from observations strictly before its first target.
    After a fold, its actual observations become available to the next fold.
    This is a historical replay, not a guarantee of future forecast skill.
    """
    observations = _validated_history(history)
    for name, value in (
        ("initial_history", initial_history),
        ("horizon", horizon),
        ("season_length", season_length),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{name} must be a positive integer")
    if initial_history < season_length:
        raise ValueError("initial_history must be at least season_length")
    if initial_history >= len(observations):
        raise ValueError("initial_history must be shorter than history")

    folds = []
    all_actual = []
    all_predicted = []
    cutoff = initial_history
    while cutoff < len(observations):
        fold_horizon = min(horizon, len(observations) - cutoff)
        forecast = forecast_tariff_prices(
            observations[:cutoff], fold_horizon, season_length=season_length
        )
        actual = [
            float(item.price_per_kwh)
            for item in observations[cutoff:cutoff + fold_horizon]
        ]
        predicted = [point.predicted_price_per_kwh for point in forecast.points]
        metrics = evaluate_tariff_forecast(actual, predicted)
        folds.append(TariffBacktestFold(
            first_target_timestamp=observations[cutoff].timestamp,
            last_target_timestamp=observations[cutoff + fold_horizon - 1].timestamp,
            metrics=metrics,
        ))
        all_actual.extend(actual)
        all_predicted.extend(predicted)
        cutoff += fold_horizon

    return TariffBacktestResult(
        method="expanding-history, contiguous rolling-origin seasonal-naive replay",
        fold_count=len(folds),
        aggregate_metrics=evaluate_tariff_forecast(all_actual, all_predicted),
        folds=tuple(folds),
    )

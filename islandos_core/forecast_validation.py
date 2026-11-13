"""Leakage-safe rolling-origin evaluation helpers for hourly forecasts.

This module is intentionally independent of a specific forecasting model:
callers supply candidate and baseline forecasters. It provides expanding
training windows, contiguous future validation blocks, and site-local
calendar features while keeping timestamps in UTC at the service boundary.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Mapping, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True)
class FoldMetrics:
    samples: int
    mae: float
    rmse: float
    bias_predicted_minus_actual: float


@dataclass(frozen=True)
class ModelBacktest:
    model_id: str
    folds: tuple[FoldMetrics, ...]

    @property
    def mean_mae(self) -> float:
        return sum(fold.mae for fold in self.folds) / len(self.folds)


def site_local_calendar_features(timestamp: datetime, site_timezone: str) -> tuple[float, ...]:
    """Return cyclic hour and weekday features in an IANA site timezone."""
    if not isinstance(timestamp, datetime) or timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    if not isinstance(site_timezone, str) or not site_timezone.strip():
        raise ValueError("site_timezone must be a non-empty IANA timezone name")
    try:
        local = timestamp.astimezone(ZoneInfo(site_timezone))
    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        raise ValueError(f"Unknown IANA site timezone: {site_timezone}") from exc
    hour = local.hour + local.minute / 60.0 + local.second / 3600.0
    weekday = local.weekday()
    return (
        math.sin(2.0 * math.pi * hour / 24.0),
        math.cos(2.0 * math.pi * hour / 24.0),
        math.sin(2.0 * math.pi * weekday / 7.0),
        math.cos(2.0 * math.pi * weekday / 7.0),
    )


def expanding_window_slices(
    observation_count: int,
    *,
    min_train_size: int = 72,
    validation_size: int = 24,
    folds: int = 4,
) -> tuple[tuple[slice, slice], ...]:
    """Create chronological expanding folds with fixed contiguous test blocks."""
    for name, value in (("observation_count", observation_count),
                        ("min_train_size", min_train_size),
                        ("validation_size", validation_size),
                        ("folds", folds)):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{name} must be a positive integer")
    required = min_train_size + validation_size * folds
    if observation_count < required:
        raise ValueError(
            f"need at least {required} observations for {folds} folds "
            f"(min_train_size={min_train_size}, validation_size={validation_size})"
        )
    first_train_end = observation_count - validation_size * folds
    return tuple(
        (slice(0, first_train_end + i * validation_size),
         slice(first_train_end + i * validation_size,
               first_train_end + (i + 1) * validation_size))
        for i in range(folds)
    )


def _score(actual: Sequence[float], predicted: Sequence[float]) -> FoldMetrics:
    if len(actual) != len(predicted) or not actual:
        raise ValueError("each fold must return one prediction per validation observation")
    errors = []
    for index, (truth, estimate) in enumerate(zip(actual, predicted)):
        if isinstance(truth, bool) or isinstance(estimate, bool):
            raise ValueError("actual values and predictions must be finite numbers")
        try:
            truth_f, estimate_f = float(truth), float(estimate)
        except (TypeError, ValueError) as exc:
            raise ValueError("actual values and predictions must be finite numbers") from exc
        if not math.isfinite(truth_f) or not math.isfinite(estimate_f):
            raise ValueError(f"non-finite value in fold at index {index}")
        errors.append(estimate_f - truth_f)
    return FoldMetrics(
        samples=len(errors),
        mae=sum(abs(error) for error in errors) / len(errors),
        rmse=math.sqrt(sum(error * error for error in errors) / len(errors)),
        bias_predicted_minus_actual=sum(errors) / len(errors),
    )


def evaluate_expanding_window(
    timestamps: Sequence[datetime],
    values: Sequence[float],
    forecasters: Mapping[str, Callable[[Sequence[float], Sequence[datetime]], Sequence[float]]],
    *,
    min_train_size: int = 72,
    validation_size: int = 24,
    folds: int = 4,
) -> Mapping[str, ModelBacktest]:
    """Evaluate candidate and baseline callbacks on identical future-only folds.

    A forecaster receives only the training values and validation timestamps;
    validation actuals are never passed to it.
    """
    if len(timestamps) != len(values):
        raise ValueError("timestamps and values must have equal lengths")
    if not forecasters or any(not isinstance(k, str) or not k.strip() for k in forecasters):
        raise ValueError("forecasters must be a non-empty mapping with named models")
    normalized_timestamps = []
    for stamp in timestamps:
        if not isinstance(stamp, datetime) or stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError("all timestamps must be timezone-aware")
        normalized_timestamps.append(stamp.astimezone(timezone.utc))
    for left, right in zip(normalized_timestamps, normalized_timestamps[1:]):
        if right - left != timedelta(hours=1):
            raise ValueError("timestamps must be strictly increasing and contiguous hourly instants")

    normalized_values = []
    for index, value in enumerate(values):
        if isinstance(value, bool):
            raise ValueError(f"training and validation values must be finite numbers (index {index})")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"training and validation values must be finite numbers (index {index})") from exc
        if not math.isfinite(number):
            raise ValueError(f"training and validation values must be finite numbers (index {index})")
        normalized_values.append(number)
    timestamps = normalized_timestamps
    values = normalized_values
    splits = expanding_window_slices(
        len(values), min_train_size=min_train_size,
        validation_size=validation_size, folds=folds,
    )
    results = {}
    for model_id, forecaster in forecasters.items():
        fold_scores = []
        for train_slice, validation_slice in splits:
            train = tuple(float(v) for v in values[train_slice])
            validation_actual = values[validation_slice]
            validation_timestamps = tuple(timestamps[validation_slice])
            predictions = forecaster(train, validation_timestamps)
            fold_scores.append(_score(validation_actual, predictions))
        results[model_id] = ModelBacktest(model_id, tuple(fold_scores))
    return results

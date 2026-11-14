"""Independent realized-data evaluation for forecast bundles.

Metrics are computed only when actual observations are supplied by the caller.
This module does not fetch public datasets or imply that synthetic fixtures are
field validation.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from numbers import Real
from typing import Mapping, Sequence


@dataclass(frozen=True)
class SignalEvaluation:
    signal_id: str
    unit: str
    samples: int
    mae: float
    rmse: float
    bias_predicted_minus_actual: float
    wape_percent: float | None
    interval_coverage_percent: float
    mean_interval_width: float


def evaluate_realized_forecast(
    *,
    signal_id: str,
    unit: str,
    forecast_points: Sequence,
    actuals: Mapping[datetime, float],
) -> SignalEvaluation:
    """Score one forecast against timestamp-keyed realized observations.

    All timestamps are normalized to UTC. Missing actual timestamps are rejected
    rather than silently dropped, preventing optimistic scoring from sparse data.
    """
    if not isinstance(signal_id, str) or not signal_id.strip():
        raise ValueError("signal_id is required")
    if not isinstance(unit, str) or not unit.strip():
        raise ValueError("unit is required")
    if not forecast_points:
        raise ValueError("forecast_points must not be empty")
    if not isinstance(actuals, Mapping):
        raise ValueError("actuals must be a timestamp mapping")

    normalized_actuals: dict[datetime, float] = {}
    for stamp, value in actuals.items():
        if not isinstance(stamp, datetime) or stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError("actual timestamps must be timezone-aware datetimes")
        if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(float(value)):
            raise ValueError("actual values must be finite numbers")
        key = stamp.astimezone(timezone.utc)
        if key in normalized_actuals:
            raise ValueError("actual timestamps must be unique after UTC normalization")
        normalized_actuals[key] = float(value)

    errors: list[float] = []
    actual_values: list[float] = []
    covered = 0
    widths: list[float] = []
    for point in forecast_points:
        stamp = point.timestamp
        if not isinstance(stamp, datetime) or stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError("forecast timestamps must be timezone-aware")
        key = stamp.astimezone(timezone.utc)
        if key not in normalized_actuals:
            raise ValueError(f"actual observation is missing for {key.isoformat()}")
        predicted, low, high = point.predicted_value, point.lower_bound, point.upper_bound
        raw = (predicted, low, high)
        if any(isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(float(value)) for value in raw):
            raise ValueError("forecast values and bounds must be finite numbers")
        predicted_f, low_f, high_f = map(float, raw)
        if low_f > predicted_f or predicted_f > high_f:
            raise ValueError("forecast interval must contain its point prediction")
        actual = normalized_actuals[key]
        errors.append(predicted_f - actual)
        actual_values.append(actual)
        covered += int(low_f <= actual <= high_f)
        widths.append(high_f - low_f)

    count = len(errors)
    denominator = sum(abs(value) for value in actual_values)
    return SignalEvaluation(
        signal_id=signal_id,
        unit=unit,
        samples=count,
        mae=sum(abs(error) for error in errors) / count,
        rmse=math.sqrt(sum(error * error for error in errors) / count),
        bias_predicted_minus_actual=sum(errors) / count,
        wape_percent=None if denominator == 0 else 100.0 * sum(abs(error) for error in errors) / denominator,
        interval_coverage_percent=100.0 * covered / count,
        mean_interval_width=sum(widths) / count,
    )

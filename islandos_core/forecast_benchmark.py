"""Horizon-aware benchmark reports for realized IslandOS forecasts.

The evaluator scores caller-supplied forecasts against timestamp-aligned actuals.
It does not download data, tune a model on the holdout, or infer site readiness.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from numbers import Real
from typing import Mapping, Sequence

from .forecast_evaluation_report import SignalEvaluation, evaluate_realized_forecast


@dataclass(frozen=True)
class LeadTimeMetrics:
    lead_step: int
    samples: int
    mae: float
    rmse: float
    bias_predicted_minus_actual: float
    interval_coverage_percent: float


@dataclass(frozen=True)
class ForecastBenchmark:
    signal_id: str
    unit: str
    overall: SignalEvaluation
    lead_time: tuple[LeadTimeMetrics, ...]
    baseline_mae: float | None
    mae_skill_percent: float | None
    evaluation_scope: str


def benchmark_forecast(
    *,
    signal_id: str,
    unit: str,
    forecast_points: Sequence,
    actuals: Mapping[datetime, float],
    baseline_predictions: Mapping[datetime, float] | None = None,
) -> ForecastBenchmark:
    """Evaluate overall and per-lead errors; optionally compare a frozen baseline.

    The baseline must cover exactly the forecast timestamps. Positive skill means
    the candidate MAE is lower than the baseline MAE. Zero baseline MAE yields
    undefined skill rather than division by zero.
    """
    overall = evaluate_realized_forecast(
        signal_id=signal_id, unit=unit,
        forecast_points=forecast_points, actuals=actuals,
    )
    lead_metrics = []
    candidate_errors = []
    baseline_errors = []
    normalized_actuals = {
        stamp.astimezone(timezone.utc): float(value)
        for stamp, value in actuals.items()
    }
    normalized_baseline = None
    if baseline_predictions is not None:
        if not isinstance(baseline_predictions, Mapping):
            raise ValueError("baseline_predictions must be a timestamp mapping")
        normalized_baseline = {}
        for stamp, value in baseline_predictions.items():
            if not isinstance(stamp, datetime) or stamp.tzinfo is None or stamp.utcoffset() is None:
                raise ValueError("baseline timestamps must be timezone-aware")
            if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(float(value)):
                raise ValueError("baseline predictions must be finite numbers")
            key = stamp.astimezone(timezone.utc)
            if key in normalized_baseline:
                raise ValueError("baseline timestamps must be unique after UTC normalization")
            normalized_baseline[key] = float(value)
        forecast_stamps = {point.timestamp.astimezone(timezone.utc) for point in forecast_points}
        if set(normalized_baseline) != forecast_stamps:
            raise ValueError("baseline must cover exactly the forecast timestamps")

    for lead, point in enumerate(forecast_points, start=1):
        stamp = point.timestamp.astimezone(timezone.utc)
        actual = normalized_actuals[stamp]
        predicted = float(point.predicted_value)
        error = predicted - actual
        candidate_errors.append(abs(error))
        if normalized_baseline is not None:
            baseline_errors.append(abs(normalized_baseline[stamp] - actual))
        lead_metrics.append(LeadTimeMetrics(
            lead_step=lead,
            samples=1,
            mae=abs(error),
            rmse=abs(error),
            bias_predicted_minus_actual=error,
            interval_coverage_percent=100.0 * int(
                float(point.lower_bound) <= actual <= float(point.upper_bound)
            ),
        ))

    baseline_mae = None
    skill = None
    if normalized_baseline is not None:
        baseline_mae = sum(baseline_errors) / len(baseline_errors)
        if baseline_mae > 0:
            skill = 100.0 * (baseline_mae - overall.mae) / baseline_mae

    return ForecastBenchmark(
        signal_id=signal_id,
        unit=unit,
        overall=overall,
        lead_time=tuple(lead_metrics),
        baseline_mae=baseline_mae,
        mae_skill_percent=skill,
        evaluation_scope=(
            "realized timestamp-aligned observations supplied by caller; "
            "per-lead metrics are descriptive and do not establish future performance"
        ),
    )

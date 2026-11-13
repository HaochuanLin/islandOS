"""Bridge the generic prediction engine into the existing dispatch forecast contract.

This is Stage D's first integration seam. It preserves per-signal model and
history provenance while refusing misaligned horizons or mixed history windows.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Mapping

from .forecast_engine import (
    ForecastBundle,
    ForecastMetrics,
    ForecastPoint as DispatchForecastPoint,
    SignalForecast,
)
from .prediction_engine import PredictionResult


def build_dispatch_forecast_bundle(
    results: Mapping[str, PredictionResult],
    *,
    history_start_utc: datetime,
    history_end_utc: datetime,
) -> ForecastBundle:
    """Convert one or more generic prediction results into a planner bundle."""
    if not isinstance(results, Mapping) or not results:
        raise ValueError("at least one named PredictionResult is required")
    for label, stamp in (("history_start_utc", history_start_utc),
                         ("history_end_utc", history_end_utc)):
        if not isinstance(stamp, datetime) or stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError(f"{label} must be timezone-aware")
    start = history_start_utc.astimezone(timezone.utc)
    end = history_end_utc.astimezone(timezone.utc)
    if end < start:
        raise ValueError("history_end_utc must not precede history_start_utc")

    forecasts = {}
    digests = {}
    common_targets = None
    for signal_name, result in sorted(results.items()):
        if not isinstance(signal_name, str) or not signal_name.strip():
            raise ValueError("forecast mapping keys must be non-empty signal names")
        if not isinstance(result, PredictionResult):
            raise TypeError(f"{signal_name} must map to a PredictionResult")
        if result.signal_id != signal_name:
            raise ValueError(f"forecast key does not match result signal_id: {signal_name}")
        digest = result.input_history_sha256
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise ValueError(f"{signal_name} has an invalid input history SHA-256")
        targets = tuple(point.timestamp.astimezone(timezone.utc) for point in result.points)
        if not targets:
            raise ValueError(f"{signal_name} forecast horizon is empty")
        if common_targets is None:
            common_targets = targets
        elif targets != common_targets:
            raise ValueError("all resource forecasts must share identical target timestamps")
        points = tuple(
            DispatchForecastPoint(
                timestamp=point.timestamp,
                predicted=point.predicted_value,
                lower_bound=point.lower_bound,
                upper_bound=point.upper_bound,
            )
            for point in result.points
        )
        metrics = ForecastMetrics(
            samples=result.backtest.samples,
            mae=result.backtest.mae,
            rmse=result.backtest.rmse,
            bias_predicted_minus_actual=None,
        )
        forecasts[signal_name] = SignalForecast(
            signal_name=signal_name,
            unit=result.unit,
            model_id=result.model_id,
            model_version=result.model_version,
            points=points,
            holdout_metrics=metrics,
            baseline_metrics=MappingProxyType({}),
            selected_model_beats_baseline=False,
            uncertainty_method=result.interval_method,
            residual_abs_error_p90=max(
                (point.upper_bound - point.predicted_value for point in result.points),
                default=0.0,
            ),
        )
        digests[signal_name] = digest

    canonical = json.dumps(digests, sort_keys=True, separators=(",", ":"))
    aggregate_digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return ForecastBundle(
        input_history_sha256=aggregate_digest,
        history_start_utc=start,
        history_end_utc=end,
        forecasts=MappingProxyType(forecasts),
    )

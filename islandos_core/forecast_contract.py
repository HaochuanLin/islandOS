"""Validated hand-off contract from forecasts to downstream planners.

This module deliberately contains no dispatch or optimization policy. It
converts a ForecastBundle into aligned, unit-labelled arrays that a later
optimizer can consume without guessing signal meaning or timestamp alignment.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Mapping

from .forecast_engine import ForecastBundle


@dataclass(frozen=True)
class ForecastPlanningInput:
    """Forecast arrays for a planning decision."""

    timestamps: tuple[datetime, ...]
    values: Mapping[str, tuple[float, ...]]
    lower_bounds: Mapping[str, tuple[float, ...]]
    upper_bounds: Mapping[str, tuple[float, ...]]
    units: Mapping[str, str]
    model_ids: Mapping[str, str]
    history_sha256: str


def build_forecast_planning_input(
    bundle: ForecastBundle,
    required_units: Mapping[str, str],
) -> ForecastPlanningInput:
    """Validate and select forecast signals required by a downstream planner.

    required_units is an explicit allow-list and unit contract, e.g.
    {"pv": "kW", "critical_load": "kW", "tariff": "USD/kWh"}.
    Extra forecasts in the bundle are ignored; missing signals, unit
    mismatches, misaligned horizons, invalid bounds, and malformed provenance
    are rejected rather than silently coerced.
    """
    if not isinstance(bundle, ForecastBundle):
        raise ValueError("bundle must be a ForecastBundle")
    if not isinstance(required_units, Mapping) or not required_units:
        raise ValueError("required_units must be a non-empty signal-to-unit mapping")
    if isinstance(required_units, (str, bytes)):
        raise ValueError("required_units must be a mapping, not a string")

    digest = bundle.input_history_sha256
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise ValueError("bundle must contain a valid lowercase SHA-256 history digest")

    timestamps: tuple[datetime, ...] | None = None
    values: dict[str, tuple[float, ...]] = {}
    lower_bounds: dict[str, tuple[float, ...]] = {}
    upper_bounds: dict[str, tuple[float, ...]] = {}
    units: dict[str, str] = {}
    model_ids: dict[str, str] = {}

    for signal_name, expected_unit in required_units.items():
        if not isinstance(signal_name, str) or not signal_name.strip():
            raise ValueError("required signal names must be non-empty strings")
        if not isinstance(expected_unit, str) or not expected_unit.strip():
            raise ValueError(f"expected unit for {signal_name} must be non-empty")
        forecast = bundle.forecasts.get(signal_name)
        if forecast is None:
            raise ValueError(f"required forecast signal is missing: {signal_name}")
        if forecast.signal_name != signal_name:
            raise ValueError(f"forecast key/name mismatch for {signal_name}")
        if forecast.unit != expected_unit:
            raise ValueError(
                f"unit mismatch for {signal_name}: expected {expected_unit}, got {forecast.unit}"
            )
        if not isinstance(forecast.model_id, str) or not forecast.model_id.strip():
            raise ValueError(f"forecast model_id is missing for {signal_name}")
        if not forecast.points:
            raise ValueError(f"forecast horizon is empty for {signal_name}")

        signal_timestamps = tuple(point.timestamp for point in forecast.points)
        for index, stamp in enumerate(signal_timestamps):
            if not isinstance(stamp, datetime) or stamp.tzinfo is None or stamp.utcoffset() is None:
                raise ValueError(f"{signal_name} forecast timestamps must be timezone-aware")
            if index and stamp - signal_timestamps[index - 1] != timedelta(hours=1):
                raise ValueError(f"{signal_name} forecast timestamps must be contiguous hourly instants")
        if timestamps is None:
            timestamps = signal_timestamps
        elif signal_timestamps != timestamps:
            raise ValueError("required forecast signals must share identical target timestamps")

        predicted_values = []
        lows = []
        highs = []
        for index, point in enumerate(forecast.points):
            raw = (point.predicted, point.lower_bound, point.upper_bound)
            if any(isinstance(value, bool) for value in raw):
                raise ValueError(f"{signal_name} forecast values must be finite numbers")
            try:
                predicted, low, high = (float(value) for value in raw)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{signal_name} forecast values must be finite numbers") from exc
            if not all(math.isfinite(value) for value in (predicted, low, high)):
                raise ValueError(f"{signal_name} forecast contains a non-finite value at index {index}")
            if low > predicted or predicted > high:
                raise ValueError(f"{signal_name} forecast bounds do not contain prediction at index {index}")
            predicted_values.append(predicted)
            lows.append(low)
            highs.append(high)

        values[signal_name] = tuple(predicted_values)
        lower_bounds[signal_name] = tuple(lows)
        upper_bounds[signal_name] = tuple(highs)
        units[signal_name] = expected_unit
        model_ids[signal_name] = forecast.model_id

    assert timestamps is not None
    return ForecastPlanningInput(
        timestamps=timestamps,
        values=values,
        lower_bounds=lower_bounds,
        upper_bounds=upper_bounds,
        units=units,
        model_ids=model_ids,
        history_sha256=digest,
    )

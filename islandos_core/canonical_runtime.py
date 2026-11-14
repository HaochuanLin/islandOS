"""Canonical forecast-to-planning facade for the IslandOS product workflow.

This module is the supported application boundary for multi-signal forecasting.
It delegates model selection to ForecastService, validates the complete bundle,
and exposes immutable, unit-labelled planning arrays. It does not dispatch or
issue device commands.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from types import MappingProxyType
from typing import Mapping

from .forecast_service import ForecastBundleRequest, ForecastBundleResult, ForecastService


@dataclass(frozen=True)
class PlanningForecast:
    """Validated forecast data ready for a downstream planner."""

    bundle_sha256: str
    timestamps: tuple[datetime, ...]
    values: Mapping[str, tuple[float, ...]]
    lower_bounds: Mapping[str, tuple[float, ...]]
    upper_bounds: Mapping[str, tuple[float, ...]]
    units: Mapping[str, str]
    model_ids: Mapping[str, str]
    history_digests: Mapping[str, str]
    limitations: tuple[str, ...]


def _utc_grid(result: ForecastBundleResult) -> tuple[datetime, ...]:
    if not result.target_timestamps:
        raise ValueError("forecast bundle horizon must not be empty")
    grid = tuple(stamp.astimezone(timezone.utc) for stamp in result.target_timestamps)
    if any(stamp.tzinfo is None or stamp.utcoffset() is None for stamp in result.target_timestamps):
        raise ValueError("forecast target timestamps must be timezone-aware")
    if any(right <= left for left, right in zip(grid, grid[1:])):
        raise ValueError("forecast target timestamps must be strictly increasing")
    return grid


def to_planning_forecast(
    result: ForecastBundleResult,
    *,
    required_units: Mapping[str, str],
) -> PlanningForecast:
    """Convert a forecast result into a strict planner input contract.

    Missing signals, unit mismatches, misaligned timestamps, malformed bounds,
    and invalid provenance fail closed. Extra signals are omitted deliberately.
    """
    if not isinstance(result, ForecastBundleResult):
        raise TypeError("result must be a ForecastBundleResult")
    if not isinstance(required_units, Mapping) or not required_units:
        raise ValueError("required_units must be a non-empty mapping")
    if any(not isinstance(key, str) or not key.strip() for key in required_units):
        raise ValueError("required signal IDs must be non-empty strings")
    if any(not isinstance(unit, str) or not unit.strip() for unit in required_units.values()):
        raise ValueError("required signal units must be non-empty strings")
    if not isinstance(result.bundle_sha256, str) or len(result.bundle_sha256) != 64:
        raise ValueError("forecast bundle must contain a SHA-256 digest")
    if any(ch not in "0123456789abcdef" for ch in result.bundle_sha256):
        raise ValueError("forecast bundle digest must be lowercase hexadecimal")

    timestamps = _utc_grid(result)
    values: dict[str, tuple[float, ...]] = {}
    lows: dict[str, tuple[float, ...]] = {}
    highs: dict[str, tuple[float, ...]] = {}
    units: dict[str, str] = {}
    models: dict[str, str] = {}
    digests: dict[str, str] = {}

    for signal_id, expected_unit in required_units.items():
        forecast = result.forecasts.get(signal_id)
        if forecast is None:
            raise ValueError(f"required forecast signal is missing: {signal_id}")
        if forecast.signal_id != signal_id:
            raise ValueError(f"forecast key/name mismatch for {signal_id}")
        if forecast.unit != expected_unit:
            raise ValueError(f"unit mismatch for {signal_id}: expected {expected_unit}, got {forecast.unit}")
        if len(forecast.points) != len(timestamps):
            raise ValueError(f"forecast horizon length mismatch for {signal_id}")
        if not isinstance(forecast.model_id, str) or not forecast.model_id.strip():
            raise ValueError(f"forecast model ID is missing for {signal_id}")
        digest = forecast.input_history_sha256
        if not isinstance(digest, str) or len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise ValueError(f"invalid input history digest for {signal_id}")

        signal_values, signal_lows, signal_highs = [], [], []
        for index, point in enumerate(forecast.points):
            stamp = point.timestamp
            if not isinstance(stamp, datetime) or stamp.tzinfo is None or stamp.utcoffset() is None:
                raise ValueError(f"{signal_id} timestamp at index {index} must be timezone-aware")
            if stamp.astimezone(timezone.utc) != timestamps[index]:
                raise ValueError(f"forecast timestamps are not aligned for {signal_id}")
            raw = (point.predicted_value, point.lower_bound, point.upper_bound)
            if any(isinstance(value, bool) for value in raw):
                raise ValueError(f"{signal_id} forecast values must be finite numbers")
            try:
                predicted, low, high = (float(value) for value in raw)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{signal_id} forecast values must be finite numbers") from exc
            if not all(math.isfinite(value) for value in (predicted, low, high)):
                raise ValueError(f"{signal_id} forecast contains a non-finite value")
            if low > predicted or predicted > high:
                raise ValueError(f"{signal_id} forecast bounds do not contain prediction at index {index}")
            signal_values.append(predicted)
            signal_lows.append(low)
            signal_highs.append(high)

        values[signal_id] = tuple(signal_values)
        lows[signal_id] = tuple(signal_lows)
        highs[signal_id] = tuple(signal_highs)
        units[signal_id] = expected_unit
        models[signal_id] = forecast.model_id
        digests[signal_id] = digest

    return PlanningForecast(
        bundle_sha256=result.bundle_sha256,
        timestamps=timestamps,
        values=MappingProxyType(values),
        lower_bounds=MappingProxyType(lows),
        upper_bounds=MappingProxyType(highs),
        units=MappingProxyType(units),
        model_ids=MappingProxyType(models),
        history_digests=MappingProxyType(digests),
        limitations=tuple(result.limitations),
    )


class CanonicalForecastRuntime:
    """Single supported facade for aligned multi-signal forecast preparation."""

    def __init__(self, service: ForecastService | None = None) -> None:
        self._service = service or ForecastService()

    def prepare(
        self,
        request: ForecastBundleRequest,
        *,
        required_units: Mapping[str, str],
        model_ids: Mapping[str, str] | None = None,
        initial_history: int | None = None,
        backtest_horizon: int = 24,
        season_length: int = 24,
        confidence_level: float = 0.90,
    ) -> PlanningForecast:
        if not isinstance(request, ForecastBundleRequest):
            raise TypeError("request must be a ForecastBundleRequest")
        requested = {item.signal_id: item.unit for item in request.requests}
        missing = sorted(set(required_units) - set(requested))
        mismatched = sorted(
            signal_id for signal_id, unit in required_units.items()
            if signal_id in requested and requested[signal_id] != unit
        )
        if missing:
            raise ValueError("required forecast request is missing: " + ", ".join(missing))
        if mismatched:
            raise ValueError("requested units do not match planner contract: " + ", ".join(mismatched))
        result = self._service.forecast_bundle(
            request,
            model_ids=model_ids,
            initial_history=initial_history,
            backtest_horizon=backtest_horizon,
            season_length=season_length,
            confidence_level=confidence_level,
        )
        return to_planning_forecast(result, required_units=required_units)

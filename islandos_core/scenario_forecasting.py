"""Transparent seasonal-naive forecasting for hourly microgrid signals.

This is a deterministic baseline, not a trained or site-validated AI model.
It forecasts from prior observations only and is intended as a benchmark
before more advanced models are evaluated with chronological backtesting.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Sequence


@dataclass(frozen=True)
class ForecastMetrics:
    samples: int
    mae: float
    rmse: float
    wape_percent: float | None


def _validated_series(values: Sequence[float], name: str, *, minimum: int = 1) -> list[float]:
    if isinstance(values, (str, bytes)):
        raise ValueError(f"{name} must be a numeric sequence")
    try:
        result = list(values)
    except TypeError as exc:
        raise ValueError(f"{name} must be a numeric sequence") from exc
    if len(result) < minimum:
        raise ValueError(f"{name} requires at least {minimum} observations")
    clean: list[float] = []
    for index, value in enumerate(result):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name}[{index}] must be numeric")
        number = float(value)
        if not math.isfinite(number) or number < 0:
            raise ValueError(f"{name}[{index}] must be finite and non-negative")
        clean.append(number)
    return clean


def seasonal_naive_forecast(
    history: Sequence[float], horizon: int, *, season_length: int = 24
) -> list[float]:
    """Repeat the most recent observed seasonal profile; never reads future values."""
    values = _validated_series(history, "history", minimum=1)
    if isinstance(horizon, bool) or not isinstance(horizon, int) or horizon < 1:
        raise ValueError("horizon must be a positive integer")
    if isinstance(season_length, bool) or not isinstance(season_length, int) or season_length < 1:
        raise ValueError("season_length must be a positive integer")
    profile_length = min(season_length, len(values))
    profile = values[-profile_length:]
    return [profile[index % profile_length] for index in range(horizon)]


def evaluate_forecast(actual: Sequence[float], predicted: Sequence[float]) -> ForecastMetrics:
    """Calculate MAE, RMSE and WAPE; WAPE is undefined for all-zero actuals."""
    truth = _validated_series(actual, "actual", minimum=1)
    estimate = _validated_series(predicted, "predicted", minimum=1)
    if len(truth) != len(estimate):
        raise ValueError("actual and predicted must have equal lengths")
    errors = [guess - observed for observed, guess in zip(truth, estimate)]
    mae = sum(abs(error) for error in errors) / len(errors)
    rmse = math.sqrt(sum(error * error for error in errors) / len(errors))
    denominator = sum(truth)
    wape = None if denominator == 0 else sum(abs(error) for error in errors) / denominator * 100.0
    return ForecastMetrics(samples=len(truth), mae=mae, rmse=rmse, wape_percent=wape)


def rolling_origin_evaluate(
    series: Sequence[float], *, initial_history: int = 48, horizon: int = 24,
    season_length: int = 24,
) -> ForecastMetrics:
    """Evaluate non-overlapping chronological folds using prior observations only."""
    values = _validated_series(series, "series", minimum=2)
    for name, value in (("initial_history", initial_history), ("horizon", horizon),
                        ("season_length", season_length)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{name} must be a positive integer")
    if initial_history >= len(values):
        raise ValueError("initial_history must be shorter than series")
    actual_all: list[float] = []
    predicted_all: list[float] = []
    cutoff = initial_history
    while cutoff < len(values):
        fold_horizon = min(horizon, len(values) - cutoff)
        predicted_all.extend(seasonal_naive_forecast(
            values[:cutoff], fold_horizon, season_length=season_length
        ))
        actual_all.extend(values[cutoff:cutoff + fold_horizon])
        cutoff += fold_horizon
    return evaluate_forecast(actual_all, predicted_all)



def generate_synthetic_microgrid_history(
    *, pv_peak_kw: float, wind_mean_kw: float, essential_load_mean_kw: float,
    water_demand_mean_m3_per_hour: float, hours: int = 168,
) -> dict[str, list[float]]:
    """Create a deterministic, deliberately non-stationary synthetic hourly history.

    Day-to-day variation makes replay metrics non-trivial; this is test/demo
    data only and must never be represented as measured site history.
    """
    parameters = {
        "pv_peak_kw": pv_peak_kw,
        "wind_mean_kw": wind_mean_kw,
        "essential_load_mean_kw": essential_load_mean_kw,
        "water_demand_mean_m3_per_hour": water_demand_mean_m3_per_hour,
    }
    for name, value in parameters.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name} must be numeric")
        if not math.isfinite(float(value)) or value < 0:
            raise ValueError(f"{name} must be finite and non-negative")
    if isinstance(hours, bool) or not isinstance(hours, int) or hours < 25:
        raise ValueError("hours must be an integer >= 25")

    history = {"pv_kw": [], "wind_kw": [], "essential_load_kw": [], "water_demand_m3": []}
    for index in range(hours):
        hour = index % 24
        day_index = index // 24
        solar_shape = max(0.0, math.sin(math.pi * (hour - 6) / 12.0))
        solar_day_factor = 0.88 + 0.12 * math.sin(day_index * 0.83 + 0.2)
        history["pv_kw"].append(float(pv_peak_kw) * solar_shape * solar_day_factor)
        wind_factor = 0.75 + 0.25 * math.sin(index * 0.41 + 0.7)
        history["wind_kw"].append(max(0.0, float(wind_mean_kw) * wind_factor))
        load_day_factor = 0.96 + 0.06 * math.sin(day_index * 0.71 + 0.4)
        load_factor = load_day_factor * (
            1.0 + 0.08 * math.sin(2 * math.pi * (hour - 8) / 24.0)
        )
        history["essential_load_kw"].append(
            float(essential_load_mean_kw) * load_factor
        )
        water_day_factor = 0.92 + 0.12 * math.sin(day_index * 0.67 + 0.9)
        water_peak_factor = 1.0 + 0.08 * (
            hour in range(6, 9) or hour in range(18, 21)
        )
        history["water_demand_m3"].append(
            float(water_demand_mean_m3_per_hour) * water_day_factor * water_peak_factor
        )
    return history

def forecast_microgrid_signals(
    history: Mapping[str, Sequence[float]], horizon: int, *, season_length: int = 24
) -> dict[str, list[float]]:
    """Forecast named hourly signals using the same transparent baseline."""
    if not isinstance(history, Mapping) or not history:
        raise ValueError("history must be a non-empty mapping of signal names to series")
    forecasts: dict[str, list[float]] = {}
    for name, values in history.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError("signal names must be non-empty strings")
        forecasts[name] = seasonal_naive_forecast(
            values, horizon, season_length=season_length
        )
    return forecasts

"""Evidence-gated multi-signal hourly forecasting for IslandOS.

The engine compares persistence and seasonal-naive baselines with a small
ridge-regression autoregressive model. A learned model is selected only when
it beats the strongest baseline on a chronological holdout. This is a
prototype forecast service, not a site-calibrated model or controller.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Mapping, Sequence

import numpy as np


@dataclass(frozen=True)
class ForecastPoint:
    timestamp: datetime
    predicted: float
    lower_bound: float
    upper_bound: float


@dataclass(frozen=True)
class ForecastMetrics:
    samples: int
    mae: float
    rmse: float
    bias_predicted_minus_actual: float


@dataclass(frozen=True)
class SignalForecast:
    signal_name: str
    unit: str
    model_id: str
    model_version: str
    points: tuple[ForecastPoint, ...]
    holdout_metrics: ForecastMetrics
    baseline_metrics: Mapping[str, ForecastMetrics]
    selected_model_beats_baseline: bool
    uncertainty_method: str
    residual_abs_error_p90: float


@dataclass(frozen=True)
class ForecastBundle:
    input_history_sha256: str
    history_start_utc: datetime
    history_end_utc: datetime
    forecasts: Mapping[str, SignalForecast]


def _finite_series(values: Sequence[float], name: str) -> list[float]:
    if isinstance(values, (str, bytes)):
        raise ValueError(f"{name} must be a numeric sequence")
    try:
        raw = list(values)
    except TypeError as exc:
        raise ValueError(f"{name} must be a numeric sequence") from exc
    if len(raw) < 72:
        raise ValueError(f"{name} requires at least 72 hourly observations")
    clean = []
    for index, value in enumerate(raw):
        if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.number)):
            raise ValueError(f"{name}[{index}] must be numeric")
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f"{name}[{index}] must be finite")
        clean.append(number)
    return clean


def _timestamps(values: Sequence[datetime]) -> list[datetime]:
    stamps = list(values)
    if len(stamps) < 72:
        raise ValueError("At least 72 hourly timestamps are required")
    normalized = []
    for stamp in stamps:
        if not isinstance(stamp, datetime) or stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError("All timestamps must be timezone-aware datetimes")
        normalized.append(stamp.astimezone(timezone.utc))
    for left, right in zip(normalized, normalized[1:]):
        if right - left != timedelta(hours=1):
            raise ValueError("Timestamps must be strictly ordered, contiguous hourly instants")
    return normalized


def _metrics(actual: Sequence[float], predicted: Sequence[float]) -> ForecastMetrics:
    if len(actual) != len(predicted) or not actual:
        raise ValueError("Metric inputs must be non-empty and have equal lengths")
    errors = [float(p) - float(a) for a, p in zip(actual, predicted)]
    return ForecastMetrics(
        samples=len(errors),
        mae=sum(abs(error) for error in errors) / len(errors),
        rmse=math.sqrt(sum(error * error for error in errors) / len(errors)),
        bias_predicted_minus_actual=sum(errors) / len(errors),
    )


def _baseline(history: Sequence[float], horizon: int, kind: str) -> list[float]:
    if kind == "persistence":
        return [float(history[-1])] * horizon
    if kind == "seasonal_naive_24h":
        profile = list(history[-24:])
        return [float(profile[i % 24]) for i in range(horizon)]
    raise ValueError(f"Unknown baseline: {kind}")


def _features(history: Sequence[float], target_index: int, stamp: datetime) -> list[float]:
    # target_index is the index of the value being predicted in the full series.
    lags = (1, 2, 3, 24, 48)
    row = [float(history[target_index - lag]) for lag in lags]
    hour = stamp.hour + stamp.minute / 60.0
    weekday = stamp.weekday()
    row.extend((
        math.sin(2.0 * math.pi * hour / 24.0),
        math.cos(2.0 * math.pi * hour / 24.0),
        math.sin(2.0 * math.pi * weekday / 7.0),
        math.cos(2.0 * math.pi * weekday / 7.0),
    ))
    return row


def _fit_ridge(history: Sequence[float], stamps: Sequence[datetime], end_index: int,
               alpha: float = 10.0) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rows = [_features(history, i, stamps[i]) for i in range(48, end_index)]
    targets = np.asarray(history[48:end_index], dtype=float)
    x = np.asarray(rows, dtype=float)
    mean = x.mean(axis=0)
    scale = x.std(axis=0)
    scale[scale < 1e-9] = 1.0
    standardized = (x - mean) / scale
    design = np.column_stack((np.ones(len(standardized)), standardized))
    penalty = np.eye(design.shape[1]) * alpha
    penalty[0, 0] = 0.0
    coefficients = np.linalg.solve(design.T @ design + penalty, design.T @ targets)
    return coefficients, mean, scale


def _ridge_predict_one(history: Sequence[float], stamp: datetime,
                       coefficients: np.ndarray, mean: np.ndarray,
                       scale: np.ndarray) -> float:
    row = np.asarray(_features(history, len(history), stamp), dtype=float)
    standardized = (row - mean) / scale
    design = np.concatenate(([1.0], standardized))
    return float(design @ coefficients)


def _clip(value: float, non_negative: bool) -> float:
    return max(0.0, value) if non_negative else value


def _forecast_one_step_holdout(values: Sequence[float], stamps: Sequence[datetime],
                               split: int, non_negative: bool) -> tuple[list[float], list[float] | None]:
    actual = list(values[split:])
    persistence = _baseline(values[:split], len(actual), "persistence")
    seasonal = [
        float(values[index - 24]) for index in range(split, len(values))
    ]
    baseline_predictions = {
        "persistence": [_clip(v, non_negative) for v in persistence],
        "seasonal_naive_24h": [_clip(v, non_negative) for v in seasonal],
    }
    best_name = min(
        baseline_predictions,
        key=lambda name: _metrics(actual, baseline_predictions[name]).mae,
    )
    best_predictions = baseline_predictions[best_name]
    ridge_predictions = None
    if split >= 72:
        try:
            coefficients, mean, scale = _fit_ridge(values, stamps, split)
            rolling_history = list(values[:split])
            ridge_predictions = []
            for stamp in stamps[split:]:
                prediction = _clip(
                    _ridge_predict_one(rolling_history, stamp, coefficients, mean, scale),
                    non_negative,
                )
                ridge_predictions.append(prediction)
                rolling_history.append(prediction)
        except (np.linalg.LinAlgError, ValueError, FloatingPointError):
            ridge_predictions = None
    return best_predictions, ridge_predictions


def _forecast_signal(name: str, unit: str, values: Sequence[float],
                     stamps: Sequence[datetime], horizon: int,
                     non_negative: bool) -> SignalForecast:
    series = _finite_series(values, name)
    if not isinstance(unit, str) or not unit.strip():
        raise ValueError(f"{name} unit must be a non-empty string")
    if isinstance(horizon, bool) or not isinstance(horizon, int) or not 1 <= horizon <= 168:
        raise ValueError("horizon must be an integer from 1 to 168 hours")
    if not isinstance(non_negative, bool):
        raise ValueError("non_negative must be a boolean")

    split = max(48, int(len(series) * 0.8))
    if split >= len(series):
        split = len(series) - 1
    actual = series[split:]
    baseline_predictions = {
        "persistence": [_clip(v, non_negative) for v in _baseline(series[:split], len(actual), "persistence")],
        "seasonal_naive_24h": [
            _clip(value, non_negative)
            for value in _baseline(series[:split], len(actual), "seasonal_naive_24h")
        ],
    }
    baseline_metrics = {
        name: _metrics(actual, predictions)
        for name, predictions in baseline_predictions.items()
    }
    best_baseline_name = min(baseline_metrics, key=lambda name: baseline_metrics[name].mae)
    best_baseline_predictions = baseline_predictions[best_baseline_name]

    ridge_predictions = None
    if split >= 72:
        try:
            coefficients, mean, scale = _fit_ridge(series, stamps, split)
            rolling_history = list(series[:split])
            ridge_predictions = []
            for stamp in stamps[split:]:
                prediction = _clip(
                    _ridge_predict_one(rolling_history, stamp, coefficients, mean, scale),
                    non_negative,
                )
                ridge_predictions.append(prediction)
                rolling_history.append(prediction)
        except (np.linalg.LinAlgError, ValueError, FloatingPointError):
            ridge_predictions = None

    if ridge_predictions is not None:
        ridge_metrics = _metrics(actual, ridge_predictions)
        baseline_metrics = dict(baseline_metrics)
        baseline_metrics["ridge_autoregressive"] = ridge_metrics
        if ridge_metrics.mae + 1e-12 < baseline_metrics[best_baseline_name].mae:
            selected_id = "ridge_autoregressive"
            selected_metrics = ridge_metrics
            selected_predictions = ridge_predictions
            selected = True
        else:
            selected_id = best_baseline_name
            selected_metrics = baseline_metrics[best_baseline_name]
            selected_predictions = best_baseline_predictions
            selected = False
    else:
        selected_id = best_baseline_name
        selected_metrics = baseline_metrics[best_baseline_name]
        selected_predictions = best_baseline_predictions
        selected = False

    residuals = [abs(pred - truth) for pred, truth in zip(selected_predictions, actual)]
    residual_p90 = float(np.quantile(np.asarray(residuals, dtype=float), 0.90)) if residuals else 0.0

    future_history = list(series)
    future_points = []
    for offset in range(horizon):
        target_stamp = stamps[-1] + timedelta(hours=offset + 1)
        if selected_id == "ridge_autoregressive" and ridge_predictions is not None:
            prediction = _clip(
                _ridge_predict_one(future_history, target_stamp, coefficients, mean, scale),
                non_negative,
            )
        else:
            prediction = _clip(
                _baseline(future_history, 1, selected_id)[0],
                non_negative,
            )
        lower = prediction - residual_p90
        upper = prediction + residual_p90
        if non_negative:
            lower = max(0.0, lower)
        future_points.append(ForecastPoint(
            timestamp=target_stamp,
            predicted=prediction,
            lower_bound=lower,
            upper_bound=upper,
        ))
        future_history.append(prediction)

    return SignalForecast(
        signal_name=name,
        unit=unit,
        model_id=selected_id,
        model_version="1.0.0",
        points=tuple(future_points),
        holdout_metrics=selected_metrics,
        baseline_metrics=baseline_metrics,
        selected_model_beats_baseline=selected,
        uncertainty_method="chronological_holdout_absolute_error_p90",
        residual_abs_error_p90=residual_p90,
    )


def forecast_signals(
    timestamps: Sequence[datetime],
    history: Mapping[str, Sequence[float]],
    units: Mapping[str, str],
    horizon: int,
    *,
    non_negative_signals: Sequence[str] | None = None,
) -> ForecastBundle:
    """Forecast aligned hourly signals with baseline-gated ridge regression.

    Every signal is evaluated independently against persistence and 24-hour
    seasonal-naive baselines. A ridge model is used only if its chronological
    holdout MAE is strictly lower than the strongest baseline's MAE.
    """
    stamps = _timestamps(timestamps)
    if not isinstance(history, Mapping) or not history:
        raise ValueError("history must be a non-empty mapping of signal names to series")
    if set(history) != set(units):
        raise ValueError("history and units must contain exactly the same signal names")
    non_negative = set(history) if non_negative_signals is None else set(non_negative_signals)
    unknown = non_negative - set(history)
    if unknown:
        raise ValueError("non_negative_signals contains unknown names: " + ", ".join(sorted(unknown)))
    forecasts = {}
    digest_payload = {
        "timestamps_utc": [stamp.isoformat() for stamp in stamps],
        "signals": {},
    }
    for name in sorted(history):
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Signal names must be non-empty strings")
        series = _finite_series(history[name], name)
        if len(series) != len(stamps):
            raise ValueError(f"{name} must have one value for every timestamp")
        digest_payload["signals"][name] = {"unit": units[name], "values": series}
        forecasts[name] = _forecast_signal(
            name, units[name], series, stamps, horizon, name in non_negative
        )
    canonical = json.dumps(digest_payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return ForecastBundle(
        input_history_sha256=digest,
        history_start_utc=stamps[0],
        history_end_utc=stamps[-1],
        forecasts=forecasts,
    )

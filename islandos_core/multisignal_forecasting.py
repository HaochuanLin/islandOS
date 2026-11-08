"""Shared multi-signal forecast contract and leakage-safe rolling backtest.

The engine is model-agnostic: PV, wind, electrical load, water demand, and other
signals use the same timestamp/unit/cadence contract. Prediction intervals are
optional and require a separate chronological calibration residual sample.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime
from statistics import mean
from typing import Protocol, Sequence


@dataclass(frozen=True)
class SignalObservation:
    timestamp: datetime
    signal_id: str
    value: float
    unit: str

    def __post_init__(self) -> None:
        if not isinstance(self.timestamp, datetime):
            raise ValueError("Observation timestamp must be a datetime")
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("Observation timestamps must include a timezone")
        if not isinstance(self.signal_id, str) or not self.signal_id.strip() or self.signal_id != self.signal_id.strip():
            raise ValueError("signal_id must be a non-empty trimmed string")
        if not isinstance(self.unit, str) or not self.unit.strip() or self.unit != self.unit.strip():
            raise ValueError("unit must be a non-empty trimmed string")
        if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
            raise ValueError("Observed signal value must be numeric")
        if not math.isfinite(float(self.value)) or self.value < 0:
            raise ValueError("Observed signal value must be finite and non-negative")


@dataclass(frozen=True)
class SignalForecastRequest:
    signal_id: str
    unit: str
    history: tuple[SignalObservation, ...]
    target_timestamps: tuple[datetime, ...]
    cadence_seconds: int = 3600

    def __post_init__(self) -> None:
        if not isinstance(self.signal_id, str) or not self.signal_id.strip() or self.signal_id != self.signal_id.strip():
            raise ValueError("signal_id must be a non-empty trimmed string")
        if not isinstance(self.unit, str) or not self.unit.strip() or self.unit != self.unit.strip():
            raise ValueError("unit must be a non-empty trimmed string")
        if isinstance(self.cadence_seconds, bool) or not isinstance(self.cadence_seconds, int) or self.cadence_seconds < 1:
            raise ValueError("cadence_seconds must be a positive integer")
        history = tuple(self.history)
        targets = tuple(self.target_timestamps)
        object.__setattr__(self, "history", history)
        object.__setattr__(self, "target_timestamps", targets)
        if not history:
            raise ValueError("Forecast history cannot be empty")
        if not targets:
            raise ValueError("At least one forecast target is required")
        for item in history:
            if not isinstance(item, SignalObservation):
                raise ValueError("history must contain SignalObservation instances")
            if item.signal_id != self.signal_id or item.unit != self.unit:
                raise ValueError("history signal_id and unit must match the request")
        for stamp in targets:
            if not isinstance(stamp, datetime):
                raise ValueError("Forecast targets must be datetime instances")
            if stamp.tzinfo is None or stamp.utcoffset() is None:
                raise ValueError("Forecast target timestamps must include a timezone")
        for left, right in zip(history, history[1:]):
            if (right.timestamp - left.timestamp).total_seconds() != self.cadence_seconds:
                raise ValueError("Forecast history must be strictly ordered at the declared cadence")
        for left, right in zip(targets, targets[1:]):
            if (right - left).total_seconds() != self.cadence_seconds:
                raise ValueError("Forecast targets must be strictly ordered at the declared cadence")
        lead = (targets[0] - history[-1].timestamp).total_seconds()
        if lead != self.cadence_seconds:
            raise ValueError("The first forecast target must be exactly one cadence after the final observation")


class SignalForecastPlugin(Protocol):
    """Implement this protocol to forecast any one signal using past observations."""

    model_id: str
    version: str

    def predict(
        self,
        history: Sequence[SignalObservation],
        target_timestamps: Sequence[datetime],
    ) -> Sequence[float]:
        ...


@dataclass(frozen=True)
class CalibrationResidual:
    """A past out-of-sample prediction error used only for interval calibration."""

    timestamp: datetime
    residual: float

    def __post_init__(self) -> None:
        if not isinstance(self.timestamp, datetime):
            raise ValueError("Calibration residual timestamp must be a datetime")
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("Calibration residual timestamps must include a timezone")
        if isinstance(self.residual, bool) or not isinstance(self.residual, (int, float)):
            raise ValueError("Calibration residual must be numeric")
        if not math.isfinite(float(self.residual)):
            raise ValueError("Calibration residual must be finite")


@dataclass(frozen=True)
class SignalForecastPoint:
    timestamp: datetime
    predicted_value: float
    lower_bound: float | None = None
    upper_bound: float | None = None


@dataclass(frozen=True)
class SignalForecastResult:
    signal_id: str
    unit: str
    cadence_seconds: int
    model_id: str
    model_version: str
    input_history_sha256: str
    points: tuple[SignalForecastPoint, ...]
    interval_coverage: float | None = None
    calibration_sample_count: int = 0
    interval_method: str | None = None


def _history_digest(history: Sequence[SignalObservation]) -> str:
    payload = [
        {
            "timestamp": item.timestamp.isoformat(),
            "signal_id": item.signal_id,
            "value": float(item.value),
            "unit": item.unit,
        }
        for item in history
    ]
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _finite_values(values: Sequence[float], name: str, *, allow_negative: bool = False) -> list[float]:
    if isinstance(values, (str, bytes)):
        raise ValueError(f"{name} must be a numeric sequence")
    try:
        result = list(values)
    except TypeError as exc:
        raise ValueError(f"{name} must be a numeric sequence") from exc
    clean: list[float] = []
    for index, value in enumerate(result):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name}[{index}] must be numeric")
        number = float(value)
        if not math.isfinite(number) or (not allow_negative and number < 0):
            qualifier = "finite" if allow_negative else "finite and non-negative"
            raise ValueError(f"{name}[{index}] must be {qualifier}")
        clean.append(number)
    return clean


def _conformal_radius(residuals: Sequence[CalibrationResidual], coverage: float) -> float:
    """Finite-sample absolute-residual quantile; callers enforce chronology."""
    errors = sorted(abs(float(item.residual)) for item in residuals)
    rank = min(len(errors), max(1, math.ceil((len(errors) + 1) * coverage)))
    return errors[rank - 1]



class PersistenceSignalPlugin:
    """Dependency-free next-step baseline that repeats the latest observation."""

    model_id = "persistence"
    version = "1.0"

    def predict(
        self,
        history: Sequence[SignalObservation],
        target_timestamps: Sequence[datetime],
    ) -> Sequence[float]:
        if not history:
            raise ValueError("Persistence forecast requires non-empty history")
        return [float(history[-1].value)] * len(target_timestamps)


class SeasonalNaiveSignalPlugin:
    """Dependency-free seasonal baseline for any non-negative hourly/sub-hourly signal."""

    model_id = "seasonal_naive"
    version = "1.0"

    def __init__(self, season_length_steps: int = 24) -> None:
        if (
            isinstance(season_length_steps, bool)
            or not isinstance(season_length_steps, int)
            or season_length_steps < 1
        ):
            raise ValueError("season_length_steps must be a positive integer")
        self.season_length_steps = season_length_steps

    def predict(
        self,
        history: Sequence[SignalObservation],
        target_timestamps: Sequence[datetime],
    ) -> Sequence[float]:
        if not history:
            raise ValueError("Seasonal-naive forecast requires non-empty history")
        profile = history[-min(self.season_length_steps, len(history)):]
        return [
            float(profile[index % len(profile)].value)
            for index, _ in enumerate(target_timestamps)
        ]


class SignalForecastRegistry:
    """Register signal-agnostic models and validate predictions/provenance."""

    def __init__(self) -> None:
        self._plugins: dict[str, tuple[SignalForecastPlugin, str]] = {}

    def register(self, plugin: SignalForecastPlugin) -> None:
        model_id = getattr(plugin, "model_id", None)
        version = getattr(plugin, "version", None)
        predict = getattr(plugin, "predict", None)
        if not isinstance(model_id, str) or not model_id.strip() or model_id != model_id.strip():
            raise ValueError("Forecast plugin model_id must be a non-empty, trimmed string")
        if not isinstance(version, str) or not version.strip() or version != version.strip():
            raise ValueError("Forecast plugin version must be a non-empty, trimmed string")
        if not callable(predict):
            raise TypeError("Forecast plugin must implement predict(history, target_timestamps)")
        if model_id in self._plugins:
            raise ValueError(f"Forecast plugin already registered: {model_id}")
        self._plugins[model_id] = (plugin, version)

    def available_models(self) -> tuple[tuple[str, str], ...]:
        return tuple(sorted((key, version) for key, (_, version) in self._plugins.items()))

    def forecast(
        self,
        model_id: str,
        request: SignalForecastRequest,
        *,
        calibration_residuals: Sequence[CalibrationResidual] | None = None,
        interval_coverage: float = 0.90,
    ) -> SignalForecastResult:
        try:
            plugin, registered_version = self._plugins[model_id]
        except KeyError as exc:
            raise KeyError(f"Unknown forecast plugin: {model_id}") from exc

        def check_identity(phase: str) -> None:
            if getattr(plugin, "model_id", None) != model_id or getattr(plugin, "version", None) != registered_version:
                raise ValueError(f"Forecast plugin identity changed {phase} registration")

        check_identity("after")
        raw = plugin.predict(request.history, request.target_timestamps)
        predictions = _finite_values(raw, "predictions")
        check_identity("during")
        if len(predictions) != len(request.target_timestamps):
            raise ValueError(
                f"Plugin {model_id} returned {len(predictions)} predictions for "
                f"{len(request.target_timestamps)} targets"
            )

        radius = None
        calibration_count = 0
        if calibration_residuals is not None:
            if (
                isinstance(interval_coverage, bool)
                or not isinstance(interval_coverage, (int, float))
                or not math.isfinite(float(interval_coverage))
                or not 0.5 < interval_coverage < 1.0
            ):
                raise ValueError("interval_coverage must be greater than 0.5 and less than 1.0")
            residuals = tuple(calibration_residuals)
            if any(not isinstance(item, CalibrationResidual) for item in residuals):
                raise ValueError("calibration_residuals must contain CalibrationResidual instances")
            if len(residuals) < 20:
                raise ValueError("At least 20 prior calibration residuals are required for prediction intervals")
            for previous, current in zip(residuals, residuals[1:]):
                if (current.timestamp - previous.timestamp).total_seconds() <= 0:
                    raise ValueError("Calibration residual timestamps must be strictly increasing")
            if any(item.timestamp >= request.target_timestamps[0] for item in residuals):
                raise ValueError("Calibration residuals must be timestamped before the forecast window")
            radius = _conformal_radius(residuals, float(interval_coverage))
            calibration_count = len(residuals)

        points = tuple(
            SignalForecastPoint(
                timestamp=stamp,
                predicted_value=value,
                lower_bound=max(0.0, value - radius) if radius is not None else None,
                upper_bound=value + radius if radius is not None else None,
            )
            for stamp, value in zip(request.target_timestamps, predictions)
        )
        return SignalForecastResult(
            signal_id=request.signal_id,
            unit=request.unit,
            cadence_seconds=request.cadence_seconds,
            model_id=model_id,
            model_version=registered_version,
            input_history_sha256=_history_digest(request.history),
            points=points,
            interval_coverage=float(interval_coverage) if radius is not None else None,
            calibration_sample_count=calibration_count,
            interval_method="split_conformal_absolute_residual_quantile" if radius is not None else None,
        )


def _metric_summary(actual: Sequence[float], predicted: Sequence[float]) -> dict[str, float | int | None]:
    if not actual or len(actual) != len(predicted):
        raise ValueError("Metric inputs must be non-empty and aligned")
    errors = [guess - observed for observed, guess in zip(actual, predicted)]
    denominator = sum(actual)
    return {
        "samples": len(errors),
        "mae": mean(abs(error) for error in errors),
        "rmse": math.sqrt(mean(error * error for error in errors)),
        "bias_predicted_minus_actual": mean(errors),
        "wape_percent": (
            sum(abs(error) for error in errors) / denominator * 100.0
            if denominator > 0 else None
        ),
        "underforecast_rate": sum(error < 0 for error in errors) / len(errors),
    }


def rolling_origin_backtest(
    observations: Sequence[SignalObservation],
    plugin: SignalForecastPlugin,
    *,
    initial_history: int,
    history_window: int | None = None,
    seasonal_lag_steps: int = 24,
) -> dict[str, object]:
    """Compare a plugin with persistence and seasonal-naive on identical timestamps.

    At each test step the plugin receives only the immediately preceding
    observations. This is a one-step rolling-origin evaluation, not a model
    training routine and not proof of transfer to another site.
    """
    series = tuple(observations)
    if len(series) < 3 or any(not isinstance(item, SignalObservation) for item in series):
        raise ValueError("observations must contain at least three SignalObservation instances")
    first = series[0]
    for previous, current in zip(series, series[1:]):
        if current.signal_id != first.signal_id or current.unit != first.unit:
            raise ValueError("Backtest observations must share signal_id and unit")
        if (current.timestamp - previous.timestamp).total_seconds() <= 0:
            raise ValueError("Backtest timestamps must be strictly increasing")
    cadence = int((series[1].timestamp - series[0].timestamp).total_seconds())
    if cadence < 1 or any(
        (current.timestamp - previous.timestamp).total_seconds() != cadence
        for previous, current in zip(series, series[1:])
    ):
        raise ValueError("Backtest observations must be continuous at one fixed cadence")
    if isinstance(initial_history, bool) or not isinstance(initial_history, int) or not 1 <= initial_history < len(series):
        raise ValueError("initial_history must be between 1 and the number of observations minus one")
    if history_window is not None and (
        isinstance(history_window, bool) or not isinstance(history_window, int) or history_window < 1
    ):
        raise ValueError("history_window must be a positive integer")
    if isinstance(seasonal_lag_steps, bool) or not isinstance(seasonal_lag_steps, int) or seasonal_lag_steps < 1:
        raise ValueError("seasonal_lag_steps must be a positive integer")

    registry = SignalForecastRegistry()
    registry.register(plugin)
    actuals: list[float] = []
    predictions: list[float] = []
    persistence: list[float] = []
    seasonal_actuals: list[float] = []
    seasonal_predictions: list[float] = []
    rows: list[dict[str, object]] = []
    for index in range(initial_history, len(series)):
        start = max(0, index - history_window) if history_window is not None else 0
        history = series[start:index]
        target = series[index]
        request = SignalForecastRequest(
            signal_id=first.signal_id,
            unit=first.unit,
            history=history,
            target_timestamps=(target.timestamp,),
            cadence_seconds=cadence,
        )
        result = registry.forecast(plugin.model_id, request)
        predicted = result.points[0].predicted_value
        persistence_value = history[-1].value
        seasonal_value = series[index - seasonal_lag_steps].value if index >= seasonal_lag_steps else None
        actuals.append(target.value)
        predictions.append(predicted)
        persistence.append(persistence_value)
        if seasonal_value is not None:
            seasonal_actuals.append(target.value)
            seasonal_predictions.append(seasonal_value)
        rows.append({
            "timestamp": target.timestamp.isoformat(),
            "actual": target.value,
            "plugin_forecast": predicted,
            "persistence_baseline": persistence_value,
            "seasonal_naive_baseline": seasonal_value,
            "history_observation_count": len(history),
            "input_history_sha256": result.input_history_sha256,
        })

    model_metrics = _metric_summary(actuals, predictions)
    persistence_metrics = _metric_summary(actuals, persistence)
    seasonal_metrics = (
        _metric_summary(seasonal_actuals, seasonal_predictions)
        if seasonal_actuals else None
    )
    seasonal_plugin_metrics = None
    if seasonal_actuals:
        seasonal_plugin_values = [
            row["plugin_forecast"] for row in rows if row["seasonal_naive_baseline"] is not None
        ]
        seasonal_plugin_metrics = _metric_summary(seasonal_actuals, seasonal_plugin_values)
    baseline_mae = persistence_metrics["mae"]
    skill = 1.0 - model_metrics["mae"] / baseline_mae if baseline_mae > 0 else None
    return {
        "status": "rolling_origin_backtest_completed",
        "signal_id": first.signal_id,
        "unit": first.unit,
        "cadence_seconds": cadence,
        "model_id": plugin.model_id,
        "model_version": plugin.version,
        "training": {
            "initial_history_observations": initial_history,
            "rolling_history_window": history_window,
            "test_samples": len(rows),
            "first_test_timestamp": rows[0]["timestamp"],
            "last_test_timestamp": rows[-1]["timestamp"],
            "one_step_ahead": True,
            "only_prior_observations_passed_to_plugin": True,
        },
        "metrics": {
            "plugin": model_metrics,
            "persistence_baseline": persistence_metrics,
            "seasonal_naive_baseline": seasonal_metrics,
            "plugin_on_seasonal_comparable_window": seasonal_plugin_metrics,
        },
        "skill_vs_persistence_mae": skill,
        "forecast_rows": rows,
        "evaluation_series_sha256": _history_digest(series),
        "limitations": [
            "The plugin receives only prior observations at each rolling-origin step.",
            "The backtest does not train or automatically promote a model.",
            "Results are specific to this signal, unit, cadence, and evaluation series.",
            "A passing software test is not evidence of site forecast accuracy.",
        ],
    }


def forecast_values_for_dispatch(
    result: SignalForecastResult,
    *,
    expected_signal_id: str,
    expected_unit: str,
    target_timestamps: Sequence[datetime],
    bound: str = "point",
) -> tuple[float, ...]:
    """Extract a timestamp-checked point/lower/upper series for a simulator.

    This adapter does not perform unit conversion or dispatch. It fails closed
    on a signal, unit, timestamp, or interval mismatch before values are passed
    to a downstream physical model.
    """
    if not isinstance(result, SignalForecastResult):
        raise ValueError("result must be a SignalForecastResult")
    if result.signal_id != expected_signal_id:
        raise ValueError("Forecast signal_id does not match the dispatch input")
    if result.unit != expected_unit:
        raise ValueError("Forecast unit does not match the dispatch input")
    if bound not in {"point", "lower", "upper"}:
        raise ValueError("bound must be 'point', 'lower', or 'upper'")
    targets = tuple(target_timestamps)
    if tuple(point.timestamp for point in result.points) != targets:
        raise ValueError("Forecast timestamps do not exactly match dispatch target timestamps")
    attribute = {
        "point": "predicted_value",
        "lower": "lower_bound",
        "upper": "upper_bound",
    }[bound]
    values = tuple(getattr(point, attribute) for point in result.points)
    if not values or any(value is None for value in values):
        raise ValueError(f"Forecast {bound} bounds are unavailable; calibrated intervals are required")
    return tuple(float(value) for value in values)

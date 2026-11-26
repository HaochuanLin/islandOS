"""Model-agnostic, evidence-gated prediction engine for IslandOS signals.

The engine compares registered forecast candidates with rolling-origin replay,
selects the lowest-MAE eligible candidate, and emits descriptive empirical
error bands. The default registry contains transparent baselines; a univariate
Ridge autoregression can be enabled explicitly for controlled evaluation.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from numbers import Real
from typing import Protocol, Sequence


@dataclass(frozen=True)
class SignalObservation:
    timestamp: datetime
    value: float

    def __post_init__(self) -> None:
        if not isinstance(self.timestamp, datetime):
            raise ValueError("observation timestamp must be a datetime")
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("observation timestamp must include a timezone")
        if isinstance(self.value, bool) or not isinstance(self.value, Real):
            raise ValueError("observation value must be numeric")
        if not math.isfinite(float(self.value)):
            raise ValueError("observation value must be finite")


@dataclass(frozen=True)
class ForecastRequest:
    signal_id: str
    unit: str
    history: tuple[SignalObservation, ...]
    target_timestamps: tuple[datetime, ...]
    non_negative: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.signal_id, str) or not self.signal_id.strip():
            raise ValueError("signal_id is required")
        if not isinstance(self.unit, str) or not self.unit.strip():
            raise ValueError("unit is required")
        if not isinstance(self.non_negative, bool):
            raise ValueError("non_negative must be a boolean")
        if len(self.history) < 3:
            raise ValueError("at least three historical observations are required")
        if not self.target_timestamps:
            raise ValueError("at least one target timestamp is required")
        if any(not isinstance(item, SignalObservation) for item in self.history):
            raise ValueError("history must contain SignalObservation records")
        if self.non_negative and any(item.value < 0 for item in self.history):
            raise ValueError("signal history must be non-negative")
        history_utc = [item.timestamp.astimezone(timezone.utc) for item in self.history]
        target_utc = []
        for stamp in self.target_timestamps:
            if not isinstance(stamp, datetime) or stamp.tzinfo is None or stamp.utcoffset() is None:
                raise ValueError("target timestamps must be timezone-aware datetimes")
            target_utc.append(stamp.astimezone(timezone.utc))
        cadence = (history_utc[1] - history_utc[0]).total_seconds()
        if cadence <= 0:
            raise ValueError("history timestamps must be strictly increasing")
        if any((right - left).total_seconds() != cadence for left, right in zip(history_utc, history_utc[1:])):
            raise ValueError("history timestamps must have a regular fixed interval")
        if (target_utc[0] - history_utc[-1]).total_seconds() != cadence:
            raise ValueError("first target must follow the final observation by one sampling interval")
        if any((right - left).total_seconds() != cadence for left, right in zip(target_utc, target_utc[1:])):
            raise ValueError("target timestamps must use the same fixed interval as history")


class ForecastCandidate(Protocol):
    model_id: str
    version: str

    def predict(self, history: Sequence[float], horizon: int, *, season_length: int) -> Sequence[float]:
        """Return one numeric point estimate per future interval."""
        ...


class PersistenceCandidate:
    """Repeat the latest observed value as a transparent no-skill baseline."""

    model_id = "persistence"
    version = "1.0"

    def predict(self, history: Sequence[float], horizon: int, *, season_length: int) -> list[float]:
        if not history:
            raise ValueError("history cannot be empty")
        if horizon < 1 or season_length < 1:
            raise ValueError("horizon and season_length must be positive")
        return [float(history[-1])] * horizon


class SeasonalNaiveCandidate:
    model_id = "seasonal_naive"
    version = "1.0"

    def predict(self, history: Sequence[float], horizon: int, *, season_length: int) -> list[float]:
        if not history:
            raise ValueError("history cannot be empty")
        if horizon < 1 or season_length < 1:
            raise ValueError("horizon and season_length must be positive")
        profile = list(history[-min(season_length, len(history)):])
        return [float(profile[index % len(profile)]) for index in range(horizon)]


class RecentMeanCandidate:
    model_id = "recent_mean"
    version = "1.0"

    def predict(self, history: Sequence[float], horizon: int, *, season_length: int) -> list[float]:
        if not history:
            raise ValueError("history cannot be empty")
        if horizon < 1 or season_length < 1:
            raise ValueError("horizon and season_length must be positive")
        window = list(history[-min(season_length, len(history)):])
        mean = sum(window) / len(window)
        return [float(mean)] * horizon


class LinearTrendCandidate:
    model_id = "linear_trend"
    version = "1.0"

    def predict(self, history: Sequence[float], horizon: int, *, season_length: int) -> list[float]:
        if len(history) < 2:
            raise ValueError("linear trend requires at least two observations")
        if horizon < 1 or season_length < 1:
            raise ValueError("horizon and season_length must be positive")
        window = [float(value) for value in history[-min(season_length * 7, len(history)):]]
        x_mean = (len(window) - 1) / 2
        y_mean = sum(window) / len(window)
        denominator = sum((index - x_mean) ** 2 for index in range(len(window)))
        slope = sum((index - x_mean) * (value - y_mean) for index, value in enumerate(window)) / denominator
        intercept = y_mean - slope * x_mean
        return [intercept + slope * (len(window) - 1 + step) for step in range(1, horizon + 1)]


class RidgeAutoregressiveCandidate:
    """Fold-local univariate Ridge autoregression using lagged signal values.

    The candidate is deliberately timestamp-independent: it uses lags 1, 2,
    3 and the configured seasonal lag only. It learns no cross-signal, weather,
    market, or calendar effects. Every call fits from the history supplied to
    that call, so rolling-origin evaluation refits inside each training fold.
    """

    model_id = "ridge_autoregressive_lag_only"

    def __init__(self, ridge_alpha: float = 1.0) -> None:
        if (
            isinstance(ridge_alpha, bool)
            or not isinstance(ridge_alpha, Real)
            or not math.isfinite(float(ridge_alpha))
            or ridge_alpha <= 0
        ):
            raise ValueError("ridge_alpha must be finite and greater than zero")
        self.ridge_alpha = float(ridge_alpha)

    @property
    def version(self) -> str:
        # Hyperparameters are part of the registered identity and provenance.
        return f"1.0.0+alpha{self.ridge_alpha!r}"

    def predict(
        self,
        history: Sequence[float],
        horizon: int,
        *,
        season_length: int,
    ) -> list[float]:
        if isinstance(history, (str, bytes)):
            raise ValueError("history must be a finite numeric sequence")
        if isinstance(horizon, bool) or not isinstance(horizon, int) or horizon < 1:
            raise ValueError("horizon must be a positive integer")
        if (
            isinstance(season_length, bool)
            or not isinstance(season_length, int)
            or season_length < 1
        ):
            raise ValueError("season_length must be a positive integer")

        values = []
        for index, value in enumerate(history):
            if isinstance(value, bool) or not isinstance(value, Real):
                raise ValueError(f"history[{index}] must be finite numeric data")
            number = float(value)
            if not math.isfinite(number):
                raise ValueError(f"history[{index}] must be finite numeric data")
            values.append(number)

        lags = tuple(sorted({1, 2, 3, season_length}))
        max_lag = max(lags)
        minimum_history = max_lag + 8
        if len(values) < minimum_history:
            raise ValueError(
                f"Ridge autoregression requires at least {minimum_history} "
                "history observations for the configured seasonal lag"
            )

        # NumPy is already a locked runtime dependency used by the Phase 2
        # forecast engine. Import lazily so baseline-only callers pay no cost.
        import numpy as np

        train_x = np.asarray([
            [values[index - lag] for lag in lags]
            for index in range(max_lag, len(values))
        ], dtype=float)
        train_y = np.asarray(values[max_lag:], dtype=float)
        if not np.all(np.isfinite(train_x)) or not np.all(np.isfinite(train_y)):
            raise ValueError("Ridge training data contain non-finite values")

        mean = train_x.mean(axis=0)
        scale = train_x.std(axis=0)
        scale[scale < 1e-9] = 1.0
        standardized = (train_x - mean) / scale
        design = np.column_stack((np.ones(len(standardized)), standardized))

        # Augmented least squares implements L2 regularisation while leaving
        # the intercept unpenalised and avoids explicitly inverting X'X.
        penalty = np.eye(design.shape[1], dtype=float) * math.sqrt(self.ridge_alpha)
        penalty[0, 0] = 0.0
        augmented_x = np.vstack((design, penalty))
        augmented_y = np.concatenate((
            train_y,
            np.zeros(design.shape[1], dtype=float),
        ))
        coefficients, *_ = np.linalg.lstsq(augmented_x, augmented_y, rcond=None)
        if not np.all(np.isfinite(coefficients)):
            raise ValueError("Ridge model produced non-finite coefficients")

        extended = list(values)
        predictions = []
        for _ in range(horizon):
            index = len(extended)
            row = np.asarray([extended[index - lag] for lag in lags], dtype=float)
            standardized_row = (row - mean) / scale
            features = np.concatenate(([1.0], standardized_row))
            prediction = float(features @ coefficients)
            if not math.isfinite(prediction):
                raise ValueError("Ridge model produced a non-finite prediction")
            predictions.append(prediction)
            extended.append(prediction)
        return predictions


@dataclass(frozen=True)
class CandidateFoldMetrics:
    fold_index: int
    train_samples: int
    samples: int
    mae: float
    rmse: float
    bias_predicted_minus_actual: float


@dataclass(frozen=True)
class CandidateMetrics:
    model_id: str
    model_version: str
    folds: int
    samples: int
    mae: float
    rmse: float
    wape_percent: float | None
    bias_predicted_minus_actual: float | None = None
    fold_metrics: tuple[CandidateFoldMetrics, ...] = ()


@dataclass(frozen=True)
class ForecastPoint:
    timestamp: datetime
    predicted_value: float
    lower_bound: float
    upper_bound: float


@dataclass(frozen=True)
class PredictionResult:
    signal_id: str
    unit: str
    model_id: str
    model_version: str
    input_history_sha256: str
    confidence_level: float
    interval_method: str
    interval_calibration_samples: int
    backtest: CandidateMetrics
    points: tuple[ForecastPoint, ...]
    limitations: tuple[str, ...]


def _validate_predictions(values: Sequence[float], horizon: int, *, non_negative: bool) -> list[float]:
    try:
        predictions = list(values)
    except TypeError as exc:
        raise ValueError("candidate output must be a numeric sequence") from exc
    if len(predictions) != horizon:
        raise ValueError(f"candidate returned {len(predictions)} values for horizon {horizon}")
    clean = []
    for index, value in enumerate(predictions):
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ValueError(f"candidate prediction {index} must be numeric")
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f"candidate prediction {index} must be finite")
        if non_negative and number < 0:
            raise ValueError(f"candidate prediction {index} cannot be negative for this signal")
        clean.append(number)
    return clean


def _metrics(actual: Sequence[float], predicted: Sequence[float]) -> tuple[float, float, float, float | None]:
    if not actual or len(actual) != len(predicted):
        raise ValueError("actual and predicted must have equal non-empty lengths")
    errors = [float(guess) - float(truth) for truth, guess in zip(actual, predicted)]
    mae = sum(abs(error) for error in errors) / len(errors)
    rmse = math.sqrt(sum(error * error for error in errors) / len(errors))
    denominator = sum(abs(float(value)) for value in actual)
    bias = sum(errors) / len(errors)
    wape = None if denominator == 0 else sum(abs(error) for error in errors) / denominator * 100.0
    return mae, rmse, bias, wape


def _history_digest(request: ForecastRequest) -> str:
    payload = {
        "signal_id": request.signal_id,
        "unit": request.unit,
        "non_negative": request.non_negative,
        "history": [
            {"timestamp_utc": item.timestamp.astimezone(timezone.utc).isoformat(), "value": float(item.value)}
            for item in request.history
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _select_fold_indices(total_folds: int, max_folds: int | None) -> tuple[int, ...]:
    """Select deterministic, evenly spaced zero-based fold indices.

    When sampling is required, both the first and last complete folds are
    retained. A None limit preserves exhaustive evaluation for library callers.
    """
    if isinstance(total_folds, bool) or not isinstance(total_folds, int) or total_folds < 0:
        raise ValueError("total_folds must be a non-negative integer")
    if total_folds == 0:
        return ()
    if max_folds is None:
        return tuple(range(total_folds))
    if isinstance(max_folds, bool) or not isinstance(max_folds, int) or max_folds < 1:
        raise ValueError("max_folds must be a positive integer or None")
    if max_folds >= total_folds:
        return tuple(range(total_folds))
    if max_folds < 2:
        raise ValueError("max_folds must be at least 2 when sampling multiple complete folds")
    return tuple(
        (index * (total_folds - 1)) // (max_folds - 1)
        for index in range(max_folds)
    )

class PredictionEngine:
    """Register candidates, compare them chronologically, and emit empirical error bands."""

    def __init__(
        self,
        *,
        include_builtin_candidates: bool = True,
        include_ridge_candidate: bool = False,
    ) -> None:
        if not isinstance(include_builtin_candidates, bool):
            raise ValueError("include_builtin_candidates must be a boolean")
        if not isinstance(include_ridge_candidate, bool):
            raise ValueError("include_ridge_candidate must be a boolean")
        self._candidates: dict[str, tuple[ForecastCandidate, str]] = {}
        if include_builtin_candidates:
            for candidate in (
                PersistenceCandidate(),
                SeasonalNaiveCandidate(),
                RecentMeanCandidate(),
                LinearTrendCandidate(),
            ):
                self.register(candidate)
        if include_ridge_candidate:
            self.register(RidgeAutoregressiveCandidate())

    def register(self, candidate: ForecastCandidate) -> None:
        model_id = getattr(candidate, "model_id", None)
        version = getattr(candidate, "version", None)
        predict = getattr(candidate, "predict", None)
        if not isinstance(model_id, str) or not model_id.strip() or model_id != model_id.strip():
            raise ValueError("candidate model_id must be a non-empty trimmed string")
        if not isinstance(version, str) or not version.strip() or version != version.strip():
            raise ValueError("candidate version must be a non-empty trimmed string")
        if not callable(predict):
            raise TypeError("candidate must implement predict(history, horizon, season_length=...)")
        if model_id in self._candidates:
            raise ValueError(f"candidate already registered: {model_id}")
        self._candidates[model_id] = (candidate, version)

    def available_candidates(self) -> tuple[tuple[str, str], ...]:
        return tuple(sorted((key, value[1]) for key, value in self._candidates.items()))

    def predict_candidate(
        self,
        request: ForecastRequest,
        model_id: str,
        *,
        season_length: int = 24,
    ) -> tuple[float, ...]:
        """Forecast one registered candidate from history only, without scoring targets.

        The request contains historical observations and target timestamps, but no
        target actuals. Callers can score the returned values separately once the
        target observations become available, keeping forecast generation isolated
        from holdout evaluation.
        """
        if not isinstance(request, ForecastRequest):
            raise TypeError("request must be a ForecastRequest")
        if not isinstance(model_id, str) or model_id not in self._candidates:
            raise KeyError(f"unknown forecast candidate: {model_id}")
        if (
            isinstance(season_length, bool)
            or not isinstance(season_length, int)
            or season_length < 1
        ):
            raise ValueError("season_length must be a positive integer")
        values = tuple(float(item.value) for item in request.history)
        return tuple(self._predict(
            model_id,
            values,
            len(request.target_timestamps),
            season_length=season_length,
            non_negative=request.non_negative,
        ))

    def _predict(
        self,
        model_id: str,
        history: Sequence[float],
        horizon: int,
        *,
        season_length: int,
        non_negative: bool,
    ) -> list[float]:
        candidate, registered_version = self._candidates[model_id]

        def verify_identity(phase: str) -> None:
            current_id = getattr(candidate, "model_id", None)
            current_version = getattr(candidate, "version", None)
            if current_id != model_id or current_version != registered_version:
                raise ValueError(
                    f"candidate identity changed {phase} prediction: expected "
                    f"{model_id!r}@{registered_version!r}, got "
                    f"{current_id!r}@{current_version!r}"
                )

        verify_identity("before")
        raw = candidate.predict(history, horizon, season_length=season_length)
        predictions = _validate_predictions(raw, horizon, non_negative=non_negative)
        verify_identity("during")
        return predictions

    def _replay(
        self,
        model_id: str,
        values: Sequence[float],
        *,
        initial_history: int,
        horizon: int,
        season_length: int,
        non_negative: bool,
        fold_indices: Sequence[int] | None = None,
    ) -> tuple[CandidateMetrics, list[float]]:
        candidate, version = self._candidates[model_id]
        actual_all: list[float] = []
        predicted_all: list[float] = []
        total_folds = (len(values) - initial_history) // horizon
        selected_fold_indices = (
            tuple(range(total_folds)) if fold_indices is None else tuple(fold_indices)
        )
        fold_metrics = []
        for original_fold_index in selected_fold_indices:
            # Preserve each sampled fold's original chronological position.
            # Training expands only through observations before that block.
            cutoff = initial_history + original_fold_index * horizon
            train = values[:cutoff]
            predicted = self._predict(
                model_id, train, horizon,
                season_length=season_length, non_negative=non_negative,
            )
            actual = [
                float(value) for value in values[cutoff:cutoff + horizon]
            ]
            fold_mae, fold_rmse, fold_bias, _ = _metrics(actual, predicted)
            fold_metrics.append(CandidateFoldMetrics(
                fold_index=original_fold_index + 1,
                train_samples=len(train),
                samples=len(actual),
                mae=fold_mae,
                rmse=fold_rmse,
                bias_predicted_minus_actual=fold_bias,
            ))
            actual_all.extend(actual)
            predicted_all.extend(predicted)
        mae, rmse, bias, wape = _metrics(actual_all, predicted_all)
        return CandidateMetrics(
            model_id=model_id,
            model_version=version,
            folds=len(fold_metrics),
            samples=len(actual_all),
            mae=mae,
            rmse=rmse,
            wape_percent=wape,
            bias_predicted_minus_actual=bias,
            fold_metrics=tuple(fold_metrics),
        ), [
            abs(guess - truth) for truth, guess in zip(actual_all, predicted_all)
        ]

    def evaluate_candidates(
        self,
        history: Sequence[float],
        *,
        initial_history: int,
        horizon: int = 24,
        season_length: int = 24,
        non_negative: bool = True,
        max_folds: int | None = None,
    ) -> tuple[CandidateMetrics, ...]:
        values = list(history)
        if (
            len(values) < 3
            or isinstance(initial_history, bool)
            or not isinstance(initial_history, int)
            or initial_history < 2
            or initial_history >= len(values)
        ):
            raise ValueError("history requires at least three values and initial_history must be an integer in [2, len(history))")
        if isinstance(horizon, bool) or not isinstance(horizon, int) or horizon < 1:
            raise ValueError("horizon must be a positive integer")
        if len(values) - initial_history < horizon:
            raise ValueError(
                f"history must contain at least one complete {horizon}-hour validation block "
                "after initial_history"
            )
        if isinstance(season_length, bool) or not isinstance(season_length, int) or season_length < 1:
            raise ValueError("season_length must be a positive integer")
        if not isinstance(non_negative, bool):
            raise ValueError("non_negative must be a boolean")
        if max_folds is not None and (
            isinstance(max_folds, bool) or not isinstance(max_folds, int) or max_folds < 1
        ):
            raise ValueError("max_folds must be a positive integer or None")
        for index, value in enumerate(values):
            if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(float(value)):
                raise ValueError(f"history[{index}] must be finite numeric data")
            if non_negative and value < 0:
                raise ValueError(f"history[{index}] cannot be negative for this signal")
        if not self._candidates:
            raise ValueError("no forecast candidates are registered")
        available_folds = (len(values) - initial_history) // horizon
        selected_fold_indices = _select_fold_indices(available_folds, max_folds)
        results = []
        for model_id in sorted(self._candidates):
            try:
                metrics, _ = self._replay(
                    model_id, values, initial_history=initial_history, horizon=horizon,
                    season_length=season_length, non_negative=non_negative,
                    fold_indices=selected_fold_indices,
                )
                results.append(metrics)
            except (TypeError, ValueError, ArithmeticError):
                # A candidate that violates the signal contract is ineligible for this signal.
                continue
        if not results:
            raise ValueError("no registered forecast candidate passed the signal contract")
        return tuple(sorted(results, key=lambda item: (item.mae, item.rmse, item.model_id)))

    def forecast(
        self,
        request: ForecastRequest,
        *,
        model_id: str | None = None,
        initial_history: int | None = None,
        backtest_horizon: int = 24,
        season_length: int = 24,
        confidence_level: float = 0.90,
    ) -> PredictionResult:
        if not isinstance(request, ForecastRequest):
            raise TypeError("request must be a ForecastRequest")
        if isinstance(confidence_level, bool) or not isinstance(confidence_level, Real) or not 0 < confidence_level < 1:
            raise ValueError("confidence_level must be between 0 and 1")
        values = [float(item.value) for item in request.history]
        cutoff = initial_history if initial_history is not None else min(48, len(values) - 1)
        ranking = self.evaluate_candidates(
            values, initial_history=cutoff, horizon=backtest_horizon,
            season_length=season_length, non_negative=request.non_negative,
        )
        selected_id = model_id or ranking[0].model_id
        if selected_id not in self._candidates:
            raise KeyError(f"unknown forecast candidate: {selected_id}")
        # Replay the explicitly selected candidate before applying the
        # eligibility gate. This preserves identity-integrity and output-contract
        # errors (for example, a mutated plug-in or negative physical output)
        # instead of masking them behind a generic ranking rejection.
        selected_metrics, absolute_errors = self._replay(
            selected_id, values, initial_history=cutoff, horizon=backtest_horizon,
            season_length=season_length, non_negative=request.non_negative,
        )
        _, registered_version = self._candidates[selected_id]
        predictions = self._predict(
            selected_id, values, len(request.target_timestamps),
            season_length=season_length, non_negative=request.non_negative,
        )
        ordered_errors = sorted(absolute_errors)
        # Empirical finite-sample rank over rolling-origin residuals. These
        # same residuals also select the model, so the resulting band is
        # descriptive only and is not independent conformal calibration.
        rank = min(len(ordered_errors), math.ceil((len(ordered_errors) + 1) * confidence_level))
        radius = ordered_errors[max(0, rank - 1)]
        points = []
        for stamp, prediction in zip(request.target_timestamps, predictions):
            lower = prediction - radius
            if request.non_negative:
                lower = max(0.0, lower)
            points.append(ForecastPoint(stamp, prediction, lower, prediction + radius))
        return PredictionResult(
            signal_id=request.signal_id,
            unit=request.unit,
            model_id=selected_id,
            model_version=registered_version,
            input_history_sha256=_history_digest(request),
            confidence_level=float(confidence_level),
            interval_method="empirical symmetric absolute-error quantile from rolling-origin replay; not independently calibrated",
            interval_calibration_samples=len(absolute_errors),
            backtest=selected_metrics,
            points=tuple(points),
            limitations=(
                "The default candidates are transparent baselines; optional Ridge is a univariate lag-only model. "
                "No cross-signal or exogenous effects are learned.",
                "Error bands summarize historical rolling-origin residuals; they are not guaranteed prediction intervals.",
                "Candidate selection and error-band estimation reuse the same rolling-origin replay; bands are descriptive, not independently calibrated.",
                "Backtest skill on supplied history does not establish future accuracy or site-wide operational suitability.",
                "Forecasts are decision-support inputs and do not issue equipment commands.",
            ),
        )

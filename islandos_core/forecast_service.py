"""Coordinated multi-signal forecast bundles for IslandOS.

Each signal is forecast independently with the evidence-gated PredictionEngine.
This service aligns timestamps and produces a reproducible bundle for downstream
optimization; it does not invent missing signals or claim multivariate learning.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Mapping, Sequence

from islandos_core.prediction_engine import (
    ForecastRequest,
    PredictionEngine,
    PredictionResult,
)


@dataclass(frozen=True)
class ForecastBundleRequest:
    requests: tuple[ForecastRequest, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.requests, tuple) or not self.requests:
            raise ValueError("requests must be a non-empty tuple of ForecastRequest values")
        if any(not isinstance(item, ForecastRequest) for item in self.requests):
            raise ValueError("every bundle request must be a ForecastRequest")
        ids = [item.signal_id for item in self.requests]
        if len(ids) != len(set(ids)):
            raise ValueError("signal_id values must be unique within a forecast bundle")
        target_grid = tuple(stamp.astimezone(timezone.utc) for stamp in self.requests[0].target_timestamps)
        history_grid = tuple(stamp.timestamp.astimezone(timezone.utc) for stamp in self.requests[0].history)
        for request in self.requests[1:]:
            if tuple(stamp.astimezone(timezone.utc) for stamp in request.target_timestamps) != target_grid:
                raise ValueError("all signals in a bundle must share the same target timestamps")
            if tuple(item.timestamp.astimezone(timezone.utc) for item in request.history) != history_grid:
                raise ValueError("all signals in a bundle must share the same historical timestamps")


@dataclass(frozen=True)
class ForecastBundleResult:
    bundle_sha256: str
    target_timestamps: tuple[datetime, ...]
    forecasts: Mapping[str, PredictionResult]
    signal_units: Mapping[str, str]
    limitations: tuple[str, ...]


class ForecastService:
    """Run aligned, independent signal forecasts and emit one stable evidence bundle."""

    def __init__(self, engine: PredictionEngine | None = None) -> None:
        self._engine = engine or PredictionEngine()

    def forecast_bundle(
        self,
        request: ForecastBundleRequest,
        *,
        model_ids: Mapping[str, str] | None = None,
        initial_history: int | None = None,
        backtest_horizon: int = 24,
        season_length: int = 24,
        confidence_level: float = 0.90,
    ) -> ForecastBundleResult:
        if not isinstance(request, ForecastBundleRequest):
            raise TypeError("request must be a ForecastBundleRequest")
        selected = dict(model_ids or {})
        known_ids = {item.signal_id for item in request.requests}
        unknown = set(selected) - known_ids
        if unknown:
            raise ValueError("model_ids contains unknown signal IDs: " + ", ".join(sorted(unknown)))

        # Fail the entire bundle if any signal cannot be forecast; partial bundles
        # are unsafe inputs for a multi-resource optimizer.
        forecasts: dict[str, PredictionResult] = {}
        units: dict[str, str] = {}
        for signal_request in sorted(request.requests, key=lambda item: item.signal_id):
            forecasts[signal_request.signal_id] = self._engine.forecast(
                signal_request,
                model_id=selected.get(signal_request.signal_id),
                initial_history=initial_history,
                backtest_horizon=backtest_horizon,
                season_length=season_length,
                confidence_level=confidence_level,
            )
            units[signal_request.signal_id] = signal_request.unit

        target_timestamps = request.requests[0].target_timestamps
        payload = {
            "target_timestamps_utc": [
                stamp.astimezone(timezone.utc).isoformat() for stamp in target_timestamps
            ],
            "forecasts": {
                signal_id: {
                    "unit": units[signal_id],
                    "model_id": result.model_id,
                    "model_version": result.model_version,
                    "input_history_sha256": result.input_history_sha256,
                    "confidence_level": result.confidence_level,
                    "points": [
                        {
                            "timestamp_utc": point.timestamp.astimezone(timezone.utc).isoformat(),
                            "predicted_value": point.predicted_value,
                            "lower_bound": point.lower_bound,
                            "upper_bound": point.upper_bound,
                        }
                        for point in result.points
                    ],
                }
                for signal_id, result in sorted(forecasts.items())
            },
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        return ForecastBundleResult(
            bundle_sha256=digest,
            target_timestamps=target_timestamps,
            forecasts=forecasts,
            signal_units=units,
            limitations=(
                "Signals are forecast independently; cross-signal causal or multivariate effects are not learned.",
                "Every signal must have complete, regular, timestamp-aligned history; missing values are not imputed.",
                "Built-in candidates are statistical baselines, not trained AI models.",
                "Historical backtest performance does not establish future accuracy or site-wide operational suitability.",
                "The bundle is decision-support evidence and does not issue equipment commands.",
            ),
        )

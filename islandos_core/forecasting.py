"""Stable, dependency-free contract for plug-in water-demand forecast models.

This registry validates model inputs and outputs; it does not select, train, or
deploy a model. Candidate promotion remains an offline, evidence-gated decision.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, Sequence


@dataclass(frozen=True)
class WaterObservation:
    timestamp: datetime
    demand_m3: float

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("Observation timestamps must include a timezone")
        if not math.isfinite(self.demand_m3) or self.demand_m3 < 0:
            raise ValueError("Observed demand must be finite and non-negative")


@dataclass(frozen=True)
class ForecastRequest:
    history: tuple[WaterObservation, ...]
    target_timestamps: tuple[datetime, ...]

    def __post_init__(self) -> None:
        if not self.history:
            raise ValueError("Forecast history cannot be empty")
        if not self.target_timestamps:
            raise ValueError("At least one forecast target is required")
        for stamp in self.target_timestamps:
            if stamp.tzinfo is None or stamp.utcoffset() is None:
                raise ValueError("Forecast target timestamps must include a timezone")
        for left, right in zip(self.history, self.history[1:]):
            seconds = (right.timestamp - left.timestamp).total_seconds()
            if seconds != 3600:
                raise ValueError("Forecast history must be strictly ordered hourly data")
        if any(
            (right - left).total_seconds() != 3600
            for left, right in zip(self.target_timestamps, self.target_timestamps[1:])
        ):
            raise ValueError("Forecast targets must be strictly ordered hourly timestamps")
        if self.target_timestamps[0] <= self.history[-1].timestamp:
            raise ValueError("Forecast targets must be after the final observed timestamp")


class WaterDemandForecastPlugin(Protocol):
    """Implement this protocol to make a model available through the registry."""

    model_id: str
    version: str

    def predict(
        self,
        history: Sequence[WaterObservation],
        target_timestamps: Sequence[datetime],
    ) -> Sequence[float]:
        """Return one non-negative demand estimate per requested timestamp."""
        ...


@dataclass(frozen=True)
class ForecastPoint:
    timestamp: datetime
    predicted_demand_m3: float


@dataclass(frozen=True)
class ForecastResult:
    model_id: str
    model_version: str
    input_history_sha256: str
    points: tuple[ForecastPoint, ...]


def _history_digest(history: Sequence[WaterObservation]) -> str:
    payload = [
        {"timestamp": item.timestamp.isoformat(), "demand_m3": item.demand_m3}
        for item in history
    ]
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ForecastModelRegistry:
    """Register forecast plugins and enforce the shared runtime data contract."""

    def __init__(self) -> None:
        self._plugins: dict[str, WaterDemandForecastPlugin] = {}

    def register(self, plugin: WaterDemandForecastPlugin) -> None:
        model_id = getattr(plugin, "model_id", None)
        version = getattr(plugin, "version", None)
        predict = getattr(plugin, "predict", None)
        if not isinstance(model_id, str) or not model_id.strip():
            raise ValueError("Forecast plugin model_id must be a non-empty string")
        if not isinstance(version, str) or not version.strip():
            raise ValueError("Forecast plugin version must be a non-empty string")
        if not callable(predict):
            raise TypeError("Forecast plugin must implement predict(history, target_timestamps)")
        if model_id in self._plugins:
            raise ValueError(f"Forecast plugin already registered: {model_id}")
        self._plugins[model_id] = plugin

    def available_models(self) -> tuple[tuple[str, str], ...]:
        return tuple(sorted((key, plugin.version) for key, plugin in self._plugins.items()))

    def forecast(self, model_id: str, request: ForecastRequest) -> ForecastResult:
        try:
            plugin = self._plugins[model_id]
        except KeyError as exc:
            raise KeyError(f"Unknown forecast plugin: {model_id}") from exc
        raw_predictions = plugin.predict(request.history, request.target_timestamps)
        predictions = list(raw_predictions)
        if len(predictions) != len(request.target_timestamps):
            raise ValueError(
                f"Plugin {model_id} returned {len(predictions)} predictions for "
                f"{len(request.target_timestamps)} targets"
            )
        points: list[ForecastPoint] = []
        for index, value in enumerate(predictions):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"Plugin {model_id} returned a non-numeric prediction at index {index}")
            number = float(value)
            if not math.isfinite(number) or number < 0:
                raise ValueError(
                    f"Plugin {model_id} predictions must be finite and non-negative (index {index})"
                )
            points.append(ForecastPoint(
                timestamp=request.target_timestamps[index],
                predicted_demand_m3=number,
            ))
        return ForecastResult(
            model_id=plugin.model_id,
            model_version=plugin.version,
            input_history_sha256=_history_digest(request.history),
            points=tuple(points),
        )

"""Normalized signal contract for virtual and future instrument adapters.

This module intentionally has no Streamlit or hardware/protocol dependencies.
It validates data shape and quality metadata; it does not claim sensor accuracy.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from typing import Any, Mapping


_ALLOWED_QUALITIES = {"good", "uncertain", "bad"}


class SignalValidationError(ValueError):
    """Raised when a signal payload cannot safely enter the decision pipeline."""


@dataclass(frozen=True)
class SignalReading:
    """One normalized, timestamped measurement from a sensor or simulator."""

    signal_id: str
    value: float
    unit: str
    timestamp: datetime
    source: str
    quality: str = "good"

    def __post_init__(self) -> None:
        if not self.signal_id.strip():
            raise SignalValidationError("signal_id is required")
        if not math.isfinite(self.value):
            raise SignalValidationError("value must be finite")
        if not self.unit.strip():
            raise SignalValidationError("unit is required")
        if not self.source.strip():
            raise SignalValidationError("source is required")
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise SignalValidationError("timestamp must include a timezone")
        if self.quality not in _ALLOWED_QUALITIES:
            raise SignalValidationError("quality must be one of: " + ", ".join(sorted(_ALLOWED_QUALITIES)))

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "SignalReading":
        """Parse and validate a JSON-like normalized signal payload."""
        required = {"signal_id", "value", "unit", "timestamp", "source"}
        missing = sorted(required - set(payload))
        if missing:
            raise SignalValidationError("missing required fields: " + ", ".join(missing))
        try:
            value = float(payload["value"])
        except (TypeError, ValueError) as exc:
            raise SignalValidationError("value must be numeric") from exc
        timestamp_raw = payload["timestamp"]
        if not isinstance(timestamp_raw, str) or not timestamp_raw.strip():
            raise SignalValidationError("timestamp must be a non-empty ISO-8601 string")
        try:
            timestamp = datetime.fromisoformat(timestamp_raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise SignalValidationError("timestamp must be valid ISO-8601") from exc
        return cls(
            signal_id=str(payload["signal_id"]), value=value, unit=str(payload["unit"]),
            timestamp=timestamp, source=str(payload["source"]),
            quality=str(payload.get("quality", "good")).lower(),
        )

    def to_payload(self) -> dict[str, str | float]:
        """Serialize into a stable JSON-compatible schema."""
        return {
            "signal_id": self.signal_id, "value": self.value, "unit": self.unit,
            "timestamp": self.timestamp.isoformat(), "source": self.source, "quality": self.quality,
        }


def validate_signal_payload(
    payload: Mapping[str, Any], *, expected_unit: str, now: datetime | None = None,
    max_age_seconds: float = 300.0, min_value: float | None = None,
    max_value: float | None = None,
) -> SignalReading:
    """Validate schema, unit, quality, range, and freshness; fail closed on errors.

    The reference time is injectable for deterministic tests. This validates the
    data contract, not sensor calibration, physical accuracy, or site suitability.
    """
    if not expected_unit.strip():
        raise SignalValidationError("expected_unit is required")
    if not math.isfinite(max_age_seconds) or max_age_seconds < 0:
        raise SignalValidationError("max_age_seconds must be finite and >= 0")
    reading = SignalReading.from_payload(payload)
    if reading.unit != expected_unit:
        raise SignalValidationError(f"unit mismatch for {reading.signal_id}: expected {expected_unit}, got {reading.unit}")
    if reading.quality != "good":
        raise SignalValidationError(f"signal {reading.signal_id} quality is {reading.quality}; only good is accepted")
    if min_value is not None and reading.value < min_value:
        raise SignalValidationError(f"{reading.signal_id} is below minimum {min_value}")
    if max_value is not None and reading.value > max_value:
        raise SignalValidationError(f"{reading.signal_id} is above maximum {max_value}")
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None or reference.utcoffset() is None:
        raise SignalValidationError("now must include a timezone")
    age = (reference.astimezone(timezone.utc) - reading.timestamp.astimezone(timezone.utc)).total_seconds()
    if age < 0:
        raise SignalValidationError(f"signal {reading.signal_id} timestamp is in the future")
    if age > max_age_seconds:
        raise SignalValidationError(f"signal {reading.signal_id} is stale ({age:.1f}s > {max_age_seconds:.1f}s)")
    return reading

"""Validate normalized telemetry messages at the IslandOS adapter boundary."""
from __future__ import annotations

from datetime import datetime
import math

SCHEMA_VERSION = "0.1"
SOURCE_TYPES = {"sensor", "meter", "plc", "manual", "public", "forecast", "synthetic"}
QUALITIES = {"good", "uncertain", "bad"}
SIGNALS = {
    "wind_power": {"kW", "min": 0},
    "pv_power": {"kW", "min": 0},
    "critical_load": {"kW", "min": 0},
    "reservoir_usable_volume": {"m3", "min": 0},
    "reservoir_capacity": {"m3", "min": 0},
    "ro_capacity": {"m3/h", "min": 0},
    "ro_specific_energy": {"kWh/m3", "min": 0},
}
REQUIRED = {
    "schema_version", "site_id", "device_id", "signal_id", "observed_at",
    "value", "unit", "quality", "source_type", "raw_reference",
}


def validate_message(message: dict, *, now: datetime | None = None,
                     max_age_seconds: int = 3600) -> list[str]:
    """Return all validation errors; an empty list means contract checks passed.

    This checks message shape and basic plausibility only, not sensor authenticity,
    calibration, engineering safety, or whether the reading reflects reality.
    """
    errors: list[str] = []
    if not isinstance(message, dict):
        return ["message must be a JSON object"]
    missing = sorted(key for key in REQUIRED if key not in message or message[key] is None or message[key] == "")
    if missing:
        errors.append("missing required fields: " + ", ".join(missing))
        return errors
    if message["schema_version"] != SCHEMA_VERSION:
        errors.append(f"unsupported schema_version: {message['schema_version']}")
    for key in ("site_id", "device_id", "signal_id", "raw_reference"):
        if not isinstance(message[key], str) or not message[key].strip():
            errors.append(f"{key} must be a non-empty string")
    signal = message["signal_id"]
    if signal not in SIGNALS:
        errors.append(f"unsupported signal_id: {signal}")
    elif message["unit"] != SIGNALS[signal]["unit"]:
        errors.append(f"unit mismatch for {signal}: expected {SIGNALS[signal]['unit']}")
    if message["quality"] not in QUALITIES:
        errors.append(f"unsupported quality: {message['quality']}")
    elif message["quality"] != "good":
        errors.append(f"quality must be 'good', got {message['quality']}")
    if message["source_type"] not in SOURCE_TYPES:
        errors.append(f"unsupported source_type: {message['source_type']}")
    value = message["value"]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        errors.append("value must be a finite number")
    elif signal in SIGNALS and value < SIGNALS[signal]["min"]:
        errors.append("value is below the allowed minimum")
    try:
        observed = datetime.fromisoformat(message["observed_at"].replace("Z", "+00:00"))
        if observed.tzinfo is None:
            errors.append("observed_at must include a timezone offset")
        else:
            reference = now
            if reference is None:
                from datetime import timezone
                reference = datetime.now(timezone.utc)
            if reference.tzinfo is None:
                errors.append("now must include a timezone")
            else:
                age = (reference - observed).total_seconds()
                if age < -300:
                    errors.append("sample timestamp is more than 5 minutes in the future")
                elif age > max_age_seconds:
                    errors.append(f"sample is stale ({age:.0f}s old; limit {max_age_seconds}s)")
    except (TypeError, ValueError, AttributeError):
        errors.append("observed_at must be a valid ISO-8601 timestamp with timezone")
    if max_age_seconds <= 0:
        errors.append("max_age_seconds must be positive")
    return errors

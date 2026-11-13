"""Validate normalized telemetry messages at the IslandOS adapter boundary."""
from __future__ import annotations

from datetime import datetime, timezone
import math

SCHEMA_VERSION = "0.1"
SOURCE_TYPES = {"sensor", "meter", "plc", "manual", "public", "forecast", "synthetic"}
QUALITIES = {"good", "uncertain", "bad"}
SIGNALS = {
    "wind_power": {"unit": "kW", "min": 0},
    "pv_power": {"unit": "kW", "min": 0},
    "critical_load": {"unit": "kW", "min": 0},
    "reservoir_usable_volume": {"unit": "m3", "min": 0},
    "reservoir_capacity": {"unit": "m3", "min": 0},
    "ro_capacity": {"unit": "m3/h", "min": 0},
    "ro_specific_energy": {"unit": "kWh/m3", "min": 0},
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
    if isinstance(max_age_seconds, bool) or not isinstance(max_age_seconds, int) or max_age_seconds <= 0:
        errors.append("max_age_seconds must be a positive integer")

    missing = sorted(
        key for key in REQUIRED
        if key not in message or message[key] is None or message[key] == ""
    )
    if missing:
        errors.append("missing required fields: " + ", ".join(missing))
        return errors
    if message["schema_version"] != SCHEMA_VERSION:
        errors.append(f"unsupported schema_version: {message['schema_version']}")
    for key in ("site_id", "device_id", "raw_reference"):
        if not isinstance(message[key], str) or not message[key].strip():
            errors.append(f"{key} must be a non-empty string")

    signal = message["signal_id"]
    signal_spec = SIGNALS.get(signal) if isinstance(signal, str) else None
    if signal_spec is None:
        errors.append(f"unsupported signal_id: {signal}")
    elif message["unit"] != signal_spec["unit"]:
        errors.append(f"unit mismatch for {signal}: expected {signal_spec['unit']}")

    quality = message["quality"]
    if not isinstance(quality, str) or quality not in QUALITIES:
        errors.append(f"unsupported quality: {quality}")
    elif quality != "good":
        errors.append(f"quality must be 'good', got {quality}")

    source_type = message["source_type"]
    if not isinstance(source_type, str) or source_type not in SOURCE_TYPES:
        errors.append(f"unsupported source_type: {source_type}")

    value = message["value"]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        errors.append("value must be a finite number")
    elif signal_spec is not None and value < signal_spec["min"]:
        errors.append("value is below the allowed minimum")

    try:
        timestamp_text = message["observed_at"]
        if not isinstance(timestamp_text, str):
            raise ValueError("timestamp must be text")
        normalized_timestamp = timestamp_text[:-1] + "+00:00" if timestamp_text.endswith("Z") else timestamp_text
        observed = datetime.fromisoformat(normalized_timestamp)
        if observed.tzinfo is None or observed.utcoffset() is None:
            errors.append("observed_at must include a timezone offset")
        else:
            reference = now if now is not None else datetime.now(timezone.utc)
            if not isinstance(reference, datetime) or reference.tzinfo is None or reference.utcoffset() is None:
                errors.append("now must include a timezone")
            elif isinstance(max_age_seconds, int) and not isinstance(max_age_seconds, bool) and max_age_seconds > 0:
                age = (reference.astimezone(timezone.utc) - observed.astimezone(timezone.utc)).total_seconds()
                if age < 0:
                    errors.append("sample timestamp is in the future")
                elif age > max_age_seconds:
                    errors.append(f"sample is stale ({age:.0f}s old; limit {max_age_seconds}s)")
    except (TypeError, ValueError, AttributeError, OverflowError):
        errors.append("observed_at must be a valid ISO-8601 timestamp with timezone")

    return errors



def validate_batch(messages, *, now: datetime | None = None,
                   max_age_seconds: int = 3600) -> list[dict]:
    """Validate a batch and quarantine duplicate device/signal/timestamp keys.

    Each result preserves the input index and original message. Duplicate
    identities are all rejected rather than silently selecting one reading.
    """
    if not isinstance(messages, (list, tuple)):
        raise ValueError("messages must be a list or tuple")
    results = []
    seen: dict[tuple, list[int]] = {}
    for index, message in enumerate(messages):
        errors = validate_message(message, now=now, max_age_seconds=max_age_seconds)
        key = None
        if isinstance(message, dict):
            fields = ("site_id", "device_id", "signal_id", "observed_at")
            if all(isinstance(message.get(field), str) and message[field].strip() for field in fields):
                try:
                    timestamp_text = message["observed_at"]
                    timestamp_text = timestamp_text[:-1] + "+00:00" if timestamp_text.endswith("Z") else timestamp_text
                    parsed_timestamp = datetime.fromisoformat(timestamp_text)
                    if parsed_timestamp.tzinfo is not None and parsed_timestamp.utcoffset() is not None:
                        key = (
                            message["site_id"], message["device_id"], message["signal_id"],
                            parsed_timestamp.astimezone(timezone.utc).isoformat(),
                        )
                except (TypeError, ValueError, OverflowError):
                    key = None
        if key is not None:
            prior = seen.setdefault(key, [])
            if prior:
                errors.append("duplicate sample identity; quarantined with rows " +
                              ", ".join(str(item + 1) for item in prior))
                for prior_index in prior:
                    prior_result = results[prior_index]
                    prior_result["errors"].append(
                        "duplicate sample identity; quarantined with row " + str(index + 1)
                    )
                    prior_result["valid"] = False
            prior.append(index)
        results.append({"row": index + 1, "valid": not errors,
                        "errors": list(dict.fromkeys(errors)), "message": message})
    return results

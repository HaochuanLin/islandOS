"""Vendor-neutral telemetry validation and fail-closed control authorization.

This module deliberately does not open sockets or write to plant hardware. It
provides the safety boundary that concrete MQTT/Modbus/serial adapters must use.
The default behavior is recommendation-only and every physical write is denied
unless all explicit interlocks have been satisfied.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
from typing import Any, Mapping, Optional, Tuple


DEFAULT_REQUIRED_FIELDS = (
    "renewable_surplus_kw",
    "water_demand_m3",
    "cooling_demand_kw_th",
)

OPTIONAL_NUMERIC_FIELDS = ("forecast_surplus_kw", "forecast_water_demand_m3")


def _parse_utc(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("timestamp_utc must be a non-empty ISO-8601 string")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError("timestamp_utc must be a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp_utc must include a timezone")
    return parsed.astimezone(timezone.utc)


def load_device_mapping(path: str) -> dict:
    """Load a versioned canonical-field map from a JSON file."""
    import json
    from pathlib import Path

    mapping = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(mapping, dict) or mapping.get("schema_version") != 1:
        raise ValueError("device mapping schema_version must be 1")
    fields = mapping.get("fields")
    if not isinstance(fields, dict) or not fields:
        raise ValueError("device mapping must define a non-empty fields object")
    for canonical, spec in fields.items():
        if not isinstance(canonical, str) or not isinstance(spec, dict):
            raise ValueError("each mapped field must have a name and object definition")
        if not isinstance(spec.get("source_key"), str) or not spec["source_key"]:
            raise ValueError("mapped field %s needs a non-empty source_key" % canonical)
        for option in ("scale", "offset"):
            if option in spec:
                value = spec[option]
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                    raise ValueError("mapped field %s %s must be finite numeric" % (canonical, option))
    return mapping


def apply_device_mapping(payload: Mapping[str, Any], mapping: Mapping[str, Any]) -> dict:
    """Map vendor-specific keys/units to canonical field names before validation."""
    if not isinstance(payload, Mapping):
        raise TypeError("payload must be a mapping")
    fields = mapping.get("fields")
    if not isinstance(fields, Mapping):
        raise ValueError("device mapping must define fields")
    normalized = dict(payload)
    for canonical, spec in fields.items():
        if not isinstance(spec, Mapping) or not isinstance(spec.get("source_key"), str):
            raise ValueError("invalid mapping definition for %s" % canonical)
        source_key = spec["source_key"]
        if source_key not in payload:
            normalized[canonical] = None
            continue
        value = payload[source_key]
        if canonical != "timestamp_utc" and value is not None:
            if isinstance(value, bool):
                normalized[canonical] = value
            else:
                try:
                    normalized[canonical] = float(value) * float(spec.get("scale", 1.0)) + float(spec.get("offset", 0.0))
                except (TypeError, ValueError):
                    normalized[canonical] = value
        else:
            normalized[canonical] = value
    return normalized


@dataclass(frozen=True)
class TelemetryFrame:
    source: str
    timestamp_utc: datetime
    values: Mapping[str, float]
    valid: bool
    errors: Tuple[str, ...]
    warnings: Tuple[str, ...]

    def as_dict(self) -> dict:
        return {
            "source": self.source,
            "timestamp_utc": self.timestamp_utc.isoformat().replace("+00:00", "Z"),
            "values": dict(self.values),
            "valid": self.valid,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }


def validate_telemetry(
    payload: Mapping[str, Any],
    source: str,
    received_at: Optional[datetime] = None,
    required_fields: Tuple[str, ...] = DEFAULT_REQUIRED_FIELDS,
    max_age_seconds: float = 300.0,
    future_tolerance_seconds: float = 30.0,
) -> TelemetryFrame:
    """Validate a vendor-neutral telemetry message without imputing missing data."""
    if not isinstance(payload, Mapping):
        raise TypeError("payload must be a mapping")
    if not str(source).strip():
        raise ValueError("source must be a non-empty identifier")
    if not math.isfinite(float(max_age_seconds)) or max_age_seconds < 0:
        raise ValueError("max_age_seconds must be finite and non-negative")
    if not math.isfinite(float(future_tolerance_seconds)) or future_tolerance_seconds < 0:
        raise ValueError("future_tolerance_seconds must be finite and non-negative")

    errors = []
    warnings = []
    try:
        timestamp = _parse_utc(payload.get("timestamp_utc"))
    except ValueError as exc:
        timestamp = datetime(1970, 1, 1, tzinfo=timezone.utc)
        errors.append(str(exc))

    now = received_at or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("received_at must be timezone-aware")
    now = now.astimezone(timezone.utc)
    age_seconds = (now - timestamp).total_seconds()
    if not errors and age_seconds > max_age_seconds:
        errors.append("telemetry is stale")
    if not errors and age_seconds < -future_tolerance_seconds:
        errors.append("telemetry timestamp is too far in the future")

    values = {}
    for field in required_fields:
        if field not in payload:
            errors.append("missing required field: " + field)
            continue
        raw = payload[field]
        if isinstance(raw, bool):
            errors.append("field must be a finite number: " + field)
            continue
        try:
            number = float(raw)
        except (TypeError, ValueError):
            errors.append("field must be a finite number: " + field)
            continue
        if not math.isfinite(number):
            errors.append("field must be a finite number: " + field)
            continue
        if number < 0:
            errors.append("field must be non-negative: " + field)
            continue
        values[field] = number

    for field in OPTIONAL_NUMERIC_FIELDS:
        if field not in payload or payload[field] in (None, ""):
            continue
        raw = payload[field]
        if isinstance(raw, bool):
            errors.append("optional field must be a finite non-negative number: " + field)
            continue
        try:
            number = float(raw)
        except (TypeError, ValueError):
            errors.append("optional field must be a finite non-negative number: " + field)
            continue
        if not math.isfinite(number) or number < 0:
            errors.append("optional field must be a finite non-negative number: " + field)
            continue
        values[field] = number

    if payload.get("quality_flag") not in (None, "good", "GOOD", True):
        errors.append("source quality flag is not good")
    if not payload.get("device_id"):
        warnings.append("device_id is absent; source identity is not independently verified")
    return TelemetryFrame(
        source=str(source),
        timestamp_utc=timestamp,
        values=values,
        valid=not errors,
        errors=tuple(dict.fromkeys(errors)),
        warnings=tuple(warnings),
    )


@dataclass(frozen=True)
class ControlRequest:
    command: str
    requested_value: float
    minimum: float
    maximum: float
    max_change_per_step: Optional[float] = None


@dataclass(frozen=True)
class SafetyContext:
    telemetry_valid: bool = False
    write_enabled: bool = False
    operator_confirmed: bool = False
    emergency_stop: bool = False
    manual_override: bool = False
    previous_value: Optional[float] = None


@dataclass(frozen=True)
class AuthorizationDecision:
    allowed: bool
    reasons: Tuple[str, ...]
    requested_value: float
    approved_value: Optional[float]

    def as_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "reasons": list(self.reasons),
            "requested_value": self.requested_value,
            "approved_value": self.approved_value,
            "physical_write_performed": False,
        }


def authorize_control(request: ControlRequest, context: SafetyContext) -> AuthorizationDecision:
    """Fail-closed interlock evaluation; it never performs a hardware write."""
    reasons = []

    def finite_number(value):
        if isinstance(value, bool):
            return False
        try:
            return math.isfinite(float(value))
        except (TypeError, ValueError, OverflowError):
            return False

    command_ok = isinstance(request.command, str) and bool(request.command.strip())
    if not command_ok:
        reasons.append("command identifier is required")

    request_numbers_ok = all(finite_number(v) for v in (
        request.requested_value, request.minimum, request.maximum
    ))
    if not request_numbers_ok:
        reasons.append("requested value and limits must be finite numbers")

    requested = float(request.requested_value) if finite_number(request.requested_value) else None
    minimum = float(request.minimum) if finite_number(request.minimum) else None
    maximum = float(request.maximum) if finite_number(request.maximum) else None
    if request_numbers_ok and minimum > maximum:
        reasons.append("minimum exceeds maximum")
    if request_numbers_ok and not (minimum <= requested <= maximum):
        reasons.append("requested value is outside configured operating limits")

    if request.max_change_per_step is not None:
        if not finite_number(request.max_change_per_step) or float(request.max_change_per_step) < 0:
            reasons.append("maximum change per step must be finite and non-negative")
        elif context.previous_value is None or not finite_number(context.previous_value):
            reasons.append("previous value unavailable for ramp-limit check")
        elif requested is not None and abs(requested - float(context.previous_value)) > float(request.max_change_per_step):
            reasons.append("requested change exceeds configured ramp limit")

    if not context.telemetry_valid:
        reasons.append("telemetry has not passed quality validation")
    if not context.write_enabled:
        reasons.append("physical write path is disabled (recommendation-only mode)")
    if not context.operator_confirmed:
        reasons.append("explicit operator confirmation is required")
    if context.emergency_stop:
        reasons.append("emergency stop is active")
    if context.manual_override:
        reasons.append("manual override is active")

    allowed = not reasons
    return AuthorizationDecision(
        allowed=allowed,
        reasons=tuple(reasons),
        requested_value=requested,
        approved_value=requested if allowed else None,
    )

def build_recommendation(
    command: str,
    requested_value: float,
    unit: str,
    reason: str,
    source: str,
    model_version: str,
    created_at: Optional[datetime] = None,
) -> dict:
    """Create an explainable recommendation record, not a command to hardware."""
    value = float(requested_value)
    if not math.isfinite(value):
        raise ValueError("requested_value must be finite")
    if not command.strip() or not unit.strip() or not reason.strip() or not source.strip():
        raise ValueError("command, unit, reason and source must be non-empty")
    timestamp = created_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("created_at must be timezone-aware")
    return {
        "kind": "recommendation_only",
        "command": command,
        "requested_value": value,
        "unit": unit,
        "reason": reason,
        "source": source,
        "model_version": model_version,
        "created_at_utc": timestamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "operator_action_required": True,
        "physical_write_performed": False,
    }

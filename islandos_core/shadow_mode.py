"""Read-only shadow-mode comparison for forecast recommendations and telemetry.

This module compares an offline recommendation with independently observed
telemetry. It never creates, authorizes, or sends equipment commands.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from numbers import Real
from typing import Mapping


def _utc(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be an ISO-8601 timestamp with timezone")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{name} must be a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _finite_number(value, name):
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be finite numeric data")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite numeric data")
    return number


def compare_shadow_run(
    recommendation: Mapping,
    observation: Mapping,
    *,
    evaluated_at_utc: str,
    max_observation_age_seconds: float = 300.0,
) -> dict:
    """Compare recommendation values with observed values without actuation.

    Expected shape:
      recommendation = {
        "recommendation_id": "...",
        "created_at_utc": "...",
        "signals": {"battery_power_kw": {"value": 4.0, "unit": "kW"}}
      }
      observation = {
        "observation_id": "...",
        "timestamp_utc": "...",
        "signals": {"battery_power_kw": {"value": 3.7, "unit": "kW",
                                         "tolerance": 0.5}}
      }

    Tolerance is declared by the caller from the sensor/asset specification.
    Missing signals, unit mismatch, stale/future observations and invalid values
    fail closed. A deviation is reported for operator review, never auto-corrected.
    """
    if not isinstance(recommendation, Mapping) or not isinstance(observation, Mapping):
        raise TypeError("recommendation and observation must be mappings")
    recommendation_id = recommendation.get("recommendation_id")
    observation_id = observation.get("observation_id")
    if not isinstance(recommendation_id, str) or not recommendation_id.strip():
        raise ValueError("recommendation_id is required")
    if not isinstance(observation_id, str) or not observation_id.strip():
        raise ValueError("observation_id is required")

    now = _utc(evaluated_at_utc, "evaluated_at_utc")
    created = _utc(recommendation.get("created_at_utc"), "created_at_utc")
    observed_at = _utc(observation.get("timestamp_utc"), "timestamp_utc")
    max_age = _finite_number(max_observation_age_seconds, "max_observation_age_seconds")
    if max_age < 0:
        raise ValueError("max_observation_age_seconds must be non-negative")
    age = (now - observed_at).total_seconds()

    recommended_signals = recommendation.get("signals")
    observed_signals = observation.get("signals")
    if not isinstance(recommended_signals, Mapping) or not recommended_signals:
        raise ValueError("recommendation signals must be a non-empty mapping")
    if not isinstance(observed_signals, Mapping) or not observed_signals:
        raise ValueError("observation signals must be a non-empty mapping")

    checks = []
    errors = []
    if created > now:
        errors.append("recommendation timestamp is in the future")
    if age < -30:
        errors.append("observation timestamp is in the future")
    elif age > max_age:
        errors.append("observation is stale")
    missing = sorted(set(recommended_signals) - set(observed_signals))
    if missing:
        errors.append("missing observed signals: " + ", ".join(missing))

    for signal_id in sorted(recommended_signals):
        expected = recommended_signals[signal_id]
        actual = observed_signals.get(signal_id)
        if not isinstance(signal_id, str) or not signal_id.strip():
            errors.append("signal IDs must be non-empty strings")
            continue
        if not isinstance(expected, Mapping) or not isinstance(actual, Mapping):
            errors.append(f"{signal_id}: signal records must be mappings")
            continue
        expected_unit = expected.get("unit")
        actual_unit = actual.get("unit")
        if not isinstance(expected_unit, str) or not expected_unit.strip():
            errors.append(f"{signal_id}: recommendation unit is required")
            continue
        if actual_unit != expected_unit:
            errors.append(f"{signal_id}: unit mismatch ({actual_unit!r} != {expected_unit!r})")
            continue
        try:
            target = _finite_number(expected.get("value"), f"{signal_id}.recommended_value")
            measured = _finite_number(actual.get("value"), f"{signal_id}.observed_value")
            tolerance = _finite_number(actual.get("tolerance"), f"{signal_id}.tolerance")
            if tolerance < 0:
                raise ValueError(f"{signal_id}.tolerance must be non-negative")
        except ValueError as exc:
            errors.append(str(exc))
            continue
        deviation = measured - target
        checks.append({
            "signal_id": signal_id,
            "unit": expected_unit,
            "recommended_value": target,
            "observed_value": measured,
            "absolute_deviation": abs(deviation),
            "signed_deviation": deviation,
            "tolerance": tolerance,
            "within_tolerance": abs(deviation) <= tolerance,
        })

    if errors:
        status = "blocked"
    elif all(item["within_tolerance"] for item in checks):
        status = "within_tolerance"
    else:
        status = "deviation"

    report = {
        "schema_version": 1,
        "mode": "read_only_shadow_comparison",
        "recommendation_id": recommendation_id,
        "observation_id": observation_id,
        "evaluated_at_utc": now.isoformat().replace("+00:00", "Z"),
        "observation_age_seconds": age,
        "status": status,
        "checks": checks,
        "errors": errors,
        "operator_review_required": status != "within_tolerance",
        "device_write_authorized": False,
        "command_generated": False,
    }
    canonical = json.dumps(report, sort_keys=True, separators=(",", ":"), allow_nan=False)
    report["audit_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return report

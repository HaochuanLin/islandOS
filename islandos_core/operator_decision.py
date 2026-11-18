"""Operator-facing, human-reviewable decision records for offline recommendations.

Records package provenance, constraints, schedules, baseline comparisons and
physical audits. They are not control commands and cannot authorize actuation.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from numbers import Real
from typing import Mapping, Sequence


def _utc(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("created_at_utc must be an ISO-8601 timestamp with timezone")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError("created_at_utc must be a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("created_at_utc must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical(value: Mapping) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def build_operator_decision_record(
    optimization_result: Mapping,
    *,
    site_ref: str,
    recommendation_id: str,
    created_at_utc: str,
    data_provenance: str,
    input_refs: Sequence[str],
    objective_weights: Mapping[str, float],
    operating_constraints: Mapping,
) -> dict:
    """Create a deterministic, hash-addressed record for human review.

    A failed or missing physical audit is marked blocked. A passed audit still
    requires operator approval; this function never creates a device command.
    """
    if not isinstance(optimization_result, Mapping):
        raise TypeError("optimization_result must be a mapping")
    for name, value in (("site_ref", site_ref), ("recommendation_id", recommendation_id),
                        ("data_provenance", data_provenance)):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string")
    refs = list(input_refs)
    if not refs or any(not isinstance(item, str) or not item.strip() for item in refs):
        raise ValueError("input_refs must contain non-empty provenance references")
    if not isinstance(objective_weights, Mapping) or not objective_weights:
        raise ValueError("objective_weights must be a non-empty mapping")
    normalized_weights = {}
    for key, value in objective_weights.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError("objective weight names must be non-empty strings")
        if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(float(value)) or value < 0:
            raise ValueError(f"objective weight {key!r} must be finite and non-negative")
        normalized_weights[key] = float(value)
    if not isinstance(operating_constraints, Mapping):
        raise ValueError("operating_constraints must be a mapping")

    customer_impact = optimization_result.get("customer_impact_assessment")
    if customer_impact is not None:
        if not isinstance(customer_impact, Mapping):
            raise ValueError("customer_impact_assessment must be a mapping")
        gross = customer_impact.get("gross_operating_benefit")
        service = customer_impact.get("service_equivalence")
        equipment = customer_impact.get("equipment_constraint_audit")
        if not all(isinstance(item, Mapping) for item in (gross, service, equipment)):
            raise ValueError("customer impact evidence must include gross benefit, service and equipment audit objects")
        gates_passed = service.get("passed") is True and equipment.get("passed") is True
        gross_value = gross.get("value")
        qualified = gross.get("status") == "qualified"
        if gross_value is not None and (
            isinstance(gross_value, bool) or not isinstance(gross_value, Real)
            or not math.isfinite(float(gross_value))
        ):
            raise ValueError("customer impact gross benefit must be finite or withheld")
        if (gross_value is not None or qualified) and not gates_passed:
            raise ValueError("customer impact benefit cannot be qualified when service or equipment audit fails")
        if qualified and gross_value is None:
            raise ValueError("qualified customer impact benefit must include a numeric value")
        if gross_value is not None and not qualified:
            raise ValueError("numeric customer impact benefit must have qualified status")

    physical_audit = optimization_result.get("physical_audit")
    audit_passed = isinstance(physical_audit, Mapping) and physical_audit.get("passed") is True
    scope = optimization_result.get("model_scope", {})
    dispatch = optimization_result.get("dispatch", {})
    summary = dispatch.get("summary", {}) if isinstance(dispatch, Mapping) else {}
    record = {
        "schema_version": 1,
        "record_type": "offline_operator_decision_record",
        "site_ref": site_ref,
        "recommendation_id": recommendation_id,
        "created_at_utc": _utc(created_at_utc),
        "data_provenance": data_provenance,
        "input_refs": refs,
        "algorithm": optimization_result.get("algorithm", "unspecified"),
        "solver_status": optimization_result.get("solver_status"),
        "optimality_proven_for_declared_model": optimization_result.get(
            "optimality_proven_for_declared_milp", False
        ),
        "objective_weights": normalized_weights,
        "operating_constraints": dict(operating_constraints),
        "recommended_schedule": {
            key: optimization_result[key]
            for key in (
                "battery_power_setpoint_kw", "diesel_commitment_schedule",
                "diesel_power_setpoint_kw", "grid_import_model_kw", "water_service",
            )
            if key in optimization_result
        },
        "objectives_and_outcomes": dict(summary) if isinstance(summary, Mapping) else {},
        "baseline_comparison": optimization_result.get("baseline_comparison", {}),
        "customer_impact_assessment": dict(customer_impact) if isinstance(customer_impact, Mapping) else None,
        "physical_audit": dict(physical_audit) if isinstance(physical_audit, Mapping) else None,
        "status": "ready_for_human_review" if audit_passed else "blocked_pending_audit",
        "human_review_required": True,
        "operator_approval": "pending",
        "model_scope": dict(scope) if isinstance(scope, Mapping) else {},
        "device_write_authorized": False,
        "command_generated": False,
    }
    rendered = _canonical(record)
    record["record_sha256"] = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
    return record


def verify_operator_decision_record(record: Mapping) -> dict:
    """Verify a record digest and its mandatory advisory-only safety boundary."""
    if not isinstance(record, Mapping):
        raise TypeError("record must be a mapping")
    value = dict(record)
    digest = value.pop("record_sha256", None)
    if not isinstance(digest, str) or len(digest) != 64:
        return {"valid": False, "errors": ["record_sha256 is missing or malformed"]}
    errors = []
    if hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest() != digest:
        errors.append("record digest mismatch")
    if value.get("device_write_authorized") is not False:
        errors.append("device writes must remain unauthorized")
    if value.get("command_generated") is not False:
        errors.append("commands must not be generated")
    if value.get("human_review_required") is not True:
        errors.append("human review must be required")
    if value.get("operator_approval") != "pending":
        errors.append("operator approval must remain pending")
    return {"valid": not errors, "errors": errors, "device_write_authorized": False}

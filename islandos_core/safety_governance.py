"""Fail-closed governance gate for supervised-trial review packages.

This module never authorizes device writes or generates equipment commands.
A passing result means only that a review package is complete for independent
site-owner and qualified engineering/safety review.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping


_REQUIRED_REFERENCES = (
    "data_permission_ref",
    "risk_assessment_ref",
    "operating_envelope_ref",
    "interlock_test_ref",
    "write_path_isolation_test_ref",
    "rollback_plan_ref",
    "emergency_procedure_ref",
    "stop_rules_ref",
)
_APPROVAL_ROLES = ("site_owner", "engineering", "safety")


def _timestamp(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a timezone-aware ISO-8601 timestamp")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{field} must be a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def evaluate_supervised_trial_readiness(
    manifest: Mapping,
    *,
    evaluated_at_utc: str,
    max_telemetry_age_seconds: float = 300.0,
    max_approval_age_hours: float = 24.0,
) -> dict:
    """Check review-package completeness; never grant operational authority."""
    if not isinstance(manifest, Mapping):
        raise TypeError("manifest must be a mapping")
    now = _timestamp(evaluated_at_utc, "evaluated_at_utc")
    blockers = []
    warnings = []

    for field in ("site_id", "asset_id", "operator_on_duty"):
        value = manifest.get(field)
        if not isinstance(value, str) or not value.strip():
            blockers.append({"code": "missing_identity", "field": field})

    for field in _REQUIRED_REFERENCES:
        value = manifest.get(field)
        if not isinstance(value, str) or not value.strip():
            blockers.append({"code": "missing_evidence_reference", "field": field})

    required_true = (
        "asset_limits_verified",
        "independent_interlocks_verified",
        "manual_stop_tested",
        "write_path_isolated",
        "site_data_permission_confirmed",
    )
    for field in required_true:
        if manifest.get(field) is not True:
            blockers.append({"code": "safety_control_not_verified", "field": field})

    try:
        max_age = float(max_telemetry_age_seconds)
        approval_age = float(max_approval_age_hours)
        if max_age <= 0 or approval_age <= 0:
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        raise ValueError("freshness limits must be positive finite numbers")
    import math
    if not math.isfinite(max_age) or not math.isfinite(approval_age):
        raise ValueError("freshness limits must be positive finite numbers")

    telemetry = manifest.get("telemetry")
    if not isinstance(telemetry, Mapping):
        blockers.append({"code": "telemetry_evidence_missing", "field": "telemetry"})
    else:
        if telemetry.get("quality_passed") is not True:
            blockers.append({"code": "telemetry_quality_not_passed", "field": "telemetry.quality_passed"})
        try:
            telemetry_time = _timestamp(telemetry.get("timestamp_utc"), "telemetry.timestamp_utc")
            age = (now - telemetry_time).total_seconds()
            if age < 0:
                blockers.append({"code": "telemetry_from_future", "field": "telemetry.timestamp_utc"})
            elif age > max_age:
                blockers.append({"code": "stale_telemetry", "field": "telemetry.timestamp_utc"})
        except ValueError as exc:
            blockers.append({"code": "invalid_telemetry_timestamp", "field": "telemetry.timestamp_utc", "detail": str(exc)})

    approvals = manifest.get("approvals")
    approver_ids = []
    if not isinstance(approvals, Mapping):
        blockers.append({"code": "approvals_missing", "field": "approvals"})
    else:
        for role in _APPROVAL_ROLES:
            approval = approvals.get(role)
            if not isinstance(approval, Mapping):
                blockers.append({"code": "approval_missing", "field": f"approvals.{role}"})
                continue
            approver_id = approval.get("approver_id")
            evidence_ref = approval.get("evidence_ref")
            if not isinstance(approver_id, str) or not approver_id.strip():
                blockers.append({"code": "approver_identity_missing", "field": f"approvals.{role}.approver_id"})
            else:
                approver_ids.append(approver_id)
            if not isinstance(evidence_ref, str) or not evidence_ref.strip():
                blockers.append({"code": "approval_evidence_missing", "field": f"approvals.{role}.evidence_ref"})
            try:
                approved_at = _timestamp(approval.get("approved_at_utc"), f"approvals.{role}.approved_at_utc")
                age_hours = (now - approved_at).total_seconds() / 3600
                if age_hours < 0:
                    blockers.append({"code": "approval_from_future", "field": f"approvals.{role}.approved_at_utc"})
                elif age_hours > approval_age:
                    blockers.append({"code": "approval_expired", "field": f"approvals.{role}.approved_at_utc"})
            except ValueError as exc:
                blockers.append({"code": "approval_timestamp_invalid", "field": f"approvals.{role}.approved_at_utc", "detail": str(exc)})
    if len(approver_ids) == len(_APPROVAL_ROLES) and len(set(approver_ids)) != len(_APPROVAL_ROLES):
        blockers.append({"code": "separation_of_duties_violation", "field": "approvals"})

    if not blockers:
        warnings.append({
            "code": "independent_authorization_still_required",
            "message": "The review package is complete only. Site-owner and qualified engineering/safety authorities must make a separate decision; this software does not authorize a trial or equipment operation.",
        })

    return {
        "schema_version": 1,
        "mode": "supervised_trial_review_readiness",
        "status": "blocked" if blockers else "review_package_complete",
        "blockers": blockers,
        "warnings": warnings,
        "independent_authorization_required": True,
        "operational_authorization": False,
        "device_write_enabled": False,
        "command_generated": False,
    }

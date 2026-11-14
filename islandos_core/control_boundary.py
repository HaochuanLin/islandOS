"""Fail-closed boundary between decision support and equipment actuation.

The current IslandOS product is read-only decision support. This module makes
that boundary machine-checkable: no function here creates a device command or
enables a write path, even when upstream readiness evidence is complete.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Mapping


def build_human_review_envelope(
    recommendation: Mapping,
    *,
    site_id: str,
    asset_ids: tuple[str, ...],
    created_at_utc: str,
    evidence_refs: Mapping[str, str] | None = None,
) -> dict:
    """Create an auditable recommendation envelope with actuation hard-disabled."""
    if not isinstance(recommendation, Mapping) or not recommendation:
        raise ValueError("recommendation must be a non-empty mapping")
    if not isinstance(site_id, str) or not site_id.strip():
        raise ValueError("site_id is required")
    if not isinstance(asset_ids, tuple) or not asset_ids or any(not isinstance(x, str) or not x.strip() for x in asset_ids):
        raise ValueError("asset_ids must be a non-empty tuple of non-empty strings")
    if len(set(asset_ids)) != len(asset_ids):
        raise ValueError("asset_ids must be unique")
    if not isinstance(created_at_utc, str) or not created_at_utc.strip():
        raise ValueError("created_at_utc is required")
    stamp_text = created_at_utc.strip()
    if stamp_text.endswith("Z"):
        stamp_text = stamp_text[:-1] + "+00:00"
    try:
        stamp = datetime.fromisoformat(stamp_text)
    except ValueError as exc:
        raise ValueError("created_at_utc must be ISO-8601") from exc
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("created_at_utc must include a timezone")
    refs = dict(evidence_refs or {})
    if any(not isinstance(key, str) or not key.strip() or not isinstance(value, str) or not value.strip() for key, value in refs.items()):
        raise ValueError("evidence_refs must contain non-empty string keys and values")

    body = {
        "schema_version": "1.0",
        "site_id": site_id,
        "asset_ids": list(asset_ids),
        "created_at_utc": stamp.astimezone(timezone.utc).isoformat(),
        "recommendation": dict(recommendation),
        "evidence_refs": refs,
        "review_state": "pending_human_review",
        "operational_authorization": False,
        "device_write_enabled": False,
        "command_generated": False,
        "control_command": None,
        "required_review_roles": ["site_owner", "engineering", "safety"],
        "limitations": [
            "This envelope is decision-support evidence, not an operating instruction.",
            "Qualified site personnel must independently review site procedures and equipment limits.",
            "No hardware write path or automatic control is provided by this module.",
        ],
    }
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False)
    body["record_sha256"] = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return body

"""JSON-compatible audit records for read-only IslandOS decisions.

Records preserve the assumptions and normalized inputs used to produce a
recommendation. They are software traceability artifacts, not proof of sensor
accuracy or real-world operational validation.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Sequence

from .configuration import SiteConfiguration
from .decision import ScreeningRecommendation
from .signals import SignalReading


def build_decision_audit_record(
    *,
    config: SiteConfiguration,
    inputs: Sequence[SignalReading],
    recommendation: ScreeningRecommendation,
    created_at: datetime,
    run_id: str,
    input_mode: str,
) -> dict[str, Any]:
    """Build a versioned, JSON-compatible record for one human-review decision.

    created_at must be supplied by the caller so tests and replay workflows can
    be deterministic. The function performs no I/O and issues no control command.
    """
    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise ValueError("created_at must include a timezone")
    if not run_id.strip():
        raise ValueError("run_id is required")
    if not input_mode.strip():
        raise ValueError("input_mode is required")
    if not inputs:
        raise ValueError("at least one input signal is required")

    signal_ids = [reading.signal_id for reading in inputs]
    if len(signal_ids) != len(set(signal_ids)):
        raise ValueError("input signal_id values must be unique")

    return {
        "audit_schema_version": "1.0",
        "run_id": run_id,
        "created_at": created_at.isoformat(),
        "site_id": config.site_id,
        "input_mode": input_mode,
        "configuration": config.to_mapping(),
        "inputs": [reading.to_payload() for reading in inputs],
        "decision": recommendation.to_payload(),
        "safety_boundary": {
            "read_only": True,
            "control_command": None,
            "requires_human_review": True,
        },
    }

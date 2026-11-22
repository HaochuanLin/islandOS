"""Render the operator decision record above every number on the schedule page.

`INTEGRATION.md` §9 asks a reader to surface `status`, `physical_audit` and
`human_review_required` *before* any number, because a schedule that failed its
audit and a schedule that passed look identical once they are reduced to
metrics. This module owns that ordering in one place so a page cannot quietly
drop the gate and show a cost figure first.
"""

from __future__ import annotations

from typing import Mapping

import streamlit as st

_STATUS_TEXT = {
    "ready_for_human_review": "the physical audit passed, but nothing is authorized.",
    "blocked_pending_audit": "the audit did not pass - do not read the numbers below as an actionable plan.",
}


def _require(record: object) -> Mapping:
    if not isinstance(record, Mapping):
        raise ValueError("decision record must be a mapping")
    if record.get("record_type") != "offline_operator_decision_record":
        raise ValueError("decision record is missing or is not an offline operator decision record")
    return record


def audit_level(record: Mapping) -> str:
    """Return the Streamlit severity for the audit gate: 'success' or 'error'."""
    audit = _require(record).get("physical_audit")
    return "success" if isinstance(audit, Mapping) and audit.get("passed") is True else "error"


def audit_text(record: Mapping) -> str:
    """One sentence about the physical audit, including what it does not prove."""
    record = _require(record)
    audit = record.get("physical_audit")
    if not isinstance(audit, Mapping) or audit.get("passed") is not True:
        errors = "; ".join(str(item) for item in (audit or {}).get("errors") or []) if isinstance(audit, Mapping) else ""
        return (
            "Physical audit did not pass"
            + (f": {errors}" if errors else ": no audit was attached to this run")
            + ". Nothing below may be treated as a plan."
        )
    scope = str(audit.get("scope") or "per-scenario simulator replay of the recommended schedule").rstrip(".")
    scenarios = audit.get("scenarios_audited") or []
    count = f"{len(scenarios)} scenario(s) replayed" if scenarios else "scenarios replayed"
    standing = "That is a simulator replay, not site validation and not a safety certification."
    # The adapter's scope already carries this sentence; do not print it twice.
    if "not site validation" in scope or "safety certification" in scope:
        return f"Physical audit passed ({count}). Scope: {scope}."
    return f"Physical audit passed ({count}). Scope: {scope}. {standing}"


def record_facts(record: Mapping) -> list[tuple[str, str]]:
    """The facts that must appear before any metric, in reading order."""
    record = _require(record)
    status = str(record.get("status") or "blocked_pending_audit")
    text = _STATUS_TEXT.get(status, f"Unrecognised status {status!r} - treat the run as blocked.")
    digest = str(record.get("record_sha256") or "")
    return [
        ("Status", status.replace("_", " ")),
        ("What that means", text),
        ("Physical audit", audit_text(record)),
        ("Human review", "required - operator approval is still pending" if record.get("human_review_required") is True else "not recorded - treat the run as blocked"),
        ("Device write", "not authorized - this record never becomes a command"),
        ("Record SHA-256", f"{digest[:8]}…" if digest else "missing"),
    ]


def render_decision_record(record: Mapping) -> None:
    """Render the gate: one banner, then the facts, then nothing else from here."""
    level = audit_level(record)
    facts = record_facts(record)
    banner = f"Status: {facts[0][1]} - {facts[1][1]}"
    if level == "success":
        st.success(banner)
    else:
        st.error(banner)
    st.caption(facts[2][1])
    st.caption(" · ".join(f"**{label}:** {value}" for label, value in facts[3:]))

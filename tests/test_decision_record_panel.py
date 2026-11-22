"""The gate that must be read before any number on the schedule page."""

from pathlib import Path

import pytest

from islandos_core.operator_decision import build_operator_decision_record
from islandos_ui.decision_record_panel import audit_level, audit_text, record_facts


PAGE = Path(__file__).resolve().parents[1] / "pages" / "06_Forecast_Led_Joint_Resource_Optimizer.py"


def _record(*, audit_passed: bool = True, errors=None, scope: str | None = None):
    audit = {
        "passed": audit_passed,
        "errors": list(errors or []),
        "scope": scope or "per-scenario simulator audit of the recommended schedule replay",
        "scenarios_audited": ["forecast_central", "forecast_low"],
    }
    return build_operator_decision_record(
        {
            "algorithm": "evolutionary_search",
            "physical_audit": audit,
            "dispatch": {"summary": {"estimated_energy_cost": 12.5}},
            "model_scope": {"model_scope": "offline"},
        },
        site_ref="site-a",
        recommendation_id="run-1:joint_resource_dispatch",
        created_at_utc="2026-11-22T00:00:00Z",
        data_provenance="synthetic",
        input_refs=["manifest_sha256:" + "a" * 64],
        objective_weights={"cost": 1.0},
        operating_constraints={"grid_available": [True], "diesel_available": [True]},
    )


def test_passed_audit_reports_ready_and_keeps_the_run_read_only():
    record = _record()
    facts = record_facts(record)
    labels = [label for label, _ in facts]
    assert labels == [
        "Status", "What that means", "Physical audit",
        "Human review", "Device write", "Record SHA-256",
    ]
    assert facts[0][1] == "ready for human review"
    assert "nothing is authorized" in facts[1][1]
    assert "Physical audit passed" in facts[2][1]
    assert "2 scenario(s) replayed" in facts[2][1]
    assert "not site validation" in facts[2][1] or "not a safety certification" in facts[2][1]
    assert audit_level(record) == "success"


def test_blocked_audit_is_rendered_as_a_failure_not_a_footnote():
    record = _record(audit_passed=False, errors=["forecast_low: recommended schedule failed the physical dispatch audit"])
    facts = record_facts(record)
    assert facts[0][1] == "blocked pending audit"
    assert "do not read the numbers below" in facts[1][1]
    assert "forecast_low" in facts[2][1]
    assert audit_level(record) == "error"


def test_audit_text_names_what_the_audit_does_not_prove():
    record = _record()
    text = audit_text(record)
    assert "simulator audit" in text
    assert "not site validation" in text or "safety certification" in text


def test_a_scope_that_already_states_the_limit_is_not_repeated():
    record = _record(
        scope=(
            "per-scenario simulator audit of the recommended schedule replay; "
            "not site validation and not a safety certification"
        )
    )
    text = audit_text(record)
    assert text.count("not site validation") == 1
    assert "not a safety certification" in text


def test_digest_is_shortened_but_present():
    record = _record()
    digest = record["record_sha256"]
    assert len(digest) == 64
    assert dict(record_facts(record))["Record SHA-256"] == digest[:8] + "…"


def test_a_run_without_a_record_is_rejected_instead_of_rendered():
    with pytest.raises(ValueError, match="decision record"):
        record_facts({"status": "ready_for_human_review"})
    with pytest.raises(ValueError, match="decision record"):
        audit_level({"record_type": "islandos_canonical_planning_run"})


def test_page_shows_the_gate_before_any_metric():
    source = PAGE.read_text(encoding="utf-8")
    gate = source.index("render_decision_record(planning_run[\"decision_record\"])")
    first_metric = source.index('st.metric("Selected policy"')
    assert gate < first_metric
    assert "from islandos_ui.decision_record_panel import render_decision_record" in source
    assert '"decision_record": planning_run["decision_record"]' in source

from copy import deepcopy

import pytest

from islandos_core.operator_decision import (
    build_operator_decision_record,
    verify_operator_decision_record,
)


def _result():
    return {
        "algorithm": "test_optimizer",
        "solver_status": 0,
        "optimality_proven_for_declared_milp": True,
        "battery_power_setpoint_kw": [1.0, -1.0],
        "diesel_commitment_schedule": [False, True],
        "diesel_power_setpoint_kw": [0.0, 2.0],
        "grid_import_model_kw": [1.0, 0.0],
        "dispatch": {"summary": {"estimated_energy_cost": 12.5, "unmet_load_kwh": 0.0}},
        "dispatch_rows": [
            {"timestep": 0, "battery_charge_kw": 1.0, "grid_import_kw": 0.0},
            {"timestep": 1, "battery_discharge_kw": 0.5, "grid_import_kw": 0.5},
        ],
        "physical_audit": {"passed": True, "errors": []},
        "baseline_comparison": {"grid_first": {"feasible": True}},
        "model_scope": {"site_validation": False},
    }


def test_operator_decision_record_is_hash_verifiable_and_advisory_only():
    record = build_operator_decision_record(
        _result(), site_ref="demo-site", recommendation_id="rec-001",
        created_at_utc="2026-11-17T10:00:00Z",
        data_provenance="synthetic demo data",
        input_refs=["synthetic://demo/history.csv"],
        objective_weights={"cost": 0.7, "reliability": 0.3},
        operating_constraints={"unmet_load_kwh_max": 0.0},
    )
    assert record["status"] == "ready_for_human_review"
    assert record["recommended_schedule"]["dispatch_rows"] == _result()["dispatch_rows"]
    assert record["human_review_required"] is True
    assert record["operator_approval"] == "pending"
    assert record["device_write_authorized"] is False
    assert verify_operator_decision_record(record)["valid"] is True


def test_failed_physical_audit_blocks_operator_review_record():
    result = _result()
    result["physical_audit"] = {"passed": False, "errors": ["power balance"]}
    record = build_operator_decision_record(
        result, site_ref="demo-site", recommendation_id="rec-002",
        created_at_utc="2026-11-17T10:00:00Z",
        data_provenance="synthetic demo data",
        input_refs=["synthetic://demo/history.csv"],
        objective_weights={"cost": 1.0},
        operating_constraints={},
    )
    assert record["status"] == "blocked_pending_audit"


def test_record_verifier_detects_tampering_and_never_authorizes_commands():
    record = build_operator_decision_record(
        _result(), site_ref="demo-site", recommendation_id="rec-003",
        created_at_utc="2026-11-17T10:00:00Z",
        data_provenance="synthetic demo data",
        input_refs=["synthetic://demo/history.csv"],
        objective_weights={"cost": 1.0},
        operating_constraints={},
    )
    tampered = deepcopy(record)
    tampered["recommended_schedule"]["diesel_power_setpoint_kw"][0] = 9.0
    assert verify_operator_decision_record(tampered)["valid"] is False


def test_record_rejects_missing_provenance_and_naive_timestamp():
    with pytest.raises(ValueError, match="input_refs"):
        build_operator_decision_record(
            _result(), site_ref="demo", recommendation_id="r",
            created_at_utc="2026-11-17T10:00:00Z", data_provenance="synthetic",
            input_refs=[], objective_weights={"cost": 1.0}, operating_constraints={},
        )
    with pytest.raises(ValueError, match="timezone"):
        build_operator_decision_record(
            _result(), site_ref="demo", recommendation_id="r",
            created_at_utc="2026-11-17T10:00:00", data_provenance="synthetic",
            input_refs=["synthetic://x"], objective_weights={"cost": 1.0}, operating_constraints={},
        )

def _qualified_impact():
    return {
        "gross_operating_benefit": {"value": 12.5, "status": "qualified", "currency": "USD", "evaluation_period": "24-hour scenario"},
        "service_equivalence": {"passed": True},
        "equipment_constraint_audit": {"passed": True},
    }


def test_operator_record_preserves_qualified_customer_impact_evidence():
    result = _result()
    result["customer_impact_assessment"] = _qualified_impact()
    record = build_operator_decision_record(
        result, site_ref="demo-site", recommendation_id="rec-impact-001",
        created_at_utc="2026-11-17T10:00:00Z", data_provenance="synthetic demo data",
        input_refs=["synthetic://demo/history.csv"], objective_weights={"cost": 1.0},
        operating_constraints={},
    )
    assert record["customer_impact_assessment"] == _qualified_impact()
    assert verify_operator_decision_record(record)["valid"] is True


@pytest.mark.parametrize(
    "service_passed,audit_passed",
    [(False, True), (True, False), (False, False)],
)
def test_operator_record_rejects_impact_benefit_when_evidence_gate_fails(service_passed, audit_passed):
    result = _result()
    impact = _qualified_impact()
    impact["service_equivalence"]["passed"] = service_passed
    impact["equipment_constraint_audit"]["passed"] = audit_passed
    result["customer_impact_assessment"] = impact
    with pytest.raises(ValueError, match="cannot be qualified"):
        build_operator_decision_record(
            result, site_ref="demo-site", recommendation_id="rec-impact-blocked",
            created_at_utc="2026-11-17T10:00:00Z", data_provenance="synthetic demo data",
            input_refs=["synthetic://demo/history.csv"], objective_weights={"cost": 1.0},
            operating_constraints={},
        )


def test_operator_record_rejects_malformed_customer_impact_evidence():
    result = _result()
    result["customer_impact_assessment"] = {"gross_operating_benefit": {"value": 10}}
    with pytest.raises(ValueError, match="must include"):
        build_operator_decision_record(
            result, site_ref="demo-site", recommendation_id="rec-impact-malformed",
            created_at_utc="2026-11-17T10:00:00Z", data_provenance="synthetic demo data",
            input_refs=["synthetic://demo/history.csv"], objective_weights={"cost": 1.0},
            operating_constraints={},
        )


def test_operator_record_hash_covers_customer_impact_evidence():
    result = _result()
    result["customer_impact_assessment"] = _qualified_impact()
    record = build_operator_decision_record(
        result, site_ref="demo-site", recommendation_id="rec-impact-tamper",
        created_at_utc="2026-11-17T10:00:00Z", data_provenance="synthetic demo data",
        input_refs=["synthetic://demo/history.csv"], objective_weights={"cost": 1.0},
        operating_constraints={},
    )
    record["customer_impact_assessment"]["gross_operating_benefit"]["value"] = 999.0
    assert verify_operator_decision_record(record)["valid"] is False


def test_operator_record_hash_covers_complete_dispatch_rows():
    record = build_operator_decision_record(
        _result(), site_ref="demo-site", recommendation_id="rec-dispatch-rows",
        created_at_utc="2026-11-17T10:00:00Z", data_provenance="synthetic demo data",
        input_refs=["synthetic://demo/history.csv"], objective_weights={"cost": 1.0},
        operating_constraints={},
    )
    assert len(record["recommended_schedule"]["dispatch_rows"]) == 2
    tampered = deepcopy(record)
    tampered["recommended_schedule"]["dispatch_rows"][1]["battery_discharge_kw"] = 99.0
    assert verify_operator_decision_record(tampered)["valid"] is False

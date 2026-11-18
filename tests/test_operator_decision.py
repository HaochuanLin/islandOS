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

from islandos_core.safety_governance import evaluate_supervised_trial_readiness


def _manifest():
    return {
        "site_id": "site-001",
        "asset_id": "battery-inverter-01",
        "operator_on_duty": "operator-17",
        "data_permission_ref": "approval/data-rights/001",
        "risk_assessment_ref": "risk/assessment/001",
        "operating_envelope_ref": "vendor/limits/001",
        "interlock_test_ref": "test/interlocks/001",
        "write_path_isolation_test_ref": "test/no-write/001",
        "rollback_plan_ref": "ops/rollback/001",
        "emergency_procedure_ref": "ops/emergency/001",
        "stop_rules_ref": "ops/stop-rules/001",
        "asset_limits_verified": True,
        "independent_interlocks_verified": True,
        "manual_stop_tested": True,
        "write_path_isolated": True,
        "site_data_permission_confirmed": True,
        "telemetry": {"timestamp_utc": "2026-11-13T10:04:00Z", "quality_passed": True},
        "approvals": {
            "site_owner": {"approver_id": "owner-1", "approved_at_utc": "2026-11-13T09:50:00Z", "evidence_ref": "approval/owner/1"},
            "engineering": {"approver_id": "engineer-1", "approved_at_utc": "2026-11-13T09:51:00Z", "evidence_ref": "approval/engineering/1"},
            "safety": {"approver_id": "safety-1", "approved_at_utc": "2026-11-13T09:52:00Z", "evidence_ref": "approval/safety/1"},
        },
    }


def test_complete_review_package_never_authorizes_operation():
    result = evaluate_supervised_trial_readiness(
        _manifest(), evaluated_at_utc="2026-11-13T10:05:00Z"
    )
    assert result["status"] == "review_package_complete"
    assert result["independent_authorization_required"] is True
    assert result["operational_authorization"] is False
    assert result["device_write_enabled"] is False
    assert result["command_generated"] is False


def test_missing_interlock_and_rollback_evidence_blocks_review():
    manifest = _manifest()
    manifest["independent_interlocks_verified"] = False
    manifest["rollback_plan_ref"] = ""
    result = evaluate_supervised_trial_readiness(manifest, evaluated_at_utc="2026-11-13T10:05:00Z")
    codes = {item["code"] for item in result["blockers"]}
    assert result["status"] == "blocked"
    assert "safety_control_not_verified" in codes
    assert "missing_evidence_reference" in codes


def test_stale_telemetry_blocks_even_with_all_approvals():
    manifest = _manifest()
    manifest["telemetry"]["timestamp_utc"] = "2026-11-13T09:00:00Z"
    result = evaluate_supervised_trial_readiness(manifest, evaluated_at_utc="2026-11-13T10:05:00Z")
    assert any(item["code"] == "stale_telemetry" for item in result["blockers"])


def test_separation_of_duties_requires_three_distinct_approvers():
    manifest = _manifest()
    manifest["approvals"]["safety"]["approver_id"] = "owner-1"
    result = evaluate_supervised_trial_readiness(manifest, evaluated_at_utc="2026-11-13T10:05:00Z")
    assert any(item["code"] == "separation_of_duties_violation" for item in result["blockers"])


def test_expired_approval_and_future_telemetry_fail_closed():
    manifest = _manifest()
    manifest["approvals"]["engineering"]["approved_at_utc"] = "2026-11-10T10:00:00Z"
    manifest["telemetry"]["timestamp_utc"] = "2026-11-13T10:06:00Z"
    result = evaluate_supervised_trial_readiness(manifest, evaluated_at_utc="2026-11-13T10:05:00Z")
    codes = {item["code"] for item in result["blockers"]}
    assert "approval_expired" in codes
    assert "telemetry_from_future" in codes
    assert result["device_write_enabled"] is False

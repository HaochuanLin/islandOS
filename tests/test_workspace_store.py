from datetime import datetime, timezone
import json
import sqlite3

import pytest

from islandos_core.workspace_store import (
    AuditIntegrityError,
    WorkspaceStoreError,
    create_project,
    create_run_manifest,
    get_run_manifest,
    initialize_workspace,
    list_import_artifacts,
    list_audit_events,
    record_import_artifact,
    record_run_record,
    get_run_record,
    list_run_records,
    record_operator_override,
    save_asset_record,
    list_asset_records,
    verify_audit_chain,
)


NOW = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)
DIGEST = "a" * 64


def ready_project(tmp_path):
    db = tmp_path / "islandos-local.sqlite3"
    initialize_workspace(db, workspace_id="workspace-01", actor_id="local-user", created_at=NOW)
    create_project(
        db, project_id="site-01", display_name="Demo Site",
        actor_id="local-user", consent_to_store_metadata=True, created_at=NOW,
    )
    return db


def test_project_metadata_requires_explicit_consent(tmp_path):
    db = tmp_path / "islandos-local.sqlite3"
    initialize_workspace(db, workspace_id="workspace-01", actor_id="local-user", created_at=NOW)
    with pytest.raises(WorkspaceStoreError, match="explicit consent"):
        create_project(
            db, project_id="site-01", display_name="Demo Site",
            actor_id="local-user", consent_to_store_metadata=False, created_at=NOW,
        )
    assert verify_audit_chain(db)["event_count"] == 1


def test_import_metadata_stores_hash_not_raw_file_and_records_basename(tmp_path):
    db = ready_project(tmp_path)
    artifact_id = record_import_artifact(
        db, project_id="site-01", file_name="C:\\customer\\private\\telemetry.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        sha256=DIGEST, source_type="customer_provided", row_count=500,
        signal_count=4, quality_status="needs_review", worksheet="Data",
        actor_id="local-user", consent_to_store_metadata=True, imported_at=NOW,
    )
    artifacts = list_import_artifacts(db, project_id="site-01")
    assert len(artifacts) == 1
    assert artifacts[0]["artifact_id"] == artifact_id
    assert artifacts[0]["file_name"] == "telemetry.xlsx"
    assert artifacts[0]["retention_mode"] == "metadata_only"
    database_bytes = db.read_bytes()
    assert b"private" not in database_bytes
    assert b"raw telemetry values" not in database_bytes
    assert verify_audit_chain(db)["valid"] is True


def test_run_manifest_is_reproducible_and_immutable(tmp_path):
    db = ready_project(tmp_path)
    record_import_artifact(
        db, project_id="site-01", file_name="site.csv", media_type="text/csv",
        sha256=DIGEST, source_type="measured", row_count=168, signal_count=2,
        quality_status="valid", actor_id="local-user",
        consent_to_store_metadata=True, imported_at=NOW,
    )
    manifest = create_run_manifest(
        db, project_id="site-01", input_artifact_hashes=[DIGEST],
        configuration={"battery_limit_kw": 100, "tariff": 0.2},
        model_versions={"forecast": "seasonal-naive-v1", "simulator": "microgrid-v1"},
        software_version="0.1.0", random_seed=20261107,
        output_summary={"unmet_load_kwh": 0, "grid_cost": 12.5},
        actor_id="local-user", created_at=NOW,
    )
    restored = get_run_manifest(db, run_id=manifest["run_id"])
    assert restored == manifest
    assert manifest["manifest_schema_version"] == "1.0"
    assert verify_audit_chain(db)["valid"] is True
    with sqlite3.connect(db) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "UPDATE run_manifests SET manifest_json='{}' WHERE run_id=?",
                (manifest["run_id"],),
            )


def test_run_manifest_hash_detects_database_tampering(tmp_path):
    db = ready_project(tmp_path)
    manifest = create_run_manifest(
        db, project_id="site-01", input_artifact_hashes=[],
        configuration={"grid_import_limit_kw": 100}, model_versions={},
        software_version="0.1.0", output_summary={}, actor_id="local-user",
        created_at=NOW,
    )
    with sqlite3.connect(db) as connection:
        connection.execute("DROP TRIGGER run_manifests_no_update")
        connection.execute(
            "UPDATE run_manifests SET manifest_json=? WHERE run_id=?",
            (json.dumps({"changed": True}), manifest["run_id"]),
        )
    with pytest.raises(AuditIntegrityError, match="hash does not match"):
        get_run_manifest(db, run_id=manifest["run_id"])


def test_run_manifest_cannot_reference_unregistered_or_duplicate_hashes(tmp_path):
    db = ready_project(tmp_path)
    args = dict(
        db_path=db, project_id="site-01", configuration={},
        model_versions={}, software_version="0.1", output_summary={},
        actor_id="local-user", created_at=NOW,
    )
    with pytest.raises(WorkspaceStoreError, match="not registered"):
        create_run_manifest(input_artifact_hashes=[DIGEST], **args)
    with pytest.raises(WorkspaceStoreError, match="unique"):
        create_run_manifest(input_artifact_hashes=[DIGEST, DIGEST], **args)


def test_non_finite_run_configuration_is_rejected(tmp_path):
    db = ready_project(tmp_path)
    with pytest.raises(WorkspaceStoreError, match="finite JSON"):
        create_run_manifest(
            db, project_id="site-01", input_artifact_hashes=[],
            configuration={"bad": float("nan")}, model_versions={},
            software_version="0.1", output_summary={}, actor_id="local-user",
            created_at=NOW,
        )


def test_audit_chain_detects_tampering(tmp_path):
    db = ready_project(tmp_path)
    with sqlite3.connect(db) as connection:
        connection.execute("DROP TRIGGER audit_events_no_update")
        connection.execute("UPDATE audit_events SET payload_json=? WHERE sequence=1", (json.dumps({"changed": True}),))
    report = verify_audit_chain(db)
    assert report["valid"] is False
    assert report["failed_sequence"] == 1


def test_operator_override_requires_reason_and_independent_review(tmp_path):
    db = ready_project(tmp_path)
    proposal_id = record_operator_override(
        db, project_id="site-01", actor_id="operator-a",
        field_path="assets.battery-01.max_charge_kw",
        previous_value=180, proposed_value=150,
        reason="Commissioning sheet lists a lower configured limit.",
        source_reference="commissioning-sheet-rev2.pdf page 4",
        approval_status="pending_review", created_at=NOW,
    )
    with pytest.raises(WorkspaceStoreError, match="cannot review their own"):
        record_operator_override(
            db, project_id="site-01", actor_id="operator-a",
            field_path="assets.battery-01.max_charge_kw",
            previous_value=180, proposed_value=150,
            reason="Commissioning sheet lists a lower configured limit.",
            source_reference="commissioning-sheet-rev2.pdf page 4",
            approval_status="approved", reviewer_id="operator-a",
            proposal_id=proposal_id, created_at=NOW,
        )
    with pytest.raises(WorkspaceStoreError, match="match the original"):
        record_operator_override(
            db, project_id="site-01", actor_id="operator-a",
            field_path="assets.battery-01.max_charge_kw",
            previous_value=180, proposed_value=140,
            reason="Commissioning sheet lists a lower configured limit.",
            source_reference="commissioning-sheet-rev2.pdf page 4",
            approval_status="approved", reviewer_id="reviewer-b",
            proposal_id=proposal_id, created_at=NOW,
        )
    record_operator_override(
        db, project_id="site-01", actor_id="operator-a",
        field_path="assets.battery-01.max_charge_kw",
        previous_value=180, proposed_value=150,
        reason="Commissioning sheet lists a lower configured limit.",
        source_reference="commissioning-sheet-rev2.pdf page 4",
        approval_status="approved", reviewer_id="reviewer-b",
        proposal_id=proposal_id, created_at=NOW,
    )
    events = list_audit_events(db, project_id="site-01")
    override_events = [item for item in events if item["event_type"].startswith("operator_override_")]
    assert [item["event_type"] for item in override_events] == [
        "operator_override_pending_review", "operator_override_approved",
    ]
    assert override_events[0]["payload"]["proposal_id"] == proposal_id
    assert override_events[1]["payload"]["proposal_id"] == proposal_id
    assert override_events[1]["payload"]["operational_authorization"] is False
    with pytest.raises(WorkspaceStoreError, match="already been reviewed"):
        record_operator_override(
            db, project_id="site-01", actor_id="operator-a",
            field_path="assets.battery-01.max_charge_kw",
            previous_value=180, proposed_value=150,
            reason="Commissioning sheet lists a lower configured limit.",
            source_reference="commissioning-sheet-rev2.pdf page 4",
            approval_status="rejected", reviewer_id="reviewer-c",
            proposal_id=proposal_id, created_at=NOW,
        )
    assert verify_audit_chain(db)["valid"] is True


def test_override_review_cannot_reference_unknown_proposal(tmp_path):
    db = ready_project(tmp_path)
    with pytest.raises(WorkspaceStoreError, match="does not identify"):
        record_operator_override(
            db, project_id="site-01", actor_id="operator-a",
            field_path="assets.pv-01.max_power_kw",
            previous_value=100, proposed_value=90, reason="Site test",
            source_reference="test report", approval_status="rejected",
            reviewer_id="reviewer-b", proposal_id="unknown", created_at=NOW,
        )


def test_audit_events_are_append_only_at_sqlite_layer(tmp_path):
    db = ready_project(tmp_path)
    with sqlite3.connect(db) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("DELETE FROM audit_events")


def test_asset_registry_persists_immutable_versions_and_audit_history(tmp_path):
    from islandos_core.assets import AssetParameter, AssetRecord, OperatingConstraint

    db = ready_project(tmp_path)
    def make_asset(power):
        return AssetRecord(
            asset_id="pv-main", site_id="site-01", asset_type="pv",
            nameplate_parameters={"rated_power_kw": AssetParameter(120, "kW", "vendor_specification", "datasheet rev 2", True)},
            installed_parameters={"configured_power_kw": AssetParameter(power, "kW", "customer_provided", "site schedule rev 1", True)},
            observed_parameters={},
            constraints=(OperatingConstraint(
                constraint_id="pv-max", parameter="max_power_kw", severity="hard",
                unit="kW", operator="max", upper_bound=power,
                source_type="customer_provided", source_reference="approved site schedule", confirmed=True,
            ),),
        )

    first = save_asset_record(db, project_id="site-01", asset=make_asset(100), actor_id="local-user", saved_at=NOW)
    second = save_asset_record(db, project_id="site-01", asset=make_asset(90), actor_id="local-user", saved_at=NOW)
    latest = list_asset_records(db, project_id="site-01")
    history = list_asset_records(db, project_id="site-01", include_history=True)
    assert first["version"] == 1 and second["version"] == 2
    assert len(latest) == 1 and latest[0]["version"] == 2
    assert latest[0]["asset"].installed_parameters["configured_power_kw"].value == 90
    assert [item["version"] for item in history] == [1, 2]
    assert verify_audit_chain(db)["valid"] is True
    with sqlite3.connect(db) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute("DELETE FROM asset_record_versions")


def test_asset_registry_detects_readiness_snapshot_tampering(tmp_path):
    from islandos_core.assets import AssetParameter, AssetRecord, OperatingConstraint
    db = ready_project(tmp_path)
    asset = AssetRecord(
        asset_id="pv-tamper", site_id="site-01", asset_type="pv",
        nameplate_parameters={},
        installed_parameters={"configured_power_kw": AssetParameter(20, "kW", "customer_provided", "site schedule", True)},
        observed_parameters={},
        constraints=(OperatingConstraint(
            constraint_id="pv-max", parameter="max_power_kw", severity="hard",
            unit="kW", operator="max", upper_bound=20,
            source_type="customer_provided", source_reference="site schedule", confirmed=True,
        ),),
    )
    save_asset_record(db, project_id="site-01", asset=asset, actor_id="local-user", saved_at=NOW)
    with sqlite3.connect(db) as connection:
        connection.execute("DROP TRIGGER asset_record_versions_no_update")
        connection.execute("UPDATE asset_record_versions SET readiness_json='{}'")
    with pytest.raises(AuditIntegrityError, match="readiness snapshot mismatch"):
        list_asset_records(db, project_id="site-01")


def test_run_record_persists_result_without_retaining_full_request_by_default(tmp_path):
    db = ready_project(tmp_path)
    record = record_run_record(
        db, project_id="site-01", run_id="canonical-run-01", page="06",
        request_sha256=DIGEST,
        request_metadata={"history_start": "2026-11-01T00:00:00Z", "row_count": 24},
        result={"grid_cost": 12.5, "unmet_load_kwh": 0},
        actor_id="local-user", consent_to_store_result=True, created_at=NOW,
    )
    assert record["retention_mode"] == "metadata_only"
    assert record["replayable"] is False
    assert record["request_payload"] is None
    listed = list_run_records(db, project_id="site-01")
    assert len(listed) == 1
    assert "request_payload" not in listed[0]
    restored = get_run_record(db, project_id="site-01", run_id="canonical-run-01")
    assert restored["result"] == {"grid_cost": 12.5, "unmet_load_kwh": 0}
    assert restored["replayable"] is False
    assert verify_audit_chain(db)["valid"] is True


def test_run_record_requires_separate_opt_in_for_full_request_retention(tmp_path):
    db = ready_project(tmp_path)
    payload = {"history": {"timestamps_utc": ["2026-11-01T00:00:00Z"], "signals": {"load_kw": [5]}}}
    args = dict(
        db_path=db, project_id="site-01", run_id="canonical-run-02", page="06",
        request_sha256=DIGEST, request_metadata={"row_count": 1},
        result={"grid_cost": 1}, actor_id="local-user",
        consent_to_store_result=True, request_payload=payload, created_at=NOW,
    )
    with pytest.raises(WorkspaceStoreError, match="separate explicit consent"):
        record_run_record(**args)
    record = record_run_record(**{**args, "consent_to_retain_request": True})
    assert record["retention_mode"] == "retained_full_request"
    assert record["replayable"] is True
    restored = get_run_record(db, project_id="site-01", run_id="canonical-run-02")
    assert restored["request_payload"] == payload
    assert restored["request_payload_sha256"] == record["request_payload_sha256"]


def test_run_record_requires_result_consent_and_existing_project(tmp_path):
    db = ready_project(tmp_path)
    args = dict(
        db_path=db, project_id="site-01", run_id="canonical-run-03", page="06",
        request_sha256=DIGEST, request_metadata={}, result={},
        actor_id="local-user", created_at=NOW,
    )
    with pytest.raises(WorkspaceStoreError, match="explicit consent"):
        record_run_record(**args, consent_to_store_result=False)
    with pytest.raises(WorkspaceStoreError, match="does not exist"):
        record_run_record(
            **{**args, "project_id": "missing-project"},
            consent_to_store_result=True,
        )


def test_run_record_integrity_and_immutability(tmp_path):
    db = ready_project(tmp_path)
    record = record_run_record(
        db, project_id="site-01", run_id="canonical-run-04", page="06",
        request_sha256=DIGEST, request_metadata={"row_count": 3},
        result={"energy_cost": 10}, actor_id="local-user",
        consent_to_store_result=True, canonical_manifest={"run_id": "canonical-run-04"},
        created_at=NOW,
    )
    with sqlite3.connect(db) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "UPDATE run_records SET result_json='{}' WHERE project_id=? AND run_id=?",
                ("site-01", record["run_id"]),
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "DELETE FROM run_records WHERE project_id=? AND run_id=?",
                ("site-01", record["run_id"]),
            )
        connection.execute("DROP TRIGGER run_records_no_update")
        connection.execute(
            "UPDATE run_records SET result_json='{}' WHERE project_id=? AND run_id=?",
            ("site-01", record["run_id"]),
        )
    with pytest.raises(AuditIntegrityError, match="run result hash"):
        get_run_record(db, project_id="site-01", run_id=record["run_id"])


def test_same_canonical_run_id_can_be_saved_in_two_projects(tmp_path):
    db = ready_project(tmp_path)
    create_project(
        db, project_id="site-02", display_name="Second Site",
        actor_id="local-user", consent_to_store_metadata=True, created_at=NOW,
    )
    for project_id in ("site-01", "site-02"):
        record_run_record(
            db, project_id=project_id, run_id="same-deterministic-run",
            page="06", request_sha256=DIGEST, request_metadata={},
            result={"ok": True}, actor_id="local-user",
            consent_to_store_result=True, created_at=NOW,
        )
    assert len(list_run_records(db, project_id="site-01")) == 1
    assert len(list_run_records(db, project_id="site-02")) == 1


def test_existing_schema_1_0_workspace_migrates_without_losing_history(tmp_path):
    db = ready_project(tmp_path)
    original_manifest = create_run_manifest(
        db, project_id="site-01", input_artifact_hashes=[],
        configuration={}, model_versions={}, software_version="0.1",
        output_summary={"preserved": True}, actor_id="local-user", created_at=NOW,
    )
    with sqlite3.connect(db) as connection:
        connection.execute("DROP TABLE run_records")
        connection.execute(
            "UPDATE workspace_meta SET value='1.0' WHERE key='schema_version'"
        )
    before = verify_audit_chain(db)["event_count"]
    initialize_workspace(db, workspace_id="workspace-01", actor_id="local-user", created_at=NOW)
    with sqlite3.connect(db) as connection:
        version = connection.execute(
            "SELECT value FROM workspace_meta WHERE key='schema_version'"
        ).fetchone()[0]
        run_count = connection.execute("SELECT COUNT(*) FROM run_manifests").fetchone()[0]
    assert version == "1.1"
    assert run_count == 1
    assert get_run_manifest(db, run_id=original_manifest["run_id"])["output_summary"] == {"preserved": True}
    events = list_audit_events(db)
    assert any(item["event_type"] == "workspace_schema_migrated" for item in events)
    assert verify_audit_chain(db)["valid"] is True
    assert verify_audit_chain(db)["event_count"] == before + 1


def test_unknown_future_workspace_schema_fails_closed(tmp_path):
    db = ready_project(tmp_path)
    with sqlite3.connect(db) as connection:
        connection.execute(
            "UPDATE workspace_meta SET value='99.0' WHERE key='schema_version'"
        )
    with pytest.raises(WorkspaceStoreError, match="unsupported workspace schema"):
        initialize_workspace(db, workspace_id="workspace-01", actor_id="local-user", created_at=NOW)

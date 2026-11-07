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
    record_operator_override,
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

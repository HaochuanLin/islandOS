from datetime import datetime, timezone
import hashlib
import sqlite3

import pytest

from islandos_core.application import (
    create_analysis_record,
    create_local_project,
    inspect_upload,
    open_local_project,
    register_inspected_import,
    register_project_asset,
    list_project_assets,
)
from islandos_core.workspace_store import list_import_artifacts, verify_audit_chain


NOW = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)
CSV = (
    b"timestamp,load_kw\n"
    b"2026-11-07T10:00:00Z,100\n"
    b"2026-11-07T11:00:00Z,110\n"
)


def test_application_services_inspect_register_and_snapshot_without_streamlit(tmp_path):
    import subprocess
    import sys

    # Check the import boundary in a fresh interpreter. The full pytest suite
    # may have imported Streamlit in earlier tests, so sys.modules in this
    # process is order-dependent and cannot prove this module's isolation.
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import islandos_core.application; "
            "assert 'streamlit' not in sys.modules",
        ],
        check=True,
    )
    result = inspect_upload(
        CSV, file_name="customer-load.csv", source_type="customer_provided",
        task="exploration", now=NOW,
    )
    assert result["format"] == "csv"
    assert result["inspection"]["status"] == "valid"
    assert result["readiness"]["can_run"] is True
    assert result["raw_file_retained"] is False

    db = tmp_path / "workspace.sqlite3"
    create_local_project(
        db, workspace_id="workspace-a", project_id="site-a",
        display_name="Site A", actor_id="user-a",
        consent_to_store_metadata=True, created_at=NOW,
    )
    artifact_id = register_inspected_import(
        db, project_id="site-a", file_name="/private/path/customer-load.csv",
        inspection_result=result, actor_id="user-a",
        consent_to_store_metadata=True, imported_at=NOW,
    )
    records = list_import_artifacts(db, project_id="site-a")
    assert len(records) == 1
    assert records[0]["artifact_id"] == artifact_id
    assert records[0]["file_name"] == "customer-load.csv"
    assert records[0]["sha256"] == hashlib.sha256(CSV).hexdigest()
    with sqlite3.connect(db) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(import_artifacts)")}
        assert "raw_bytes" not in columns

    manifest = create_analysis_record(
        db, project_id="site-a", inspection_result=result,
        configuration={"task": "exploration"},
        model_versions={"onboarding": "1.0"},
        software_version="test", actor_id="user-a", created_at=NOW,
    )
    assert manifest["output_summary"]["execution_performed"] is False
    assert manifest["input_artifact_hashes"] == [hashlib.sha256(CSV).hexdigest()]
    assert verify_audit_chain(db)["valid"] is True


def test_application_service_reopens_existing_project_after_audit_verification(tmp_path):
    db = tmp_path / "workspace.sqlite3"
    create_local_project(
        db, workspace_id="workspace-a", project_id="site-a",
        display_name="Site A", actor_id="user-a",
        consent_to_store_metadata=True, created_at=NOW,
    )
    opened = open_local_project(db, project_id="site-a")
    assert opened["project"]["display_name"] == "Site A"
    assert opened["audit"]["valid"] is True
    assert opened["audit"]["event_count"] == 2


def test_application_service_refuses_to_open_unknown_project(tmp_path):
    db = tmp_path / "workspace.sqlite3"
    create_local_project(
        db, workspace_id="workspace-a", project_id="site-a",
        display_name="Site A", actor_id="user-a",
        consent_to_store_metadata=True, created_at=NOW,
    )
    with pytest.raises(ValueError, match="does not exist"):
        open_local_project(db, project_id="unknown")


def test_application_service_requires_consent_before_workspace_creation(tmp_path):
    with pytest.raises(ValueError, match="explicit consent"):
        create_local_project(
            tmp_path / "not-created.sqlite3", workspace_id="w", project_id="p",
            display_name="No consent", actor_id="u",
            consent_to_store_metadata=False, created_at=NOW,
        )
    assert not (tmp_path / "not-created.sqlite3").exists()


def test_application_service_blocks_analysis_when_task_is_not_ready(tmp_path):
    result = inspect_upload(
        CSV, file_name="customer-load.csv", source_type="customer_provided",
        task="forecasting", now=NOW,
    )
    assert result["readiness"]["can_run"] is False
    with pytest.raises(ValueError, match="blocked by task readiness"):
        create_analysis_record(
            tmp_path / "unused.sqlite3", project_id="site-a",
            inspection_result=result, configuration={},
            model_versions={"forecast": "0"}, software_version="test",
            actor_id="user-a", created_at=NOW,
        )


def test_application_service_rejects_unsupported_file_types():
    with pytest.raises(ValueError, match="unsupported upload format"):
        inspect_upload(b"anything", file_name="site.pdf", source_type="customer_provided", now=NOW)


def test_application_service_does_not_accept_raw_bytes_for_metadata_registration():
    with pytest.raises(ValueError, match="inspection report"):
        register_inspected_import(
            ":memory:", project_id="site-a", file_name="site.csv",
            inspection_result={"inspection": b"raw customer bytes"},
            actor_id="user-a", consent_to_store_metadata=True, imported_at=NOW,
        )


def test_application_service_persists_and_reloads_versioned_asset_registry(tmp_path):
    from islandos_core.assets import AssetParameter, AssetRecord, OperatingConstraint
    db = tmp_path / "workspace.sqlite3"
    create_local_project(
        db, workspace_id="workspace-a", project_id="site-a",
        display_name="Site A", actor_id="user-a",
        consent_to_store_metadata=True, created_at=NOW,
    )
    asset = AssetRecord(
        asset_id="pv-01", site_id="site-a", asset_type="pv",
        nameplate_parameters={"rated_power_kw": AssetParameter(100, "kW", "vendor_specification", "datasheet", True)},
        installed_parameters={"configured_power_kw": AssetParameter(80, "kW", "customer_provided", "site schedule", True)},
        observed_parameters={},
        constraints=(OperatingConstraint(
            constraint_id="pv-max", parameter="max_power_kw", severity="hard",
            unit="kW", operator="max", upper_bound=80,
            source_type="customer_provided", source_reference="approved schedule", confirmed=True,
        ),),
    )
    saved = register_project_asset(db, project_id="site-a", asset=asset, actor_id="user-a", consent_to_store_assets=True, saved_at=NOW)
    restored = list_project_assets(db, project_id="site-a")
    assert saved["version"] == 1
    assert restored[0]["asset"] == asset
    assert restored[0]["readiness"]["can_screen"] is True


def test_application_service_requires_explicit_consent_to_store_asset_configuration(tmp_path):
    from islandos_core.assets import AssetParameter, AssetRecord
    db = tmp_path / "workspace.sqlite3"
    create_local_project(
        db, workspace_id="workspace-a", project_id="site-a",
        display_name="Site A", actor_id="user-a",
        consent_to_store_metadata=True, created_at=NOW,
    )
    asset = AssetRecord(
        asset_id="pv-01", site_id="site-a", asset_type="pv",
        nameplate_parameters={}, installed_parameters={
            "configured_power_kw": AssetParameter(10, "kW", "customer_provided", "site schedule", True)
        }, observed_parameters={}, constraints=(),
    )
    with pytest.raises(ValueError, match="explicit consent"):
        register_project_asset(
            db, project_id="site-a", asset=asset, actor_id="user-a",
            consent_to_store_assets=False, saved_at=NOW,
        )

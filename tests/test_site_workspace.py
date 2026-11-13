from __future__ import annotations

import hashlib
import json
import sqlite3
import zipfile

import pytest

from islandos_core.site_workspace import (
    export_project_package,
    import_project_package,
    inspect_project_package,
    list_site_profiles,
    read_retained_source_file,
    retain_source_file,
    save_site_profile,
)
from islandos_core.workspace_store import (
    WorkspaceStoreError,
    create_project,
    initialize_workspace,
    record_import_artifact,
    list_import_artifacts,
    verify_audit_chain,
)


def make_workspace(tmp_path):
    db = tmp_path / "workspace.sqlite3"
    initialize_workspace(db, workspace_id="test-workspace", actor_id="tester")
    create_project(
        db, project_id="site-1", display_name="Test site",
        actor_id="tester", consent_to_store_metadata=True,
    )
    return db


def test_site_profile_is_versioned_and_timezone_validated(tmp_path):
    db = make_workspace(tmp_path)
    first = save_site_profile(
        db, project_id="site-1",
        profile={
            "site_name": "North microgrid", "site_type": "microgrid",
            "country": "Japan", "timezone": "Asia/Tokyo", "currency": "JPY",
        },
        actor_id="tester",
    )
    second = save_site_profile(
        db, project_id="site-1",
        profile={
            "site_name": "North microgrid", "site_type": "microgrid",
            "country": "Japan", "timezone": "Asia/Tokyo", "currency": "JPY",
            "description": "Updated operating context",
        },
        actor_id="tester",
    )
    history = list_site_profiles(db, project_id="site-1")
    assert [item["version"] for item in history] == [1, 2]
    assert first["profile_sha256"] != second["profile_sha256"]
    with pytest.raises(WorkspaceStoreError, match="IANA timezone"):
        save_site_profile(
            db, project_id="site-1",
            profile={"site_name": "Bad timezone", "timezone": "Mars/Olympus", "currency": "USD"},
            actor_id="tester",
        )
    with sqlite3.connect(db) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "UPDATE site_profile_versions SET profile_json='{}' WHERE profile_version_id=?",
                (first["profile_version_id"],),
            )
    assert verify_audit_chain(db)["valid"] is True


def test_source_retention_requires_consent_and_matches_import_hash(tmp_path):
    db = make_workspace(tmp_path)
    source = b"timestamp,load_kw\n2026-01-01T00:00:00Z,10\n"
    digest = hashlib.sha256(source).hexdigest()
    artifact_id = record_import_artifact(
        db, project_id="site-1", file_name="C:\\private\\meter.csv",
        media_type="text/csv", sha256=digest, source_type="customer_provided",
        row_count=1, signal_count=1, quality_status="valid",
        actor_id="tester", consent_to_store_metadata=True,
    )
    storage = tmp_path / "private-source-store"
    with pytest.raises(WorkspaceStoreError, match="explicit consent"):
        retain_source_file(
            db, storage, project_id="site-1", artifact_id=artifact_id,
            file_name="meter.csv", content=source, actor_id="tester",
            explicit_consent=False,
        )
    with pytest.raises(WorkspaceStoreError, match="do not match"):
        retain_source_file(
            db, storage, project_id="site-1", artifact_id=artifact_id,
            file_name="meter.csv", content=b"tampered", actor_id="tester",
            explicit_consent=True,
        )
    retained = retain_source_file(
        db, storage, project_id="site-1", artifact_id=artifact_id,
        file_name="meter.csv", content=source, actor_id="tester",
        explicit_consent=True,
    )
    metadata, restored = read_retained_source_file(db, storage, artifact_id=artifact_id)
    assert restored == source
    assert metadata["sha256"] == digest
    assert retained["byte_count"] == len(source)
    assert verify_audit_chain(db)["valid"] is True


def test_exported_project_package_verifies_and_contains_optional_source(tmp_path):
    db = make_workspace(tmp_path)
    save_site_profile(
        db, project_id="site-1",
        profile={
            "site_name": "Test site", "site_type": "island",
            "country": "Japan", "timezone": "Asia/Tokyo", "currency": "JPY",
        },
        actor_id="tester",
    )
    source = b"timestamp,load_kw\n2026-01-01T00:00:00Z,10\n"
    digest = hashlib.sha256(source).hexdigest()
    artifact_id = record_import_artifact(
        db, project_id="site-1", file_name="meter.csv", media_type="text/csv",
        sha256=digest, source_type="measured", row_count=1, signal_count=1,
        quality_status="valid", actor_id="tester", consent_to_store_metadata=True,
    )
    storage = tmp_path / "source-store"
    retain_source_file(
        db, storage, project_id="site-1", artifact_id=artifact_id,
        file_name="meter.csv", content=source, actor_id="tester",
        explicit_consent=True,
    )
    target = tmp_path / "site-1.zip"
    result = export_project_package(
        db, target, project_id="site-1", storage_dir=storage,
        include_retained_sources=True,
    )
    assert result["integrity"] == "verified"
    inspected = inspect_project_package(target.read_bytes())
    assert inspected["valid"] is True
    assert inspected["project_id"] == "site-1"
    assert inspected["import_count"] == 1
    assert inspected["retained_source_count"] == 1
    with zipfile.ZipFile(target) as archive:
        assert archive.read(f"source_files/{artifact_id}.csv") == source


def test_package_inspection_rejects_tampered_payload(tmp_path):
    db = make_workspace(tmp_path)
    target = tmp_path / "empty-project.zip"
    export_project_package(db, target, project_id="site-1")
    content = bytearray(target.read_bytes())
    content[-10] ^= 0x01
    with pytest.raises(WorkspaceStoreError):
        inspect_project_package(bytes(content))


def test_project_package_import_creates_new_project_and_revalidates_sources(tmp_path):
    source_db = make_workspace(tmp_path / "source")
    save_site_profile(
        source_db, project_id="site-1",
        profile={
            "site_name": "Portable site", "site_type": "community",
            "country": "Japan", "timezone": "Asia/Tokyo", "currency": "JPY",
        },
        actor_id="tester",
    )
    source_bytes = b"timestamp,load_kw\\n2026-01-01T00:00:00Z,10\\n"
    digest = hashlib.sha256(source_bytes).hexdigest()
    old_artifact = record_import_artifact(
        source_db, project_id="site-1", file_name="meter.csv", media_type="text/csv",
        sha256=digest, source_type="measured", row_count=1, signal_count=1,
        quality_status="valid", actor_id="tester", consent_to_store_metadata=True,
    )
    source_storage = tmp_path / "source-files"
    retain_source_file(
        source_db, source_storage, project_id="site-1", artifact_id=old_artifact,
        file_name="meter.csv", content=source_bytes, actor_id="tester",
        explicit_consent=True,
    )
    package_path = tmp_path / "portable.zip"
    export_project_package(
        source_db, package_path, project_id="site-1",
        storage_dir=source_storage, include_retained_sources=True,
    )

    destination_db = tmp_path / "destination" / "workspace.sqlite3"
    initialize_workspace(destination_db, workspace_id="destination-workspace", actor_id="importer")
    destination_storage = tmp_path / "destination-files"
    imported = import_project_package(
        destination_db, package_path.read_bytes(), actor_id="importer",
        new_project_id="site-imported", new_project_name="Imported site",
        consent_to_store_metadata=True, storage_dir=destination_storage,
        retain_sources=True,
    )
    assert imported["project_id"] == "site-imported"
    assert imported["site_profile_versions_imported"] == 1
    assert imported["import_artifacts_imported"] == 1
    assert imported["source_files_retained"] == 1
    imported_artifacts = list_import_artifacts(destination_db, project_id="site-imported")
    assert len(imported_artifacts) == 1
    _, restored = read_retained_source_file(
        destination_db, destination_storage, artifact_id=imported_artifacts[0]["artifact_id"]
    )
    assert restored == source_bytes
    assert verify_audit_chain(destination_db)["valid"] is True

from datetime import datetime, timezone
import sqlite3

import pytest

from islandos_core.workspace_store import (
    AuditIntegrityError,
    WorkspaceStoreError,
    backup_workspace,
    create_project,
    initialize_workspace,
    restore_workspace,
    verify_audit_chain,
)


NOW = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)


def make_workspace(path):
    initialize_workspace(
        path, workspace_id="workspace-backup-test",
        actor_id="test-operator", created_at=NOW,
    )
    create_project(
        path, project_id="site-backup-test", display_name="Backup Test Site",
        actor_id="test-operator", consent_to_store_metadata=True, created_at=NOW,
    )


def test_backup_and_restore_preserve_projects_and_audit_chain(tmp_path):
    source = tmp_path / "source.sqlite3"
    backup = tmp_path / "backups" / "workspace.sqlite3"
    restored = tmp_path / "restored.sqlite3"
    make_workspace(source)

    result = backup_workspace(source, backup)
    assert result["integrity"] == "ok"
    assert len(result["sha256"]) == 64
    assert result["audit_event_count"] == 2

    restored_result = restore_workspace(backup, restored)
    assert restored_result["integrity"] == "ok"
    assert restored_result["sha256"] == result["sha256"]
    assert verify_audit_chain(restored)["valid"] is True
    with sqlite3.connect(restored) as connection:
        row = connection.execute(
            "SELECT display_name FROM projects WHERE project_id=?",
            ("site-backup-test",),
        ).fetchone()
    assert row == ("Backup Test Site",)


def test_backup_refuses_overwrite_without_explicit_opt_in(tmp_path):
    source = tmp_path / "source.sqlite3"
    backup = tmp_path / "backup.sqlite3"
    make_workspace(source)
    backup.write_bytes(b"keep existing backup")
    with pytest.raises(WorkspaceStoreError, match="already exists"):
        backup_workspace(source, backup)
    assert backup.read_bytes() == b"keep existing backup"


def test_restore_refuses_invalid_or_tampered_backup(tmp_path):
    source = tmp_path / "source.sqlite3"
    backup = tmp_path / "backup.sqlite3"
    destination = tmp_path / "restored.sqlite3"
    make_workspace(source)
    backup_workspace(source, backup)

    with sqlite3.connect(backup) as connection:
        connection.execute("DROP TRIGGER audit_events_no_update")
        connection.execute(
            "UPDATE audit_events SET payload_json='{}' WHERE sequence=1"
        )
    with pytest.raises(AuditIntegrityError, match="audit chain is invalid"):
        restore_workspace(backup, destination)
    assert not destination.exists()


def test_backup_requires_supported_workspace_and_distinct_paths(tmp_path):
    arbitrary = tmp_path / "not-a-workspace.sqlite3"
    with sqlite3.connect(arbitrary):
        pass
    with pytest.raises(WorkspaceStoreError, match="supported IslandOS workspace"):
        backup_workspace(arbitrary, tmp_path / "backup.sqlite3")

    source = tmp_path / "source.sqlite3"
    make_workspace(source)
    with pytest.raises(WorkspaceStoreError, match="must differ"):
        backup_workspace(source, source)

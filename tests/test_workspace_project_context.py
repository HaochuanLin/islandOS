from __future__ import annotations

from pathlib import Path

from islandos_core.workspace_store import create_project, initialize_workspace
from islandos_ui.workspace_project_context import (
    load_workspace_projects,
    resolve_selected_project,
)


def _enabled_env(db_path: Path) -> dict[str, str]:
    return {
        "ISLANDOS_ENABLE_LOCAL_WORKSPACE": "1",
        "ISLANDOS_WORKSPACE_DB": str(db_path),
    }


def test_workspace_project_lookup_is_disabled_by_default(tmp_path):
    db_path = tmp_path / "not-created.sqlite3"

    lookup = load_workspace_projects(environ={"ISLANDOS_WORKSPACE_DB": str(db_path)})

    assert lookup.status == "disabled"
    assert lookup.db_path is None
    assert lookup.projects == ()
    assert not db_path.exists()


def test_enabled_but_missing_workspace_is_not_initialised_implicitly(tmp_path):
    db_path = tmp_path / "missing" / "workspace.sqlite3"

    lookup = load_workspace_projects(environ=_enabled_env(db_path))

    assert lookup.status == "not_initialized"
    assert lookup.db_path == db_path
    assert lookup.projects == ()
    assert not db_path.exists()
    assert not db_path.parent.exists()


def test_existing_empty_workspace_returns_available_empty_project_list(tmp_path):
    db_path = tmp_path / "workspace.sqlite3"
    initialize_workspace(db_path, workspace_id="test-workspace", actor_id="test")

    lookup = load_workspace_projects(environ=_enabled_env(db_path))

    assert lookup.status == "available"
    assert lookup.projects == ()


def test_lookup_lists_only_explicitly_created_projects_and_resolves_selection(tmp_path):
    db_path = tmp_path / "workspace.sqlite3"
    initialize_workspace(db_path, workspace_id="test-workspace", actor_id="test")
    create_project(
        db_path,
        project_id="site-test123",
        display_name="Demo site",
        actor_id="test",
        consent_to_store_metadata=True,
    )

    lookup = load_workspace_projects(environ=_enabled_env(db_path))

    assert lookup.status == "available"
    assert [(item.project_id, item.display_name) for item in lookup.projects] == [
        ("site-test123", "Demo site")
    ]
    assert resolve_selected_project(lookup, "site-test123") == lookup.projects[0]
    assert resolve_selected_project(lookup, "site-deleted") is None
    assert resolve_selected_project(lookup, None) is None
    assert resolve_selected_project(lookup, "   ") is None


def test_unavailable_database_fails_closed(tmp_path):
    db_path = tmp_path / "not-a-workspace.sqlite3"
    db_path.write_text("not sqlite", encoding="utf-8")

    lookup = load_workspace_projects(environ=_enabled_env(db_path))

    assert lookup.status == "unavailable"
    assert lookup.projects == ()
    assert resolve_selected_project(lookup, "site-anything") is None

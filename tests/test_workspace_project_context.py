from __future__ import annotations

import hashlib
from pathlib import Path
import sqlite3

from islandos_core.workspace_store import create_project, initialize_workspace
from islandos_ui.workspace_project_context import (
    ACTIVE_PROJECT_SESSION_KEY,
    ProjectBinding,
    WorkspaceProjectLookup,
    clear_active_project,
    get_active_project_id,
    load_project_binding,
    load_workspace_projects,
    resolve_project_binding,
    resolve_selected_project,
    set_active_project,
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


def test_empty_workspace_is_unregistered_not_registered(tmp_path):
    db_path = tmp_path / "workspace.sqlite3"
    initialize_workspace(db_path, workspace_id="test-workspace", actor_id="test")

    lookup = load_workspace_projects(environ=_enabled_env(db_path))

    assert lookup.status == "available"
    binding = resolve_project_binding(lookup, None)
    assert binding.status == "unregistered"
    assert binding.project is None
    assert binding.selection_source == "none"


def test_registered_and_no_selection_bindings_are_distinct(tmp_path):
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

    registered = resolve_project_binding(lookup, "site-test123")
    unregistered = resolve_project_binding(lookup, None)
    invalid = resolve_project_binding(lookup, "site-unknown")

    assert registered.status == "registered"
    assert registered.project is not None
    assert registered.project.project_id == "site-test123"
    assert registered.selection_source == "active_project_key"
    assert unregistered.status == "unregistered"
    assert invalid.status == "invalid"
    assert invalid.project is None
    assert invalid.selected_project_id == "site-unknown"


def test_deleted_project_leaves_the_old_selection_invalid(tmp_path):
    db_path = tmp_path / "workspace.sqlite3"
    initialize_workspace(db_path, workspace_id="test-workspace", actor_id="test")
    create_project(
        db_path,
        project_id="site-deleted123",
        display_name="Deleted site",
        actor_id="test",
        consent_to_store_metadata=True,
    )
    with sqlite3.connect(db_path) as connection:
        connection.execute("DELETE FROM projects WHERE project_id = ?", ("site-deleted123",))

    lookup = load_workspace_projects(environ=_enabled_env(db_path))
    binding = resolve_project_binding(lookup, "site-deleted123")

    assert binding.status == "invalid"
    assert binding.project is None
    assert resolve_selected_project(lookup, "site-deleted123") is None


def test_shared_session_key_helpers_do_not_invent_a_project():
    session_state: dict[str, object] = {}
    assert get_active_project_id(session_state) is None
    assert ACTIVE_PROJECT_SESSION_KEY == "islandos_active_project_id"

    set_active_project(session_state, "site-test123")
    assert get_active_project_id(session_state) == "site-test123"
    clear_active_project(session_state)
    assert get_active_project_id(session_state) is None


def test_load_project_binding_reads_the_shared_key(tmp_path):
    db_path = tmp_path / "workspace.sqlite3"
    initialize_workspace(db_path, workspace_id="test-workspace", actor_id="test")
    create_project(
        db_path,
        project_id="site-test123",
        display_name="Demo site",
        actor_id="test",
        consent_to_store_metadata=True,
    )
    session_state = {ACTIVE_PROJECT_SESSION_KEY: "site-test123"}

    binding = load_project_binding(
        environ=_enabled_env(db_path),
        session_state=session_state,
    )

    assert binding.status == "registered"
    assert binding.project is not None
    assert binding.project.project_id == "site-test123"


def test_lookup_is_read_only_and_does_not_change_workspace_bytes(tmp_path):
    db_path = tmp_path / "workspace.sqlite3"
    initialize_workspace(db_path, workspace_id="test-workspace", actor_id="test")
    before = hashlib.sha256(db_path.read_bytes()).hexdigest()
    before_children = sorted(path.name for path in db_path.parent.iterdir())

    lookup = load_workspace_projects(environ=_enabled_env(db_path))

    assert lookup.status == "available"
    assert hashlib.sha256(db_path.read_bytes()).hexdigest() == before
    assert sorted(path.name for path in db_path.parent.iterdir()) == before_children


def test_pages_share_the_same_binding_surface():
    root = Path(__file__).parents[1]
    page_05 = (root / "pages" / "05_Customer_Decision_Dashboard.py").read_text(encoding="utf-8")
    page_06 = (root / "pages" / "06_Forecast_Led_Joint_Resource_Optimizer.py").read_text(encoding="utf-8")
    page_08 = (root / "pages" / "08_Site_Workspace.py").read_text(encoding="utf-8")

    assert "render_optional_project_selector(" in page_05
    assert "render_optional_project_selector(" in page_06
    assert "sync_project_selector_widget_state(" in page_08
    assert "set_active_project(st.session_state, project_id)" in page_08


def test_binding_covers_disabled_not_initialized_and_unavailable():
    for status in ("disabled", "not_initialized", "unavailable"):
        binding = resolve_project_binding(
            WorkspaceProjectLookup(status=status, db_path=None),
            "site-test123",
        )
        assert binding.status == status
        assert binding.project is None
        assert binding.selection_source == "none"


def test_binding_is_not_a_consent_or_write_permission():
    binding = ProjectBinding(status="registered")
    assert not hasattr(binding, "consent_to_store")
    assert not hasattr(binding, "persistence_allowed")
    assert not hasattr(binding, "can_write")


def test_project_selector_widget_state_is_refreshed_from_shared_selection():
    from islandos_ui.project_context_selector import sync_project_selector_widget_state

    labels = {
        "North site · site-north": "site-north",
        "South site · site-south": "site-south",
    }
    session_state: dict[str, object] = {
        ACTIVE_PROJECT_SESSION_KEY: "site-south",
        "page_05_project_selector": "North site · site-north",
    }

    selected = sync_project_selector_widget_state(
        session_state,
        widget_key="page_05_project_selector",
        labels=labels,
    )

    assert selected == "South site · site-south"
    assert session_state["page_05_project_selector"] == selected


def test_project_selector_widget_change_updates_shared_selection():
    from islandos_ui.project_context_selector import apply_project_selector_widget_change

    labels = {
        "North site · site-north": "site-north",
        "South site · site-south": "site-south",
    }
    session_state: dict[str, object] = {
        ACTIVE_PROJECT_SESSION_KEY: "site-north",
        "page_06_project_selector": "South site · site-south",
    }

    apply_project_selector_widget_change(
        session_state,
        widget_key="page_06_project_selector",
        labels=labels,
    )

    assert get_active_project_id(session_state) == "site-south"


def test_project_selector_clears_stale_shared_selection():
    from islandos_ui.project_context_selector import sync_project_selector_widget_state

    session_state: dict[str, object] = {
        ACTIVE_PROJECT_SESSION_KEY: "site-deleted",
    }
    labels = {"Current site · site-current": "site-current"}

    selected = sync_project_selector_widget_state(
        session_state,
        widget_key="page_05_project_selector",
        labels=labels,
    )

    assert selected == "— No project selected —"
    assert get_active_project_id(session_state) is None

"""Read-only access to explicitly created local Workspace projects.

This adapter never initialises a Workspace or creates a project. It is safe for
Pages 05/06 to use as an optional persistence-context lookup: calculations must
remain available when the Workspace is disabled or no project is selected.
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
import os
from pathlib import Path
import sqlite3
from collections.abc import Mapping, MutableMapping
from typing import Literal


WorkspaceLookupStatus = Literal["disabled", "not_initialized", "available", "unavailable"]
ProjectBindingStatus = Literal[
    "disabled", "not_initialized", "unregistered", "registered", "invalid", "unavailable"
]
SelectionSource = Literal["none", "active_project_key"]

ACTIVE_PROJECT_SESSION_KEY = "islandos_active_project_id"


@dataclass(frozen=True)
class WorkspaceProject:
    project_id: str
    display_name: str


@dataclass(frozen=True)
class WorkspaceProjectLookup:
    status: WorkspaceLookupStatus
    db_path: Path | None
    projects: tuple[WorkspaceProject, ...] = ()


@dataclass(frozen=True)
class ProjectBinding:
    """A read-only project selection state; it is never a write permission."""

    status: ProjectBindingStatus
    project: WorkspaceProject | None = None
    selected_project_id: str | None = None
    selection_source: SelectionSource = "none"


def load_workspace_projects(
    *,
    environ: Mapping[str, str] | None = None,
) -> WorkspaceProjectLookup:
    """List existing local projects without creating or migrating a Workspace.

    The Workspace must be explicitly enabled with ISLANDOS_ENABLE_LOCAL_WORKSPACE=1.
    A missing database is reported as not_initialized; callers must not initialise
    it implicitly. SQLite is opened in read-only mode to avoid creating a database
    if the file disappears between the existence check and the connection.
    """
    env = os.environ if environ is None else environ
    if env.get("ISLANDOS_ENABLE_LOCAL_WORKSPACE", "").strip() != "1":
        return WorkspaceProjectLookup(status="disabled", db_path=None)

    raw_path = env.get("ISLANDOS_WORKSPACE_DB", ".islandos/workspace.sqlite3").strip()
    if not raw_path:
        raw_path = ".islandos/workspace.sqlite3"
    db_path = Path(raw_path).expanduser()
    if not db_path.is_file():
        return WorkspaceProjectLookup(status="not_initialized", db_path=db_path)

    try:
        read_only_uri = db_path.resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(read_only_uri, uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                "SELECT project_id, display_name FROM projects ORDER BY created_at, project_id"
            ).fetchall()
    except (OSError, sqlite3.Error):
        # Do not leak a local path or database details into a page-level message.
        return WorkspaceProjectLookup(status="unavailable", db_path=db_path)

    projects = tuple(
        WorkspaceProject(
            project_id=str(row["project_id"]),
            display_name=str(row["display_name"]),
        )
        for row in rows
    )
    return WorkspaceProjectLookup(status="available", db_path=db_path, projects=projects)


def resolve_selected_project(
    lookup: WorkspaceProjectLookup,
    selected_project_id: str | None,
) -> WorkspaceProject | None:
    """Resolve a session selection against the current DB snapshot.

    A stale, unknown, blank, or unselected ID returns None. The caller must
    refresh the lookup immediately before any persistence write as well.
    """
    if lookup.status != "available":
        return None
    if not isinstance(selected_project_id, str) or not selected_project_id.strip():
        return None
    return next(
        (project for project in lookup.projects if project.project_id == selected_project_id),
        None,
    )


def get_active_project_id(session_state: Mapping[str, object]) -> str | None:
    """Read the shared selection key without inventing or persisting a project."""
    value = session_state.get(ACTIVE_PROJECT_SESSION_KEY)
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def set_active_project(
    session_state: MutableMapping[str, object],
    project_id: str,
) -> None:
    """Record an explicit selection in the one shared session key."""
    if not isinstance(project_id, str) or not project_id.strip():
        raise ValueError("project_id must be a non-empty string")
    session_state[ACTIVE_PROJECT_SESSION_KEY] = project_id.strip()


def clear_active_project(session_state: MutableMapping[str, object]) -> None:
    """Remove the selection; a later run is unregistered, not auto-bound."""
    session_state.pop(ACTIVE_PROJECT_SESSION_KEY, None)


def resolve_project_binding(
    lookup: WorkspaceProjectLookup,
    selected_project_id: str | None,
) -> ProjectBinding:
    """Classify the shared selection against a fresh read-only lookup.

    ``registered`` only means that the project exists. It does not assert
    result-storage consent or authorize a write; those checks belong to the
    persistence layer.
    """
    if lookup.status in {"disabled", "not_initialized", "unavailable"}:
        return ProjectBinding(status=lookup.status)

    selected = (
        selected_project_id.strip()
        if isinstance(selected_project_id, str) and selected_project_id.strip()
        else None
    )
    if selected is None:
        return ProjectBinding(status="unregistered")

    project = resolve_selected_project(lookup, selected)
    if project is None:
        return ProjectBinding(
            status="invalid",
            selected_project_id=selected,
            selection_source="active_project_key",
        )
    return ProjectBinding(
        status="registered",
        project=project,
        selected_project_id=selected,
        selection_source="active_project_key",
    )


def load_project_binding(
    *,
    environ: Mapping[str, str] | None = None,
    session_state: Mapping[str, object] | None = None,
) -> ProjectBinding:
    """Load a fresh lookup and classify the shared session selection."""
    lookup = load_workspace_projects(environ=environ)
    selected = get_active_project_id(session_state) if session_state is not None else None
    return resolve_project_binding(lookup, selected)

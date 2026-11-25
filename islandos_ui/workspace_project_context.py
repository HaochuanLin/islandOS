"""Read-only access to explicitly created local Workspace projects.

This adapter never initialises a Workspace or creates a project. It is safe for
Pages 05/06 to use as an optional persistence-context lookup: calculations must
remain available when the Workspace is disabled or no project is selected.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sqlite3
from typing import Literal, Mapping


WorkspaceLookupStatus = Literal["disabled", "not_initialized", "available", "unavailable"]


@dataclass(frozen=True)
class WorkspaceProject:
    project_id: str
    display_name: str


@dataclass(frozen=True)
class WorkspaceProjectLookup:
    status: WorkspaceLookupStatus
    db_path: Path | None
    projects: tuple[WorkspaceProject, ...] = ()


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
        with sqlite3.connect(read_only_uri, uri=True) as connection:
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

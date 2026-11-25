"""Optional Streamlit selector for the shared local Workspace project context."""
from __future__ import annotations

from collections.abc import MutableMapping

import streamlit as st

from islandos_ui.workspace_project_context import (
    ProjectBinding,
    clear_active_project,
    get_active_project_id,
    load_workspace_projects,
    resolve_project_binding,
    set_active_project,
)


_NO_PROJECT_LABEL = "— No project selected —"


def render_optional_project_selector(
    session_state: MutableMapping[str, object],
    *,
    widget_key: str = "project_context_active_project_selector",
) -> ProjectBinding:
    """Render a read-only selector; never create, initialise or authorize a write."""
    lookup = load_workspace_projects()
    if lookup.status == "disabled":
        return ProjectBinding(status="disabled")
    if lookup.status == "not_initialized":
        st.caption("Project context: local Workspace not initialized. Simulation-only run.")
        return ProjectBinding(status="not_initialized")
    if lookup.status == "unavailable":
        st.warning("Project context is unavailable. Simulation can continue; no project is selected.")
        return ProjectBinding(status="unavailable")
    if not lookup.projects:
        st.caption("Project context: no local projects. Simulation-only run.")
        return ProjectBinding(status="unregistered")

    st.subheader("Project context (optional)")
    labels = {
        f"{project.display_name} · {project.project_id}": project.project_id
        for project in lookup.projects
    }
    current = get_active_project_id(session_state)
    options = [_NO_PROJECT_LABEL, *labels]
    index = 0
    if current is not None:
        index = next(
            (position for position, label in enumerate(options) if labels.get(label) == current),
            0,
        )
    selected = st.selectbox(
        "Active project",
        options,
        index=index,
        key=widget_key,
        help="Selection only. It does not grant consent or write permission.",
    )
    if selected == _NO_PROJECT_LABEL:
        clear_active_project(session_state)
    else:
        set_active_project(session_state, labels[selected])

    binding = resolve_project_binding(lookup, get_active_project_id(session_state))
    if binding.status == "invalid":
        st.warning("The selected project no longer exists. Selection cleared; simulation-only run.")
        clear_active_project(session_state)
        return ProjectBinding(status="unregistered")
    if binding.status == "registered" and binding.project is not None:
        st.caption(
            f"Project: {binding.project.display_name} · {binding.project.project_id}. "
            "Selection only; this page does not persist run records."
        )
    else:
        st.caption("No project selected. Simulation can run; results are not saved to a project.")
    return binding

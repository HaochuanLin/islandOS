"""Optional Streamlit selector for the shared local Workspace project context."""
from __future__ import annotations

from collections.abc import Mapping, MutableMapping

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


def sync_project_selector_widget_state(
    session_state: MutableMapping[str, object],
    *,
    widget_key: str,
    labels: Mapping[str, str],
) -> str:
    """Seed a page-local widget from the shared active-project session value."""
    active_project_id = get_active_project_id(session_state)
    if active_project_id is not None and active_project_id not in labels.values():
        clear_active_project(session_state)
        active_project_id = None

    selected_label = next(
        (label for label, project_id in labels.items() if project_id == active_project_id),
        _NO_PROJECT_LABEL,
    )
    session_state[widget_key] = selected_label
    return selected_label


def apply_project_selector_widget_change(
    session_state: MutableMapping[str, object],
    *,
    widget_key: str,
    labels: Mapping[str, str],
) -> None:
    """Copy a page-local widget change into the shared active-project value."""
    selected_label = session_state.get(widget_key)
    if selected_label == _NO_PROJECT_LABEL:
        clear_active_project(session_state)
    elif isinstance(selected_label, str) and selected_label in labels:
        set_active_project(session_state, labels[selected_label])
    else:
        clear_active_project(session_state)


def on_project_selector_widget_change(
    widget_key: str,
    labels: Mapping[str, str],
) -> None:
    """Streamlit callback shared by the Page 05/06 and Page 08 selectors."""
    apply_project_selector_widget_change(
        st.session_state,
        widget_key=widget_key,
        labels=labels,
    )


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
        clear_active_project(session_state)
        session_state[widget_key] = _NO_PROJECT_LABEL
        st.caption("Project context: no local projects. Simulation-only run.")
        return ProjectBinding(status="unregistered")

    st.subheader("Project context (optional)")
    labels = {
        f"{project.display_name} · {project.project_id}": project.project_id
        for project in lookup.projects
    }
    sync_project_selector_widget_state(
        session_state,
        widget_key=widget_key,
        labels=labels,
    )
    st.selectbox(
        "Active project",
        [_NO_PROJECT_LABEL, *labels],
        key=widget_key,
        on_change=on_project_selector_widget_change,
        args=(widget_key, labels),
        help="Selection only. It does not grant consent or write permission.",
    )

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

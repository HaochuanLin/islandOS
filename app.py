"""IslandOS entry point: one navigation menu for every surface.

The section UI itself lives in ``islandos_ui/workspace.py``. This module only
decides which pages exist and how they are grouped, so the menu can be changed
without touching the workspace logic, and the workspace can grow without adding
another competing sidebar.

Local-only pages (customer workspace, site workspace) need different
prerequisites. The customer workspace needs the loopback reference service
(`ISLANDOS_API_BASE_URL`); the site workspace needs the local data directory
(`ISLANDOS_ENABLE_LOCAL_WORKSPACE=1`). Each page is registered only when its own
prerequisite is present, so neither can become a dead end for the other. Both
pages keep their own guards; this file only decides whether to offer them in the
menu.
"""

from __future__ import annotations

import streamlit as st

from islandos_core import build_info
from islandos_ui.deployment_gates import (
    local_customer_workspace_enabled,
    local_site_workspace_enabled,
)
from islandos_ui.navigation import page_url_path



st.set_page_config(
    page_title="IslandOS | Decision Lab",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_data(ttl=300, show_spinner=False)
def deployment_stamp() -> dict:
    """The build stamp for this deployment, written to ``static/build_info.json``.

    A self-hosted run serves that file at ``/app/static/build_info.json``;
    Community Cloud answers that route with the front-end shell, so the sidebar
    renders the same stamp as a caption plus a JSON download, and
    ``scripts/check_deployment.py`` reads the file where it is served and the
    download where it is not. The write is best-effort: a read-only deployment
    still renders the page, and the stamp still reaches the reader through the
    sidebar.
    """
    stamp = build_info.build_stamp()
    try:
        build_info.write_stamp(stamp)
    except OSError:
        pass
    return stamp


def _url_path(page_file: str) -> str:
    return page_url_path(page_file)


def navigation_pages() -> dict:
    """Build the single menu. Order and groups are the only thing this file owns."""
    groups = {
        "Decision workspace": [
            st.Page("islandos_ui/workspace.py", title="Workspace", icon="⚡", default=True),
        ],
        "Customer views": [
            st.Page(
                "pages/05_Customer_Decision_Dashboard.py",
                title="Decision dashboard",
                icon="📊",
                url_path=_url_path("pages/05_Customer_Decision_Dashboard.py"),
            ),
            st.Page(
                "pages/06_Forecast_Led_Joint_Resource_Optimizer.py",
                title="Joint resource optimizer",
                icon="🔁",
                url_path=_url_path("pages/06_Forecast_Led_Joint_Resource_Optimizer.py"),
            ),
            st.Page(
                "pages/09_Device_Flexibility_Planner.py",
                title="Device flexibility planner",
                icon="🔌",
                url_path=_url_path("pages/09_Device_Flexibility_Planner.py"),
            ),
        ],
        "Experimental": [
            st.Page(
                "pages/2_Rolling_Horizon_Lab.py",
                title="Rolling horizon lab",
                icon="🧪",
                url_path=_url_path("pages/2_Rolling_Horizon_Lab.py"),
            ),
        ],
    }
    local_pages = []
    if local_customer_workspace_enabled():
        local_pages.append(
            st.Page(
                "pages/07_Local_Customer_Workspace.py",
                title="Customer workspace (local)",
                icon="🗂️",
                url_path=_url_path("pages/07_Local_Customer_Workspace.py"),
            )
        )
    if local_site_workspace_enabled():
        local_pages.append(
            st.Page(
                "pages/08_Site_Workspace.py",
                title="Site workspace (local)",
                icon="🏗️",
                url_path=_url_path("pages/08_Site_Workspace.py"),
            )
        )
    if local_pages:
        groups["Local deployment only"] = local_pages
    return groups


navigation = st.navigation(navigation_pages())
navigation.run()

with st.sidebar:
    st.divider()
    stamp = deployment_stamp()
    st.caption(build_info.caption(stamp))
    # Static file serving is not guaranteed on Community Cloud (it serves repository
    # files, not files a session writes), so the same bytes are also handed to the
    # reader here. scripts/check_deployment.py falls back to this download when
    # /app/static/build_info.json answers with the front-end shell.
    st.download_button(
        "Download build stamp (JSON)",
        data=build_info.serialise_stamp(stamp),
        file_name=build_info.STAMP_FILENAME,
        mime="application/json",
        key="download_build_stamp",
        help=(
            "The deployment's own stamp: commit, how it was resolved, and when it was read. "
            "Same bytes as /app/static/build_info.json where that route is served."
        ),
    )

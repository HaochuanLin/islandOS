"""IslandOS entry point: one navigation menu for every surface.

The section UI itself lives in ``islandos_ui/workspace.py``. This module only
decides which pages exist and how they are grouped, so the menu can be changed
without touching the workspace logic, and the workspace can grow without adding
another competing sidebar.

Local-only pages (customer workspace, site workspace) need the loopback
reference service and a local data directory. They are registered only when the
local deployment is actually configured — ``ISLANDOS_ENABLE_LOCAL_WORKSPACE=1``
for the site workspace, or ``ISLANDOS_API_BASE_URL`` for the customer workspace
— so the public demo never shows entries that can only fail. Both pages keep
their own guards; this file only decides whether to offer them in the menu.
"""

from __future__ import annotations

import os

import streamlit as st

from islandos_core import build_info
from islandos_ui.navigation import page_url_path

LOCAL_WORKSPACE_FLAG = "ISLANDOS_ENABLE_LOCAL_WORKSPACE"
LOCAL_API_BASE_URL = "ISLANDOS_API_BASE_URL"


def local_ui_enabled() -> bool:
    """True only when a local deployment is explicitly configured."""
    workspace_flag = os.environ.get(LOCAL_WORKSPACE_FLAG, "").strip() == "1"
    api_base_url = os.environ.get(LOCAL_API_BASE_URL, "").strip()
    return workspace_flag or bool(api_base_url)


st.set_page_config(
    page_title="IslandOS | Decision Lab",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_data(ttl=300, show_spinner=False)
def deployment_stamp() -> dict:
    """The build stamp for this deployment, also published as a static file.

    ``/app/static/build_info.json`` is the only route on the hosted app that
    returns the app's own data instead of the front-end shell, so it is what
    ``scripts/check_deployment.py`` reads. The write is best-effort: a read-only
    deployment still renders the page, and the sidebar line is then the only
    place the stamp appears.
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
    if local_ui_enabled():
        groups["Local deployment only"] = [
            st.Page(
                "pages/07_Local_Customer_Workspace.py",
                title="Customer workspace (local)",
                icon="🗂️",
                url_path=_url_path("pages/07_Local_Customer_Workspace.py"),
            ),
            st.Page(
                "pages/08_Site_Workspace.py",
                title="Site workspace (local)",
                icon="🏗️",
                url_path=_url_path("pages/08_Site_Workspace.py"),
            ),
        ]
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

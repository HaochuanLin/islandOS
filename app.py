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
            ),
            st.Page(
                "pages/06_Forecast_Led_Joint_Resource_Optimizer.py",
                title="Joint resource optimizer",
                icon="🔁",
            ),
            st.Page(
                "pages/09_Device_Flexibility_Planner.py",
                title="Device flexibility planner",
                icon="🔌",
            ),
        ],
        "Experimental": [
            st.Page(
                "pages/2_Rolling_Horizon_Lab.py",
                title="Rolling horizon lab",
                icon="🧪",
            ),
        ],
    }
    if local_ui_enabled():
        groups["Local deployment only"] = [
            st.Page(
                "pages/07_Local_Customer_Workspace.py",
                title="Customer workspace (local)",
                icon="🗂️",
            ),
            st.Page(
                "pages/08_Site_Workspace.py",
                title="Site workspace (local)",
                icon="🏗️",
            ),
        ]
    return groups


st.navigation(navigation_pages()).run()

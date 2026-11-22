"""Contract for the single navigation menu.

One menu, one entry point. These assertions exist because the app used to show
two competing sidebars: Streamlit's automatic ``pages/`` list plus an in-app
``st.radio``. Adding a page then silently changed the menu, and two pages that
need local services appeared in the public demo as dead ends.

The checks below are cheap source-level guards; rendering is covered by
``test_ui_smoke_all_pages.py``.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP = REPO_ROOT / "app.py"
PAGES_DIR = REPO_ROOT / "pages"

LOCAL_ONLY_PAGES = ["pages/07_Local_Customer_Workspace.py", "pages/08_Site_Workspace.py"]


def app_source() -> str:
    return APP.read_text(encoding="utf-8")


def test_menu_is_built_by_st_navigation_only():
    source = app_source()
    assert "st.navigation(" in source
    assert "st.radio(" not in source, "app.py must not add a second sidebar radio"


def test_every_page_file_is_registered_by_the_menu():
    registered = set(re.findall(r'"(pages/[^"]+\.py)"', app_source()))
    on_disk = {f"pages/{path.name}" for path in PAGES_DIR.glob("*.py")}
    assert registered, "app.py registers no page files"
    missing = on_disk - registered
    assert not missing, f"pages not reachable from the menu: {sorted(missing)}"
    stale = registered - on_disk
    assert not stale, f"menu points at files that do not exist: {sorted(stale)}"


def test_local_only_pages_are_gated_behind_the_local_flag():
    source = app_source()
    assert "ISLANDOS_ENABLE_LOCAL_WORKSPACE" in source
    guard = source.index("if local_ui_enabled():")
    for page in LOCAL_ONLY_PAGES:
        assert page in source, f"{page} is not registered anywhere in app.py"
        assert source.index(page) > guard, f"{page} must be registered inside the local-only block"


def test_workspace_page_is_the_default():
    source = app_source()
    default_line = next(
        line for line in source.splitlines() if "default=True" in line
    )
    assert "islandos_ui/workspace.py" in default_line

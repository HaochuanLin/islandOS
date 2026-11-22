"""Smoke tests: every user-facing Streamlit surface opens without exceptions.

Why this exists
---------------
The app exposes many surfaces: the workspace sections (a second-level radio
inside ``islandos_ui/workspace.py``), the standalone ``pages/`` views, and the
local-only deployment pages. Only two surfaces had a render test before. A
broken page reaches users silently, so this test opens each surface once and
fails if Streamlit reports an exception.

What it does NOT prove
----------------------
Rendering without exceptions is not proof of correct numbers, forecast accuracy,
engineering feasibility or real-world benefit.
"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_FILE = REPO_ROOT / "app.py"
WORKSPACE_FILE = REPO_ROOT / "islandos_ui" / "workspace.py"
# Sections reached through the workspace sub-navigation (order = sidebar order).
APP_SECTIONS = [
    "Overview",
    "Data onboarding & workspace",
    "Forecast lab",
    "Flexible-load cost optimizer",
    "Strategy simulator",
    "Microgrid screening",
    "Historical RO baseline",
    "Data guide",
]

# Standalone Streamlit pages reached from the single navigation menu.
MULTIPAGE_FILES = [
    "pages/05_Customer_Decision_Dashboard.py",
    "pages/06_Forecast_Led_Joint_Resource_Optimizer.py",
    "pages/09_Device_Flexibility_Planner.py",
    "pages/2_Rolling_Horizon_Lab.py",
]

# Public demo default: these need local services, so they are not registered.
PUBLIC_MENU_PAGES = MULTIPAGE_FILES[:3]


def _assert_clean(app, label: str) -> None:
    assert not app.exception, f"{label} raised: " + "\n".join(str(e) for e in app.exception)


def test_app_shell_opens_without_exception():
    app = AppTest.from_file(str(APP_FILE), default_timeout=90).run()
    _assert_clean(app, "app.py shell (default page)")


@pytest.mark.parametrize("relative_path", PUBLIC_MENU_PAGES)
def test_public_menu_page_opens_from_shell(relative_path: str):
    """Every page registered in the default menu is reachable through app.py."""
    page = REPO_ROOT / relative_path
    assert page.exists(), f"missing page file: {relative_path}"
    app = AppTest.from_file(str(APP_FILE), default_timeout=90).run()
    app.switch_page(relative_path).run()
    _assert_clean(app, f"app.py -> {relative_path}")


@pytest.mark.parametrize("section", APP_SECTIONS)
def test_workspace_section_renders(section: str):
    # Run the real entrypoint: the default page is the workspace, and the
    # workspace's in-page links only resolve for pages st.navigation registered.
    app = AppTest.from_file(str(APP_FILE), default_timeout=90).run()
    assert app.radio, "expected the workspace sub-navigation radio to exist"
    app.radio[0].set_value(section).run()
    _assert_clean(app, f'workspace section "{section}"')


@pytest.mark.parametrize("relative_path", MULTIPAGE_FILES)
def test_multipage_page_renders(relative_path: str):
    page = REPO_ROOT / relative_path
    assert page.exists(), f"missing page file: {relative_path}"
    app = AppTest.from_file(str(page), default_timeout=90).run()
    _assert_clean(app, relative_path)

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

import pytest

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


def test_page_url_path_strips_only_a_leading_number():
    from islandos_ui.navigation import page_url_path

    assert page_url_path("pages/06_Forecast_Led_Joint_Resource_Optimizer.py") == (
        "Forecast_Led_Joint_Resource_Optimizer"
    )
    assert page_url_path("pages/2_Rolling_Horizon_Lab.py") == "Rolling_Horizon_Lab"
    assert page_url_path("pages/07_Local_Customer_Workspace.py") == "Local_Customer_Workspace"
    assert page_url_path("islandos_ui/workspace.py") == "workspace"
    with pytest.raises(ValueError, match="non-empty path"):
        page_url_path("")


def _page_blocks(source: str) -> list[str]:
    """Return the argument text of every st.Page(...) call, balanced on parentheses."""
    blocks = []
    for match in re.finditer(r"st\.Page\(", source):
        depth = 1
        index = match.end()
        while index < len(source) and depth:
            if source[index] == "(":
                depth += 1
            elif source[index] == ")":
                depth -= 1
            index += 1
        blocks.append(source[match.end():index - 1])
    return blocks


def test_every_page_declares_its_url_path():
    """A page file rename must not change its public URL without a visible edit."""
    blocks = [block for block in _page_blocks(app_source()) if '"pages/' in block]
    assert len(blocks) >= 6, f"expected at least six registered page files, saw {len(blocks)}"
    for block in blocks:
        page_file = re.search(r'"(pages/[^"]+\.py)"', block).group(1)
        assert f'url_path=_url_path("{page_file}")' in block, (
            f"{page_file} does not declare a url_path"
        )

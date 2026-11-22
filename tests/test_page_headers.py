"""Every entry page must state what it answers, where its data comes from, what
a reader can conclude and what its limits are.

A page that grows a new number without saying where it came from is the failure
this guards against, so the check is structural: the shared header helper must
exist, carry all four lines, and be called from each entry page.
"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

REPO_ROOT = Path(__file__).resolve().parents[1]
HELPER = REPO_ROOT / "islandos_ui" / "page_header.py"
APP = REPO_ROOT / "app.py"

ENTRY_PAGES = [
    "islandos_ui/workspace.py",
    "pages/05_Customer_Decision_Dashboard.py",
    "pages/06_Forecast_Led_Joint_Resource_Optimizer.py",
    "pages/09_Device_Flexibility_Planner.py",
    "pages/2_Rolling_Horizon_Lab.py",
]

HEADER_LINES = ("question=", "data=", "conclusions=", "limits=")


def test_helper_defines_the_four_lines():
    source = HELPER.read_text(encoding="utf-8")
    for label in ("Answers:", "Data:", "You can conclude:", "Limits:"):
        assert label in source


@pytest.mark.parametrize("relative_path", ENTRY_PAGES)
def test_entry_page_calls_the_header(relative_path: str):
    source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
    assert "render_page_header(" in source, f"{relative_path} renders no page header"
    call = source.split("render_page_header(", 1)[1].split("\n)", 1)[0]
    for line in HEADER_LINES:
        assert line in call, f"{relative_path} header is missing {line}"
    assert "TODO" not in call


def test_workspace_header_reaches_the_rendered_page():
    app = AppTest.from_file(str(APP), default_timeout=90).run()
    assert not app.exception
    rendered = "\n".join(m.value for m in app.markdown)
    assert "Answers:" in rendered and "Limits:" in rendered

"""Smoke tests: every user-facing Streamlit surface opens without exceptions.

Why this exists
---------------
The app has two navigation layers (the ``app.py`` sidebar radio and the
multi-page ``pages/`` folder). Only two surfaces had a render test before.
A broken page in either layer reaches users silently, so this test opens each
surface once and fails if Streamlit reports an exception.

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

# Sections reached through the sidebar radio in app.py (order = sidebar order).
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

# Standalone Streamlit pages that customers reach from the automatic page menu.
MULTIPAGE_FILES = [
    "pages/05_Customer_Decision_Dashboard.py",
    "pages/06_Forecast_Led_Joint_Resource_Optimizer.py",
    "pages/09_Device_Flexibility_Planner.py",
]


def _assert_clean(app, label: str) -> None:
    assert not app.exception, f"{label} raised: " + "\n".join(str(e) for e in app.exception)


def test_app_shell_opens_without_exception():
    app = AppTest.from_file(str(APP_FILE), default_timeout=90).run()
    _assert_clean(app, "app.py shell (default section)")


@pytest.mark.parametrize("section", APP_SECTIONS)
def test_app_section_renders(section: str):
    app = AppTest.from_file(str(APP_FILE), default_timeout=90).run()
    assert app.radio, "expected the sidebar navigation radio to exist"
    app.radio[0].set_value(section).run()
    _assert_clean(app, f'app.py section "{section}"')


@pytest.mark.parametrize("relative_path", MULTIPAGE_FILES)
def test_multipage_page_renders(relative_path: str):
    page = REPO_ROOT / relative_path
    assert page.exists(), f"missing page file: {relative_path}"
    app = AppTest.from_file(str(page), default_timeout=90).run()
    _assert_clean(app, relative_path)

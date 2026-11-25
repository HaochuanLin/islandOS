"""F-02: 05/06 failure paths use the same readable boundary as 09."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

REPO_ROOT = Path(__file__).resolve().parents[1]

PAGES = {
    "05": REPO_ROOT / "pages" / "05_Customer_Decision_Dashboard.py",
    "06": REPO_ROOT / "pages" / "06_Forecast_Led_Joint_Resource_Optimizer.py",
}

EXPECTED_TUPLE = "except (ValueError, KeyError, TypeError, ArithmeticError, IndexError) as exc:"

CAPTIONS = {
    "05": "No partial decision result is shown; nothing is written to equipment.",
    "06": "No partial schedule is shown; nothing is written to equipment.",
}


def _source(page: str) -> str:
    return PAGES[page].read_text(encoding="utf-8")


def test_pages_use_extended_exception_tuple():
    for page in PAGES:
        assert EXPECTED_TUPLE in _source(page)


def test_error_branch_has_caption_and_stop():
    for page, caption in CAPTIONS.items():
        source = _source(page)
        branch = source.split(EXPECTED_TUPLE, 1)[1][:500]
        assert caption in branch
        assert "st.stop()" in branch


def test_no_broad_exception_catch_in_error_branch():
    for page in PAGES:
        assert "except Exception" not in _source(page)


def test_default_pages_still_render():
    for label, page in PAGES.items():
        app = AppTest.from_file(str(page), default_timeout=120).run()
        assert not app.exception, f"{label} raised: " + "\n".join(str(e) for e in app.exception)

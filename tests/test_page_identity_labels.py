"""F-03: 05 and 06 must name their own identity, not imply a shared run."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

REPO_ROOT = Path(__file__).resolve().parents[1]

PAGE_05 = REPO_ROOT / "pages" / "05_Customer_Decision_Dashboard.py"
PAGE_06 = REPO_ROOT / "pages" / "06_Forecast_Led_Joint_Resource_Optimizer.py"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_page_05_labels_its_local_request_hash():
    source = _source(PAGE_05)
    assert "Local request SHA-256" in source
    assert "run_request_view['request_sha256']" in source
    assert "not a cross-page run identity" in source


def test_page_06_labels_its_canonical_page_run():
    source = _source(PAGE_06)
    assert "Canonical page run:" in source
    assert "not a cross-page handoff id for 05" in source


def test_pages_do_not_claim_a_shared_run():
    for path in (PAGE_05, PAGE_06):
        lowered = _source(path).lower()
        for phrase in ("same run", "shared run", "one run across both pages", "shared run id"):
            assert phrase not in lowered, f"{path.name} contains {phrase!r}"


def test_default_pages_show_the_new_labels():
    app_05 = AppTest.from_file(str(PAGE_05), default_timeout=120).run()
    assert not app_05.exception, "\n".join(str(e) for e in app_05.exception)
    text_05 = " ".join(
        str(item.value) for item in [*app_05.markdown, *app_05.caption]
    )
    assert "Local request SHA-256:" in text_05

    app_06 = AppTest.from_file(str(PAGE_06), default_timeout=120).run()
    assert not app_06.exception, "\n".join(str(e) for e in app_06.exception)
    text_06 = " ".join(str(item.value) for item in app_06.caption)
    assert "Canonical page run:" in text_06

"""Presentation tests: page 05 assumption summary and recommended dispatch view.

Why this exists
---------------
Page 05 now shows (a) the assumptions the run actually used and (b) the hourly
dispatch behind the recommended policy, both read from the stored run result.
These tests pin that the blocks render on the default inputs, that the dispatch
table comes from the stored rows, and that a run without those rows (or without
a given column) degrades to a readable message instead of an exception.

What it does NOT prove
----------------------
No pixel rendering, no numerical validation of the dispatch, and nothing about
optimality or executability of the schedule on real equipment.
"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

REPO_ROOT = Path(__file__).resolve().parents[1]
PAGE_FILE = REPO_ROOT / "pages" / "05_Customer_Decision_Dashboard.py"

DISPATCH_HEADER = "Hourly dispatch for the recommended policy"
ASSUMPTION_HEADER = "Inputs and assumptions for this run"


def _render_page() -> AppTest:
    app = AppTest.from_file(str(PAGE_FILE), default_timeout=90).run()
    assert not app.exception, "page 05 raised: " + "\n".join(str(e) for e in app.exception)
    return app


def _caption_text(app: AppTest) -> str:
    return "\n".join(str(item.value) for item in app.get("caption"))


def _json_text(app: AppTest) -> str:
    return "\n".join(str(item.value) for item in app.get("json"))


def _markdown_text(app: AppTest) -> str:
    return "\n".join(str(item.value) for item in app.markdown)


def _dispatch_table(app: AppTest):
    for frame in app.table:
        columns = list(getattr(frame.value, "columns", []))
        if "Hour" in columns and "Grid import (kW)" in columns:
            return frame.value
    return None


def test_default_inputs_render_both_new_blocks():
    app = _render_page()
    headers = [item.value for item in app.subheader]
    assert DISPATCH_HEADER in headers
    assert ASSUMPTION_HEADER in [item.label for item in app.expander]


def test_assumption_summary_reports_provenance_and_scope():
    app = _render_page()
    markdown = _markdown_text(app)
    captions = _caption_text(app)
    payload = _json_text(app)

    for label in ("Data source", "History SHA-256", "Time window", "hourly rows"):
        assert label in markdown, f"assumption summary is missing {label!r}"
    for label in (
        "Installed PV capacity (kW)",
        "Installed wind capacity (kW)",
        "Grid import limit (kW)",
        "Battery capacity (kWh)",
        "Battery charge/discharge limit (kW)",
        "Currency label",
        "Essential load level (demand scale)",
        "Electricity tariff level (tariff scale)",
        "Cost priority",
        "Reliability weight",
    ):
        assert label in payload, f"assumption summary is missing {label!r}"
    assert "offline screening; synthetic defaults unless a csv is uploaded" in captions.lower()
    assert "not measured customer savings" in captions.lower()


def test_dispatch_detail_table_comes_from_stored_hours():
    app = _render_page()
    captions = _caption_text(app)
    assert "not an equipment command" in captions
    assert "not real-time control" in captions
    assert "not a proof that this schedule is globally optimal" in captions

    table = _dispatch_table(app)
    assert table is not None, "expected an hourly dispatch detail table"
    assert len(table) > 0
    assert list(table["Hour"]) == list(range(1, len(table) + 1))
    assert table["Battery SOC (%)"].between(0.0, 100.0).all()
    assert app.get("vega_lite_chart"), "expected at least one dispatch chart"


def test_empty_dispatch_rows_explain_the_gap(monkeypatch):
    from islandos_core import run_orchestration

    original = run_orchestration.run_customer_dashboard

    def without_rows(*args, **kwargs):
        outputs = original(*args, **kwargs)
        for candidate in outputs["result"]["candidates"]:
            if "dispatch" in candidate:
                candidate["dispatch"] = {**candidate["dispatch"], "rows": []}
        return outputs

    monkeypatch.setattr(run_orchestration, "run_customer_dashboard", without_rows)
    app = AppTest.from_file(str(PAGE_FILE), default_timeout=90).run()
    assert not app.exception, "page 05 raised: " + "\n".join(str(e) for e in app.exception)
    infos = "\n".join(str(item.value) for item in app.info)
    assert "Hourly dispatch is not available in this run" in infos
    assert DISPATCH_HEADER in [item.value for item in app.subheader]


def test_missing_dispatch_columns_explain_the_gap(monkeypatch):
    from islandos_core import run_orchestration

    original = run_orchestration.run_customer_dashboard

    def without_optional_columns(*args, **kwargs):
        outputs = original(*args, **kwargs)
        for candidate in outputs["result"]["candidates"]:
            dispatch = candidate.get("dispatch")
            if not dispatch:
                continue
            stripped = [
                {key: value for key, value in row.items()
                 if key not in ("battery_soc", "diesel_generation_kw")}
                for row in dispatch.get("rows") or []
            ]
            candidate["dispatch"] = {**dispatch, "rows": stripped}
        return outputs

    monkeypatch.setattr(run_orchestration, "run_customer_dashboard", without_optional_columns)
    app = AppTest.from_file(str(PAGE_FILE), default_timeout=90).run()
    assert not app.exception, "page 05 raised: " + "\n".join(str(e) for e in app.exception)
    captions = _caption_text(app)
    infos = "\n".join(str(item.value) for item in app.info)
    assert "Battery state of charge is not available in this run" in infos
    assert "Diesel generation is not available in this run" in captions
    table = _dispatch_table(app)
    assert table is not None
    assert "Battery SOC (%)" not in table.columns


@pytest.mark.parametrize("heading", [DISPATCH_HEADER, ASSUMPTION_HEADER])
def test_new_block_headings_are_declared_in_source(heading):
    """Keep the wording stable even if AppTest cannot render a surface."""
    source = PAGE_FILE.read_text(encoding="utf-8")
    assert heading in source

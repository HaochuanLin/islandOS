"""Page05's actual HTML, decision-report and human-review downloads must agree.

The page is driven through AppTest. Each byte string is captured from the real
``st.download_button`` handlers, then parsed independently. The test does not
rebuild a report object from page internals and call that a download.
"""

from __future__ import annotations

from html.parser import HTMLParser
import json
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

REPO_ROOT = Path(__file__).resolve().parents[1]
PAGE = REPO_ROOT / "pages" / "05_Customer_Decision_Dashboard.py"

HTML_LABEL = "Download customer summary (HTML)"
REPORT_LABEL = "Download decision report (JSON)"
RECORD_LABEL = "Download human-review decision record (JSON)"


class _TableRows(HTMLParser):
    """Read the summary's two-cell table rows without depending on styling."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "tr":
            self._row = []
        elif tag == "td" and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self._row is not None and self._cell is not None:
            self._row.append(" ".join(" ".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None


def _parse_html(html_text: str) -> dict[str, str]:
    parser = _TableRows()
    parser.feed(html_text)
    return {
        row[0]: row[1]
        for row in parser.rows
        if len(row) >= 2
    }


def _capture_downloads(currency: str = "USD") -> tuple[AppTest, dict[str, bytes]]:
    captured: dict[str, bytes] = {}
    original = st.download_button

    def recorder(label, data=None, *args, **kwargs):
        if data is not None and str(label) in {HTML_LABEL, REPORT_LABEL, RECORD_LABEL}:
            captured[str(label)] = data if isinstance(data, bytes) else bytes(data)
        return original(label, data=data, *args, **kwargs)

    st.download_button = recorder
    try:
        app = AppTest.from_file(str(PAGE), default_timeout=180).run()
        assert not app.exception, [str(error) for error in app.exception]
        if currency != "USD":
            currency_input = next(
                widget for widget in app.text_input if widget.label == "Currency label"
            )
            currency_input.set_value(currency).run()
            assert not app.exception, [str(error) for error in app.exception]
    finally:
        st.download_button = original

    assert set(captured) == {HTML_LABEL, REPORT_LABEL, RECORD_LABEL}, captured.keys()
    return app, captured


def _decode_exports(captured: dict[str, bytes]) -> tuple[str, dict, dict]:
    return (
        captured[HTML_LABEL].decode("utf-8"),
        json.loads(captured[REPORT_LABEL]),
        json.loads(captured[RECORD_LABEL]),
    )


def _assert_exports_agree(captured: dict[str, bytes], *, currency: str) -> None:
    html_text, report, record = _decode_exports(captured)
    cells = _parse_html(html_text)

    assert "IslandOS customer decision summary" in html_text
    assert f" {currency}" in html_text
    assert report["currency"] == currency
    assert report["investment_economics"]["assumptions"]["currency"] == currency
    result = report["application_views"]["result"]
    selected = report["recommended_summary"]
    investment = report["investment_economics"]

    assert result["currency"] == currency
    assert result["estimated_24h_energy_cost"] == pytest.approx(24.5222959, abs=1e-8)
    assert result["grid_first_estimated_24h_energy_cost"] == pytest.approx(
        35.06733423, abs=1e-8
    )
    assert result["cost_reduction_vs_grid_first"] == pytest.approx(10.54503833, abs=1e-8)
    assert result["unmet_load_kwh"] == 0.0

    assert report["application_views"]["result"] == result
    assert report["estimated_cost_reduction"] == pytest.approx(
        result["cost_reduction_vs_grid_first"], abs=1e-8
    )
    assert selected["estimated_energy_cost"] == pytest.approx(
        result["estimated_24h_energy_cost"], abs=1e-8
    )
    assert report["reference_summary"]["estimated_energy_cost"] == pytest.approx(
        result["grid_first_estimated_24h_energy_cost"], abs=1e-8
    )

    # The three exports describe one decision: the human-review record is the
    # same record embedded in the decision report, not a second rendering.
    assert record == report["operator_decision_record"]
    assert record["record_sha256"] == report["operator_decision_record"]["record_sha256"]
    assert record["status"] == "ready_for_human_review"
    assert record["human_review_required"] is True
    assert record["device_write_authorized"] is False
    assert record["record_type"] == "offline_operator_decision_record"

    # Formatting is checked from the JSON numbers, not from a duplicated string.
    assert cells["Recommended policy"] == result["recommended_policy_label"]
    assert cells["Modeled 24-hour energy cost"] == (
        f"{result['estimated_24h_energy_cost']:,.2f} {currency}"
    )
    assert cells["Modeled difference vs grid-first"] == (
        f"{result['cost_reduction_vs_grid_first']:,.2f} {currency}"
    )
    assert cells["Grid import"] == f"{selected['grid_import_kwh']:,.2f} kWh"
    assert cells["Renewable curtailment"] == (
        f"{selected['renewable_curtailed_kwh']:,.2f} kWh"
    )
    assert cells["Unmet load"] == f"{selected['unmet_load_kwh']:,.2f} kWh"
    assert cells["Net present value"] == f"{investment['net_present_value']:,.0f} {currency}"
    assert cells["Simple payback"] == f"{investment['simple_payback_years']:.1f} years"


def test_default_page05_captures_html_and_both_json_exports():
    _, captured = _capture_downloads()
    _assert_exports_agree(captured, currency="USD")


def test_currency_label_propagates_to_all_page05_exports():
    _, captured = _capture_downloads(currency="EUR")
    _assert_exports_agree(captured, currency="EUR")

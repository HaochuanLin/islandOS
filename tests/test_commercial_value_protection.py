"""Protect the commercial values at the page and decision-report boundaries.

The default Page05 scenario is the one used in the public demonstration. These tests
load the real page, read the values it renders, and parse the actual decision-report
download. They fail if a formula, default, or formatting mapping moves the protected
numbers, but they do not hard-code a second copy of the page's maths.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from islandos_ui.annual_economics_panel import DEMONSTRATION_VALUES

REPO_ROOT = Path(__file__).resolve().parents[1]
PAGE = REPO_ROOT / "pages" / "05_Customer_Decision_Dashboard.py"
REPORT_LABEL = "Download decision report (JSON)"


def _read_default_page() -> tuple[AppTest, dict]:
    captured: dict[str, bytes] = {}
    original = st.download_button

    def recorder(label, data=None, *args, **kwargs):
        if data is not None and str(label) == REPORT_LABEL:
            captured["report"] = data if isinstance(data, bytes) else bytes(data)
        return original(label, data=data, *args, **kwargs)

    st.download_button = recorder
    try:
        app = AppTest.from_file(str(PAGE), default_timeout=180).run()
        assert not app.exception, [str(error) for error in app.exception]
    finally:
        st.download_button = original

    assert "report" in captured, "Page05 did not emit its decision-report download"
    return app, json.loads(captured["report"])


@pytest.fixture(scope="module")
def default_page() -> tuple[AppTest, dict]:
    return _read_default_page()


def _metric_values(app: AppTest) -> dict[str, str]:
    return {metric.label: metric.value for metric in app.metric}


def test_default_dashboard_displays_the_protected_commercial_values(default_page):
    app, report = default_page
    values = _metric_values(app)

    assert values["Recommended policy"] == "Battery First"
    assert values["Estimated 24h energy cost"] == "24.52 USD"
    assert values["Modeled cost difference vs grid-first"] == "10.55 USD"
    assert values["Unmet energy"] == "0.00 kWh"
    assert values["Net present value"] == "21,302 USD"
    assert values["Simple payback"] == "6.0 years"

    # 35.07 is the grid-first reference cost. Page05 reports it in the decision
    # report and the reference summary, not in the visible metric row.
    result = report["application_views"]["result"]
    assert result["grid_first_estimated_24h_energy_cost"] == pytest.approx(
        35.06733423, abs=1e-8
    )
    assert report["reference_summary"]["estimated_energy_cost"] == pytest.approx(
        result["grid_first_estimated_24h_energy_cost"], abs=1e-8
    )


def test_the_decision_report_preserves_the_same_underlying_numbers(default_page):
    _, report = default_page
    result = report["application_views"]["result"]

    assert report["currency"] == "USD"
    assert result["currency"] == "USD"
    assert result["recommended_policy_label"] == "Battery First"
    assert result["estimated_24h_energy_cost"] == pytest.approx(24.5222959, abs=1e-8)
    assert result["grid_first_estimated_24h_energy_cost"] == pytest.approx(
        35.06733423, abs=1e-8
    )
    assert result["cost_reduction_vs_grid_first"] == pytest.approx(10.54503833, abs=1e-8)
    assert result["unmet_load_kwh"] == 0.0

    assert report["estimated_cost_reduction"] == pytest.approx(
        result["cost_reduction_vs_grid_first"], abs=1e-8
    )
    assert report["recommended_summary"]["estimated_energy_cost"] == pytest.approx(
        result["estimated_24h_energy_cost"], abs=1e-8
    )
    assert report["application_views"]["result"] == result
    assert len(result["summary_sha256"]) == 64


def test_the_report_formats_the_protected_values_exactly(default_page):
    _, report = default_page
    result = report["application_views"]["result"]
    investment = report["investment_economics"]

    assert f"{result['estimated_24h_energy_cost']:,.2f} USD" == "24.52 USD"
    assert f"{result['grid_first_estimated_24h_energy_cost']:,.2f} USD" == "35.07 USD"
    assert f"{result['cost_reduction_vs_grid_first']:,.2f} USD" == "10.55 USD"
    assert f"{investment['net_present_value']:,.0f} USD" == "21,302 USD"
    assert f"{investment['simple_payback_years']:.1f} years" == "6.0 years"


def test_the_demonstration_defaults_are_the_values_under_test(default_page):
    _, report = default_page
    assumptions = report["investment_economics"]["assumptions"]

    assert assumptions["baseline_annual_energy_cost"] == DEMONSTRATION_VALUES[
        "baseline_annual_bill"
    ]
    assert assumptions["proposed_annual_energy_cost"] == DEMONSTRATION_VALUES[
        "proposed_annual_bill"
    ]
    assert assumptions["annual_incremental_om_cost"] == DEMONSTRATION_VALUES[
        "annual_incremental_om"
    ]
    assert assumptions["upfront_capex"] == DEMONSTRATION_VALUES["upfront_capex"]
    assert assumptions["project_life_years"] == 10
    assert assumptions["discount_rate"] == 0.08

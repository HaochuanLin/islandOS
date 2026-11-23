"""The demo clock pins the synthetic window so a recorded number can be reproduced.

These are page-level tests: the unit properties of the window itself live in
``test_demo_site_history.py``. What is asserted here is that the sidebar control
reaches the page's own annual/24-hour output, and that pinning the recorded window
lands on the numbers the work log quotes. 06 needs only the hour; 05 also needs the
date, because its synthetic load carries a weekday term.
"""

import json
from datetime import date
from pathlib import Path

import streamlit as st
from streamlit.testing.v1 import AppTest

REPO_ROOT = Path(__file__).resolve().parents[1]
PAGE_05 = REPO_ROOT / "pages" / "05_Customer_Decision_Dashboard.py"
PAGE_06 = REPO_ROOT / "pages" / "06_Forecast_Led_Joint_Resource_Optimizer.py"
INTEGRATION_DOC = REPO_ROOT / "APP_INTEGRATION.md"

CLOCK_05 = "demo_clock_hour_dashboard"
CLOCK_06 = "demo_clock_hour_joint_optimizer"


def _metric(app: AppTest, label_fragment: str) -> str:
    matches = [metric for metric in app.metric if label_fragment in metric.label]
    assert matches, [metric.label for metric in app.metric]
    return matches[0].value


def test_the_default_clock_is_frozen_on_both_pages():
    """Opening the page on any day shows the recorded window, not the wall clock."""
    app5 = AppTest.from_file(str(PAGE_05), default_timeout=180).run()
    assert not app5.exception, [str(error) for error in app5.exception]
    assert app5.date_input(key="demo_date_dashboard").value == date(2026, 11, 22)
    assert app5.slider(key=CLOCK_05).value == 14
    assert _metric(app5, "Estimated 24h energy cost") == "17.93 USD"

    app6 = AppTest.from_file(str(PAGE_06), default_timeout=180).run()
    assert not app6.exception, [str(error) for error in app6.exception]
    assert app6.date_input(key="demo_date_joint_optimizer").value == date(2026, 11, 22)
    assert app6.slider(key=CLOCK_06).value == 14
    app6.checkbox(key="annual_projection_joint_optimizer").check().run()
    assert not app6.exception, [str(error) for error in app6.exception]
    assert _metric(app6, "Annual load energy") == "186,150 kWh"
    assert _metric(app6, "Annual energy cost") == "7,709.55"


def test_pinning_06_at_14_and_2_reproduces_the_two_recorded_annual_costs():
    app = AppTest.from_file(str(PAGE_06), default_timeout=180).run()
    assert not app.exception, [str(error) for error in app.exception]
    app.date_input(key="demo_date_joint_optimizer").set_value(date(2026, 11, 22))
    app.slider(key=CLOCK_06).set_value(14)
    app.checkbox(key="annual_projection_joint_optimizer").check()
    app.run()
    assert not app.exception, [str(error) for error in app.exception]
    assert _metric(app, "Annual load energy") == "186,150 kWh"
    assert _metric(app, "Annual energy cost") == "7,709.55"

    # Only the hour moves; the seven-day load total and the year are unchanged.
    app.slider(key=CLOCK_06).set_value(2).run()
    assert not app.exception, [str(error) for error in app.exception]
    assert _metric(app, "Annual load energy") == "186,150 kWh"
    assert _metric(app, "Annual energy cost") == "5,332.57"


def test_pinning_05_at_14_reproduces_the_recorded_24_hour_cost():
    app = AppTest.from_file(str(PAGE_05), default_timeout=180).run()
    assert not app.exception, [str(error) for error in app.exception]
    # 05's synthetic load carries a weekday term, so the hour alone is not a full pin:
    # the recorded 17.93 is the window ending Sunday 2026-11-22 at 13:00 UTC,
    # whose demo anchor (the hour the page would have run) is 14:00.
    app.date_input(key="demo_date_dashboard").set_value(date(2026, 11, 22))
    app.slider(key=CLOCK_05).set_value(14).run()
    assert not app.exception, [str(error) for error in app.exception]
    assert _metric(app, "Estimated 24h energy cost") == "17.93 USD"


def test_the_document_no_longer_implies_the_demo_figures_are_clock_independent():
    text = INTEGRATION_DOC.read_text(encoding="utf-8")
    assert "## 6. The demo clock" in text
    assert "17.93" in text and "19.91" in text
    # The old sentence claimed the deployed app renders "the same numbers the tests pin".
    assert "renders the same numbers the tests pin" not in text


def _annual_identity(date: date, hour: int) -> dict:
    """Pin 06 at ``date``/``hour`` and read the identity fields of its own annual view."""
    captured: dict[str, bytes] = {}
    original = st.download_button

    def recorder(label, data=None, *args, **kwargs):
        if data is not None:
            captured[label] = data if isinstance(data, bytes) else bytes(data)
        return original(label, data=data, *args, **kwargs)

    st.download_button = recorder
    try:
        app = AppTest.from_file(str(PAGE_06), default_timeout=180).run()
        assert not app.exception, [str(error) for error in app.exception]
        app.date_input(key="demo_date_joint_optimizer").set_value(date)
        app.slider(key=CLOCK_06).set_value(hour)
        app.checkbox(key="annual_projection_joint_optimizer").check()
        app.run()
        assert not app.exception, [str(error) for error in app.exception]
    finally:
        st.download_button = original
    payload = next(value for label, value in captured.items() if "joint schedule audit" in label.lower())
    views = json.loads(payload)["application_views"]
    annual = views["annual"]
    return {
        "run_id": annual["run_id"],
        "manifest_sha256": annual["manifest_sha256"],
        "projection_sha256": annual["projection_sha256"],
    }


def test_a_pinned_window_downloads_as_the_same_record_twice():
    first = _annual_identity(date(2026, 11, 22), 14)
    second = _annual_identity(date(2026, 11, 22), 14)
    assert first == second
    # A different window is a different run, so its identity must move with it.
    other = _annual_identity(date(2026, 11, 22), 2)
    assert other["projection_sha256"] != first["projection_sha256"]
    assert other["run_id"] != first["run_id"]

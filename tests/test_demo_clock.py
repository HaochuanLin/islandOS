"""The demo clock pins the synthetic window so a recorded number can be reproduced.

These are page-level tests: the unit properties of the window itself live in
``test_demo_site_history.py``. What is asserted here is that the sidebar control
reaches the page's own annual/24-hour output, and that pinning the recorded window
lands on the numbers the work log quotes. 06 needs only the hour; 05 also needs the
date, because its synthetic load carries a weekday term.
"""

from datetime import date
from pathlib import Path

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

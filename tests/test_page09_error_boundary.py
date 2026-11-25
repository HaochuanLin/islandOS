"""Error-boundary tests for the 09 device flexibility page.

Why this exists
---------------
The page used to catch ``ValueError`` only and print ``Scenario infeasible``.
Any ``KeyError`` in the planner's result, a ``TypeError`` from an unexpected
shape, or an arithmetic failure in a horizon calculation escaped the page and
Streamlit reported a raw stack trace. The page now has two explicit boundaries:
an unevaluable scenario, and an incomplete planner result. Both stop the page
before any table or metric is rendered.

What these tests do and do not prove
------------------------------------
They prove the page renders on its default synthetic input, that both failure
families stop the page with a readable message and no partial schedule, and
that the source keeps the broadened exception list. They do not prove the
planner's numbers or any engineering feasibility.
"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import islandos_core.run_orchestration as orchestration

REPO_ROOT = Path(__file__).resolve().parents[1]
PAGE = REPO_ROOT / "pages" / "09_Device_Flexibility_Planner.py"
SCHEDULE_SUBHEADER = "Per-device schedule"

SCENARIO_HEADLINE = "Device scenario could not be evaluated"
INCOMPLETE_HEADLINE = "Device planner returned an incomplete schedule"
NO_PARTIAL = "No partial schedule is shown; nothing is written to equipment."


def _page_source() -> str:
    return PAGE.read_text(encoding="utf-8")


def _subheaders(app) -> list[str]:
    return [element.value for element in app.subheader]


def _errors(app) -> list[str]:
    return [element.value for element in app.error]


def test_default_synthetic_scenario_still_renders():
    app = AppTest.from_file(str(PAGE), default_timeout=90).run()
    assert not app.exception, [str(e) for e in app.exception]
    assert SCHEDULE_SUBHEADER in _subheaders(app)
    assert not _errors(app)


def test_source_broadens_the_caught_exception_families():
    source = _page_source()
    expected = ("ValueError", "KeyError", "TypeError", "ArithmeticError", "IndexError")
    missing = [name for name in expected if name not in source]
    assert not missing, missing
    # Explicit tuple, not a blanket catch, and not the raw Streamlit-wide escape.
    assert "except Exception" not in source
    assert "except (ValueError, TypeError, ArithmeticError, IndexError)" in source
    assert "except (KeyError, TypeError, ArithmeticError, IndexError)" in source


def test_source_no_longer_reports_a_bare_scenario_infeasible():
    source = _page_source()
    assert "Scenario infeasible" not in source
    assert SCENARIO_HEADLINE in source
    assert INCOMPLETE_HEADLINE in source
    # The failure caption must say both things the reviewer asked for.
    assert "No partial schedule is shown" in source
    assert "nothing is written to equipment" in source


def test_unevaluable_scenario_stops_before_the_schedule(monkeypatch):
    def _raise(*args, **kwargs):
        raise ValueError("available_power_kw must be non-negative")

    monkeypatch.setattr(orchestration, "run_device_planner", _raise)
    app = AppTest.from_file(str(PAGE), default_timeout=90).run()

    assert not app.exception, [str(e) for e in app.exception]
    messages = _errors(app)
    assert any(SCENARIO_HEADLINE in message for message in messages), messages
    assert any("Adjust the task window, power budget or tariff and rerun." in message
               for message in messages), messages
    assert NO_PARTIAL in [caption.value for caption in app.caption]
    assert SCHEDULE_SUBHEADER not in _subheaders(app)


def test_incomplete_planner_result_stops_before_the_schedule(monkeypatch):
    def _missing_replay(*args, **kwargs):
        return {"schedule": object()}

    monkeypatch.setattr(orchestration, "run_device_planner", _missing_replay)
    app = AppTest.from_file(str(PAGE), default_timeout=90).run()

    assert not app.exception, [str(e) for e in app.exception]
    messages = _errors(app)
    assert any(INCOMPLETE_HEADLINE in message for message in messages), messages
    assert NO_PARTIAL in [caption.value for caption in app.caption]
    assert SCHEDULE_SUBHEADER not in _subheaders(app)


def test_arithmetic_failure_in_the_scenario_is_readable(monkeypatch):
    def _overflow(*args, **kwargs):
        return 1.0 / 0.0

    monkeypatch.setattr(orchestration, "run_device_planner", _overflow)
    app = AppTest.from_file(str(PAGE), default_timeout=90).run()

    assert not app.exception, [str(e) for e in app.exception]
    messages = _errors(app)
    assert any(SCENARIO_HEADLINE in message for message in messages), messages
    assert SCHEDULE_SUBHEADER not in _subheaders(app)

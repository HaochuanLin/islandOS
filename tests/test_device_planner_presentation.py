"""Presentation contract for the device flexibility planner.

The judged page must not show two unlabelled money figures or an empty section
heading. This is a source-level guard because the defect is copy/heading text,
not a model calculation; the page still renders through the shared smoke test.
"""

from pathlib import Path

PAGE = Path(__file__).resolve().parents[1] / "pages" / "09_Device_Flexibility_Planner.py"


def page_source() -> str:
    return PAGE.read_text(encoding="utf-8")


def test_task_charge_and_replay_cost_are_named_separately():
    source = page_source()
    assert 'summary[2].metric("Scheduled task energy charge"' in source
    assert 'c2.metric("Replayed system energy cost"' in source


def test_two_cost_figures_are_explained():
    source = page_source()
    assert "covers only the energy used by the scheduled tasks" in source
    assert "not expected to match" in source


def test_no_empty_shared_replay_heading():
    source = page_source()
    assert 'st.subheader("Shared energy-system replay")' not in source
    assert (
        'st.subheader("Shared energy-system replay: like-for-like operating comparison")'
        in source
    )

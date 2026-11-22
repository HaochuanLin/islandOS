"""A 24-hour run may become an annual figure only with a declared assumption.

`INTEGRATION.md` §6.5 recorded that nothing bridged the run's day to a year. The bridge
now exists, but in a form that cannot pretend: the caller states how many days a year
stands for, the record prints that statement beside the numbers, and the record says it
is a projection — not a bill, not measured consumption, not site-validated.

What this does NOT prove
------------------------
The projection inherits every weakness of the run it comes from, and adds one of its
own (the equal-days assumption). A verified record means the arithmetic and the labels
agree, nothing more.
"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from islandos_core.annual_operating_basis import (
    DEFINITIONS,
    annualise_run_summary,
    verify_annual_operating_basis,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PAGE = REPO_ROOT / "pages" / "06_Forecast_Led_Joint_Resource_Optimizer.py"


def _summary(**overrides):
    values = {
        "load_energy_kwh": 480.0,
        "load_served_kwh": 470.0,
        "unmet_load_kwh": 10.0,
        "estimated_energy_cost": 1000.0,
        "diesel_fuel_cost": 200.0,
        "battery_degradation_cost": 50.0,
        "diesel_start_cost": 10.0,
        "diesel_stop_cost": 10.0,
    }
    values.update(overrides)
    return values


def _rows(diesel_hours=4):
    return [
        {"diesel_generation_kw": 5.0 if index < diesel_hours else 0.0}
        for index in range(24)
    ]


def _record(**overrides):
    args = dict(
        summary=_summary(),
        dispatch_rows=_rows(),
        simulated_hours=24,
        days_equivalent_per_year=365,
        run_id="run-joint-001",
        manifest_sha256="a" * 64,
        data_provenance="Synthetic demonstration data",
        summary_source="recommended schedule's own nominal dispatch summary",
    )
    args.update(overrides)
    return annualise_run_summary(**args)


def test_the_projection_scales_the_run_and_carries_the_declared_assumption():
    record = _record()
    assert record["basis"]["days_equivalent_per_year"] == 365
    assert record["basis"]["hours_equivalent_per_year"] == 365 * 24
    assert record["figures"]["annual_load_energy_kwh"] == pytest.approx(480 * 365)
    assert record["figures"]["annual_energy_cost"] == pytest.approx(1000 * 365)
    assert record["figures"]["annual_unmet_load_kwh"] == pytest.approx(10 * 365)
    assert verify_annual_operating_basis(record)["valid"] is True


def test_a_different_assumption_produces_a_different_projection():
    conservative = _record(days_equivalent_per_year=200)
    naive = _record(days_equivalent_per_year=365)
    assert conservative["figures"]["annual_energy_cost"] < naive["figures"]["annual_energy_cost"]
    assert conservative["basis"]["hours_equivalent_per_year"] == 200 * 24


def test_equipment_operating_cost_is_a_breakdown_not_an_addition():
    record = _record()
    figures = record["figures"]
    components = record["components_inside_annual_energy_cost"]
    assert figures["annual_equipment_operating_cost"] == pytest.approx(
        components["diesel_fuel_cost"] + components["battery_degradation_cost"]
        + components["diesel_start_stop_cost"]
    )
    # Fuel, throughput and start/stop are already inside the run's energy cost, so
    # the breakdown must never exceed it.
    assert figures["annual_equipment_operating_cost"] <= figures["annual_energy_cost"]


def test_diesel_run_hours_count_only_committed_hours():
    assert _record(dispatch_rows=_rows(diesel_hours=0))["figures"]["annual_diesel_run_hours"] == 0
    assert _record(dispatch_rows=_rows(diesel_hours=6))["figures"]["annual_diesel_run_hours"] == 6 * 365


@pytest.mark.parametrize("days", [0, 367, True, 1.5])
def test_a_projection_refuses_an_impossible_or_non_integer_assumption(days):
    with pytest.raises(ValueError, match="days_equivalent_per_year must be"):
        _record(days_equivalent_per_year=days)


def test_a_projection_refuses_an_incomplete_run_summary():
    with pytest.raises(ValueError, match="summary is missing estimated_energy_cost"):
        _record(summary={key: value for key, value in _summary().items() if key != "estimated_energy_cost"})


def test_a_tampered_projection_does_not_verify():
    record = _record()
    record["figures"]["annual_energy_cost"] = 1.0
    errors = verify_annual_operating_basis(record)["errors"]
    assert any("does not match the record contents" in error for error in errors)


@pytest.mark.parametrize(
    "field, value, message",
    [
        ("derived_from_run", False, "must say it is derived from the run"),
        ("site_validated", True, "must never claim site validation"),
        ("bill", True, "must never claim to be a utility bill"),
    ],
)
def test_a_projection_must_keep_saying_what_it_is(field, value, message):
    record = _record()
    record["basis"][field] = value
    errors = verify_annual_operating_basis(record)["errors"]
    assert any(message in error for error in errors)


def test_every_figure_carries_its_own_definition():
    record = _record()
    assert set(record["definitions"]) == set(DEFINITIONS)
    for name, payload in record["definitions"].items():
        assert payload["unit"] and payload["meaning"], name
    assert "not a utility bill" in record["scope"]


def test_a_projection_must_name_the_summary_it_projected():
    record = _record()
    record["summary_source"] = "   "
    errors = verify_annual_operating_basis(record)["errors"]
    assert any("must name the summary it projected" in error for error in errors)


def test_the_joint_page_withholds_annual_figures_until_the_assumption_is_declared():
    source = PAGE.read_text(encoding="utf-8")
    hour_section = source.index('st.subheader("Recommended joint schedule")')
    annual_section = source.index("annualise_run_summary(")
    checkbox = source.index("project_annual = st.checkbox(")
    # The run is shown first, then the page offers the projection; nothing multiplies
    # by 365 without the checkbox.
    assert hour_section < checkbox < annual_section
    assert "annual_operating_basis" in source
    assert "verify_annual_operating_basis(" in source


def test_the_page_projects_the_selected_schedules_own_dispatch():
    source = PAGE.read_text(encoding="utf-8")
    # The page must annualise the dispatch it already drew, not a per-scenario replay
    # or a candidate list that the optimizer behind this page does not return.
    assert 'dispatch.get("summary")' in source
    assert "summary_source=summary_source" in source


def test_the_projected_state_renders_without_an_exception():
    app = AppTest.from_file(str(PAGE), default_timeout=120).run()
    assert not app.exception, [str(e) for e in app.exception]
    app.checkbox(key="annual_projection_joint_optimizer").check().run()
    assert not app.exception, [str(e) for e in app.exception]
    labels = [metric.label for metric in app.metric]
    assert any("Annual load energy" in label for label in labels)
    assert any("Annual energy cost" in label for label in labels)

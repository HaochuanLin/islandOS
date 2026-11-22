"""The annual figures must say what they are before they say how much.

`INTEGRATION.md` §6.3 makes the annual bills a citation *into* a run, never a
derivation *from* it: the customer types them. So a page may not print NPV and
admit the provenance in a caption underneath, because a reader who stops at the
number never learns that the run did not produce it.

What this does NOT prove
------------------------
A passing binding proves the citation is internally consistent. It says nothing
about whether the customer's bills are correct, and nothing about whether the
equipment will perform.
"""

from pathlib import Path

import pytest

from islandos_core.canonical_run import create_run_manifest
from islandos_core.investment_economics import (
    bind_annual_economics_to_run,
    evaluate_investment_economics,
)
from islandos_ui.annual_economics_panel import (
    annual_basis_text,
    basis_level,
    binding_errors,
    binding_facts,
    withheld_text,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PAGE = REPO_ROOT / "pages" / "05_Customer_Decision_Dashboard.py"


def _manifest():
    return create_run_manifest(
        project_id="project-dashboard",
        run_id="run-dashboard-0123456789abcdef",
        site_ref="synthetic-demo-site",
        created_at_utc="2026-11-22T00:00:00Z",
        dataset_sha256="a" * 64,
        dataset_schema_version="canonical-hourly-signals-v1",
        source_type="synthetic",
        site_configuration_version="1",
        site_configuration_sha256="b" * 64,
        required_signals={"pv_power": "kW", "wind_power": "kW", "essential_load": "kW"},
        forecast_horizon_hours=24,
        optimizer_id="prediction_resource_dispatch",
        optimizer_version="1",
        optimizer_settings={"cost": 0.6},
        scenario_assumptions={"grid_available": [True] * 24, "horizon_hours": 24},
        forecast_settings={"backtest_horizon": 24, "season_length": 24, "confidence_level": 0.9},
    ).to_dict()


def _economics(**overrides):
    args = dict(
        baseline_annual_energy_cost=100_000,
        proposed_annual_energy_cost=70_000,
        annual_incremental_om_cost=5_000,
        upfront_capex=100_000,
        project_life_years=10,
        discount_rate=0.08,
        replacement_year=None,
        replacement_cost=0.0,
        residual_value=0.0,
        service_equivalent=True,
    )
    args.update(overrides)
    return evaluate_investment_economics(**args)


def _binding(**overrides):
    return bind_annual_economics_to_run(
        _economics(**overrides),
        _manifest(),
        annual_bill_source="customer_entered_annual_bills",
    )


def test_the_basis_says_the_bills_were_entered_and_never_derived_from_the_run():
    facts = dict(binding_facts(_binding()))
    assert facts["Run"] == "run-dashboard-0123456789abcdef"
    assert facts["Derived from this run"].startswith("no")
    assert facts["Withheld"] == "no"
    text = annual_basis_text(_binding())
    assert "entered by the customer" in text
    assert "not a procurement guarantee" in text


def test_the_basis_repeats_the_stated_billing_period_when_one_is_given():
    binding = bind_annual_economics_to_run(
        _economics(),
        _manifest(),
        annual_bill_period_utc=("2025-09-01T00:00:00Z", "2026-08-31T23:59:59Z"),
    )
    text = annual_basis_text(binding)
    assert "2025-09-01T00:00:00Z" in text
    assert "2026-08-31T23:59:59Z" in text


def test_a_withheld_result_is_a_warning_and_says_no_metric_is_quoted():
    binding = _binding(service_equivalent=False)
    assert basis_level(binding) == "warning"
    assert binding_facts(binding)[2] == ("Withheld", "yes")
    assert "no investment metric is quoted" in withheld_text(binding)


def test_a_service_equivalent_result_is_information_not_a_warning():
    binding = _binding()
    assert basis_level(binding) == "info"
    assert "Withheld: no" in withheld_text(binding)


def test_a_tampered_binding_reports_the_digest_mismatch_before_any_render():
    binding = _binding()
    binding["economics"]["net_present_value"] = 999_999.0
    errors = binding_errors(binding)
    assert errors
    assert any("binding_sha256 does not match" in error for error in errors)


def test_something_that_is_not_a_binding_is_refused_rather_than_rendered():
    with pytest.raises(ValueError, match="investment economics run binding"):
        basis_level({"record_type": "offline_operator_decision_record"})
    with pytest.raises(ValueError, match="investment economics run binding"):
        binding_facts({"record_type": "investment_economics_run_binding_v2"})
    assert binding_errors(None) == ["annual economics binding is not a mapping"]


def test_the_dashboard_places_the_basis_above_the_first_investment_metric():
    source = PAGE.read_text(encoding="utf-8")
    binding_call = source.index("bind_annual_economics_to_run(")
    render_call = source.index("render_annual_economics_basis(")
    first_metric = source.index('i1.metric("Net present value"')
    assert binding_call < render_call < first_metric


def test_the_dashboard_binds_a_manifest_built_from_its_own_inputs():
    source = PAGE.read_text(encoding="utf-8")
    assert "create_run_manifest(" in source
    assert "deterministic_run_id(" in source
    assert "verify_investment_economics_binding(" in source
    # The citation must reach the downloadable report, not only the screen.
    assert '"investment_economics_binding": economics_binding' in source

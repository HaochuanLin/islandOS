import pytest

from islandos_core.canonical_run import create_run_manifest
from islandos_core.investment_economics import (
    bind_annual_economics_to_run,
    evaluate_investment_economics,
    verify_investment_economics_binding,
)


def _manifest():
    return create_run_manifest(
        project_id="project-annual",
        run_id="run-annual-001",
        site_ref="site-annual",
        created_at_utc="2026-11-18T00:00:00Z",
        dataset_sha256="c" * 64,
        dataset_schema_version="1.0",
        source_type="customer_provided",
        site_configuration_version="1",
        site_configuration_sha256="d" * 64,
        required_signals={"load_kw": "kW"},
        forecast_horizon_hours=24,
        optimizer_id="prediction_resource_dispatch",
        optimizer_version="1",
        optimizer_settings={},
        scenario_assumptions={"grid_available": [True] * 24, "diesel_available": [True] * 24},
        forecast_settings={"backtest_horizon": 24, "season_length": 24, "confidence_level": 0.9},
    ).to_dict()


def base(**overrides):
    args = dict(
        baseline_annual_energy_cost=100_000,
        proposed_annual_energy_cost=70_000,
        annual_incremental_om_cost=5_000,
        upfront_capex=100_000,
        project_life_years=10,
        discount_rate=0.08,
        replacement_year=6,
        replacement_cost=10_000,
        residual_value=5_000,
        service_equivalent=True,
    )
    args.update(overrides)
    return evaluate_investment_economics(**args)


def test_positive_screen_calculates_npv_payback_and_sensitivity():
    result = base()
    assert result.decision == "screen_positive"
    assert result.annual_energy_cost_saving == 30_000
    assert result.annual_net_operating_benefit == 25_000
    assert result.net_present_value > 0
    assert result.simple_payback_years == 4
    assert result.discounted_payback_years is not None
    assert result.sensitivity_npv["low_20pct_energy_saving"] < result.sensitivity_npv["base"]
    assert result.sensitivity_npv["base"] < result.sensitivity_npv["high_20pct_energy_saving"]
    assert len(result.annual_cashflows) == 10


def test_escalation_changes_year_by_year_cashflows_and_npv():
    flat = base()
    escalated = base(annual_energy_saving_escalation_rate=0.04, annual_om_escalation_rate=0.03)
    assert escalated.annual_cashflows[1]["energy_bill_saving"] == pytest.approx(31_200)
    assert escalated.annual_cashflows[1]["incremental_om_cost"] == pytest.approx(5_150)
    assert escalated.net_present_value > flat.net_present_value


def test_non_equivalent_service_blocks_all_investment_metrics():
    result = base(service_equivalent=False)
    assert result.decision == "blocked"
    assert result.net_present_value is None
    assert result.simple_payback_years is None
    assert result.break_even_annual_energy_saving is None
    assert result.annual_cashflows is None


def test_negative_npv_is_a_no_go_screen():
    result = base(upfront_capex=500_000)
    assert result.decision == "screen_negative"
    assert result.net_present_value < 0
    assert any("negative" in reason for reason in result.reasons)


def test_no_annual_net_benefit_has_no_payback():
    result = base(proposed_annual_energy_cost=100_000, annual_incremental_om_cost=1_000)
    assert result.annual_net_operating_benefit == -1_000
    assert result.simple_payback_years is None
    assert result.decision == "screen_negative"


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"upfront_capex": -1}, "upfront_capex cannot be negative"),
        ({"discount_rate": 0.8}, "discount_rate must be between"),
        ({"project_life_years": 0}, "project_life_years must be between"),
        ({"replacement_year": 11}, "replacement_year must fall"),
        ({"replacement_cost": 1, "replacement_year": None}, "replacement_cost requires"),
        ({"baseline_annual_energy_cost": float("nan")}, "must be a finite number"),
        ({"annual_energy_saving_escalation_rate": 1.5}, "must be between -0.5 and 1.0"),
    ],
)
def test_invalid_assumptions_are_rejected(overrides, message):
    with pytest.raises(ValueError, match=message):
        base(**overrides)


def test_negative_energy_saving_sensitivity_remains_ordered():
    result = base(proposed_annual_energy_cost=120_000)
    values = result.sensitivity_npv
    assert values["low_20pct_energy_saving"] < values["base"]
    assert values["base"] < values["high_20pct_energy_saving"]


def test_annual_economics_can_be_bound_to_the_run_it_describes():
    binding = bind_annual_economics_to_run(
        base(), _manifest(), annual_bill_period_utc=("2025-09-01T00:00:00Z", "2026-08-31T23:59:59Z")
    )
    assert binding["record_type"] == "investment_economics_run_binding"
    assert binding["run_id"] == "run-annual-001"
    assert binding["manifest_sha256"] == _manifest()["manifest_sha256"]
    assert binding["dataset_sha256"] == "c" * 64
    assert binding["dataset_source_type"] == "customer_provided"
    assert binding["annual_basis"]["derived_from_run"] is False
    assert binding["annual_basis"]["period_utc"][0].startswith("2025-09-01")
    # The declaration is scoped to this screen: since the joint optimizer gained its
    # own declared-assumption projection, "a simulated day is never annualised" would
    # be false as a product-wide claim.
    assert "never turns a simulated day into the bills it screens" in binding["annual_basis"]["annualisation"]
    assert binding["decision"] == "screen_positive"
    assert binding["withheld"] is False
    assert len(binding["binding_sha256"]) == 64
    verification = verify_investment_economics_binding(binding)
    assert verification["valid"], verification["errors"]


def test_a_tampered_binding_does_not_verify():
    binding = bind_annual_economics_to_run(base(), _manifest())
    binding["economics"]["net_present_value"] += 1000.0
    assert verify_investment_economics_binding(binding)["valid"] is False


def test_a_withheld_result_must_say_it_is_withheld():
    binding = bind_annual_economics_to_run(base(service_equivalent=False), _manifest())
    assert binding["decision"] == "blocked"
    assert binding["withheld"] is True
    assert verify_investment_economics_binding(binding)["valid"] is True
    binding["withheld"] = False
    verification = verify_investment_economics_binding(binding)
    assert verification["valid"] is False


def test_binding_refuses_a_payload_that_is_not_a_run_manifest():
    with pytest.raises(ValueError, match="canonical run manifest"):
        bind_annual_economics_to_run(base(), {"run_id": "loose", "site_ref": "s"})

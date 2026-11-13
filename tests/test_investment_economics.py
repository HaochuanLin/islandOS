import pytest

from islandos_core.investment_economics import evaluate_investment_economics


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


def test_non_equivalent_service_blocks_all_investment_metrics():
    result = base(service_equivalent=False)
    assert result.decision == "blocked"
    assert result.net_present_value is None
    assert result.simple_payback_years is None
    assert result.break_even_annual_energy_saving is None


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
    ],
)
def test_invalid_assumptions_are_rejected(overrides, message):
    with pytest.raises(ValueError, match=message):
        base(**overrides)

import pytest

from islandos_core.lifecycle_economics import (
    LifecycleEconomicsError,
    LifecycleEconomicsInputs,
    evaluate_lifecycle_economics,
)


def test_lifecycle_economics_calculates_npv_payback_and_annual_cashflows():
    inputs = LifecycleEconomicsInputs(
        baseline_annual_energy_cost=120_000,
        project_annual_energy_cost=90_000,
        initial_capex=100_000,
        project_years=5,
        discount_rate=0.0,
        annual_fixed_om=5_000,
    )
    result = evaluate_lifecycle_economics(inputs)
    assert result["annual_savings_before_om"] == pytest.approx(30_000)
    assert result["annual_operating_savings"] == pytest.approx(25_000)
    assert result["simple_payback_year"] == 4
    assert result["npv"] == pytest.approx(25_000)
    assert len(result["yearly_rows"]) == 5


def test_battery_replacement_is_charged_when_efc_threshold_is_reached():
    inputs = LifecycleEconomicsInputs(
        baseline_annual_energy_cost=100,
        project_annual_energy_cost=80,
        initial_capex=50,
        project_years=5,
        discount_rate=0,
        annual_battery_efc=500,
        battery_cycle_life_efc=1_000,
        battery_capacity_kwh=10,
        battery_replacement_cost_per_kwh=20,
    )
    result = evaluate_lifecycle_economics(inputs)
    assert result["battery_replacement_years"] == [2, 4]
    assert result["battery_replacement_count"] == 2
    assert result["battery_replacement_cost_per_event"] == 200
    assert [row["battery_replacement_cost"] for row in result["yearly_rows"]] == [
        0, 200, 0, 200, 0,
    ]


def test_battery_replacement_inputs_are_all_or_none():
    with pytest.raises(LifecycleEconomicsError, match="requires annual EFC"):
        LifecycleEconomicsInputs(
            baseline_annual_energy_cost=100,
            project_annual_energy_cost=80,
            initial_capex=50,
            project_years=5,
            annual_battery_efc=100,
        )


@pytest.mark.parametrize("rate", [-0.1, 1.0, float("nan")])
def test_invalid_discount_rate_is_rejected(rate):
    with pytest.raises(LifecycleEconomicsError):
        LifecycleEconomicsInputs(
            baseline_annual_energy_cost=100,
            project_annual_energy_cost=80,
            initial_capex=50,
            project_years=5,
            discount_rate=rate,
        )


def test_negative_operating_savings_and_no_payback_are_preserved():
    result = evaluate_lifecycle_economics(LifecycleEconomicsInputs(
        baseline_annual_energy_cost=80,
        project_annual_energy_cost=100,
        initial_capex=10,
        project_years=3,
    ))
    assert result["annual_operating_savings"] == -20
    assert result["simple_payback_year"] is None
    assert result["npv"] == pytest.approx(-61.5419396998)

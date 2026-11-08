from islandos_core.application import evaluate_project_lifecycle_economics
from islandos_core.lifecycle_economics import LifecycleEconomicsInputs


def test_application_service_exposes_lifecycle_economics_to_client_interfaces():
    result = evaluate_project_lifecycle_economics(LifecycleEconomicsInputs(
        baseline_annual_energy_cost=100,
        project_annual_energy_cost=70,
        initial_capex=50,
        project_years=2,
        discount_rate=0,
    ))
    assert result["annual_operating_savings"] == 30
    assert result["npv"] == 10

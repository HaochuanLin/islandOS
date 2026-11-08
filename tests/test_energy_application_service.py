import pytest

from islandos_core.application import run_energy_policy_comparison
from islandos_core.energy_system import (
    BatterySpec,
    EnergySystemConfig,
    EnergySystemInputs,
)


def test_application_service_returns_comparable_policy_results():
    config = EnergySystemConfig(
        pv_rated_kw=4, wind_rated_kw=0, grid_import_limit_kw=5,
        battery=BatterySpec(
            capacity_kwh=8, max_charge_kw=4, max_discharge_kw=4,
            initial_soc=0.8, min_soc=0.2, max_soc=0.95,
        ),
    )
    inputs = EnergySystemInputs(
        pv_generation_kw=[0, 0], wind_generation_kw=[0, 0],
        load_kw=[4, 4], grid_price_per_kwh=[0.1, 1.0],
        grid_available=[True, True],
    )
    result = run_energy_policy_comparison(inputs, config)
    assert result["battery_first"]["policy"] == "battery_first"
    assert result["grid_first"]["policy"] == "grid_first"
    assert "estimated_energy_cost" in result["difference_battery_first_minus_grid_first"]
    assert result["battery_first"]["summary"]["load_energy_kwh"] == pytest.approx(8)
    assert result["grid_first"]["summary"]["load_energy_kwh"] == pytest.approx(8)
    assert "does not establish a better" in result["interpretation"]


def test_application_service_does_not_hide_unmet_load_tradeoffs():
    config = EnergySystemConfig(
        pv_rated_kw=0, wind_rated_kw=0, grid_import_limit_kw=0,
    )
    inputs = EnergySystemInputs(
        pv_generation_kw=[0], wind_generation_kw=[0], load_kw=[2],
        grid_price_per_kwh=[0.5], grid_available=[False],
    )
    result = run_energy_policy_comparison(inputs, config)
    assert result["battery_first"]["summary"]["unmet_load_kwh"] == pytest.approx(2)
    assert result["grid_first"]["summary"]["unmet_load_kwh"] == pytest.approx(2)

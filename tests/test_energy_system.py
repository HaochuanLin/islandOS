import pytest

from islandos_core.energy_system import (
    BatterySpec,
    DieselSpec,
    EnergyModelError,
    EnergySystemConfig,
    EnergySystemInputs,
    dispatch_energy_system,
)


def test_renewable_surplus_charges_battery_then_curtails_with_balance():
    config = EnergySystemConfig(
        pv_rated_kw=10, wind_rated_kw=0, grid_import_limit_kw=5,
        battery=BatterySpec(
            capacity_kwh=10, max_charge_kw=8, max_discharge_kw=8,
            initial_soc=0.5, min_soc=0.1, max_soc=0.9,
            charge_efficiency=0.9, discharge_efficiency=0.9,
        ),
    )
    inputs = EnergySystemInputs(
        pv_generation_kw=[10], wind_generation_kw=[0], load_kw=[4],
        grid_price_per_kwh=[0.5], grid_available=[True],
    )
    result = dispatch_energy_system(inputs, config)
    row = result["rows"][0]
    assert row["battery_charge_kw"] == pytest.approx(4.4444444444)
    assert row["renewable_curtailed_kw"] == pytest.approx(1.5555555556)
    assert row["battery_soc"] == pytest.approx(0.9)
    assert row["energy_balance_residual_kw"] == pytest.approx(0)
    assert result["summary"]["unmet_load_kwh"] == 0


def test_battery_grid_and_diesel_cover_deficit_without_double_counting():
    config = EnergySystemConfig(
        pv_rated_kw=2, wind_rated_kw=0, grid_import_limit_kw=2,
        battery=BatterySpec(
            capacity_kwh=10, max_charge_kw=5, max_discharge_kw=8,
            initial_soc=0.8, min_soc=0.2, max_soc=0.95,
            charge_efficiency=0.9, discharge_efficiency=0.9,
        ),
        diesel=DieselSpec(rated_power_kw=1, variable_cost_per_kwh=1.2),
    )
    inputs = EnergySystemInputs(
        pv_generation_kw=[2], wind_generation_kw=[0], load_kw=[10],
        grid_price_per_kwh=[0.4], grid_available=[True], diesel_available=[True],
    )
    result = dispatch_energy_system(inputs, config)
    row = result["rows"][0]
    assert row["battery_discharge_kw"] == pytest.approx(5.4)
    assert row["grid_import_kw"] == pytest.approx(2)
    assert row["diesel_generation_kw"] == pytest.approx(0.6)
    assert row["unmet_load_kw"] == pytest.approx(0)
    assert row["energy_balance_residual_kw"] == pytest.approx(0)
    assert result["summary"]["estimated_energy_cost"] == pytest.approx(1.52)


def test_grid_first_policy_preserves_battery_when_grid_is_available():
    config = EnergySystemConfig(
        pv_rated_kw=2, wind_rated_kw=0, grid_import_limit_kw=3,
        battery=BatterySpec(
            capacity_kwh=10, max_charge_kw=5, max_discharge_kw=8,
            initial_soc=0.8, min_soc=0.2, max_soc=0.95,
        ),
    )
    inputs = EnergySystemInputs(
        pv_generation_kw=[2], wind_generation_kw=[0], load_kw=[10],
        grid_price_per_kwh=[0.2], grid_available=[True],
    )
    row = dispatch_energy_system(inputs, config, policy="grid_first")["rows"][0]
    assert row["grid_import_kw"] == pytest.approx(3)
    assert row["battery_discharge_kw"] == pytest.approx(5)
    assert row["unmet_load_kw"] == pytest.approx(0)


def test_unavailable_grid_and_diesel_are_reported_as_unmet_load():
    config = EnergySystemConfig(
        pv_rated_kw=1, wind_rated_kw=0, grid_import_limit_kw=10,
    )
    inputs = EnergySystemInputs(
        pv_generation_kw=[0], wind_generation_kw=[0], load_kw=[3],
        grid_price_per_kwh=[0.3], grid_available=[False], diesel_available=[False],
    )
    result = dispatch_energy_system(inputs, config)
    assert result["summary"]["unmet_load_kwh"] == pytest.approx(3)
    assert result["summary"]["unmet_load_fraction"] == pytest.approx(1)


def test_energy_balance_holds_for_every_timestep_in_mixed_profile():
    config = EnergySystemConfig(
        pv_rated_kw=8, wind_rated_kw=5, grid_import_limit_kw=4, dt_hours=0.5,
        battery=BatterySpec(
            capacity_kwh=12, max_charge_kw=4, max_discharge_kw=3,
            initial_soc=0.55, min_soc=0.15, max_soc=0.9,
        ),
        diesel=DieselSpec(rated_power_kw=2, variable_cost_per_kwh=1.0),
    )
    inputs = EnergySystemInputs(
        pv_generation_kw=[0, 2, 8, 5, 0, 0],
        wind_generation_kw=[1, 4, 5, 2, 0, 0],
        load_kw=[4, 4, 6, 7, 5, 8],
        grid_price_per_kwh=[0.2, 0.2, 0.5, 0.5, 0.8, 0.8],
        grid_available=[True, True, True, True, False, False],
        diesel_available=[True, True, True, True, True, False],
    )
    result = dispatch_energy_system(inputs, config)
    assert all(abs(row["energy_balance_residual_kw"]) < 1e-8 for row in result["rows"])
    assert all(0.15 - 1e-9 <= row["battery_soc"] <= 0.9 + 1e-9 for row in result["rows"])
    assert result["summary"]["unmet_load_kwh"] > 0


def test_rejects_generation_above_nameplate_rating():
    config = EnergySystemConfig(pv_rated_kw=3, wind_rated_kw=0, grid_import_limit_kw=0)
    inputs = EnergySystemInputs(
        pv_generation_kw=[3.1], wind_generation_kw=[0], load_kw=[1],
        grid_price_per_kwh=[0], grid_available=[False],
    )
    with pytest.raises(EnergyModelError, match="PV generation exceeds"):
        dispatch_energy_system(inputs, config)


def test_rejects_mismatched_series_and_boolean_physical_values():
    config = EnergySystemConfig(pv_rated_kw=5, wind_rated_kw=0, grid_import_limit_kw=5)
    mismatch = EnergySystemInputs(
        pv_generation_kw=[1, 2], wind_generation_kw=[0], load_kw=[1, 2],
        grid_price_per_kwh=[0.2, 0.2], grid_available=[True, True],
    )
    with pytest.raises(EnergyModelError, match="equal lengths"):
        dispatch_energy_system(mismatch, config)
    boolean_power = EnergySystemInputs(
        pv_generation_kw=[True], wind_generation_kw=[0], load_kw=[1],
        grid_price_per_kwh=[0.2], grid_available=[True],
    )
    with pytest.raises(EnergyModelError, match="must be numeric"):
        dispatch_energy_system(boolean_power, config)


def test_rejects_invalid_battery_soc_and_efficiency():
    with pytest.raises(EnergyModelError, match="initial_soc"):
        BatterySpec(
            capacity_kwh=10, max_charge_kw=2, max_discharge_kw=2,
            initial_soc=0.05, min_soc=0.1,
        )
    with pytest.raises(EnergyModelError, match="efficiencies must be > 0"):
        BatterySpec(
            capacity_kwh=10, max_charge_kw=2, max_discharge_kw=2,
            charge_efficiency=0,
        )


def test_rejects_unknown_dispatch_policy():
    config = EnergySystemConfig(pv_rated_kw=1, wind_rated_kw=0, grid_import_limit_kw=1)
    inputs = EnergySystemInputs(
        pv_generation_kw=[0], wind_generation_kw=[0], load_kw=[0],
        grid_price_per_kwh=[0], grid_available=[True],
    )
    with pytest.raises(EnergyModelError, match="policy"):
        dispatch_energy_system(inputs, config, policy="ai_magic")


def test_grid_availability_must_be_explicit():
    config = EnergySystemConfig(pv_rated_kw=1, wind_rated_kw=0, grid_import_limit_kw=5)
    inputs = EnergySystemInputs(
        pv_generation_kw=[0], wind_generation_kw=[0], load_kw=[1],
        grid_price_per_kwh=[0.2], grid_available=None,
    )
    with pytest.raises(EnergyModelError, match="grid_available must be explicitly supplied"):
        dispatch_energy_system(inputs, config)


def test_configured_diesel_requires_explicit_availability():
    config = EnergySystemConfig(
        pv_rated_kw=1, wind_rated_kw=0, grid_import_limit_kw=0,
        diesel=DieselSpec(rated_power_kw=2, variable_cost_per_kwh=1.0),
    )
    inputs = EnergySystemInputs(
        pv_generation_kw=[0], wind_generation_kw=[0], load_kw=[1],
        grid_price_per_kwh=[0.2], grid_available=[False],
    )
    with pytest.raises(EnergyModelError, match="diesel_available must be explicitly supplied"):
        dispatch_energy_system(inputs, config)

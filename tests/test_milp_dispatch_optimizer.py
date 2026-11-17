import pytest
from dataclasses import replace

from islandos_core.energy_system import (
    BatterySpec,
    DieselSpec,
    EnergySystemConfig,
    EnergySystemInputs,
)
from optimization.energy_system_optimizer import OptimizationError
from islandos_core.water_resource_adapter import WaterServiceSpec
from optimization.milp_dispatch_optimizer import (
    _validate_diesel_schedule,
    optimize_dispatch_milp,
)


def _case():
    config = EnergySystemConfig(
        pv_rated_kw=5.0,
        wind_rated_kw=0.0,
        grid_import_limit_kw=10.0,
        dt_hours=1.0,
        battery=BatterySpec(
            capacity_kwh=6.0,
            max_charge_kw=2.0,
            max_discharge_kw=2.0,
            initial_soc=0.5,
            min_soc=0.1,
            max_soc=0.9,
            charge_efficiency=1.0,
            discharge_efficiency=1.0,
        ),
        diesel=DieselSpec(
            rated_power_kw=8.0,
            variable_cost_per_kwh=0.5,
            min_stable_power_kw=2.0,
            ramp_up_kw_per_hour=8.0,
            ramp_down_kw_per_hour=8.0,
            min_up_time_hours=2.0,
            min_down_time_hours=1.0,
            start_cost_per_start=1.0,
            stop_cost_per_stop=0.25,
        ),
    )
    inputs = EnergySystemInputs(
        pv_generation_kw=[2.0, 0.0, 0.0, 2.0],
        wind_generation_kw=[0.0, 0.0, 0.0, 0.0],
        load_kw=[5.0, 8.0, 8.0, 5.0],
        grid_price_per_kwh=[0.2, 0.3, 0.3, 0.2],
        grid_available=[True, False, False, True],
        diesel_available=[True, True, True, True],
    )
    return inputs, config


def test_milp_dispatch_solves_and_passes_independent_and_physical_audits():
    inputs, config = _case()
    result = optimize_dispatch_milp(inputs, config)

    assert result["algorithm"] == "scipy_highs_mixed_integer_linear_program"
    assert result["solver_status"] == 0
    assert result["solve_time_seconds"] >= 0.0
    assert result["optimality_proven_for_declared_milp"] is True
    assert result["physical_audit"]["passed"] is True
    assert result["diesel_constraint_audit"]["passed"] is True
    assert result["dispatch"]["summary"]["unmet_load_kwh"] == pytest.approx(0.0)
    assert result["diesel_commitment_schedule"][1:3] == [True, True]
    assert result["model_scope"]["site_validation"] is False
    assert result["model_scope"]["device_write_authorized"] is False


def test_independent_diesel_validator_detects_ramp_and_minimum_time_violations():
    _, config = _case()
    config = EnergySystemConfig(
        pv_rated_kw=config.pv_rated_kw,
        wind_rated_kw=config.wind_rated_kw,
        grid_import_limit_kw=config.grid_import_limit_kw,
        dt_hours=config.dt_hours,
        battery=config.battery,
        diesel=replace(config.diesel, ramp_down_kw_per_hour=3.0),
    )
    errors = _validate_diesel_schedule(
        [0.0, 8.0, 0.0, 0.0],
        [False, True, False, False],
        [True, True, True, True],
        config,
    )
    assert "ramp_up_exceeded_at_1" not in errors
    assert "ramp_down_exceeded_at_2" in errors
    assert "minimum_up_time_violated_before_2" in errors


def test_milp_fails_closed_when_grid_outage_exceeds_available_supply():
    inputs, config = _case()
    impossible = EnergySystemInputs(
        pv_generation_kw=[0.0, 0.0],
        wind_generation_kw=[0.0, 0.0],
        load_kw=[30.0, 30.0],
        grid_price_per_kwh=[0.2, 0.2],
        grid_available=[False, False],
        diesel_available=[True, True],
    )
    with pytest.raises(OptimizationError, match="did not produce a feasible schedule"):
        optimize_dispatch_milp(impossible, config)


def test_milp_rejects_unsupported_grid_export_and_nonlinear_fuel_curve():
    inputs, config = _case()
    export_config = EnergySystemConfig(
        pv_rated_kw=5.0,
        wind_rated_kw=0.0,
        grid_import_limit_kw=10.0,
        grid_export_limit_kw=1.0,
        battery=config.battery,
        diesel=config.diesel,
    )
    with pytest.raises(OptimizationError, match="does not support grid export"):
        optimize_dispatch_milp(inputs, export_config)



def test_milp_models_constant_rate_fuel_inventory_and_deliveries():
    inputs, config = _case()
    diesel = replace(
        config.diesel,
        fuel_consumption_l_per_kwh=0.25,
        initial_fuel_liters=1.0,
        fuel_tank_capacity_liters=5.0,
        fuel_price_per_liter=1.0,
    )
    config = replace(config, diesel=diesel)
    inputs = replace(inputs, diesel_fuel_delivery_liters=[4.0, 0.0, 0.0, 0.0])

    result = optimize_dispatch_milp(inputs, config)

    assert result["physical_audit"]["passed"] is True
    assert result["dispatch"]["summary"]["diesel_fuel_used_liters"] > 0.0
    assert 0.0 <= result["dispatch"]["summary"]["ending_diesel_fuel_liters"] <= 5.0


def test_milp_fails_closed_when_cycle_fade_is_configured_but_not_modelled():
    inputs, config = _case()
    aged_battery = replace(config.battery, cycle_life_efc=100.0)
    config = replace(config, battery=aged_battery)

    with pytest.raises(OptimizationError, match="does not yet model cycle-driven battery capacity fade"):
        optimize_dispatch_milp(inputs, config)



def test_milp_jointly_optimizes_water_inventory_ro_power_and_energy_balance():
    inputs, config = _case()
    water = WaterServiceSpec(
        specific_energy_kwh_per_m3=2.0,
        ro_capacity_m3_per_hour=2.0,
        tank_capacity_m3=4.0,
        initial_inventory_m3=1.0,
        reserve_m3=0.5,
    )

    result = optimize_dispatch_milp(
        inputs, config,
        water_service=water,
        water_demand_m3_per_hour=[1.0, 1.0, 1.0, 1.0],
    )

    service = result["water_service"]
    assert service["service_feasible"] is True
    assert service["production_policy"] == "joint_milp_water_energy"
    assert sum(service["production_m3_per_hour"]) == pytest.approx(3.5)
    assert all(0.5 - 1e-7 <= value <= 4.0 + 1e-7 for value in service["inventory_end_m3"])
    assert all(value <= 2.0 + 1e-7 for value in service["production_m3_per_hour"])
    assert result["physical_audit"]["passed"] is True
    assert result["dispatch"]["summary"]["unmet_load_kwh"] == pytest.approx(0.0)
    assert result["dispatch"]["rows"][0]["load_kw"] == pytest.approx(
        inputs.load_kw[0] + service["ro_power_kw"][0]
    )
    assert result["model_scope"]["device_write_authorized"] is False


def test_milp_joint_water_energy_fails_closed_when_ro_capacity_cannot_serve_demand():
    inputs, config = _case()
    water = WaterServiceSpec(
        specific_energy_kwh_per_m3=2.0,
        ro_capacity_m3_per_hour=0.2,
        tank_capacity_m3=2.0,
        initial_inventory_m3=0.5,
        reserve_m3=0.5,
    )
    with pytest.raises(OptimizationError, match="did not produce a feasible schedule"):
        optimize_dispatch_milp(
            inputs, config,
            water_service=water,
            water_demand_m3_per_hour=[1.0, 1.0, 1.0, 1.0],
        )


def test_milp_requires_water_spec_and_demand_together():
    inputs, config = _case()
    water = WaterServiceSpec(
        specific_energy_kwh_per_m3=2.0,
        ro_capacity_m3_per_hour=1.0,
        tank_capacity_m3=2.0,
        initial_inventory_m3=1.0,
    )
    with pytest.raises(OptimizationError, match="must be supplied together"):
        optimize_dispatch_milp(inputs, config, water_service=water)

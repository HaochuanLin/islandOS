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


def test_grid_export_respects_limit_and_reconciles_energy_and_revenue():
    config = EnergySystemConfig(
        pv_rated_kw=10, wind_rated_kw=0, grid_import_limit_kw=5,
        dt_hours=0.5, grid_export_limit_kw=3,
    )
    inputs = EnergySystemInputs(
        pv_generation_kw=[10], wind_generation_kw=[0], load_kw=[4],
        grid_price_per_kwh=[0.2], grid_available=[True],
        grid_export_price_per_kwh=[0.2],
        grid_export_available=[True],
    )
    result = dispatch_energy_system(inputs, config)
    row = result["rows"][0]
    summary = result["summary"]
    assert row["grid_available"] is True
    assert row["grid_export_kw"] == pytest.approx(3)
    assert row["grid_import_kw"] == 0
    assert row["renewable_curtailed_kw"] == pytest.approx(3)
    assert row["energy_balance_residual_kw"] == pytest.approx(0)
    assert summary["grid_export_energy_kwh"] == pytest.approx(1.5)
    assert summary["grid_export_revenue"] == pytest.approx(0.3)
    assert summary["gross_energy_cost"] == pytest.approx(0)
    assert summary["estimated_energy_cost"] == pytest.approx(-0.3)


def test_grid_export_is_blocked_when_grid_is_unavailable():
    config = EnergySystemConfig(
        pv_rated_kw=10, wind_rated_kw=0, grid_import_limit_kw=5,
        grid_export_limit_kw=5,
    )
    inputs = EnergySystemInputs(
        pv_generation_kw=[10], wind_generation_kw=[0], load_kw=[4],
        grid_price_per_kwh=[0.2], grid_available=[False],
        grid_export_price_per_kwh=[0.1],
        grid_export_available=[True],
    )
    result = dispatch_energy_system(inputs, config)
    assert result["rows"][0]["grid_available"] is False
    assert result["rows"][0]["grid_export_kw"] == 0
    assert result["summary"]["grid_export_revenue"] == 0
    assert result["summary"]["renewable_curtailed_kwh"] == pytest.approx(6)


def test_grid_export_requires_explicit_price_series_and_matching_length():
    config = EnergySystemConfig(
        pv_rated_kw=10, wind_rated_kw=0, grid_import_limit_kw=5,
        grid_export_limit_kw=5,
    )
    base = dict(
        pv_generation_kw=[10], wind_generation_kw=[0], load_kw=[4],
        grid_price_per_kwh=[0.2], grid_available=[True],
    )
    with pytest.raises(EnergyModelError, match="grid_export_price_per_kwh must be explicitly supplied"):
        dispatch_energy_system(EnergySystemInputs(**base), config)
    with pytest.raises(EnergyModelError, match="equal lengths"):
        dispatch_energy_system(
            EnergySystemInputs(**base, grid_export_price_per_kwh=[0.1, 0.2], grid_export_available=[True]),
            config,
        )


def test_export_price_without_export_capacity_is_rejected():
    config = EnergySystemConfig(pv_rated_kw=10, wind_rated_kw=0, grid_import_limit_kw=5)
    inputs = EnergySystemInputs(
        pv_generation_kw=[10], wind_generation_kw=[0], load_kw=[4],
        grid_price_per_kwh=[0.2], grid_available=[True],
        grid_export_price_per_kwh=[0.1],
        grid_export_available=[True],
    )
    with pytest.raises(EnergyModelError, match="grid_export_limit_kw is zero"):
        dispatch_energy_system(inputs, config)


def test_negative_export_price_is_accounted_as_a_cost_not_revenue():
    config = EnergySystemConfig(
        pv_rated_kw=10, wind_rated_kw=0, grid_import_limit_kw=5,
        grid_export_limit_kw=5,
    )
    inputs = EnergySystemInputs(
        pv_generation_kw=[10], wind_generation_kw=[0], load_kw=[4],
        grid_price_per_kwh=[0.2], grid_available=[True],
        grid_export_price_per_kwh=[-0.1],
        grid_export_available=[True],
    )
    result = dispatch_energy_system(inputs, config)
    assert result["summary"]["grid_export_revenue"] == pytest.approx(-0.5)
    assert result["summary"]["estimated_energy_cost"] == pytest.approx(0.5)


def test_battery_is_charged_before_remaining_surplus_is_exported():
    config = EnergySystemConfig(
        pv_rated_kw=10, wind_rated_kw=0, grid_import_limit_kw=5,
        grid_export_limit_kw=4,
        battery=BatterySpec(
            capacity_kwh=4, max_charge_kw=2, max_discharge_kw=2,
            initial_soc=0.5, min_soc=0.1, max_soc=0.9,
            charge_efficiency=1.0, discharge_efficiency=1.0,
        ),
    )
    inputs = EnergySystemInputs(
        pv_generation_kw=[10], wind_generation_kw=[0], load_kw=[4],
        grid_price_per_kwh=[0.2], grid_available=[True],
        grid_export_price_per_kwh=[0.1],
        grid_export_available=[True],
    )
    result = dispatch_energy_system(inputs, config)
    row = result["rows"][0]
    assert row["battery_charge_kw"] == pytest.approx(1.6)
    assert row["grid_export_kw"] == pytest.approx(4)
    assert row["renewable_curtailed_kw"] == pytest.approx(0.4)
    assert row["energy_balance_residual_kw"] == pytest.approx(0)


def test_model_scope_discloses_export_configuration_without_claiming_interconnection_approval():
    config = EnergySystemConfig(
        pv_rated_kw=1, wind_rated_kw=0, grid_import_limit_kw=1,
        grid_export_limit_kw=1,
    )
    inputs = EnergySystemInputs(
        pv_generation_kw=[0], wind_generation_kw=[0], load_kw=[0],
        grid_price_per_kwh=[0.2], grid_available=[True],
        grid_export_price_per_kwh=[0.1],
        grid_export_available=[True],
    )
    result = dispatch_energy_system(inputs, config)
    assert result["grid_export_limit_kw"] == 1
    assert result["model_scope"]["grid_export_enabled"] is True
    assert result["model_scope"]["interconnection_permission_validated"] is False
    assert result["model_scope"]["network_power_flow_modeled"] is False


def test_grid_export_requires_explicit_export_permission_series():
    config = EnergySystemConfig(
        pv_rated_kw=10, wind_rated_kw=0, grid_import_limit_kw=5,
        grid_export_limit_kw=5,
    )
    inputs = EnergySystemInputs(
        pv_generation_kw=[10], wind_generation_kw=[0], load_kw=[4],
        grid_price_per_kwh=[0.2], grid_available=[True],
        grid_export_price_per_kwh=[0.1],
    )
    with pytest.raises(EnergyModelError, match="grid_export_available must be explicitly supplied"):
        dispatch_energy_system(inputs, config)


def test_export_permission_can_be_false_while_grid_remains_available():
    config = EnergySystemConfig(
        pv_rated_kw=10, wind_rated_kw=0, grid_import_limit_kw=5,
        grid_export_limit_kw=5,
    )
    inputs = EnergySystemInputs(
        pv_generation_kw=[10], wind_generation_kw=[0], load_kw=[4],
        grid_price_per_kwh=[0.2], grid_available=[True],
        grid_export_price_per_kwh=[0.1], grid_export_available=[False],
    )
    result = dispatch_energy_system(inputs, config)
    row = result["rows"][0]
    assert row["grid_available"] is True
    assert row["grid_export_available"] is False
    assert row["grid_export_kw"] == 0
    assert row["grid_export_revenue"] == 0
    assert row["renewable_curtailed_kw"] == pytest.approx(6)



def test_diesel_minimum_stable_output_blocks_uneconomic_partial_start():
    config = EnergySystemConfig(
        pv_rated_kw=0, wind_rated_kw=0, grid_import_limit_kw=0,
        diesel=DieselSpec(
            rated_power_kw=20, variable_cost_per_kwh=1.0,
            min_stable_power_kw=6,
        ),
    )
    inputs = EnergySystemInputs(
        pv_generation_kw=[0, 0], wind_generation_kw=[0, 0],
        load_kw=[4, 8], grid_price_per_kwh=[0, 0],
        grid_available=[False, False], diesel_available=[True, True],
    )
    result = dispatch_energy_system(inputs, config)
    assert result["rows"][0]["diesel_generation_kw"] == 0
    assert result["rows"][0]["unmet_load_kw"] == 4
    assert result["rows"][1]["diesel_generation_kw"] == 8
    assert result["rows"][1]["diesel_started"] is True
    assert result["summary"]["diesel_start_count"] == 1


def test_diesel_ramp_up_and_start_stop_costs_are_audited():
    config = EnergySystemConfig(
        pv_rated_kw=0, wind_rated_kw=0, grid_import_limit_kw=0,
        dt_hours=0.5,
        diesel=DieselSpec(
            rated_power_kw=20, variable_cost_per_kwh=1.0,
            min_stable_power_kw=2, ramp_up_kw_per_hour=4,
            start_cost_per_start=3.0, stop_cost_per_stop=1.5,
        ),
    )
    inputs = EnergySystemInputs(
        pv_generation_kw=[0, 0, 0], wind_generation_kw=[0, 0, 0],
        load_kw=[2, 8, 0], grid_price_per_kwh=[0, 0, 0],
        grid_available=[False, False, False],
        diesel_available=[True, True, True],
    )
    result = dispatch_energy_system(inputs, config)
    rows = result["rows"]
    assert [row["diesel_generation_kw"] for row in rows] == pytest.approx([2, 4, 0])
    assert rows[0]["diesel_started"] is True
    assert rows[2]["diesel_stopped"] is True
    assert result["summary"]["diesel_start_count"] == 1
    assert result["summary"]["diesel_stop_count"] == 1
    assert result["summary"]["diesel_start_cost"] == pytest.approx(3.0)
    assert result["summary"]["diesel_stop_cost"] == pytest.approx(1.5)
    assert result["summary"]["estimated_energy_cost"] == pytest.approx(7.5)


def test_diesel_rejects_minimum_above_rated_and_invalid_ramp():
    with pytest.raises(EnergyModelError, match="cannot exceed rated"):
        DieselSpec(
            rated_power_kw=10, variable_cost_per_kwh=1,
            min_stable_power_kw=11,
        )
    with pytest.raises(EnergyModelError, match="ramp_up_kw_per_hour"):
        DieselSpec(
            rated_power_kw=10, variable_cost_per_kwh=1,
            ramp_up_kw_per_hour=0,
        )



def test_diesel_stops_and_records_cost_when_other_sources_cover_load():
    config = EnergySystemConfig(
        pv_rated_kw=0, wind_rated_kw=0, grid_import_limit_kw=10,
        diesel=DieselSpec(
            rated_power_kw=10, variable_cost_per_kwh=1.0,
            min_stable_power_kw=2, stop_cost_per_stop=2.5,
        ),
    )
    inputs = EnergySystemInputs(
        pv_generation_kw=[0, 0], wind_generation_kw=[0, 0],
        load_kw=[8, 5], grid_price_per_kwh=[0.2, 0.2],
        grid_available=[False, True], diesel_available=[True, True],
    )
    result = dispatch_energy_system(inputs, config, policy="grid_first")
    assert result["rows"][0]["diesel_generation_kw"] == pytest.approx(8)
    assert result["rows"][1]["diesel_generation_kw"] == 0
    assert result["rows"][1]["diesel_stopped"] is True
    assert result["summary"]["diesel_stop_count"] == 1
    assert result["summary"]["diesel_stop_cost"] == pytest.approx(2.5)


def test_diesel_startup_reaches_stable_minimum_before_ramp_limit_applies():
    config = EnergySystemConfig(
        pv_rated_kw=0, wind_rated_kw=0, grid_import_limit_kw=0,
        diesel=DieselSpec(
            rated_power_kw=10, variable_cost_per_kwh=1.0,
            min_stable_power_kw=5, ramp_up_kw_per_hour=2,
        ),
    )
    inputs = EnergySystemInputs(
        pv_generation_kw=[0, 0], wind_generation_kw=[0, 0],
        load_kw=[8, 10], grid_price_per_kwh=[0, 0],
        grid_available=[False, False], diesel_available=[True, True],
    )
    rows = dispatch_energy_system(inputs, config)["rows"]
    assert [row["diesel_generation_kw"] for row in rows] == pytest.approx([8, 10])



def test_diesel_fuel_inventory_limits_generation_and_tracks_remaining_fuel():
    config = EnergySystemConfig(
        pv_rated_kw=0, wind_rated_kw=0, grid_import_limit_kw=0,
        dt_hours=1,
        diesel=DieselSpec(
            rated_power_kw=10, variable_cost_per_kwh=1.0,
            min_stable_power_kw=2,
            fuel_consumption_l_per_kwh=0.25,
            initial_fuel_liters=3.0,
        ),
    )
    inputs = EnergySystemInputs(
        pv_generation_kw=[0, 0], wind_generation_kw=[0, 0],
        load_kw=[8, 8], grid_price_per_kwh=[0, 0],
        grid_available=[False, False], diesel_available=[True, True],
    )
    result = dispatch_energy_system(inputs, config)
    rows = result["rows"]
    assert rows[0]["diesel_generation_kw"] == pytest.approx(8)
    assert rows[0]["diesel_fuel_used_liters"] == pytest.approx(2)
    assert rows[0]["diesel_fuel_remaining_liters"] == pytest.approx(1)
    # Remaining fuel can only support 4 kWh, but that is above the stable minimum.
    assert rows[1]["diesel_generation_kw"] == pytest.approx(4)
    assert rows[1]["unmet_load_kw"] == pytest.approx(4)
    assert rows[1]["diesel_fuel_remaining_liters"] == pytest.approx(0)
    assert result["summary"]["diesel_fuel_used_liters"] == pytest.approx(3)
    assert result["summary"]["ending_diesel_fuel_liters"] == pytest.approx(0)


def test_diesel_does_not_start_when_remaining_fuel_cannot_support_minimum_load():
    config = EnergySystemConfig(
        pv_rated_kw=0, wind_rated_kw=0, grid_import_limit_kw=0,
        diesel=DieselSpec(
            rated_power_kw=10, variable_cost_per_kwh=1.0,
            min_stable_power_kw=3,
            fuel_consumption_l_per_kwh=0.5,
            initial_fuel_liters=1.0,
        ),
    )
    inputs = EnergySystemInputs(
        pv_generation_kw=[0], wind_generation_kw=[0], load_kw=[8],
        grid_price_per_kwh=[0], grid_available=[False], diesel_available=[True],
    )
    result = dispatch_energy_system(inputs, config)
    assert result["rows"][0]["diesel_generation_kw"] == 0
    assert result["rows"][0]["unmet_load_kw"] == 8
    assert result["summary"]["diesel_fuel_used_liters"] == 0


def test_diesel_fuel_configuration_requires_both_inventory_and_consumption_rate():
    with pytest.raises(EnergyModelError, match="must be supplied together"):
        DieselSpec(
            rated_power_kw=10, variable_cost_per_kwh=1.0,
            fuel_consumption_l_per_kwh=0.25,
        )


def test_diesel_fuel_exactly_supporting_minimum_load_then_exhaustion_stops_cleanly():
    config = EnergySystemConfig(
        pv_rated_kw=0, wind_rated_kw=0, grid_import_limit_kw=0,
        dt_hours=0.5,
        diesel=DieselSpec(
            rated_power_kw=10, variable_cost_per_kwh=1.0,
            min_stable_power_kw=2,
            fuel_consumption_l_per_kwh=0.5,
            initial_fuel_liters=0.5,
        ),
    )
    inputs = EnergySystemInputs(
        pv_generation_kw=[0, 0], wind_generation_kw=[0, 0],
        load_kw=[2, 2], grid_price_per_kwh=[0, 0],
        grid_available=[False, False], diesel_available=[True, True],
    )
    result = dispatch_energy_system(inputs, config)
    first, second = result["rows"]
    assert first["diesel_generation_kw"] == pytest.approx(2)
    assert first["diesel_fuel_used_liters"] == pytest.approx(0.5)
    assert first["diesel_fuel_remaining_liters"] == pytest.approx(0)
    assert second["diesel_generation_kw"] == 0
    assert second["diesel_started"] is False
    assert second["unmet_load_kw"] == pytest.approx(2)
    assert result["summary"]["diesel_fuel_used_liters"] == pytest.approx(0.5)
    assert result["summary"]["ending_diesel_fuel_liters"] == pytest.approx(0)


def test_diesel_fuel_delivery_is_added_before_dispatch_and_audited():
    config = EnergySystemConfig(
        pv_rated_kw=0, wind_rated_kw=0, grid_import_limit_kw=0,
        diesel=DieselSpec(
            rated_power_kw=10, variable_cost_per_kwh=1.0,
            min_stable_power_kw=2,
            fuel_consumption_l_per_kwh=0.5,
            initial_fuel_liters=0,
        ),
    )
    inputs = EnergySystemInputs(
        pv_generation_kw=[0, 0], wind_generation_kw=[0, 0],
        load_kw=[4, 4], grid_price_per_kwh=[0, 0],
        grid_available=[False, False], diesel_available=[True, True],
        diesel_fuel_delivery_liters=[1.0, 0.0],
    )
    result = dispatch_energy_system(inputs, config)
    first, second = result["rows"]
    assert first["diesel_fuel_delivered_liters"] == pytest.approx(1.0)
    assert first["diesel_generation_kw"] == pytest.approx(2)
    assert first["diesel_fuel_used_liters"] == pytest.approx(1.0)
    assert first["diesel_fuel_remaining_liters"] == pytest.approx(0)
    assert second["diesel_generation_kw"] == 0
    assert second["diesel_fuel_delivered_liters"] == 0
    assert result["summary"]["diesel_fuel_delivered_liters"] == pytest.approx(1.0)
    assert result["summary"]["diesel_fuel_used_liters"] == pytest.approx(1.0)


def test_diesel_fuel_delivery_requires_configured_fuel_inventory():
    config = EnergySystemConfig(
        pv_rated_kw=0, wind_rated_kw=0, grid_import_limit_kw=0,
        diesel=DieselSpec(rated_power_kw=10, variable_cost_per_kwh=1.0),
    )
    inputs = EnergySystemInputs(
        pv_generation_kw=[0], wind_generation_kw=[0], load_kw=[1],
        grid_price_per_kwh=[0], grid_available=[False],
        diesel_available=[True], diesel_fuel_delivery_liters=[10],
    )
    with pytest.raises(EnergyModelError, match="requires a diesel fuel-inventory model"):
        dispatch_energy_system(inputs, config)


def test_diesel_fuel_delivery_series_must_match_dispatch_horizon():
    config = EnergySystemConfig(
        pv_rated_kw=0, wind_rated_kw=0, grid_import_limit_kw=0,
        diesel=DieselSpec(
            rated_power_kw=10, variable_cost_per_kwh=1.0,
            fuel_consumption_l_per_kwh=0.5, initial_fuel_liters=10,
        ),
    )
    inputs = EnergySystemInputs(
        pv_generation_kw=[0, 0], wind_generation_kw=[0, 0], load_kw=[1, 1],
        grid_price_per_kwh=[0, 0], grid_available=[False, False],
        diesel_available=[True, True], diesel_fuel_delivery_liters=[1],
    )
    with pytest.raises(EnergyModelError, match="equal lengths"):
        dispatch_energy_system(inputs, config)

def test_diesel_fuel_delivery_rejects_negative_liters():
    config = EnergySystemConfig(
        pv_rated_kw=0, wind_rated_kw=0, grid_import_limit_kw=0,
        diesel=DieselSpec(
            rated_power_kw=10, variable_cost_per_kwh=1.0,
            fuel_consumption_l_per_kwh=0.5, initial_fuel_liters=10,
        ),
    )
    inputs = EnergySystemInputs(
        pv_generation_kw=[0], wind_generation_kw=[0], load_kw=[1],
        grid_price_per_kwh=[0], grid_available=[False],
        diesel_available=[True], diesel_fuel_delivery_liters=[-1],
    )
    with pytest.raises(EnergyModelError, match=r"diesel_fuel_delivery_liters\[0\]"):
        dispatch_energy_system(inputs, config)

def test_diesel_fuel_delivery_cannot_overfill_confirmed_tank_capacity():
    config = EnergySystemConfig(
        pv_rated_kw=0, wind_rated_kw=0, grid_import_limit_kw=0,
        diesel=DieselSpec(
            rated_power_kw=10, variable_cost_per_kwh=1.0,
            fuel_consumption_l_per_kwh=0.5, initial_fuel_liters=8,
            fuel_tank_capacity_liters=10,
        ),
    )
    inputs = EnergySystemInputs(
        pv_generation_kw=[0], wind_generation_kw=[0], load_kw=[1],
        grid_price_per_kwh=[0], grid_available=[False],
        diesel_available=[True], diesel_fuel_delivery_liters=[3],
    )
    with pytest.raises(EnergyModelError, match="exceeds tank capacity at timestep 0"):
        dispatch_energy_system(inputs, config)


def test_diesel_initial_inventory_cannot_exceed_tank_capacity():
    with pytest.raises(EnergyModelError, match="cannot exceed fuel_tank_capacity_liters"):
        DieselSpec(
            rated_power_kw=10, variable_cost_per_kwh=1.0,
            fuel_consumption_l_per_kwh=0.5, initial_fuel_liters=11,
            fuel_tank_capacity_liters=10,
        )

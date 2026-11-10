import pytest

from islandos_core.energy_system import (
    BatterySpec,
    DieselSpec,
    EnergyModelError,
    EnergySystemConfig,
    EnergySystemInputs,
    dispatch_energy_system,
    compare_energy_policies,
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

def test_battery_throughput_cost_counts_charge_and_discharge_energy():
    config = EnergySystemConfig(
        pv_rated_kw=5, wind_rated_kw=0, grid_import_limit_kw=0,
        battery=BatterySpec(
            capacity_kwh=10, max_charge_kw=5, max_discharge_kw=5,
            initial_soc=0.2, min_soc=0.1, max_soc=0.95,
            charge_efficiency=1, discharge_efficiency=1,
            throughput_cost_per_kwh=0.1,
        ),
    )
    inputs = EnergySystemInputs(
        pv_generation_kw=[5, 0], wind_generation_kw=[0, 0],
        load_kw=[0, 5], grid_price_per_kwh=[0, 0],
        grid_available=[False, False],
    )
    result = dispatch_energy_system(inputs, config, policy="battery_first")
    first, second = result["rows"]
    assert first["battery_throughput_kwh"] == pytest.approx(5)
    assert second["battery_throughput_kwh"] == pytest.approx(5)
    assert first["battery_degradation_cost"] == pytest.approx(0.5)
    assert second["battery_degradation_cost"] == pytest.approx(0.5)
    assert result["summary"]["battery_throughput_kwh"] == pytest.approx(10)
    assert result["summary"]["battery_degradation_cost"] == pytest.approx(1)
    assert result["summary"]["gross_energy_cost"] == pytest.approx(1)
    assert result["summary"]["estimated_energy_cost"] == pytest.approx(1)
    assert result["model_scope"]["battery_throughput_cost_enabled"] is True
    assert result["model_scope"]["battery_degradation_is_physical_capacity_fade"] is False


def test_battery_throughput_cost_defaults_to_zero_for_backward_compatibility():
    config = EnergySystemConfig(
        pv_rated_kw=0, wind_rated_kw=0, grid_import_limit_kw=10,
        battery=BatterySpec(
            capacity_kwh=10, max_charge_kw=5, max_discharge_kw=5,
            initial_soc=0.8, min_soc=0.1, max_soc=0.95,
            charge_efficiency=1, discharge_efficiency=1,
        ),
    )
    inputs = EnergySystemInputs(
        pv_generation_kw=[0], wind_generation_kw=[0], load_kw=[5],
        grid_price_per_kwh=[0.2], grid_available=[True],
    )
    result = dispatch_energy_system(inputs, config, policy="battery_first")
    assert result["summary"]["battery_throughput_kwh"] == pytest.approx(5)
    assert result["summary"]["battery_degradation_cost"] == 0
    assert result["summary"]["estimated_energy_cost"] == 0
    assert result["model_scope"]["battery_throughput_cost_enabled"] is False


def test_battery_throughput_cost_rejects_negative_values():
    with pytest.raises(EnergyModelError, match="throughput_cost_per_kwh"):
        BatterySpec(
            capacity_kwh=10, max_charge_kw=5, max_discharge_kw=5,
            throughput_cost_per_kwh=-0.01,
        )

def test_nonlinear_diesel_fuel_curve_interpolates_and_limits_output_by_inventory():
    config = EnergySystemConfig(
        pv_rated_kw=0, wind_rated_kw=0, grid_import_limit_kw=0,
        diesel=DieselSpec(
            rated_power_kw=10, variable_cost_per_kwh=1.0,
            min_stable_power_kw=2,
            fuel_curve_liters_per_hour=((0.0, 0.0), (5.0, 2.5), (10.0, 6.0)),
            initial_fuel_liters=3.5,
        ),
    )
    inputs = EnergySystemInputs(
        pv_generation_kw=[0], wind_generation_kw=[0], load_kw=[10],
        grid_price_per_kwh=[0], grid_available=[False], diesel_available=[True],
    )
    result = dispatch_energy_system(inputs, config)
    row = result["rows"][0]
    # The 3.5 L inventory supports exactly 6.25 kW on the upper curve segment.
    assert row["diesel_generation_kw"] == pytest.approx(6.428571428571429, abs=1e-7)
    assert row["diesel_fuel_used_liters"] == pytest.approx(3.5, abs=1e-7)
    assert row["diesel_fuel_remaining_liters"] == pytest.approx(0, abs=1e-7)
    assert row["unmet_load_kw"] == pytest.approx(3.571428571428571, abs=1e-7)
    assert result["summary"]["diesel_fuel_used_liters"] == pytest.approx(3.5)
    assert result["model_scope"]["diesel_nonlinear_fuel_curve_enabled"] is True
    assert result["model_scope"]["diesel_fuel_consumption_model"] == "piecewise_linear_curve"


def test_nonlinear_diesel_fuel_curve_requires_enough_fuel_for_stable_minimum():
    config = EnergySystemConfig(
        pv_rated_kw=0, wind_rated_kw=0, grid_import_limit_kw=0,
        diesel=DieselSpec(
            rated_power_kw=10, variable_cost_per_kwh=1.0,
            min_stable_power_kw=5,
            fuel_curve_liters_per_hour=((0.0, 0.0), (5.0, 2.5), (10.0, 6.0)),
            initial_fuel_liters=2.49,
        ),
    )
    inputs = EnergySystemInputs(
        pv_generation_kw=[0], wind_generation_kw=[0], load_kw=[8],
        grid_price_per_kwh=[0], grid_available=[False], diesel_available=[True],
    )
    result = dispatch_energy_system(inputs, config)
    assert result["rows"][0]["diesel_generation_kw"] == 0
    assert result["rows"][0]["unmet_load_kw"] == pytest.approx(8)


@pytest.mark.parametrize(
    "curve, message",
    [
        (((1.0, 1.0), (10.0, 6.0)), "must start at"),
        (((0.0, 0.0), (5.0, 2.5)), "must end at rated_power_kw"),
        (((0.0, 0.0), (5.0, 2.5), (4.0, 3.0), (10.0, 6.0)), "power must increase"),
        (((0.0, 0.0), (5.0, 3.0), (10.0, 2.0)), "fuel rate must not decrease"),
        (((0.0, 0.0), (10.0, 0.0)), "rated-power fuel rate must be > 0"),
    ],
)
def test_nonlinear_diesel_fuel_curve_rejects_invalid_shapes(curve, message):
    with pytest.raises(EnergyModelError, match=message):
        DieselSpec(
            rated_power_kw=10, variable_cost_per_kwh=1.0,
            fuel_curve_liters_per_hour=curve, initial_fuel_liters=20,
        )


def test_diesel_constant_rate_and_curve_cannot_be_configured_together():
    with pytest.raises(EnergyModelError, match="mutually exclusive"):
        DieselSpec(
            rated_power_kw=10, variable_cost_per_kwh=1.0,
            fuel_consumption_l_per_kwh=0.25,
            fuel_curve_liters_per_hour=((0.0, 0.0), (10.0, 3.0)),
            initial_fuel_liters=20,
        )

def test_diesel_fuel_price_is_accounted_separately_from_nonfuel_variable_cost():
    config = EnergySystemConfig(
        pv_rated_kw=0, wind_rated_kw=0, grid_import_limit_kw=0,
        diesel=DieselSpec(
            rated_power_kw=10, variable_cost_per_kwh=0.1,
            fuel_curve_liters_per_hour=((0.0, 0.0), (10.0, 6.0)),
            initial_fuel_liters=10,
            fuel_price_per_liter=1.5,
        ),
    )
    inputs = EnergySystemInputs(
        pv_generation_kw=[0], wind_generation_kw=[0], load_kw=[10],
        grid_price_per_kwh=[0], grid_available=[False], diesel_available=[True],
    )
    result = dispatch_energy_system(inputs, config)
    row = result["rows"][0]
    assert row["diesel_fuel_used_liters"] == pytest.approx(6)
    assert row["diesel_fuel_cost"] == pytest.approx(9)
    assert result["summary"]["diesel_energy_cost"] == pytest.approx(1)
    assert result["summary"]["diesel_fuel_cost"] == pytest.approx(9)
    assert result["summary"]["gross_energy_cost"] == pytest.approx(10)
    assert result["model_scope"]["diesel_fuel_cost_enabled"] is True


def test_diesel_fuel_price_requires_inventory_model_and_nonnegative_value():
    with pytest.raises(EnergyModelError, match="requires a configured fuel model"):
        DieselSpec(
            rated_power_kw=10, variable_cost_per_kwh=0.1,
            fuel_price_per_liter=1.5,
        )
    with pytest.raises(EnergyModelError, match="fuel_price_per_liter"):
        DieselSpec(
            rated_power_kw=10, variable_cost_per_kwh=0.1,
            fuel_consumption_l_per_kwh=0.25, initial_fuel_liters=10,
            fuel_price_per_liter=-0.1,
        )

def test_policy_comparison_reports_diesel_fuel_cost_and_consumption_differences():
    config = EnergySystemConfig(
        pv_rated_kw=0, wind_rated_kw=0, grid_import_limit_kw=0,
        diesel=DieselSpec(
            rated_power_kw=10, variable_cost_per_kwh=0.1,
            fuel_curve_liters_per_hour=((0.0, 0.0), (10.0, 6.0)),
            initial_fuel_liters=10, fuel_price_per_liter=1.5,
        ),
    )
    inputs = EnergySystemInputs(
        pv_generation_kw=[0], wind_generation_kw=[0], load_kw=[5],
        grid_price_per_kwh=[0], grid_available=[False], diesel_available=[True],
    )
    comparison = compare_energy_policies(inputs, config)
    differences = comparison["difference_battery_first_minus_grid_first"]
    assert "diesel_fuel_used_liters" in differences
    assert "diesel_fuel_cost" in differences
    assert "diesel_energy_cost" in differences
    assert differences["diesel_fuel_cost"] == pytest.approx(0)
    assert comparison["battery_first"]["summary"]["diesel_fuel_cost"] == pytest.approx(4.5)

def test_battery_cycle_aging_tracks_efc_state_of_health_and_capacity_fade():
    config = EnergySystemConfig(
        pv_rated_kw=5, wind_rated_kw=0, grid_import_limit_kw=0,
        battery=BatterySpec(
            capacity_kwh=10, max_charge_kw=5, max_discharge_kw=5,
            initial_soc=0.5, min_soc=0.1, max_soc=0.95,
            charge_efficiency=1, discharge_efficiency=1,
            cycle_life_efc=100, end_of_life_capacity_fraction=0.8,
        ),
    )
    inputs = EnergySystemInputs(
        pv_generation_kw=[5, 0], wind_generation_kw=[0, 0],
        load_kw=[0, 5], grid_price_per_kwh=[0, 0],
        grid_available=[False, False],
    )
    result = dispatch_energy_system(inputs, config, policy="battery_first")
    first, second = result["rows"]
    summary = result["summary"]
    assert first["battery_efc_increment"] == pytest.approx(0.225)
    assert second["battery_efc_increment"] == pytest.approx(0.25)
    assert summary["battery_equivalent_full_cycles"] == pytest.approx(0.475)
    assert summary["battery_capacity_fade_kwh"] == pytest.approx(0.0095)
    assert summary["ending_battery_state_of_health"] == pytest.approx(0.99905)
    assert summary["ending_battery_effective_capacity_kwh"] == pytest.approx(9.9905)
    assert first["battery_capacity_fade_spill_kwh"] > 0
    assert result["model_scope"]["battery_cycle_aging_enabled"] is True
    assert result["model_scope"]["battery_calendar_aging_modeled"] is False
    assert result["model_scope"]["battery_temperature_aging_modeled"] is False


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"cycle_life_efc": 0}, "cycle_life_efc must be > 0"),
        ({"cycle_life_efc": 100, "end_of_life_capacity_fraction": 1}, "must be between 0 and 1"),
        ({"cycle_life_efc": 100, "initial_state_of_health": 0.7}, "cannot be below end-of-life"),
        ({"end_of_life_capacity_fraction": 0.75}, "requires cycle_life_efc"),
    ],
)
def test_battery_cycle_aging_rejects_invalid_lifecycle_parameters(kwargs, message):
    with pytest.raises(EnergyModelError, match=message):
        BatterySpec(
            capacity_kwh=10, max_charge_kw=5, max_discharge_kw=5,
            **kwargs,
        )


def test_negative_grid_import_price_is_accounted_as_a_credit():
    config = EnergySystemConfig(
        pv_rated_kw=0, wind_rated_kw=0, grid_import_limit_kw=5,
    )
    inputs = EnergySystemInputs(
        pv_generation_kw=[0], wind_generation_kw=[0], load_kw=[3],
        grid_price_per_kwh=[-0.12], grid_available=[True],
    )
    result = dispatch_energy_system(inputs, config)
    row = result["rows"][0]
    assert row["grid_import_kw"] == pytest.approx(3)
    assert row["energy_balance_residual_kw"] == pytest.approx(0)
    assert result["summary"]["grid_energy_cost"] == pytest.approx(-0.36)
    assert result["summary"]["estimated_energy_cost"] == pytest.approx(-0.36)


def test_seeded_multiresolution_dispatch_preserves_physical_invariants():
    import random

    rng = random.Random(20261108)
    for dt_hours in (0.25, 0.5, 1.0, 2.0):
        steps = 48
        pv = [rng.uniform(0, 8) for _ in range(steps)]
        wind = [rng.uniform(0, 4) for _ in range(steps)]
        load = [rng.uniform(2, 10) for _ in range(steps)]
        grid_available = [rng.random() > 0.12 for _ in range(steps)]
        diesel_available = [rng.random() > 0.08 for _ in range(steps)]
        config = EnergySystemConfig(
            pv_rated_kw=8, wind_rated_kw=4, grid_import_limit_kw=3,
            dt_hours=dt_hours,
            battery=BatterySpec(
                capacity_kwh=20, max_charge_kw=5, max_discharge_kw=5,
                initial_soc=0.55, min_soc=0.15, max_soc=0.9,
                charge_efficiency=0.94, discharge_efficiency=0.93,
            ),
            diesel=DieselSpec(
                rated_power_kw=5, variable_cost_per_kwh=0.8,
                min_stable_power_kw=1.0, ramp_up_kw_per_hour=2.0,
            ),
        )
        inputs = EnergySystemInputs(
            pv_generation_kw=pv, wind_generation_kw=wind, load_kw=load,
            grid_price_per_kwh=[0.2 + 0.01 * (i % 5) for i in range(steps)],
            grid_available=grid_available, diesel_available=diesel_available,
        )
        result = dispatch_energy_system(inputs, config)
        rows = result["rows"]
        assert len(rows) == steps
        for index, row in enumerate(rows):
            assert abs(row["energy_balance_residual_kw"]) <= 1e-7
            assert 0.15 - 1e-9 <= row["battery_soc"] <= 0.9 + 1e-9
            assert not (row["battery_charge_kw"] > 1e-9 and row["battery_discharge_kw"] > 1e-9)
            diesel_kw = row["diesel_generation_kw"]
            assert diesel_kw == pytest.approx(0) or diesel_kw >= 1.0 - 1e-9
            assert diesel_kw <= 5.0 + 1e-9
            if index and rows[index - 1]["diesel_generation_kw"] > 0 and diesel_kw > rows[index - 1]["diesel_generation_kw"]:
                assert diesel_kw - rows[index - 1]["diesel_generation_kw"] <= 2.0 * dt_hours + 1e-9
        assert result["summary"]["load_energy_kwh"] == pytest.approx(sum(load) * dt_hours)
        assert result["summary"]["unmet_load_kwh"] >= 0



def test_72_hour_grid_outage_exhausts_battery_and_diesel_fuel_without_violating_balance():
    config = EnergySystemConfig(
        pv_rated_kw=0, wind_rated_kw=0, grid_import_limit_kw=5,
        dt_hours=1.0,
        battery=BatterySpec(
            capacity_kwh=4, max_charge_kw=2, max_discharge_kw=3,
            initial_soc=0.9, min_soc=0.2, max_soc=0.95,
            charge_efficiency=0.95, discharge_efficiency=0.95,
        ),
        diesel=DieselSpec(
            rated_power_kw=3, variable_cost_per_kwh=0.2,
            min_stable_power_kw=1,
            fuel_curve_liters_per_hour=((0.0, 0.0), (3.0, 1.5)),
            initial_fuel_liters=3.0, fuel_tank_capacity_liters=3.0,
        ),
    )
    inputs = EnergySystemInputs(
        pv_generation_kw=[0.0] * 72,
        wind_generation_kw=[0.0] * 72,
        load_kw=[4.0] * 72,
        grid_price_per_kwh=[0.2] * 72,
        grid_available=[False] * 72,
        diesel_available=[True] * 72,
    )

    result = dispatch_energy_system(inputs, config)
    rows = result["rows"]
    summary = result["summary"]

    assert len(rows) == 72
    assert any(row["battery_discharge_kw"] > 0 for row in rows)
    assert any(row["diesel_generation_kw"] > 0 for row in rows)
    assert rows[-1]["battery_soc"] == pytest.approx(0.2)
    assert rows[-1]["diesel_fuel_remaining_liters"] == pytest.approx(0.0)
    assert rows[-1]["diesel_generation_kw"] == pytest.approx(0.0)
    assert rows[-1]["unmet_load_kw"] == pytest.approx(4.0)
    for row in rows:
        assert abs(row["energy_balance_residual_kw"]) <= 1e-7
        assert 0.2 - 1e-9 <= row["battery_soc"] <= 0.95 + 1e-9
        assert row["diesel_fuel_remaining_liters"] >= -1e-9
        assert row["diesel_fuel_used_liters"] >= 0
    remaining = [row["diesel_fuel_remaining_liters"] for row in rows]
    assert remaining == sorted(remaining, reverse=True)
    assert summary["diesel_fuel_used_liters"] == pytest.approx(3.0)
    assert summary["diesel_fuel_delivered_liters"] == pytest.approx(0.0)
    assert summary["unmet_load_kwh"] > 0
    assert summary["load_energy_kwh"] == pytest.approx(288.0)
    assert summary["load_served_kwh"] + summary["unmet_load_kwh"] == pytest.approx(288.0)


def test_diesel_power_setpoint_caps_output_and_is_audited():
    config = EnergySystemConfig(
        pv_rated_kw=0, wind_rated_kw=0, grid_import_limit_kw=0,
        diesel=DieselSpec(rated_power_kw=10, variable_cost_per_kwh=0.2),
    )
    inputs = EnergySystemInputs(
        pv_generation_kw=[0, 0], wind_generation_kw=[0, 0], load_kw=[8, 8],
        grid_price_per_kwh=[0.2, 0.2], grid_available=[False, False],
        diesel_available=[True, True], diesel_power_setpoint_kw=[5, 10],
    )
    result = dispatch_energy_system(inputs, config)
    assert [row["diesel_generation_kw"] for row in result["rows"]] == pytest.approx([5, 8])
    assert [row["diesel_power_setpoint_kw"] for row in result["rows"]] == [5, 10]
    assert result["model_scope"]["diesel_power_setpoint_input_enabled"] is True


def test_diesel_power_setpoint_respects_minimum_stable_output():
    config = EnergySystemConfig(
        pv_rated_kw=0, wind_rated_kw=0, grid_import_limit_kw=0,
        diesel=DieselSpec(rated_power_kw=10, variable_cost_per_kwh=0.2, min_stable_power_kw=4),
    )
    inputs = EnergySystemInputs(
        pv_generation_kw=[0], wind_generation_kw=[0], load_kw=[8],
        grid_price_per_kwh=[0.2], grid_available=[False], diesel_available=[True],
        diesel_power_setpoint_kw=[3],
    )
    result = dispatch_energy_system(inputs, config)
    assert result["rows"][0]["diesel_generation_kw"] == 0
    assert result["rows"][0]["unmet_load_kw"] == pytest.approx(8)


def test_diesel_power_setpoint_rejects_missing_unit_and_out_of_range_values():
    no_diesel = EnergySystemConfig(pv_rated_kw=0, wind_rated_kw=0, grid_import_limit_kw=1)
    with pytest.raises(EnergyModelError, match="requires a configured diesel"):
        dispatch_energy_system(EnergySystemInputs(
            pv_generation_kw=[0], wind_generation_kw=[0], load_kw=[1],
            grid_price_per_kwh=[0.2], grid_available=[True], diesel_power_setpoint_kw=[1],
        ), no_diesel)
    config = EnergySystemConfig(
        pv_rated_kw=0, wind_rated_kw=0, grid_import_limit_kw=1,
        diesel=DieselSpec(rated_power_kw=5, variable_cost_per_kwh=0.2),
    )
    with pytest.raises(EnergyModelError, match="exactly 2 values"):
        dispatch_energy_system(EnergySystemInputs(
            pv_generation_kw=[0, 0], wind_generation_kw=[0, 0], load_kw=[1, 1],
            grid_price_per_kwh=[0.2, 0.2], grid_available=[True, True],
            diesel_available=[True, True], diesel_power_setpoint_kw=[1],
        ), config)
    with pytest.raises(EnergyModelError, match="exceeds configured rated power"):
        dispatch_energy_system(EnergySystemInputs(
            pv_generation_kw=[0], wind_generation_kw=[0], load_kw=[1],
            grid_price_per_kwh=[0.2], grid_available=[True], diesel_available=[True],
            diesel_power_setpoint_kw=[6],
        ), config)


def test_grid_export_setpoint_caps_export_and_preserves_energy_balance():
    config = EnergySystemConfig(
        pv_rated_kw=10, wind_rated_kw=0, grid_import_limit_kw=0,
        grid_export_limit_kw=8,
    )
    inputs = EnergySystemInputs(
        pv_generation_kw=[10], wind_generation_kw=[0], load_kw=[2],
        grid_price_per_kwh=[0.2], grid_available=[True],
        grid_export_price_per_kwh=[0.05], grid_export_available=[True],
        grid_export_power_setpoint_kw=[3],
    )
    result = dispatch_energy_system(inputs, config)
    row = result["rows"][0]
    assert row["grid_export_kw"] == pytest.approx(3)
    assert row["renewable_curtailed_kw"] == pytest.approx(5)
    assert row["energy_balance_residual_kw"] == pytest.approx(0)
    assert result["summary"]["grid_export_energy_kwh"] == pytest.approx(3)


def test_grid_demand_charge_uses_peak_import_and_is_included_in_total_cost():
    config = EnergySystemConfig(
        pv_rated_kw=0, wind_rated_kw=0, grid_import_limit_kw=10,
        grid_demand_charge_per_kw=12,
    )
    inputs = EnergySystemInputs(
        pv_generation_kw=[0, 0], wind_generation_kw=[0, 0], load_kw=[2, 5],
        grid_price_per_kwh=[0.2, 0.2], grid_available=[True, True],
    )
    result = dispatch_energy_system(inputs, config)
    summary = result["summary"]
    assert summary["peak_grid_import_kw"] == pytest.approx(5)
    assert summary["grid_demand_charge"] == pytest.approx(60)
    assert summary["grid_energy_cost"] == pytest.approx(1.4)
    assert summary["estimated_energy_cost"] == pytest.approx(61.4)


def test_grid_export_setpoint_rejects_values_above_interconnection_limit():
    config = EnergySystemConfig(
        pv_rated_kw=5, wind_rated_kw=0, grid_import_limit_kw=0,
        grid_export_limit_kw=2,
    )
    inputs = EnergySystemInputs(
        pv_generation_kw=[1], wind_generation_kw=[0], load_kw=[0],
        grid_price_per_kwh=[0.2], grid_available=[True],
        grid_export_price_per_kwh=[0.05], grid_export_available=[True],
        grid_export_power_setpoint_kw=[3],
    )
    with pytest.raises(EnergyModelError, match="cannot exceed grid_export_limit_kw"):
        dispatch_energy_system(inputs, config)


def test_critical_load_is_served_before_flexible_load_and_shedding_is_separate():
    config = EnergySystemConfig(
        pv_rated_kw=0, wind_rated_kw=0, grid_import_limit_kw=3,
    )
    inputs = EnergySystemInputs(
        pv_generation_kw=[0], wind_generation_kw=[0], load_kw=[3],
        grid_price_per_kwh=[0.2], grid_available=[True],
        critical_load_kw=[2], flexible_load_kw=[2],
    )
    result = dispatch_energy_system(inputs, config)
    row = result["rows"][0]
    summary = result["summary"]
    assert row["load_kw"] == pytest.approx(5)
    assert row["load_served_kw"] == pytest.approx(3)
    assert row["critical_unmet_kw"] == pytest.approx(0)
    assert row["flexible_load_shed_kw"] == pytest.approx(1)
    assert summary["critical_unmet_load_kwh"] == pytest.approx(0)
    assert summary["flexible_load_shed_kwh"] == pytest.approx(1)
    assert summary["unmet_load_kwh"] == pytest.approx(2)
    assert result["model_scope"]["critical_load_priority_reporting_enabled"] is True


def test_critical_load_shortfall_is_reported_separately_from_flexible_shedding():
    config = EnergySystemConfig(
        pv_rated_kw=0, wind_rated_kw=0, grid_import_limit_kw=1,
    )
    inputs = EnergySystemInputs(
        pv_generation_kw=[0], wind_generation_kw=[0], load_kw=[3],
        grid_price_per_kwh=[0.2], grid_available=[True],
        critical_load_kw=[2], flexible_load_kw=[2],
    )
    result = dispatch_energy_system(inputs, config)
    summary = result["summary"]
    assert summary["critical_unmet_load_kwh"] == pytest.approx(1)
    assert summary["flexible_load_shed_kwh"] == pytest.approx(2)
    assert summary["critical_unmet_load_fraction"] == pytest.approx(0.5)


def test_critical_load_cannot_exceed_base_load():
    config = EnergySystemConfig(
        pv_rated_kw=0, wind_rated_kw=0, grid_import_limit_kw=1,
    )
    inputs = EnergySystemInputs(
        pv_generation_kw=[0], wind_generation_kw=[0], load_kw=[1],
        grid_price_per_kwh=[0.2], grid_available=[True], critical_load_kw=[2],
    )
    with pytest.raises(EnergyModelError, match="cannot exceed base load"):
        dispatch_energy_system(inputs, config)


def test_diesel_minimum_up_time_rejects_early_shutdown_in_commitment_schedule():
    config = EnergySystemConfig(
        pv_rated_kw=0, wind_rated_kw=0, grid_import_limit_kw=0,
        diesel=DieselSpec(
            rated_power_kw=5, variable_cost_per_kwh=0.3,
            min_up_time_hours=3,
        ),
    )
    inputs = EnergySystemInputs(
        pv_generation_kw=[0, 0, 0], wind_generation_kw=[0, 0, 0],
        load_kw=[1, 1, 0], grid_price_per_kwh=[0, 0, 0],
        grid_available=[False, False, False], diesel_available=[True] * 3,
        diesel_commitment_schedule=[True, True, False],
    )
    with pytest.raises(EnergyModelError, match="minimum up time violated"):
        dispatch_energy_system(inputs, config)


def test_diesel_minimum_down_time_rejects_early_restart_after_stop():
    config = EnergySystemConfig(
        pv_rated_kw=0, wind_rated_kw=0, grid_import_limit_kw=0,
        diesel=DieselSpec(
            rated_power_kw=5, variable_cost_per_kwh=0.3,
            min_down_time_hours=2,
        ),
    )
    inputs = EnergySystemInputs(
        pv_generation_kw=[0] * 4, wind_generation_kw=[0] * 4,
        load_kw=[1, 0, 0, 1], grid_price_per_kwh=[0] * 4,
        grid_available=[False] * 4, diesel_available=[True] * 4,
        diesel_commitment_schedule=[True, False, True, True],
    )
    with pytest.raises(EnergyModelError, match="minimum down time violated"):
        dispatch_energy_system(inputs, config)


def test_diesel_minimum_up_and_down_time_accepts_valid_commitment_schedule():
    config = EnergySystemConfig(
        pv_rated_kw=0, wind_rated_kw=0, grid_import_limit_kw=0,
        diesel=DieselSpec(
            rated_power_kw=5, variable_cost_per_kwh=0.3,
            min_up_time_hours=2, min_down_time_hours=2,
        ),
    )
    inputs = EnergySystemInputs(
        pv_generation_kw=[0] * 6, wind_generation_kw=[0] * 6,
        load_kw=[1, 1, 0, 0, 1, 1], grid_price_per_kwh=[0] * 6,
        grid_available=[False] * 6, diesel_available=[True] * 6,
        diesel_commitment_schedule=[True, True, False, False, True, True],
    )
    result = dispatch_energy_system(inputs, config)
    assert result["time_steps"] == 6


def test_diesel_minimum_times_respect_subhourly_dispatch_interval():
    config = EnergySystemConfig(
        pv_rated_kw=0, wind_rated_kw=0, grid_import_limit_kw=0,
        dt_hours=0.5,
        diesel=DieselSpec(
            rated_power_kw=5, variable_cost_per_kwh=0.3,
            min_up_time_hours=1.0,
        ),
    )
    inputs = EnergySystemInputs(
        pv_generation_kw=[0, 0], wind_generation_kw=[0, 0],
        load_kw=[1, 0], grid_price_per_kwh=[0, 0],
        grid_available=[False, False], diesel_available=[True, True],
        diesel_commitment_schedule=[True, False],
    )
    with pytest.raises(EnergyModelError, match="minimum up time violated"):
        dispatch_energy_system(inputs, config)


@pytest.mark.parametrize("field", ["min_up_time_hours", "min_down_time_hours"])
def test_diesel_minimum_times_reject_negative_configuration(field):
    with pytest.raises(EnergyModelError, match=field):
        DieselSpec(
            rated_power_kw=5, variable_cost_per_kwh=0.3,
            **{field: -0.5},
        )

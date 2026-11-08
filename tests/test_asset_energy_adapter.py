import pytest

from islandos_core.asset_energy_adapter import (
    AssetEnergyAdapterError,
    build_energy_system_config_from_assets,
)
from islandos_core.assets import AssetParameter, AssetRecord, OperatingConstraint
from islandos_core.energy_system import EnergySystemInputs, dispatch_energy_system


def parameter(value, unit, *, confirmed=True):
    return AssetParameter(
        value=value,
        unit=unit,
        source_type="customer_provided",
        source_reference="signed site equipment schedule",
        confirmed=confirmed,
    )


def assumption(value, unit):
    return AssetParameter(
        value=value,
        unit=unit,
        source_type="customer_provided",
        source_reference="approved operating assumption sheet",
        confirmed=True,
    )


def constraint(name, operator, value, unit):
    return OperatingConstraint(
        constraint_id=f"{name}-constraint",
        parameter=name,
        severity="hard",
        unit=unit,
        operator=operator,
        lower_bound=value if operator == "min" else None,
        upper_bound=value if operator == "max" else None,
        source_type="customer_provided",
        source_reference="approved operating limits",
        confirmed=True,
    )


def asset(kind, installed, limits, *, nameplate=None, asset_id=None):
    return AssetRecord(
        asset_id=asset_id or f"{kind}-01",
        site_id="site-01",
        asset_type=kind,
        nameplate_parameters=(
            {"rated_power_kw": parameter(nameplate, "kW")}
            if nameplate is not None else {}
        ),
        installed_parameters={
            key: parameter(value, unit)
            for key, (value, unit) in installed.items()
        },
        observed_parameters={},
        constraints=tuple(
            constraint(name, operator, value, unit)
            for name, (operator, value, unit) in limits.items()
        ),
    )


def test_builds_pv_wind_and_grid_config_from_confirmed_assets():
    assets = [
        asset("pv", {"configured_power_kw": (80, "kW")},
              {"max_power_kw": ("max", 75, "kW")}, nameplate=100),
        asset("wind", {"configured_power_kw": (40, "kW")},
              {"max_power_kw": ("max", 35, "kW")}, nameplate=50),
        asset("grid_connection", {"configured_power_kw": (60, "kW")},
              {"import_limit_kw": ("max", 55, "kW")}),
    ]
    config = build_energy_system_config_from_assets(assets, dt_hours=0.5)
    assert config.pv_rated_kw == 75
    assert config.wind_rated_kw == 35
    assert config.grid_import_limit_kw == 55
    assert config.dt_hours == 0.5
    assert config.battery is None
    assert config.diesel is None


def test_battery_requires_explicit_efficiency_and_initial_soc_assumptions():
    battery = asset(
        "battery",
        {
            "configured_power_kw": (100, "kW"),
            "usable_energy_capacity_kwh": (240, "kWh"),
        },
        {
            "max_charge_kw": ("max", 80, "kW"),
            "max_discharge_kw": ("max", 90, "kW"),
            "soc_min_pct": ("min", 10, "%"),
            "soc_max_pct": ("max", 90, "%"),
        },
    )
    with pytest.raises(AssetEnergyAdapterError, match="explicit battery operating assumptions"):
        build_energy_system_config_from_assets([battery])

    config = build_energy_system_config_from_assets(
        [battery],
        operating_assumptions={
            "battery_initial_soc": assumption(0.5, "fraction"),
            "battery_charge_efficiency": assumption(0.94, "fraction"),
            "battery_discharge_efficiency": assumption(0.93, "fraction"),
        },
    )
    assert config.battery.capacity_kwh == 240
    assert config.battery.min_soc == 0.1
    assert config.battery.max_soc == 0.9
    assert config.battery.initial_soc == 0.5
    assert config.battery.charge_efficiency == 0.94


def test_diesel_requires_explicit_cost_and_blocks_unmodeled_minimum_loading():
    generator = asset(
        "diesel_generator",
        {"configured_power_kw": (30, "kW")},
        {
            "max_power_kw": ("max", 28, "kW"),
            "min_stable_power_kw": ("min", 5, "kW"),
        },
    )
    with pytest.raises(AssetEnergyAdapterError, match="minimum stable loading is not modeled"):
        build_energy_system_config_from_assets(
            [generator], operating_assumptions={"diesel_variable_cost_per_kwh": assumption(1.2, "USD/kWh")}
        )


def test_diesel_zero_minimum_stable_loading_still_requires_explicit_cost():
    generator = asset(
        "diesel_generator",
        {"configured_power_kw": (30, "kW")},
        {
            "max_power_kw": ("max", 28, "kW"),
            "min_stable_power_kw": ("min", 0, "kW"),
        },
    )
    with pytest.raises(AssetEnergyAdapterError, match="explicit diesel_variable_cost"):
        build_energy_system_config_from_assets([generator])
    config = build_energy_system_config_from_assets(
        [generator], operating_assumptions={"diesel_variable_cost_per_kwh": assumption(1.25, "USD/kWh")}
    )
    assert config.diesel.rated_power_kw == 28
    assert config.diesel.variable_cost_per_kwh == 1.25


def test_unconfirmed_or_incomplete_asset_blocks_conversion():
    incomplete = AssetRecord(
        asset_id="pv-01",
        site_id="site-01",
        asset_type="pv",
        nameplate_parameters={},
        installed_parameters={
            "configured_power_kw": parameter(20, "kW", confirmed=False)
        },
        observed_parameters={},
        constraints=(),
    )
    with pytest.raises(AssetEnergyAdapterError, match="not ready for offline screening"):
        build_energy_system_config_from_assets([incomplete])


def test_rejects_mixed_sites_duplicate_types_and_unsupported_assets():
    pv = asset("pv", {"configured_power_kw": (20, "kW")},
               {"max_power_kw": ("max", 20, "kW")})
    second_pv = asset("pv", {"configured_power_kw": (10, "kW")},
                      {"max_power_kw": ("max", 10, "kW")}, asset_id="pv-02")
    with pytest.raises(AssetEnergyAdapterError, match="multiple assets"):
        build_energy_system_config_from_assets([pv, second_pv])

    other_site = AssetRecord(
        asset_id="wind-01", site_id="site-02", asset_type="wind",
        nameplate_parameters={}, installed_parameters={}, observed_parameters={},
        constraints=(),
    )
    with pytest.raises(AssetEnergyAdapterError, match="same site"):
        build_energy_system_config_from_assets([pv, other_site])

    flexible = AssetRecord(
        asset_id="load-01", site_id="site-01", asset_type="flexible_load",
        nameplate_parameters={}, installed_parameters={}, observed_parameters={},
        constraints=(),
    )
    with pytest.raises(AssetEnergyAdapterError, match="not yet supported"):
        build_energy_system_config_from_assets([flexible])


def test_rejects_wrong_installed_units_instead_of_converting_silently():
    pv = asset("pv", {"configured_power_kw": (20, "MW")},
               {"max_power_kw": ("max", 20, "kW")})
    with pytest.raises(AssetEnergyAdapterError, match="must use kW"):
        build_energy_system_config_from_assets([pv])



def test_operating_assumptions_must_carry_confirmed_provenance():
    pv = asset("pv", {"configured_power_kw": (20, "kW")},
               {"max_power_kw": ("max", 20, "kW")})
    with pytest.raises(AssetEnergyAdapterError, match="provenance-bearing"):
        build_energy_system_config_from_assets(
            [pv], operating_assumptions={"unrelated": 0.5}
        )

    battery = asset(
        "battery",
        {
            "configured_power_kw": (10, "kW"),
            "usable_energy_capacity_kwh": (20, "kWh"),
        },
        {
            "max_charge_kw": ("max", 10, "kW"),
            "max_discharge_kw": ("max", 10, "kW"),
            "soc_min_pct": ("min", 10, "%"),
            "soc_max_pct": ("max", 90, "%"),
        },
    )
    assumptions = {
        "battery_initial_soc": assumption(0.5, "fraction"),
        "battery_charge_efficiency": assumption(0.95, "fraction"),
        "battery_discharge_efficiency": AssetParameter(
            value=0.95, unit="fraction", source_type="customer_provided",
            source_reference="unapproved estimate", confirmed=False,
        ),
    }
    with pytest.raises(AssetEnergyAdapterError, match="not confirmed"):
        build_energy_system_config_from_assets([battery], operating_assumptions=assumptions)



def test_asset_registry_output_runs_through_offline_energy_dispatch():
    assets = [
        asset("pv", {"configured_power_kw": (10, "kW")},
              {"max_power_kw": ("max", 10, "kW")}),
        asset("grid_connection", {"configured_power_kw": (5, "kW")},
              {"import_limit_kw": ("max", 5, "kW")}),
    ]
    config = build_energy_system_config_from_assets(assets)
    result = dispatch_energy_system(
        EnergySystemInputs(
            pv_generation_kw=[5],
            wind_generation_kw=[0],
            load_kw=[8],
            grid_price_per_kwh=[0.3],
            grid_available=[True],
        ),
        config,
    )
    row = result["rows"][0]
    assert row["pv_generation_kw"] == 5
    assert row["grid_import_kw"] == 3
    assert row["unmet_load_kw"] == 0
    assert abs(row["energy_balance_residual_kw"]) < 1e-8

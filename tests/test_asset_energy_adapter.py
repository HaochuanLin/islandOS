import pytest

from islandos_core.asset_energy_adapter import (
    AssetEnergyAdapterError,
    build_energy_system_config_from_assets,
)
from islandos_core.assets import AssetParameter, AssetRecord, AssetValidationError, OperatingConstraint
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


def test_diesel_maps_confirmed_minimum_stable_loading_and_requires_explicit_cost():
    generator = asset(
        "diesel_generator",
        {"configured_power_kw": (30, "kW")},
        {
            "max_power_kw": ("max", 28, "kW"),
            "min_stable_power_kw": ("min", 5, "kW"),
        },
    )
    config_with_minimum = build_energy_system_config_from_assets(
        [generator],
        operating_assumptions={"diesel_variable_cost_per_kwh": assumption(1.2, "USD/kWh")},
    )
    assert config_with_minimum.diesel.min_stable_power_kw == 5


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
    assert config.diesel.min_stable_power_kw == 0


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
    # PV capacities are additive only after each PV asset passes validation.
    assert build_energy_system_config_from_assets([pv, second_pv]).pv_rated_kw == 30

    battery_a = asset(
        "battery",
        {"configured_power_kw": (10, "kW"), "usable_energy_capacity_kwh": (20, "kWh")},
        {
            "max_charge_kw": ("max", 10, "kW"),
            "max_discharge_kw": ("max", 10, "kW"),
            "soc_min_pct": ("min", 10, "%"),
            "soc_max_pct": ("max", 90, "%"),
        },
        asset_id="battery-a",
    )
    battery_b = asset(
        "battery",
        {"configured_power_kw": (10, "kW"), "usable_energy_capacity_kwh": (20, "kWh")},
        {
            "max_charge_kw": ("max", 10, "kW"),
            "max_discharge_kw": ("max", 10, "kW"),
            "soc_min_pct": ("min", 10, "%"),
            "soc_max_pct": ("max", 90, "%"),
        },
        asset_id="battery-b",
    )
    with pytest.raises(AssetEnergyAdapterError, match="per-device state"):
        build_energy_system_config_from_assets([battery_a, battery_b])

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
    with pytest.raises(AssetValidationError, match="installed_parameters.configured_power_kw must use kW"):
        asset("pv", {"configured_power_kw": (20, "MW")},
              {"max_power_kw": ("max", 20, "kW")})



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



def test_aggregates_multiple_pv_wind_and_grid_assets_after_individual_validation():
    assets = [
        asset("pv", {"configured_power_kw": (12, "kW")},
              {"max_power_kw": ("max", 10, "kW")}, asset_id="pv-a"),
        asset("pv", {"configured_power_kw": (8, "kW")},
              {"max_power_kw": ("max", 7, "kW")}, asset_id="pv-b"),
        asset("wind", {"configured_power_kw": (30, "kW")},
              {"max_power_kw": ("max", 25, "kW")}, asset_id="wind-a"),
        asset("wind", {"configured_power_kw": (20, "kW")},
              {"max_power_kw": ("max", 18, "kW")}, asset_id="wind-b"),
        asset("grid_connection", {"configured_power_kw": (50, "kW")},
              {"import_limit_kw": ("max", 45, "kW")}, asset_id="grid-a"),
        asset("grid_connection", {"configured_power_kw": (40, "kW")},
              {"import_limit_kw": ("max", 35, "kW")}, asset_id="grid-b"),
    ]
    config = build_energy_system_config_from_assets(assets)
    assert config.pv_rated_kw == 17
    assert config.wind_rated_kw == 43
    assert config.grid_import_limit_kw == 80


def test_duplicate_asset_ids_are_rejected_before_aggregation():
    pv_a = asset("pv", {"configured_power_kw": (12, "kW")},
                 {"max_power_kw": ("max", 10, "kW")}, asset_id="same-id")
    pv_b = asset("pv", {"configured_power_kw": (8, "kW")},
                 {"max_power_kw": ("max", 7, "kW")}, asset_id="same-id")
    with pytest.raises(AssetEnergyAdapterError, match="asset_id values must be unique"):
        build_energy_system_config_from_assets([pv_a, pv_b])


def test_unavailable_member_blocks_aggregate_instead_of_being_silently_ignored():
    available = asset("pv", {"configured_power_kw": (12, "kW")},
                      {"max_power_kw": ("max", 10, "kW")}, asset_id="pv-a")
    unavailable = AssetRecord(
        asset_id="pv-b", site_id="site-01", asset_type="pv",
        nameplate_parameters={}, installed_parameters={}, observed_parameters={},
        constraints=(), available=False,
    )
    with pytest.raises(AssetEnergyAdapterError, match="not ready for offline screening"):
        build_energy_system_config_from_assets([available, unavailable])


def test_grid_export_capacity_is_mapped_only_from_confirmed_hard_asset_limit():
    connection = asset(
        "grid_connection",
        {"configured_power_kw": (50, "kW")},
        {
            "import_limit_kw": ("max", 45, "kW"),
            "export_limit_kw": ("max", 30, "kW"),
        },
    )
    config = build_energy_system_config_from_assets([connection])
    assert config.grid_import_limit_kw == 45
    assert config.grid_export_limit_kw == 30

    no_export_record = asset(
        "grid_connection",
        {"configured_power_kw": (50, "kW")},
        {"import_limit_kw": ("max", 45, "kW")},
    )
    no_export_config = build_energy_system_config_from_assets([no_export_record])
    assert no_export_config.grid_export_limit_kw == 0


def test_unconfirmed_or_duplicate_grid_export_limit_blocks_asset_conversion():
    connection = AssetRecord(
        asset_id="grid-01",
        site_id="site-01",
        asset_type="grid_connection",
        nameplate_parameters={},
        installed_parameters={"configured_power_kw": parameter(50, "kW")},
        observed_parameters={},
        constraints=(
            constraint("import_limit_kw", "max", 45, "kW"),
            OperatingConstraint(
                constraint_id="export-unconfirmed",
                parameter="export_limit_kw",
                severity="hard",
                unit="kW",
                operator="max",
                upper_bound=30,
                source_type="customer_provided",
                source_reference="draft interconnection application",
                confirmed=False,
            ),
        ),
    )
    with pytest.raises(AssetEnergyAdapterError, match="confirmed hard max"):
        build_energy_system_config_from_assets([connection])


def test_multiple_export_capable_grid_connections_are_not_summed_without_shared_poi_model():
    first = asset(
        "grid_connection",
        {"configured_power_kw": (50, "kW")},
        {
            "import_limit_kw": ("max", 45, "kW"),
            "export_limit_kw": ("max", 20, "kW"),
        },
        asset_id="grid-a",
    )
    second = asset(
        "grid_connection",
        {"configured_power_kw": (40, "kW")},
        {
            "import_limit_kw": ("max", 35, "kW"),
            "export_limit_kw": ("max", 15, "kW"),
        },
        asset_id="grid-b",
    )
    with pytest.raises(AssetEnergyAdapterError, match="shared point-of-connection"):
        build_energy_system_config_from_assets([first, second])


def test_confirmed_asset_export_limit_flows_into_energy_dispatch():
    pv = asset(
        "pv",
        {"configured_power_kw": (10, "kW")},
        {"max_power_kw": ("max", 10, "kW")},
        asset_id="pv-01",
    )
    connection = asset(
        "grid_connection",
        {"configured_power_kw": (5, "kW")},
        {
            "import_limit_kw": ("max", 5, "kW"),
            "export_limit_kw": ("max", 2, "kW"),
        },
        asset_id="grid-01",
    )
    config = build_energy_system_config_from_assets([pv, connection])
    result = dispatch_energy_system(
        EnergySystemInputs(
            pv_generation_kw=[5],
            wind_generation_kw=[0],
            load_kw=[2],
            grid_price_per_kwh=[0.3],
            grid_available=[True],
            grid_export_price_per_kwh=[0.1],
            grid_export_available=[True],
        ),
        config,
    )
    row = result["rows"][0]
    assert row["grid_export_kw"] == 2
    assert row["renewable_curtailed_kw"] == 1
    assert row["grid_export_revenue"] == pytest.approx(0.2)
    assert row["energy_balance_residual_kw"] == pytest.approx(0)



def test_diesel_fuel_assumptions_are_mapped_only_as_confirmed_provenance():
    generator = asset(
        "diesel_generator",
        {"configured_power_kw": (30, "kW")},
        {
            "max_power_kw": ("max", 30, "kW"),
            "min_stable_power_kw": ("min", 5, "kW"),
        },
    )
    base = {"diesel_variable_cost_per_kwh": assumption(1.2, "USD/kWh")}
    with pytest.raises(AssetEnergyAdapterError, match="must be supplied together"):
        build_energy_system_config_from_assets(
            [generator],
            operating_assumptions={
                **base,
                "diesel_fuel_consumption_l_per_kwh": assumption(0.25, "L/kWh"),
            },
        )
    with pytest.raises(AssetEnergyAdapterError, match="must be supplied together"):
        build_energy_system_config_from_assets(
            [generator],
            operating_assumptions={
                **base,
                "diesel_initial_fuel_liters": assumption(100, "L"),
            },
        )
    config = build_energy_system_config_from_assets(
        [generator],
        operating_assumptions={
            **base,
            "diesel_fuel_consumption_l_per_kwh": assumption(0.25, "L/kWh"),
            "diesel_initial_fuel_liters": assumption(100, "L"),
        },
    )
    assert config.diesel.fuel_consumption_l_per_kwh == pytest.approx(0.25)
    assert config.diesel.initial_fuel_liters == pytest.approx(100)

def test_diesel_tank_capacity_requires_and_maps_confirmed_fuel_assumption():
    generator = asset(
        "diesel_generator",
        {"configured_power_kw": (30, "kW")},
        {
            "max_power_kw": ("max", 30, "kW"),
            "min_stable_power_kw": ("min", 5, "kW"),
        },
    )
    base = {"diesel_variable_cost_per_kwh": assumption(1.2, "USD/kWh")}
    with pytest.raises(AssetEnergyAdapterError, match="requires a fuel model and initial inventory"):
        build_energy_system_config_from_assets(
            [generator],
            operating_assumptions={
                **base,
                "diesel_fuel_tank_capacity_liters": assumption(200, "L"),
            },
        )
    config = build_energy_system_config_from_assets(
        [generator],
        operating_assumptions={
            **base,
            "diesel_fuel_consumption_l_per_kwh": assumption(0.25, "L/kWh"),
            "diesel_initial_fuel_liters": assumption(100, "L"),
            "diesel_fuel_tank_capacity_liters": assumption(200, "L"),
        },
    )
    assert config.diesel.fuel_tank_capacity_liters == pytest.approx(200)


def test_diesel_tank_capacity_below_initial_inventory_fails_adapter_closed():
    generator = asset(
        "diesel_generator",
        {"configured_power_kw": (30, "kW")},
        {
            "max_power_kw": ("max", 30, "kW"),
            "min_stable_power_kw": ("min", 5, "kW"),
        },
    )
    with pytest.raises(AssetEnergyAdapterError, match="cannot exceed fuel_tank_capacity_liters"):
        build_energy_system_config_from_assets(
            [generator],
            operating_assumptions={
                "diesel_variable_cost_per_kwh": assumption(1.2, "USD/kWh"),
                "diesel_fuel_consumption_l_per_kwh": assumption(0.25, "L/kWh"),
                "diesel_initial_fuel_liters": assumption(100, "L"),
                "diesel_fuel_tank_capacity_liters": assumption(80, "L"),
            },
        )

def test_optional_battery_throughput_cost_requires_provenance_and_maps():
    battery = asset(
        "battery",
        {
            "configured_power_kw": (20, "kW"),
            "usable_energy_capacity_kwh": (40, "kWh"),
        },
        {
            "max_charge_kw": ("max", 20, "kW"),
            "max_discharge_kw": ("max", 20, "kW"),
            "soc_min_pct": ("min", 10, "%"),
            "soc_max_pct": ("max", 90, "%"),
        },
    )
    base = {
        "battery_initial_soc": assumption(0.5, "fraction"),
        "battery_charge_efficiency": assumption(0.95, "fraction"),
        "battery_discharge_efficiency": assumption(0.95, "fraction"),
    }
    config = build_energy_system_config_from_assets(
        [battery],
        operating_assumptions={
            **base,
            "battery_throughput_cost_per_kwh": assumption(0.08, "USD/kWh"),
        },
    )
    assert config.battery.throughput_cost_per_kwh == pytest.approx(0.08)
    default_config = build_energy_system_config_from_assets(
        [battery], operating_assumptions=base,
    )
    assert default_config.battery.throughput_cost_per_kwh == 0

def test_provenance_backed_nonlinear_diesel_fuel_curve_maps_to_engine():
    generator = asset(
        "diesel_generator",
        {"configured_power_kw": (30, "kW")},
        {
            "max_power_kw": ("max", 30, "kW"),
            "min_stable_power_kw": ("min", 5, "kW"),
        },
    )
    assumptions = {
        "diesel_variable_cost_per_kwh": assumption(1.2, "USD/kWh"),
        "diesel_initial_fuel_liters": assumption(120, "L"),
        "diesel_fuel_price_per_liter": assumption(1.45, "CNY/L"),
        "diesel_fuel_curve_0_power_kw": assumption(0, "kW"),
        "diesel_fuel_curve_0_fuel_l_per_hour": assumption(0, "L/h"),
        "diesel_fuel_curve_1_power_kw": assumption(15, "kW"),
        "diesel_fuel_curve_1_fuel_l_per_hour": assumption(4.2, "L/h"),
        "diesel_fuel_curve_2_power_kw": assumption(30, "kW"),
        "diesel_fuel_curve_2_fuel_l_per_hour": assumption(9.0, "L/h"),
    }
    config = build_energy_system_config_from_assets(
        [generator], operating_assumptions=assumptions,
    )
    assert config.diesel.fuel_curve_liters_per_hour == (
        (0.0, 0.0), (15.0, 4.2), (30.0, 9.0),
    )
    assert config.diesel.initial_fuel_liters == pytest.approx(120)
    assert config.diesel.fuel_price_per_liter == pytest.approx(1.45)


def test_nonlinear_diesel_curve_rejects_unconfirmed_or_incomplete_point():
    generator = asset(
        "diesel_generator",
        {"configured_power_kw": (30, "kW")},
        {
            "max_power_kw": ("max", 30, "kW"),
            "min_stable_power_kw": ("min", 5, "kW"),
        },
    )
    assumptions = {
        "diesel_variable_cost_per_kwh": assumption(1.2, "USD/kWh"),
        "diesel_initial_fuel_liters": assumption(120, "L"),
        "diesel_fuel_curve_0_power_kw": assumption(0, "kW"),
        "diesel_fuel_curve_0_fuel_l_per_hour": assumption(0, "L/h"),
        "diesel_fuel_curve_1_power_kw": assumption(15, "kW"),
        "diesel_fuel_curve_2_power_kw": assumption(30, "kW"),
        "diesel_fuel_curve_2_fuel_l_per_hour": assumption(9.0, "L/h"),
    }
    with pytest.raises(AssetEnergyAdapterError, match="requires both power and fuel-rate"):
        build_energy_system_config_from_assets(
            [generator], operating_assumptions=assumptions,
        )


def test_nonlinear_diesel_curve_cannot_be_mixed_with_legacy_constant_rate():
    generator = asset(
        "diesel_generator",
        {"configured_power_kw": (30, "kW")},
        {
            "max_power_kw": ("max", 30, "kW"),
            "min_stable_power_kw": ("min", 5, "kW"),
        },
    )
    assumptions = {
        "diesel_variable_cost_per_kwh": assumption(1.2, "USD/kWh"),
        "diesel_initial_fuel_liters": assumption(120, "L"),
        "diesel_fuel_consumption_l_per_kwh": assumption(0.25, "L/kWh"),
        "diesel_fuel_curve_0_power_kw": assumption(0, "kW"),
        "diesel_fuel_curve_0_fuel_l_per_hour": assumption(0, "L/h"),
        "diesel_fuel_curve_1_power_kw": assumption(30, "kW"),
        "diesel_fuel_curve_1_fuel_l_per_hour": assumption(9.0, "L/h"),
    }
    with pytest.raises(AssetEnergyAdapterError, match="cannot both be supplied"):
        build_energy_system_config_from_assets(
            [generator], operating_assumptions=assumptions,
        )

def test_diesel_fuel_curve_is_interpolated_at_derated_installed_rating():
    generator = asset(
        "diesel_generator",
        {"configured_power_kw": (25, "kW")},
        {
            "max_power_kw": ("max", 25, "kW"),
            "min_stable_power_kw": ("min", 5, "kW"),
        },
    )
    assumptions = {
        "diesel_variable_cost_per_kwh": assumption(1.2, "USD/kWh"),
        "diesel_initial_fuel_liters": assumption(120, "L"),
        "diesel_fuel_curve_0_power_kw": assumption(0, "kW"),
        "diesel_fuel_curve_0_fuel_l_per_hour": assumption(0, "L/h"),
        "diesel_fuel_curve_1_power_kw": assumption(15, "kW"),
        "diesel_fuel_curve_1_fuel_l_per_hour": assumption(4.2, "L/h"),
        "diesel_fuel_curve_2_power_kw": assumption(30, "kW"),
        "diesel_fuel_curve_2_fuel_l_per_hour": assumption(9.0, "L/h"),
    }
    config = build_energy_system_config_from_assets(
        [generator], operating_assumptions=assumptions,
    )
    assert config.diesel.rated_power_kw == pytest.approx(25)
    assert config.diesel.fuel_curve_liters_per_hour[-1] == pytest.approx((25, 7.4))


def test_diesel_fuel_curve_must_cover_installed_rated_power():
    generator = asset(
        "diesel_generator",
        {"configured_power_kw": (30, "kW")},
        {
            "max_power_kw": ("max", 30, "kW"),
            "min_stable_power_kw": ("min", 5, "kW"),
        },
    )
    assumptions = {
        "diesel_variable_cost_per_kwh": assumption(1.2, "USD/kWh"),
        "diesel_initial_fuel_liters": assumption(120, "L"),
        "diesel_fuel_curve_0_power_kw": assumption(0, "kW"),
        "diesel_fuel_curve_0_fuel_l_per_hour": assumption(0, "L/h"),
        "diesel_fuel_curve_1_power_kw": assumption(15, "kW"),
        "diesel_fuel_curve_1_fuel_l_per_hour": assumption(4.2, "L/h"),
        "diesel_fuel_curve_2_power_kw": assumption(25, "kW"),
        "diesel_fuel_curve_2_fuel_l_per_hour": assumption(7.4, "L/h"),
    }
    with pytest.raises(AssetEnergyAdapterError, match="does not cover the installed rated power"):
        build_energy_system_config_from_assets(
            [generator], operating_assumptions=assumptions,
        )

def test_confirmed_battery_cycle_life_and_initial_soh_map_to_engine():
    battery = asset(
        "battery",
        {
            "configured_power_kw": (20, "kW"),
            "usable_energy_capacity_kwh": (40, "kWh"),
        },
        {
            "max_charge_kw": ("max", 20, "kW"),
            "max_discharge_kw": ("max", 20, "kW"),
            "soc_min_pct": ("min", 10, "%"),
            "soc_max_pct": ("max", 90, "%"),
        },
    )
    assumptions = {
        "battery_initial_soc": assumption(0.5, "fraction"),
        "battery_charge_efficiency": assumption(0.95, "fraction"),
        "battery_discharge_efficiency": assumption(0.95, "fraction"),
        "battery_initial_state_of_health": assumption(0.96, "fraction"),
        "battery_cycle_life_efc": assumption(6000, "EFC"),
        "battery_end_of_life_capacity_fraction": assumption(0.8, "fraction"),
    }
    config = build_energy_system_config_from_assets(
        [battery], operating_assumptions=assumptions,
    )
    assert config.battery.initial_state_of_health == pytest.approx(0.96)
    assert config.battery.cycle_life_efc == pytest.approx(6000)
    assert config.battery.end_of_life_capacity_fraction == pytest.approx(0.8)


def test_battery_end_of_life_fraction_without_cycle_life_fails_closed():
    battery = asset(
        "battery",
        {
            "configured_power_kw": (20, "kW"),
            "usable_energy_capacity_kwh": (40, "kWh"),
        },
        {
            "max_charge_kw": ("max", 20, "kW"),
            "max_discharge_kw": ("max", 20, "kW"),
            "soc_min_pct": ("min", 10, "%"),
            "soc_max_pct": ("max", 90, "%"),
        },
    )
    assumptions = {
        "battery_initial_soc": assumption(0.5, "fraction"),
        "battery_charge_efficiency": assumption(0.95, "fraction"),
        "battery_discharge_efficiency": assumption(0.95, "fraction"),
        "battery_end_of_life_capacity_fraction": assumption(0.8, "fraction"),
    }
    with pytest.raises(AssetEnergyAdapterError, match="requires cycle_life_efc"):
        build_energy_system_config_from_assets(
            [battery], operating_assumptions=assumptions,
        )



def test_unsupported_confirmed_hard_diesel_ramp_constraint_fails_closed():
    generator = asset(
        "diesel_generator",
        {"configured_power_kw": (30, "kW")},
        {
            "max_power_kw": ("max", 30, "kW"),
            "min_stable_power_kw": ("min", 5, "kW"),
        },
    )
    from dataclasses import replace
    from islandos_core.assets import OperatingConstraint

    generator = replace(
        generator,
        constraints=generator.constraints + (
            OperatingConstraint(
                constraint_id="diesel-ramp-down",
                parameter="ramp_limit_kw_per_min",
                severity="hard",
                unit="kW/min",
                operator="max",
                upper_bound=2.0,
                source_reference="vendor manual section 7",
                confirmed=True,
            ),
        ),
    )
    with pytest.raises(AssetEnergyAdapterError, match="hard constraint is not supported"):
        build_energy_system_config_from_assets(
            [generator],
            operating_assumptions={
                "diesel_variable_cost_per_kwh": assumption(0.25, "USD/kWh"),
            },
        )


def test_unconfirmed_additional_hard_constraint_fails_closed():
    pv = asset(
        "pv",
        {"configured_power_kw": (20, "kW")},
        {"max_power_kw": ("max", 20, "kW")},
    )
    from dataclasses import replace
    from islandos_core.assets import OperatingConstraint

    pv = replace(
        pv,
        constraints=pv.constraints + (
            OperatingConstraint(
                constraint_id="pv-export-limit",
                parameter="export_limit_kw",
                severity="hard",
                unit="kW",
                operator="max",
                upper_bound=5.0,
                source_reference="unconfirmed interconnection note",
                confirmed=False,
            ),
        ),
    )
    with pytest.raises(AssetEnergyAdapterError, match="hard constraint is not confirmed"):
        build_energy_system_config_from_assets([pv])

import pytest

from islandos_core.assets import (
    AssetParameter,
    AssetRecord,
    AssetValidationError,
    OperatingConstraint,
    evaluate_asset_readiness,
)


def parameter(value, unit, source="vendor_specification", confirmed=True):
    return AssetParameter(value, unit, source, "datasheet-or-site-record", confirmed)


def constraint(name, operator, value, unit, confirmed=True, parameter_name=None):
    return OperatingConstraint(
        constraint_id=name,
        parameter=parameter_name or name,
        severity="hard",
        unit=unit,
        operator=operator,
        lower_bound=value if operator == "min" else None,
        upper_bound=value if operator == "max" else None,
        source_type="customer_provided",
        source_reference="commissioning record",
        confirmed=confirmed,
    )


def battery_asset(constraints=None):
    return AssetRecord(
        asset_id="battery-01",
        site_id="site-01",
        asset_type="battery",
        nameplate_parameters={"energy_capacity_kwh": parameter(600, "kWh")},
        installed_parameters={
            "configured_power_kw": parameter(200, "kW", "customer_provided"),
            "usable_energy_capacity_kwh": parameter(500, "kWh", "customer_provided"),
        },
        observed_parameters={},
        constraints=tuple([
            constraint("max_charge_kw", "max", 200, "kW"),
            constraint("max_discharge_kw", "max", 200, "kW"),
            constraint("soc_min_pct", "min", 15, "%"),
            constraint("soc_max_pct", "max", 90, "%"),
        ] if constraints is None else constraints),
    )


def test_asset_keeps_nameplate_and_installed_values_separate():
    asset = battery_asset()
    assert asset.nameplate_parameters["energy_capacity_kwh"].value == 600
    assert asset.installed_parameters["usable_energy_capacity_kwh"].value == 500
    assert evaluate_asset_readiness(asset)["can_screen"] is True


def test_unconfirmed_hard_constraint_blocks_asset_readiness():
    asset = battery_asset([
        constraint("max_charge_kw", "max", 200, "kW", confirmed=False),
        constraint("max_discharge_kw", "max", 200, "kW"),
        constraint("soc_min_pct", "min", 15, "%"),
        constraint("soc_max_pct", "max", 90, "%"),
    ])
    report = evaluate_asset_readiness(asset)
    assert report["can_screen"] is False
    assert "confirmed_hard_constraint_required:max_charge_kw:max" in report["blockers"]


def test_required_hard_constraint_must_use_correct_operator():
    asset = battery_asset([
        constraint("max_charge_kw", "min", 200, "kW"),
        constraint("max_discharge_kw", "max", 200, "kW"),
        constraint("soc_min_pct", "min", 15, "%"),
        constraint("soc_max_pct", "max", 90, "%"),
    ])
    report = evaluate_asset_readiness(asset)
    assert report["can_screen"] is False
    assert "confirmed_hard_constraint_required:max_charge_kw:max" in report["blockers"]


def test_missing_battery_constraints_block_readiness():
    report = evaluate_asset_readiness(battery_asset([]))
    assert report["can_screen"] is False
    assert len(report["blockers"]) == 4


def test_hard_power_limit_cannot_exceed_installed_configuration():
    asset = battery_asset([
        constraint("max_charge_kw", "max", 300, "kW"),
        constraint("max_discharge_kw", "max", 200, "kW"),
        constraint("soc_min_pct", "min", 15, "%"),
        constraint("soc_max_pct", "max", 90, "%"),
    ])
    assert "constraint_exceeds_installed_power:max_charge_kw" in evaluate_asset_readiness(asset)["blockers"]


def test_installed_configuration_cannot_exceed_vendor_nameplate():
    asset = AssetRecord(
        asset_id="pv-01", site_id="site-01", asset_type="pv",
        nameplate_parameters={"rated_power_kw": parameter(100, "kW")},
        installed_parameters={"configured_power_kw": parameter(120, "kW", "customer_provided")},
        observed_parameters={},
        constraints=(constraint("max_power_kw", "max", 100, "kW"),),
    )
    assert "installed_power_exceeds_nameplate" in evaluate_asset_readiness(asset)["blockers"]


def test_inconsistent_soc_bounds_block_readiness():
    asset = battery_asset([
        constraint("max_charge_kw", "max", 200, "kW"),
        constraint("max_discharge_kw", "max", 200, "kW"),
        constraint("soc_min_pct", "min", 95, "%"),
        constraint("soc_max_pct", "max", 90, "%"),
    ])
    assert "battery_soc_bounds_inconsistent" in evaluate_asset_readiness(asset)["blockers"]


def test_constraint_rejects_bad_units_and_invalid_ranges():
    with pytest.raises(AssetValidationError, match="unit must be kW"):
        OperatingConstraint(
            constraint_id="c1", parameter="max_power_kw", severity="hard",
            unit="MW", operator="max", upper_bound=1,
            source_type="customer_provided", source_reference="site spec",
        )
    with pytest.raises(AssetValidationError, match="lower_bound cannot exceed"):
        OperatingConstraint(
            constraint_id="c2", parameter="soc_range", severity="hard",
            unit="%", operator="range", lower_bound=90, upper_bound=10,
            source_type="customer_provided", source_reference="site spec",
        )


def test_asset_mapping_round_trip():
    asset = battery_asset()
    restored = AssetRecord.from_mapping(asset.to_mapping())
    assert restored == asset


def test_unavailable_asset_is_not_screened():
    asset = AssetRecord(
        asset_id="pv-01", site_id="site-01", asset_type="pv",
        nameplate_parameters={}, installed_parameters={}, observed_parameters={},
        constraints=(), available=False,
    )
    report = evaluate_asset_readiness(asset)
    assert report["status"] == "unavailable"
    assert report["can_screen"] is False


def test_duplicate_confirmed_hard_constraints_block_asset_readiness():
    asset = battery_asset([
        constraint("max_charge_kw_a", "max", 180, "kW", parameter_name="max_charge_kw"),
        constraint("max_charge_kw_b", "max", 200, "kW", parameter_name="max_charge_kw"),
        constraint("max_discharge_kw", "max", 200, "kW"),
        constraint("soc_min_pct", "min", 15, "%"),
        constraint("soc_max_pct", "max", 90, "%"),
    ])
    report = evaluate_asset_readiness(asset)
    assert report["can_screen"] is False
    assert "ambiguous_confirmed_hard_constraints:max_charge_kw:max" in report["blockers"]


def test_required_installed_parameter_must_have_expected_unit_and_positive_value():
    with pytest.raises(AssetValidationError, match="installed_parameters.configured_power_kw must use kW"):
        AssetRecord(
            asset_id="pv-bad-unit", site_id="site-01", asset_type="pv",
            nameplate_parameters={},
            installed_parameters={"configured_power_kw": parameter(20, "MW")},
            observed_parameters={},
            constraints=(constraint("max_power_kw", "max", 20, "kW"),),
        )

    with pytest.raises(AssetValidationError, match="installed_parameters.configured_power_kw must be positive"):
        AssetRecord(
            asset_id="pv-zero", site_id="site-01", asset_type="pv",
            nameplate_parameters={},
            installed_parameters={"configured_power_kw": parameter(0, "kW")},
            observed_parameters={},
            constraints=(constraint("max_power_kw", "max", 0, "kW"),),
        )


def test_soc_constraints_outside_physical_percentage_range_are_rejected():
    with pytest.raises(AssetValidationError, match="between 0 and 100"):
        OperatingConstraint(
            constraint_id="soc-high", parameter="soc_max_pct", severity="hard",
            unit="%", operator="max", upper_bound=105,
            source_type="customer_provided", source_reference="commissioning record",
        )


def test_nameplate_and_installed_rating_parameters_require_canonical_units():
    with pytest.raises(AssetValidationError, match="nameplate_parameters.rated_power_kw must use kW"):
        AssetRecord(
            asset_id="pv-unit", site_id="site-01", asset_type="pv",
            nameplate_parameters={"rated_power_kw": parameter(1, "MW")},
            installed_parameters={"configured_power_kw": parameter(500, "kW")},
            observed_parameters={},
            constraints=(constraint("max_power_kw", "max", 500, "kW"),),
        )


def test_nameplate_and_installed_capacity_ratings_must_be_positive():
    with pytest.raises(AssetValidationError, match="installed_parameters.configured_power_kw must be positive"):
        AssetRecord(
            asset_id="pv-negative", site_id="site-01", asset_type="pv",
            nameplate_parameters={"rated_power_kw": parameter(100, "kW")},
            installed_parameters={"configured_power_kw": parameter(-1, "kW")},
            observed_parameters={},
            constraints=(constraint("max_power_kw", "max", 10, "kW"),),
        )

"""Fail-closed adapter from confirmed asset records to the offline energy model.

This adapter is deliberately narrow: one asset per supported resource type.
It never guesses efficiencies, initial SOC, or diesel variable cost. It does
not imply device compatibility, field validation, or authorization for control.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from islandos_core.assets import AssetRecord, evaluate_asset_readiness
from islandos_core.energy_system import (
    BatterySpec,
    DieselSpec,
    EnergySystemConfig,
    EnergyModelError,
)


class AssetEnergyAdapterError(ValueError):
    """Raised when asset records cannot safely configure the energy model."""


_SUPPORTED_TYPES = {
    "pv", "wind", "battery", "grid_connection", "diesel_generator",
}


def _required_parameter(asset: AssetRecord, name: str, unit: str) -> float:
    parameter = asset.installed_parameters.get(name)
    if parameter is None:
        raise AssetEnergyAdapterError(
            f"{asset.asset_id}: installed parameter required: {name}"
        )
    if not parameter.confirmed:
        raise AssetEnergyAdapterError(
            f"{asset.asset_id}: installed parameter is not confirmed: {name}"
        )
    if parameter.unit != unit:
        raise AssetEnergyAdapterError(
            f"{asset.asset_id}: {name} must use {unit}, got {parameter.unit}"
        )
    return float(parameter.value)


def _required_constraint(asset: AssetRecord, parameter: str, operator: str) -> float:
    matches = [
        item for item in asset.constraints
        if item.parameter == parameter
        and item.severity == "hard"
        and item.operator == operator
        and item.confirmed
    ]
    if len(matches) != 1:
        raise AssetEnergyAdapterError(
            f"{asset.asset_id}: expected exactly one confirmed hard "
            f"{operator} constraint for {parameter}; found {len(matches)}"
        )
    item = matches[0]
    expected_unit = "%" if parameter.startswith("soc_") else "kW"
    if item.unit != expected_unit:
        raise AssetEnergyAdapterError(
            f"{asset.asset_id}: {parameter} constraint must use {expected_unit}"
        )
    return float(item.lower_bound if operator == "min" else item.upper_bound)


def build_energy_system_config_from_assets(
    assets: Sequence[AssetRecord],
    *,
    dt_hours: float = 1.0,
    operating_assumptions: Mapping[str, Any] | None = None,
) -> EnergySystemConfig:
    """Build an offline energy model config from confirmed, compatible assets.

    Required explicit assumptions when a battery exists:
      battery_initial_soc, battery_charge_efficiency,
      battery_discharge_efficiency.
    Required explicit assumption when a diesel generator exists:
      diesel_variable_cost_per_kwh.

    The initial SOC is a fraction in [0, 1]. Efficiencies are fractions in
    (0, 1]. Diesel minimum stable loading is not modeled by the current engine;
    a non-zero minimum therefore blocks conversion rather than being ignored.
    """
    if not isinstance(assets, Sequence) or isinstance(assets, (str, bytes)) or not assets:
        raise AssetEnergyAdapterError("assets must be a non-empty sequence of AssetRecord")
    if any(not isinstance(asset, AssetRecord) for asset in assets):
        raise AssetEnergyAdapterError("every item must be an AssetRecord")

    site_ids = {asset.site_id for asset in assets}
    if len(site_ids) != 1:
        raise AssetEnergyAdapterError("all assets must belong to the same site")

    grouped: dict[str, list[AssetRecord]] = {}
    for asset in assets:
        if asset.asset_type not in _SUPPORTED_TYPES:
            raise AssetEnergyAdapterError(
                f"asset type is not yet supported by the energy model: {asset.asset_type}"
            )
        grouped.setdefault(asset.asset_type, []).append(asset)

    duplicates = sorted(kind for kind, items in grouped.items() if len(items) > 1)
    if duplicates:
        raise AssetEnergyAdapterError(
            "multiple assets of the same type require aggregation support first: "
            + ", ".join(duplicates)
        )

    for asset in assets:
        readiness = evaluate_asset_readiness(asset)
        if readiness.get("can_screen") is not True:
            raise AssetEnergyAdapterError(
                f"{asset.asset_id} is not ready for offline screening: "
                + ", ".join(readiness.get("blockers", []))
            )

    assumptions = dict(operating_assumptions or {})
    pv_rated_kw = wind_rated_kw = grid_import_limit_kw = 0.0
    battery_spec = None
    diesel_spec = None

    if "pv" in grouped:
        asset = grouped["pv"][0]
        installed = _required_parameter(asset, "configured_power_kw", "kW")
        hard_limit = _required_constraint(asset, "max_power_kw", "max")
        pv_rated_kw = min(installed, hard_limit)

    if "wind" in grouped:
        asset = grouped["wind"][0]
        installed = _required_parameter(asset, "configured_power_kw", "kW")
        hard_limit = _required_constraint(asset, "max_power_kw", "max")
        wind_rated_kw = min(installed, hard_limit)

    if "grid_connection" in grouped:
        asset = grouped["grid_connection"][0]
        installed = _required_parameter(asset, "configured_power_kw", "kW")
        hard_limit = _required_constraint(asset, "import_limit_kw", "max")
        grid_import_limit_kw = min(installed, hard_limit)

    if "battery" in grouped:
        asset = grouped["battery"][0]
        power = _required_parameter(asset, "configured_power_kw", "kW")
        capacity = _required_parameter(asset, "usable_energy_capacity_kwh", "kWh")
        max_charge = _required_constraint(asset, "max_charge_kw", "max")
        max_discharge = _required_constraint(asset, "max_discharge_kw", "max")
        min_soc_pct = _required_constraint(asset, "soc_min_pct", "min")
        max_soc_pct = _required_constraint(asset, "soc_max_pct", "max")
        if max_charge > power or max_discharge > power:
            raise AssetEnergyAdapterError(
                f"{asset.asset_id}: charge/discharge limit exceeds installed power"
            )
        required = (
            "battery_initial_soc",
            "battery_charge_efficiency",
            "battery_discharge_efficiency",
        )
        missing = [key for key in required if key not in assumptions]
        if missing:
            raise AssetEnergyAdapterError(
                "explicit battery operating assumptions required: " + ", ".join(missing)
            )
        battery_spec = BatterySpec(
            capacity_kwh=capacity,
            max_charge_kw=max_charge,
            max_discharge_kw=max_discharge,
            initial_soc=assumptions["battery_initial_soc"],
            min_soc=min_soc_pct / 100.0,
            max_soc=max_soc_pct / 100.0,
            charge_efficiency=assumptions["battery_charge_efficiency"],
            discharge_efficiency=assumptions["battery_discharge_efficiency"],
        )

    if "diesel_generator" in grouped:
        asset = grouped["diesel_generator"][0]
        installed = _required_parameter(asset, "configured_power_kw", "kW")
        max_power = _required_constraint(asset, "max_power_kw", "max")
        min_stable = _required_constraint(asset, "min_stable_power_kw", "min")
        if min_stable > 0:
            raise AssetEnergyAdapterError(
                "diesel minimum stable loading is not modeled yet; "
                "cannot safely convert this generator"
            )
        if "diesel_variable_cost_per_kwh" not in assumptions:
            raise AssetEnergyAdapterError(
                "explicit diesel_variable_cost_per_kwh assumption is required"
            )
        diesel_spec = DieselSpec(
            rated_power_kw=min(installed, max_power),
            variable_cost_per_kwh=assumptions["diesel_variable_cost_per_kwh"],
        )

    try:
        return EnergySystemConfig(
            pv_rated_kw=pv_rated_kw,
            wind_rated_kw=wind_rated_kw,
            grid_import_limit_kw=grid_import_limit_kw,
            dt_hours=dt_hours,
            battery=battery_spec,
            diesel=diesel_spec,
        )
    except (EnergyModelError, TypeError, ValueError) as exc:
        raise AssetEnergyAdapterError(f"invalid asset-derived energy configuration: {exc}") from exc

"""Fail-closed adapter from confirmed asset records to the offline energy model.

PV, wind, and grid import capacities can be summed after each asset independently
passes readiness and constraint checks. Batteries and diesel units remain
single-instance until per-device state and commitment constraints are modeled.
This does not imply equipment compatibility, field validation, or control authority.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
import re

from islandos_core.assets import AssetParameter, AssetRecord, evaluate_asset_readiness
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


def _required_assumption(
    assumptions: Mapping[str, AssetParameter],
    name: str,
    *,
    unit: str | None = None,
) -> float:
    assumption = assumptions.get(name)
    if not isinstance(assumption, AssetParameter):
        raise AssetEnergyAdapterError(
            f"{name} must be supplied as a provenance-bearing AssetParameter"
        )
    if not assumption.confirmed:
        raise AssetEnergyAdapterError(f"{name} is not confirmed")
    if unit is not None and assumption.unit != unit:
        raise AssetEnergyAdapterError(f"{name} must use {unit}")
    if unit is None and not assumption.unit.endswith("/kWh"):
        raise AssetEnergyAdapterError(f"{name} unit must be a currency per kWh")
    return float(assumption.value)


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



def _optional_grid_export_limit(asset: AssetRecord, installed_power_kw: float) -> float:
    """Use export capacity only when one confirmed hard limit is explicitly declared."""
    matches = [
        item for item in asset.constraints
        if item.parameter == "export_limit_kw"
    ]
    if not matches:
        return 0.0
    if len(matches) != 1:
        raise AssetEnergyAdapterError(
            f"{asset.asset_id}: expected at most one export_limit_kw constraint"
        )
    item = matches[0]
    if (
        item.severity != "hard"
        or item.operator != "max"
        or not item.confirmed
    ):
        raise AssetEnergyAdapterError(
            f"{asset.asset_id}: export_limit_kw must be one confirmed hard max constraint"
        )
    if item.unit != "kW":
        raise AssetEnergyAdapterError(
            f"{asset.asset_id}: export_limit_kw constraint must use kW"
        )
    return min(installed_power_kw, float(item.upper_bound))

def build_energy_system_config_from_assets(
    assets: Sequence[AssetRecord],
    *,
    dt_hours: float = 1.0,
    operating_assumptions: Mapping[str, AssetParameter] | None = None,
) -> EnergySystemConfig:
    """Build an offline energy model config from confirmed, compatible assets.

    Required explicit assumptions when a battery exists:
      battery_initial_soc, battery_charge_efficiency,
      battery_discharge_efficiency.
    Required explicit assumption when a diesel generator exists:
      diesel_variable_cost_per_kwh. Optional paired assumptions:
      diesel_fuel_consumption_l_per_kwh and diesel_initial_fuel_liters.

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
    asset_ids = [asset.asset_id for asset in assets]
    if len(asset_ids) != len(set(asset_ids)):
        raise AssetEnergyAdapterError("asset_id values must be unique within a site")

    grouped: dict[str, list[AssetRecord]] = {}
    for asset in assets:
        if asset.asset_type not in _SUPPORTED_TYPES:
            raise AssetEnergyAdapterError(
                f"asset type is not yet supported by the energy model: {asset.asset_type}"
            )
        grouped.setdefault(asset.asset_type, []).append(asset)

    aggregatable = {"pv", "wind", "grid_connection"}
    unsupported_duplicates = sorted(
        kind for kind, items in grouped.items()
        if len(items) > 1 and kind not in aggregatable
    )
    if unsupported_duplicates:
        raise AssetEnergyAdapterError(
            "multiple assets of these types require per-device state or "
            "commitment modeling first: " + ", ".join(unsupported_duplicates)
        )

    for asset in assets:
        readiness = evaluate_asset_readiness(asset)
        if readiness.get("can_screen") is not True:
            raise AssetEnergyAdapterError(
                f"{asset.asset_id} is not ready for offline screening: "
                + ", ".join(readiness.get("blockers", []))
            )

    assumptions = dict(operating_assumptions or {})
    if any(not isinstance(value, AssetParameter) for value in assumptions.values()):
        raise AssetEnergyAdapterError(
            "operating assumptions must be provenance-bearing AssetParameter records"
        )
    pv_rated_kw = wind_rated_kw = grid_import_limit_kw = 0.0
    export_limits: list[float] = []
    battery_spec = None
    diesel_spec = None

    # Aggregate only additive nameplate/connection capacities. Every component
    # is validated independently before it contributes to the site total.
    for asset in grouped.get("pv", []):
        installed = _required_parameter(asset, "configured_power_kw", "kW")
        hard_limit = _required_constraint(asset, "max_power_kw", "max")
        pv_rated_kw += min(installed, hard_limit)

    for asset in grouped.get("wind", []):
        installed = _required_parameter(asset, "configured_power_kw", "kW")
        hard_limit = _required_constraint(asset, "max_power_kw", "max")
        wind_rated_kw += min(installed, hard_limit)

    for asset in grouped.get("grid_connection", []):
        installed = _required_parameter(asset, "configured_power_kw", "kW")
        hard_limit = _required_constraint(asset, "import_limit_kw", "max")
        grid_import_limit_kw += min(installed, hard_limit)
        export_limits.append(_optional_grid_export_limit(asset, installed))

    positive_export_limits = [limit for limit in export_limits if limit > 0]
    if len(positive_export_limits) > 1:
        raise AssetEnergyAdapterError(
            "multiple export-capable grid connections require an explicit "
            "shared point-of-connection aggregation model"
        )
    grid_export_limit_kw = positive_export_limits[0] if positive_export_limits else 0.0

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
        try:
            battery_spec = BatterySpec(
                capacity_kwh=capacity,
                max_charge_kw=max_charge,
                max_discharge_kw=max_discharge,
                initial_soc=_required_assumption(assumptions, "battery_initial_soc", unit="fraction"),
                min_soc=min_soc_pct / 100.0,
                max_soc=max_soc_pct / 100.0,
                charge_efficiency=_required_assumption(
                    assumptions, "battery_charge_efficiency", unit="fraction"
                ),
                discharge_efficiency=_required_assumption(
                    assumptions, "battery_discharge_efficiency", unit="fraction"
                ),
                throughput_cost_per_kwh=(
                    _required_assumption(assumptions, "battery_throughput_cost_per_kwh")
                    if "battery_throughput_cost_per_kwh" in assumptions else 0.0
                ),
            )
        except EnergyModelError as exc:
            raise AssetEnergyAdapterError(
                f"invalid battery asset-derived configuration: {exc}"
            ) from exc

    if "diesel_generator" in grouped:
        asset = grouped["diesel_generator"][0]
        installed = _required_parameter(asset, "configured_power_kw", "kW")
        max_power = _required_constraint(asset, "max_power_kw", "max")
        min_stable = _required_constraint(asset, "min_stable_power_kw", "min")
        if "diesel_variable_cost_per_kwh" not in assumptions:
            raise AssetEnergyAdapterError(
                "explicit diesel_variable_cost_per_kwh assumption is required"
            )
        constant_rate_supplied = "diesel_fuel_consumption_l_per_kwh" in assumptions
        initial_fuel_supplied = "diesel_initial_fuel_liters" in assumptions
        curve_keys = [name for name in assumptions if name.startswith("diesel_fuel_curve_")]
        curve_indices = sorted({
            int(match.group(1))
            for name in curve_keys
            if (match := re.fullmatch(
                r"diesel_fuel_curve_(\d+)_(?:power_kw|fuel_l_per_hour)", name
            ))
        })
        curve_points = []
        if curve_keys:
            if len(curve_indices) < 2 or curve_indices != list(range(len(curve_indices))):
                raise AssetEnergyAdapterError(
                    "diesel fuel curve assumptions must contain contiguous indices starting at 0 and at least two points"
                )
            for index in curve_indices:
                power_name = f"diesel_fuel_curve_{index}_power_kw"
                rate_name = f"diesel_fuel_curve_{index}_fuel_l_per_hour"
                if (power_name in assumptions) != (rate_name in assumptions):
                    raise AssetEnergyAdapterError(
                        f"diesel fuel curve point {index} requires both power and fuel-rate assumptions"
                    )
                curve_points.append((
                    _required_assumption(assumptions, power_name, unit="kW"),
                    _required_assumption(assumptions, rate_name, unit="L/h"),
                ))
            if len(curve_keys) != 2 * len(curve_indices):
                raise AssetEnergyAdapterError("unrecognized diesel fuel curve assumption name")
        if constant_rate_supplied and curve_keys:
            raise AssetEnergyAdapterError(
                "constant diesel fuel rate and nonlinear fuel curve cannot both be supplied"
            )
        has_fuel_model = constant_rate_supplied or bool(curve_keys)
        if has_fuel_model != initial_fuel_supplied:
            raise AssetEnergyAdapterError(
                "diesel fuel model and diesel_initial_fuel_liters must be supplied together"
            )
        if "diesel_fuel_tank_capacity_liters" in assumptions and not has_fuel_model:
            raise AssetEnergyAdapterError(
                "diesel_fuel_tank_capacity_liters requires a fuel model and initial inventory"
            )
        try:
            diesel_spec = DieselSpec(
                rated_power_kw=min(installed, max_power),
                min_stable_power_kw=min_stable,
                variable_cost_per_kwh=_required_assumption(
                    assumptions, "diesel_variable_cost_per_kwh"
                ),
                fuel_consumption_l_per_kwh=(
                    _required_assumption(
                        assumptions, "diesel_fuel_consumption_l_per_kwh", unit="L/kWh"
                    ) if constant_rate_supplied else None
                ),
                fuel_curve_liters_per_hour=tuple(curve_points) if curve_points else None,
                initial_fuel_liters=(
                    _required_assumption(
                        assumptions, "diesel_initial_fuel_liters", unit="L"
                    ) if "diesel_initial_fuel_liters" in assumptions else None
                ),
                fuel_tank_capacity_liters=(
                    _required_assumption(
                        assumptions, "diesel_fuel_tank_capacity_liters", unit="L"
                    ) if "diesel_fuel_tank_capacity_liters" in assumptions else None
                ),
            )
        except EnergyModelError as exc:
            raise AssetEnergyAdapterError(
                f"invalid diesel asset-derived configuration: {exc}"
            ) from exc

    try:
        return EnergySystemConfig(
            pv_rated_kw=pv_rated_kw,
            wind_rated_kw=wind_rated_kw,
            grid_import_limit_kw=grid_import_limit_kw,
            grid_export_limit_kw=grid_export_limit_kw,
            dt_hours=dt_hours,
            battery=battery_spec,
            diesel=diesel_spec,
        )
    except (EnergyModelError, TypeError, ValueError) as exc:
        raise AssetEnergyAdapterError(f"invalid asset-derived energy configuration: {exc}") from exc

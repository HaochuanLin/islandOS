"""Deterministic, auditable energy-system dispatch for IslandOS.

This is an offline planning model, not a live controller or a validated plant model.
PV/wind inputs are available generation forecasts or measurements in kW. The model
balances each time step across renewables, load, battery, grid, diesel and curtailment.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence


class EnergyModelError(ValueError):
    """Raised when an energy-system configuration or input series is invalid."""


def _number(name: str, value: float, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EnergyModelError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < minimum:
        raise EnergyModelError(f"{name} must be finite and >= {minimum}")
    return result


@dataclass(frozen=True)
class BatterySpec:
    capacity_kwh: float
    max_charge_kw: float
    max_discharge_kw: float
    initial_soc: float = 0.5
    min_soc: float = 0.1
    max_soc: float = 0.95
    charge_efficiency: float = 0.95
    discharge_efficiency: float = 0.95

    def __post_init__(self) -> None:
        for name in ("capacity_kwh", "max_charge_kw", "max_discharge_kw"):
            _number(name, getattr(self, name))
        for name in ("initial_soc", "min_soc", "max_soc",
                     "charge_efficiency", "discharge_efficiency"):
            value = _number(name, getattr(self, name))
            if value > 1:
                raise EnergyModelError(f"{name} must be <= 1")
        if self.capacity_kwh <= 0:
            raise EnergyModelError("battery capacity_kwh must be > 0")
        if self.max_soc <= self.min_soc:
            raise EnergyModelError("battery max_soc must be greater than min_soc")
        if not self.min_soc <= self.initial_soc <= self.max_soc:
            raise EnergyModelError("battery initial_soc must be within SOC limits")
        if self.charge_efficiency <= 0 or self.discharge_efficiency <= 0:
            raise EnergyModelError("battery efficiencies must be > 0")


@dataclass(frozen=True)
class DieselSpec:
    rated_power_kw: float
    variable_cost_per_kwh: float

    def __post_init__(self) -> None:
        _number("diesel rated_power_kw", self.rated_power_kw)
        _number("diesel variable_cost_per_kwh", self.variable_cost_per_kwh)
        if self.rated_power_kw <= 0:
            raise EnergyModelError("diesel rated_power_kw must be > 0")


@dataclass(frozen=True)
class EnergySystemConfig:
    pv_rated_kw: float
    wind_rated_kw: float
    grid_import_limit_kw: float
    dt_hours: float = 1.0
    battery: BatterySpec | None = None
    diesel: DieselSpec | None = None
    grid_export_limit_kw: float = 0.0

    def __post_init__(self) -> None:
        for name in (
            "pv_rated_kw", "wind_rated_kw", "grid_import_limit_kw",
            "grid_export_limit_kw",
        ):
            _number(name, getattr(self, name))
        _number("dt_hours", self.dt_hours)
        if self.dt_hours <= 0:
            raise EnergyModelError("dt_hours must be > 0")


@dataclass(frozen=True)
class EnergySystemInputs:
    pv_generation_kw: Sequence[float]
    wind_generation_kw: Sequence[float]
    load_kw: Sequence[float]
    grid_price_per_kwh: Sequence[float]
    grid_available: Sequence[bool]
    diesel_available: Sequence[bool] | None = None
    grid_export_price_per_kwh: Sequence[float] | None = None


def _series(name: str, values: Sequence[float], *, allow_zero: bool = True) -> list[float]:
    try:
        result = list(values)
    except TypeError as exc:
        raise EnergyModelError(f"{name} must be a one-dimensional series") from exc
    if not result:
        raise EnergyModelError(f"{name} must contain at least one time step")
    normalized = [_number(f"{name}[{i}]", value) for i, value in enumerate(result)]
    if not allow_zero and any(value <= 0 for value in normalized):
        raise EnergyModelError(f"{name} values must be > 0")
    return normalized



def _signed_series(name: str, values: Sequence[float]) -> list[float]:
    """Validate finite numeric values while allowing negative market prices."""
    try:
        result = list(values)
    except TypeError as exc:
        raise EnergyModelError(f"{name} must be a one-dimensional series") from exc
    if not result:
        raise EnergyModelError(f"{name} must contain at least one time step")
    normalized = []
    for index, value in enumerate(result):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise EnergyModelError(f"{name}[{index}] must be numeric")
        number = float(value)
        if not math.isfinite(number):
            raise EnergyModelError(f"{name}[{index}] must be finite")
        normalized.append(number)
    return normalized


def _flags(name: str, values: Sequence[bool] | None, n: int, *, default: bool) -> list[bool]:
    if values is None:
        return [default] * n
    result = list(values)
    if len(result) != n or any(not isinstance(value, bool) for value in result):
        raise EnergyModelError(f"{name} must contain exactly {n} boolean values")
    return result


def dispatch_energy_system(
    inputs: EnergySystemInputs,
    config: EnergySystemConfig,
    *,
    policy: str = "battery_first",
) -> dict:
    """Run a transparent rule-based dispatch and return hourly audit rows + summary.

    Policies are explicit operating priorities, not optimized schedules:
    - battery_first: renewables -> battery -> grid -> diesel
    - grid_first: renewables -> grid -> battery -> diesel

    Renewable surplus charges the battery first, then exports up to the explicit
    grid export limit when the grid is available. Remaining surplus is curtailed.
    Export requires an explicit feed-in price series. Diesel minimum-load, ramp,
    start-cost, degradation-cost, and network constraints are not modeled.
    """
    if policy not in {"battery_first", "grid_first"}:
        raise EnergyModelError("policy must be 'battery_first' or 'grid_first'")
    pv = _series("pv_generation_kw", inputs.pv_generation_kw)
    wind = _series("wind_generation_kw", inputs.wind_generation_kw)
    load = _series("load_kw", inputs.load_kw)
    price = _series("grid_price_per_kwh", inputs.grid_price_per_kwh)
    export_price = (
        _signed_series("grid_export_price_per_kwh", inputs.grid_export_price_per_kwh)
        if inputs.grid_export_price_per_kwh is not None else [0.0] * len(load)
    )
    n = len(load)
    if any(len(values) != n for values in (pv, wind, price, export_price)):
        raise EnergyModelError("all numeric input series must have equal lengths")
    if any(value > config.pv_rated_kw + 1e-9 for value in pv):
        raise EnergyModelError("PV generation exceeds configured rated power")
    if any(value > config.wind_rated_kw + 1e-9 for value in wind):
        raise EnergyModelError("wind generation exceeds configured rated power")
    if inputs.grid_available is None:
        raise EnergyModelError("grid_available must be explicitly supplied")
    if config.grid_export_limit_kw > 0 and inputs.grid_export_price_per_kwh is None:
        raise EnergyModelError(
            "grid_export_price_per_kwh must be explicitly supplied when grid export is enabled"
        )
    if config.grid_export_limit_kw == 0 and inputs.grid_export_price_per_kwh is not None:
        raise EnergyModelError(
            "grid_export_price_per_kwh was supplied but grid_export_limit_kw is zero"
        )
    if config.diesel is not None and inputs.diesel_available is None:
        raise EnergyModelError(
            "diesel_available must be explicitly supplied when diesel is configured"
        )
    grid_ok = _flags("grid_available", inputs.grid_available, n, default=False)
    # An unconfigured diesel unit is never implicitly treated as available.
    diesel_ok = _flags("diesel_available", inputs.diesel_available, n, default=False)

    battery = config.battery
    soc = battery.initial_soc if battery else 0.0
    rows: list[dict] = []
    totals = {
        "load_energy_kwh": 0.0, "load_served_kwh": 0.0, "unmet_load_kwh": 0.0,
        "pv_energy_kwh": 0.0, "wind_energy_kwh": 0.0,
        "renewable_curtailed_kwh": 0.0, "battery_charge_input_kwh": 0.0,
        "battery_discharge_output_kwh": 0.0, "grid_import_kwh": 0.0,
        "diesel_generation_kwh": 0.0, "grid_energy_cost": 0.0,
        "diesel_energy_cost": 0.0, "grid_export_energy_kwh": 0.0,
        "grid_export_revenue": 0.0,
    }

    for t in range(n):
        renewable = pv[t] + wind[t]
        direct_renewable = min(renewable, load[t])
        surplus = renewable - direct_renewable
        deficit = load[t] - direct_renewable
        charge_kw = discharge_kw = grid_kw = diesel_kw = 0.0

        if battery and surplus > 0:
            soc_room_kwh = (battery.max_soc - soc) * battery.capacity_kwh
            charge_kw = min(
                surplus, battery.max_charge_kw,
                soc_room_kwh / (battery.charge_efficiency * config.dt_hours),
            )
            soc += charge_kw * config.dt_hours * battery.charge_efficiency / battery.capacity_kwh
            surplus -= charge_kw

        def discharge(remaining_kw: float) -> float:
            nonlocal soc
            if not battery or remaining_kw <= 0:
                return 0.0
            available_kwh = (soc - battery.min_soc) * battery.capacity_kwh
            output_limit_kw = available_kwh * battery.discharge_efficiency / config.dt_hours
            delivered = min(remaining_kw, battery.max_discharge_kw, output_limit_kw)
            soc -= delivered * config.dt_hours / (
                battery.discharge_efficiency * battery.capacity_kwh
            )
            return delivered

        def import_grid(remaining_kw: float) -> float:
            return min(remaining_kw, config.grid_import_limit_kw) if grid_ok[t] else 0.0

        def run_diesel(remaining_kw: float) -> float:
            if not config.diesel or not diesel_ok[t]:
                return 0.0
            return min(remaining_kw, config.diesel.rated_power_kw)

        if deficit > 0 and policy == "battery_first":
            discharge_kw = discharge(deficit)
            deficit -= discharge_kw
            grid_kw = import_grid(deficit)
            deficit -= grid_kw
            diesel_kw = run_diesel(deficit)
            deficit -= diesel_kw
        elif deficit > 0:
            grid_kw = import_grid(deficit)
            deficit -= grid_kw
            discharge_kw = discharge(deficit)
            deficit -= discharge_kw
            diesel_kw = run_diesel(deficit)
            deficit -= diesel_kw

        export_kw = (
            min(surplus, config.grid_export_limit_kw)
            if grid_ok[t] and config.grid_export_limit_kw > 0 else 0.0
        )
        curtailed_kw = max(0.0, surplus - export_kw)
        served_kw = load[t] - max(0.0, deficit)
        balance_residual = (
            pv[t] + wind[t] + discharge_kw + grid_kw + diesel_kw
            - served_kw - charge_kw - export_kw - curtailed_kw
        )
        if abs(balance_residual) > 1e-7:
            raise RuntimeError(f"energy balance failed at timestep {t}: {balance_residual}")
        if battery and not battery.min_soc - 1e-9 <= soc <= battery.max_soc + 1e-9:
            raise RuntimeError(f"battery SOC outside configured bounds at timestep {t}")

        row = {
            "timestep": t, "pv_generation_kw": pv[t], "wind_generation_kw": wind[t],
            "load_kw": load[t], "renewable_direct_to_load_kw": direct_renewable,
            "battery_charge_kw": charge_kw, "battery_discharge_kw": discharge_kw,
            "grid_available": grid_ok[t],
            "diesel_available": diesel_ok[t],
            "grid_import_kw": grid_kw, "grid_export_kw": export_kw,
            "grid_export_price_per_kwh": export_price[t],
            "grid_export_revenue": export_kw * config.dt_hours * export_price[t],
            "diesel_generation_kw": diesel_kw,
            "load_served_kw": served_kw, "unmet_load_kw": max(0.0, deficit),
            "renewable_curtailed_kw": curtailed_kw, "battery_soc": soc,
            "grid_price_per_kwh": price[t], "energy_balance_residual_kw": balance_residual,
        }
        rows.append(row)
        scale = config.dt_hours
        totals["load_energy_kwh"] += load[t] * scale
        totals["load_served_kwh"] += served_kw * scale
        totals["unmet_load_kwh"] += max(0.0, deficit) * scale
        totals["pv_energy_kwh"] += pv[t] * scale
        totals["wind_energy_kwh"] += wind[t] * scale
        totals["renewable_curtailed_kwh"] += curtailed_kw * scale
        totals["battery_charge_input_kwh"] += charge_kw * scale
        totals["battery_discharge_output_kwh"] += discharge_kw * scale
        totals["grid_import_kwh"] += grid_kw * scale
        totals["grid_export_energy_kwh"] += export_kw * scale
        totals["grid_export_revenue"] += export_kw * scale * export_price[t]
        totals["diesel_generation_kwh"] += diesel_kw * scale
        totals["grid_energy_cost"] += grid_kw * scale * price[t]
        if config.diesel:
            totals["diesel_energy_cost"] += diesel_kw * scale * config.diesel.variable_cost_per_kwh

    totals = {key: round(value, 8) for key, value in totals.items()}
    totals["unmet_load_fraction"] = (
        totals["unmet_load_kwh"] / totals["load_energy_kwh"]
        if totals["load_energy_kwh"] else 0.0
    )
    totals["ending_battery_soc"] = round(soc, 8) if battery else None
    totals["gross_energy_cost"] = round(
        totals["grid_energy_cost"] + totals["diesel_energy_cost"], 8
    )
    totals["estimated_energy_cost"] = round(
        totals["gross_energy_cost"] - totals["grid_export_revenue"], 8
    )
    return {
        "policy": policy,
        "time_steps": n,
        "dt_hours": config.dt_hours,
        "grid_export_limit_kw": config.grid_export_limit_kw,
        "summary": totals,
        "rows": rows,
        "model_scope": {
            "type": "deterministic_rule_based_offline_screening",
            "not_an_optimizer": True,
            "not_a_controller": True,
            "synthetic_or_user_supplied_inputs_only": True,
            "grid_export_enabled": config.grid_export_limit_kw > 0,
            "interconnection_permission_validated": False,
            "network_power_flow_modeled": False,
        },
    }



def compare_energy_policies(
    inputs: EnergySystemInputs,
    config: EnergySystemConfig,
) -> dict:
    """Compare the two explicit dispatch baselines without declaring a winner."""
    battery_first = dispatch_energy_system(inputs, config, policy="battery_first")
    grid_first = dispatch_energy_system(inputs, config, policy="grid_first")
    metrics = (
        "estimated_energy_cost", "grid_import_kwh", "grid_export_energy_kwh",
        "grid_export_revenue", "diesel_generation_kwh", "renewable_curtailed_kwh",
        "unmet_load_kwh", "battery_discharge_output_kwh",
    )
    differences = {
        key: round(
            battery_first["summary"][key] - grid_first["summary"][key], 8
        )
        for key in metrics
    }
    return {
        "battery_first": battery_first,
        "grid_first": grid_first,
        "difference_battery_first_minus_grid_first": differences,
        "interpretation": (
            "Compare cost, unmet load, curtailment and battery use together. "
            "A lower estimated energy bill alone does not establish a better "
            "or safer operating policy."
        ),
    }

"""Integrated microgrid energy + water balance model (simulation only).

This is a deterministic physical-accounting baseline, not a forecast model,
optimizer, protection system, or equipment controller. Flexible RO demand is
served only from renewable power remaining after essential electricity demand.
Battery discharge is reserved for essential electricity demand; surplus
renewables may charge the battery after scheduled RO consumption.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence

import numpy as np


@dataclass(frozen=True)
class MicrogridConfig:
    """Site-level limits. All power values are kW and energy values are kWh."""

    battery_capacity_kwh: float = 0.0
    battery_initial_soc_kwh: float = 0.0
    battery_min_soc_kwh: float = 0.0
    battery_max_charge_kw: float = 0.0
    battery_max_discharge_kw: float = 0.0
    battery_charge_efficiency: float = 1.0
    battery_discharge_efficiency: float = 1.0
    grid_import_limit_kw: float = 0.0
    diesel_capacity_kw: float = 0.0
    ro_rated_power_kw: float = 0.0
    ro_specific_energy_kwh_per_m3: float = 4.0
    water_tank_capacity_m3: float = 0.0
    water_initial_inventory_m3: float = 0.0


@dataclass(frozen=True)
class MicrogridInputs:
    """Aligned hourly (or constant-step) scenario inputs."""

    pv_power_kw: Sequence[float]
    wind_power_kw: Sequence[float]
    essential_load_kw: Sequence[float]
    ro_requested_power_kw: Sequence[float]
    water_demand_m3: Sequence[float]
    grid_available: Sequence[bool] | None = None
    grid_price_per_kwh: Sequence[float] | None = None
    diesel_cost_per_kwh: float = 0.0
    diesel_emissions_kg_per_kwh: float = 0.0
    grid_emissions_kg_per_kwh: Sequence[float] | None = None
    dt_hours: float = 1.0


@dataclass(frozen=True)
class MicrogridResult:
    """Auditable per-step energy, battery, water, cost and emissions outputs."""

    renewable_available_kw: np.ndarray
    essential_load_kw: np.ndarray
    ro_requested_power_kw: np.ndarray
    essential_renewable_kw: np.ndarray
    battery_discharge_kw: np.ndarray
    grid_import_kw: np.ndarray
    diesel_generation_kw: np.ndarray
    unserved_essential_kw: np.ndarray
    ro_power_served_kw: np.ndarray
    battery_charge_kw: np.ndarray
    renewable_curtailed_kw: np.ndarray
    battery_soc_kwh: np.ndarray
    water_produced_m3: np.ndarray
    water_served_m3: np.ndarray
    unmet_water_demand_m3: np.ndarray
    water_inventory_m3: np.ndarray
    operating_cost: np.ndarray
    emissions_kg: np.ndarray
    dt_hours: float

    def summary(self) -> dict[str, float]:
        """Return aggregate metrics; cost/emissions reflect supplied factors."""
        energy = lambda values: float(np.sum(values) * self.dt_hours)
        return {
            "renewable_generation_kwh": energy(self.renewable_available_kw),
            "essential_demand_kwh": energy(self.essential_load_kw),
            "essential_unserved_kwh": energy(self.unserved_essential_kw),
            "ro_electricity_kwh": energy(self.ro_power_served_kw),
            "battery_charge_kwh": energy(self.battery_charge_kw),
            "battery_discharge_kwh": energy(self.battery_discharge_kw),
            "grid_import_kwh": energy(self.grid_import_kw),
            "diesel_generation_kwh": energy(self.diesel_generation_kw),
            "renewable_curtailed_kwh": energy(self.renewable_curtailed_kw),
            "water_produced_m3": float(np.sum(self.water_produced_m3)),
            "water_served_m3": float(np.sum(self.water_served_m3)),
            "unmet_water_demand_m3": float(np.sum(self.unmet_water_demand_m3)),
            "final_water_inventory_m3": float(self.water_inventory_m3[-1]),
            "operating_cost": float(np.sum(self.operating_cost)),
            "emissions_kg": float(np.sum(self.emissions_kg)),
        }


def _series(values: Sequence[float], name: str, *, allow_zero=True) -> np.ndarray:
    try:
        array = np.asarray(values, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a numeric one-dimensional series") from exc
    if array.ndim != 1 or array.size == 0:
        raise ValueError(f"{name} must be a non-empty one-dimensional series")
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must contain only finite values")
    if np.any(array < 0) or (not allow_zero and np.any(array <= 0)):
        raise ValueError(f"{name} must be {'positive' if not allow_zero else 'non-negative'}")
    return array


def _validate_config(c: MicrogridConfig) -> None:
    numeric = {
        "battery_capacity_kwh": c.battery_capacity_kwh,
        "battery_initial_soc_kwh": c.battery_initial_soc_kwh,
        "battery_min_soc_kwh": c.battery_min_soc_kwh,
        "battery_max_charge_kw": c.battery_max_charge_kw,
        "battery_max_discharge_kw": c.battery_max_discharge_kw,
        "battery_charge_efficiency": c.battery_charge_efficiency,
        "battery_discharge_efficiency": c.battery_discharge_efficiency,
        "grid_import_limit_kw": c.grid_import_limit_kw,
        "diesel_capacity_kw": c.diesel_capacity_kw,
        "ro_rated_power_kw": c.ro_rated_power_kw,
        "ro_specific_energy_kwh_per_m3": c.ro_specific_energy_kwh_per_m3,
        "water_tank_capacity_m3": c.water_tank_capacity_m3,
        "water_initial_inventory_m3": c.water_initial_inventory_m3,
    }
    for name, value in numeric.items():
        if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.integer, np.floating)) or not math.isfinite(float(value)):
            raise ValueError(f"{name} must be a finite number")
        if value < 0:
            raise ValueError(f"{name} must be >= 0")
    if c.battery_min_soc_kwh > c.battery_initial_soc_kwh or c.battery_initial_soc_kwh > c.battery_capacity_kwh:
        raise ValueError("battery SOC must satisfy min <= initial <= capacity")
    if not 0 < c.battery_charge_efficiency <= 1:
        raise ValueError("battery_charge_efficiency must be in (0, 1]")
    if not 0 < c.battery_discharge_efficiency <= 1:
        raise ValueError("battery_discharge_efficiency must be in (0, 1]")
    if c.ro_specific_energy_kwh_per_m3 <= 0:
        raise ValueError("ro_specific_energy_kwh_per_m3 must be > 0")
    if c.water_initial_inventory_m3 > c.water_tank_capacity_m3:
        raise ValueError("initial water inventory exceeds tank capacity")
    if c.ro_rated_power_kw > 0 and c.water_tank_capacity_m3 <= 0:
        raise ValueError("a positive RO rating requires positive water tank capacity")


def simulate_microgrid(
    inputs: MicrogridInputs,
    config: MicrogridConfig,
) -> MicrogridResult:
    """Simulate one chronological dispatch under a transparent priority policy.

    Priority: (1) essential load, supplied by renewables, battery, grid, diesel;
    (2) scheduled RO load from remaining renewables only; (3) battery charging
    from remaining renewables; (4) curtail any remaining renewable power.
    RO is clipped to its rating and available tank headroom. Water demand is
    served from opening inventory plus same-step production. This simple
    within-step convention must be revisited for sub-hourly/site-specific use.
    """
    _validate_config(config)
    dt = inputs.dt_hours
    if isinstance(dt, (bool, np.bool_)) or not isinstance(dt, (int, float)) or not math.isfinite(float(dt)) or dt <= 0:
        raise ValueError("dt_hours must be a finite number > 0")

    pv = _series(inputs.pv_power_kw, "pv_power_kw")
    wind = _series(inputs.wind_power_kw, "wind_power_kw")
    essential = _series(inputs.essential_load_kw, "essential_load_kw")
    ro_requested = _series(inputs.ro_requested_power_kw, "ro_requested_power_kw")
    water_demand = _series(inputs.water_demand_m3, "water_demand_m3")
    n = len(pv)
    if any(len(x) != n for x in (wind, essential, ro_requested, water_demand)):
        raise ValueError("all required input series must have equal lengths")
    if np.any(ro_requested > config.ro_rated_power_kw + 1e-9):
        raise ValueError("ro_requested_power_kw exceeds configured RO rating")

    grid_available = np.ones(n, dtype=bool) if inputs.grid_available is None else np.asarray(inputs.grid_available)
    if grid_available.shape != (n,) or not np.all(np.isin(grid_available, [True, False, 0, 1])):
        raise ValueError("grid_available must be a boolean series matching the inputs")
    grid_price = np.zeros(n) if inputs.grid_price_per_kwh is None else _series(inputs.grid_price_per_kwh, "grid_price_per_kwh")
    grid_emissions = np.zeros(n) if inputs.grid_emissions_kg_per_kwh is None else _series(inputs.grid_emissions_kg_per_kwh, "grid_emissions_kg_per_kwh")
    if len(grid_price) != n or len(grid_emissions) != n:
        raise ValueError("optional grid price/emissions series must match input length")
    for name, value in (("diesel_cost_per_kwh", inputs.diesel_cost_per_kwh),
                        ("diesel_emissions_kg_per_kwh", inputs.diesel_emissions_kg_per_kwh)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or value < 0:
            raise ValueError(f"{name} must be finite and >= 0")

    names = ("essential_renewable_kw", "battery_discharge_kw", "grid_import_kw",
             "diesel_generation_kw", "unserved_essential_kw", "ro_power_served_kw",
             "battery_charge_kw", "renewable_curtailed_kw", "water_produced_m3",
             "water_served_m3", "unmet_water_demand_m3", "operating_cost", "emissions_kg")
    out = {name: np.zeros(n, dtype=float) for name in names}
    soc = np.zeros(n + 1, dtype=float); soc[0] = config.battery_initial_soc_kwh
    water = np.zeros(n + 1, dtype=float); water[0] = config.water_initial_inventory_m3
    renewable = pv + wind

    for t in range(n):
        remaining_renewable = float(renewable[t])
        out["essential_renewable_kw"][t] = min(remaining_renewable, essential[t])
        remaining_renewable -= out["essential_renewable_kw"][t]
        essential_deficit = essential[t] - out["essential_renewable_kw"][t]

        available_battery_energy = max(0.0, soc[t] - config.battery_min_soc_kwh)
        battery_output_limit = min(config.battery_max_discharge_kw, available_battery_energy * config.battery_discharge_efficiency / dt)
        out["battery_discharge_kw"][t] = min(essential_deficit, battery_output_limit)
        soc_after_discharge = soc[t] - out["battery_discharge_kw"][t] * dt / config.battery_discharge_efficiency
        essential_deficit -= out["battery_discharge_kw"][t]

        if bool(grid_available[t]):
            out["grid_import_kw"][t] = min(essential_deficit, config.grid_import_limit_kw)
        essential_deficit -= out["grid_import_kw"][t]
        out["diesel_generation_kw"][t] = min(essential_deficit, config.diesel_capacity_kw)
        essential_deficit -= out["diesel_generation_kw"][t]
        out["unserved_essential_kw"][t] = max(0.0, essential_deficit)

        # RO is a scheduled flexible load and may use renewable power left
        # after essential electricity service; it never borrows from battery.
        ro_power = min(ro_requested[t], config.ro_rated_power_kw, remaining_renewable)
        water_headroom = max(0.0, config.water_tank_capacity_m3 - water[t])
        max_ro_power_for_headroom = water_headroom * config.ro_specific_energy_kwh_per_m3 / dt
        ro_power = min(ro_power, max_ro_power_for_headroom)
        out["ro_power_served_kw"][t] = ro_power
        remaining_renewable -= ro_power
        produced = ro_power * dt / config.ro_specific_energy_kwh_per_m3
        out["water_produced_m3"][t] = produced
        available_water = water[t] + produced
        out["water_served_m3"][t] = min(water_demand[t], available_water)
        out["unmet_water_demand_m3"][t] = water_demand[t] - out["water_served_m3"][t]
        water[t + 1] = available_water - out["water_served_m3"][t]

        charge_power_limit = min(
            config.battery_max_charge_kw,
            max(0.0, config.battery_capacity_kwh - soc_after_discharge) / (dt * config.battery_charge_efficiency),
        )
        out["battery_charge_kw"][t] = min(remaining_renewable, charge_power_limit)
        soc[t + 1] = soc_after_discharge + out["battery_charge_kw"][t] * dt * config.battery_charge_efficiency
        remaining_renewable -= out["battery_charge_kw"][t]
        out["renewable_curtailed_kw"][t] = max(0.0, remaining_renewable)

        out["operating_cost"][t] = (
            out["grid_import_kw"][t] * dt * grid_price[t]
            + out["diesel_generation_kw"][t] * dt * inputs.diesel_cost_per_kwh
        )
        out["emissions_kg"][t] = (
            out["grid_import_kw"][t] * dt * grid_emissions[t]
            + out["diesel_generation_kw"][t] * dt * inputs.diesel_emissions_kg_per_kwh
        )

    result = MicrogridResult(
        renewable_available_kw=renewable.copy(),
        essential_load_kw=essential.copy(),
        ro_requested_power_kw=ro_requested.copy(),
        battery_soc_kwh=soc,
        water_inventory_m3=water,
        dt_hours=float(dt),
        **{name: out[name] for name in names},
    )
    validate_microgrid_result(result, config)
    return result


def validate_microgrid_result(result: MicrogridResult, config: MicrogridConfig, *, atol: float = 1e-7) -> None:
    """Raise if the energy, battery, water, or inventory limits do not balance."""
    n = len(result.renewable_available_kw)
    per_step = (
        result.essential_renewable_kw + result.ro_power_served_kw
        + result.battery_charge_kw + result.renewable_curtailed_kw
    )
    if not np.allclose(per_step, result.renewable_available_kw, atol=atol, rtol=1e-9):
        raise RuntimeError("renewable allocation balance failed")
    essential_supply = (
        result.essential_renewable_kw + result.battery_discharge_kw
        + result.grid_import_kw + result.diesel_generation_kw
        + result.unserved_essential_kw
    )
    if not np.allclose(essential_supply, result.essential_load_kw, atol=atol, rtol=1e-9):
        raise RuntimeError("essential electricity balance failed")
    if len(result.battery_soc_kwh) != n + 1 or np.any(result.battery_soc_kwh < config.battery_min_soc_kwh - atol) or np.any(result.battery_soc_kwh > config.battery_capacity_kwh + atol):
        raise RuntimeError("battery SOC bounds failed")
    if len(result.water_inventory_m3) != n + 1 or np.any(result.water_inventory_m3 < -atol) or np.any(result.water_inventory_m3 > config.water_tank_capacity_m3 + atol):
        raise RuntimeError("water inventory bounds failed")
    water_balance = result.water_inventory_m3[:-1] + result.water_produced_m3 - result.water_served_m3
    if not np.allclose(result.water_inventory_m3[1:], water_balance, atol=atol, rtol=1e-9):
        raise RuntimeError("water inventory balance failed")
    if np.any(result.grid_import_kw > config.grid_import_limit_kw + atol) or np.any(result.diesel_generation_kw > config.diesel_capacity_kw + atol):
        raise RuntimeError("grid or diesel power limit failed")
    if np.any(result.ro_power_served_kw > result.ro_requested_power_kw + atol) or np.any(result.ro_power_served_kw > config.ro_rated_power_kw + atol):
        raise RuntimeError("RO power limit failed")

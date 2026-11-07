"""Deterministic, auditable hourly electricity balance for IslandOS.

This is an offline screening model, not a controller or a site-validated optimizer.
All power series are kW at the timestep boundary; energy is kWh over dt_hours.
Renewable input is available generation before curtailment.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence

import numpy as np


class EnergyBalanceError(ValueError):
    """Raised when an energy-system input is incomplete or physically invalid."""


def _number(name: str, value: float, *, minimum: float = 0.0) -> float:
    if isinstance(value, (bool, np.bool_)):
        raise EnergyBalanceError(f"{name} must be a finite number, not bool")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise EnergyBalanceError(f"{name} must be numeric") from exc
    if not math.isfinite(result) or result < minimum:
        raise EnergyBalanceError(f"{name} must be finite and >= {minimum}")
    return result


def _series(name: str, values: Sequence[float]) -> np.ndarray:
    raw = np.asarray(values)
    if raw.ndim != 1 or raw.size == 0 or raw.dtype.kind not in "iuf":
        raise EnergyBalanceError(f"{name} must be a non-empty numeric 1-D series")
    result = raw.astype(float, copy=False)
    if not np.all(np.isfinite(result)) or np.any(result < 0):
        raise EnergyBalanceError(f"{name} must contain finite non-negative values")
    return result


@dataclass(frozen=True)
class BatterySpec:
    """Battery nameplate/operating envelope; no degradation model is implied."""

    capacity_kwh: float
    max_charge_kw: float
    max_discharge_kw: float
    charge_efficiency: float = 0.95
    discharge_efficiency: float = 0.95
    min_soc_fraction: float = 0.10
    max_soc_fraction: float = 0.90
    initial_soc_fraction: float = 0.50

    def __post_init__(self) -> None:
        for field in ("capacity_kwh", "max_charge_kw", "max_discharge_kw"):
            object.__setattr__(self, field, _number(field, getattr(self, field)))
        for field in ("charge_efficiency", "discharge_efficiency"):
            value = _number(field, getattr(self, field))
            if not 0 < value <= 1:
                raise EnergyBalanceError(f"{field} must be in (0, 1]")
            object.__setattr__(self, field, value)
        for field in ("min_soc_fraction", "max_soc_fraction", "initial_soc_fraction"):
            value = _number(field, getattr(self, field))
            if value > 1:
                raise EnergyBalanceError(f"{field} must be <= 1")
            object.__setattr__(self, field, value)
        if self.min_soc_fraction > self.max_soc_fraction:
            raise EnergyBalanceError("minimum SOC cannot exceed maximum SOC")
        if not self.min_soc_fraction <= self.initial_soc_fraction <= self.max_soc_fraction:
            raise EnergyBalanceError("initial SOC must be within configured SOC limits")


@dataclass(frozen=True)
class EnergyBalanceResult:
    """Per-step flows and aggregate KPIs; all series are aligned to input steps."""

    renewable_available_kw: np.ndarray
    renewable_used_kw: np.ndarray
    curtailment_kw: np.ndarray
    battery_charge_kw: np.ndarray
    battery_discharge_kw: np.ndarray
    battery_soc_kwh: np.ndarray
    grid_import_kw: np.ndarray
    diesel_generation_kw: np.ndarray
    load_served_kw: np.ndarray
    unmet_load_kw: np.ndarray
    step_cost: np.ndarray
    total_cost: float
    renewable_utilization_fraction: float
    total_unmet_energy_kwh: float
    total_curtailment_kwh: float
    total_grid_energy_kwh: float
    total_diesel_energy_kwh: float


def simulate_energy_balance(
    load_kw: Sequence[float],
    renewable_available_kw: Sequence[float],
    *,
    dt_hours: float = 1.0,
    strategy: str = "renewable_first",
    grid_import_limit_kw: float = 0.0,
    grid_price_per_kwh: float = 0.0,
    diesel_limit_kw: float = 0.0,
    diesel_cost_per_kwh: float = 0.0,
    battery: BatterySpec | None = None,
) -> EnergyBalanceResult:
    """Run a deterministic dispatch baseline and audit conservation each step.

    Strategies:
      - renewable_first: renewable -> battery discharge -> grid -> diesel.
      - grid_first: grid -> renewable -> battery discharge -> diesel.
    Battery charging is only from renewable surplus, avoiding hidden grid charging.
    """
    load = _series("load_kw", load_kw)
    renewable = _series("renewable_available_kw", renewable_available_kw)
    if load.shape != renewable.shape:
        raise EnergyBalanceError("load_kw and renewable_available_kw must have equal length")
    dt = _number("dt_hours", dt_hours)
    if dt <= 0:
        raise EnergyBalanceError("dt_hours must be > 0")
    if strategy not in {"renewable_first", "grid_first"}:
        raise EnergyBalanceError("strategy must be renewable_first or grid_first")
    grid_limit = _number("grid_import_limit_kw", grid_import_limit_kw)
    grid_price = _number("grid_price_per_kwh", grid_price_per_kwh)
    diesel_limit = _number("diesel_limit_kw", diesel_limit_kw)
    diesel_cost = _number("diesel_cost_per_kwh", diesel_cost_per_kwh)

    n = len(load)
    renewable_used = np.zeros(n)
    curtailment = np.zeros(n)
    charge = np.zeros(n)
    discharge = np.zeros(n)
    grid = np.zeros(n)
    diesel = np.zeros(n)
    served = np.zeros(n)
    unmet = np.zeros(n)
    cost = np.zeros(n)
    soc = np.zeros(n + 1)
    if battery:
        soc[0] = battery.capacity_kwh * battery.initial_soc_fraction
        min_soc = battery.capacity_kwh * battery.min_soc_fraction
        max_soc = battery.capacity_kwh * battery.max_soc_fraction
    else:
        min_soc = max_soc = 0.0

    for t in range(n):
        demand = float(load[t])
        ren = float(renewable[t])
        remaining = demand

        if strategy == "grid_first":
            grid[t] = min(remaining, grid_limit)
            remaining -= grid[t]
            renewable_used[t] = min(ren, remaining)
            remaining -= renewable_used[t]
        else:
            renewable_used[t] = min(ren, remaining)
            remaining -= renewable_used[t]

        if battery and remaining > 0:
            available_energy = max(0.0, soc[t] - min_soc)
            max_output = min(battery.max_discharge_kw, available_energy * battery.discharge_efficiency / dt)
            discharge[t] = min(remaining, max_output)
            remaining -= discharge[t]
            soc[t + 1] = soc[t] - discharge[t] * dt / battery.discharge_efficiency
        else:
            soc[t + 1] = soc[t]

        if strategy == "renewable_first":
            grid[t] = min(remaining, grid_limit)
            remaining -= grid[t]
        diesel[t] = min(remaining, diesel_limit)
        remaining -= diesel[t]
        served[t] = demand - remaining
        unmet[t] = remaining

        renewable_surplus = max(0.0, ren - renewable_used[t])
        if battery and renewable_surplus > 0:
            room_input = max(0.0, (max_soc - soc[t + 1]) / (battery.charge_efficiency * dt))
            charge[t] = min(renewable_surplus, battery.max_charge_kw, room_input)
            soc[t + 1] += charge[t] * dt * battery.charge_efficiency
        curtailment[t] = renewable_surplus - charge[t]
        cost[t] = grid[t] * dt * grid_price + diesel[t] * dt * diesel_cost

        supply = renewable_used[t] + discharge[t] + grid[t] + diesel[t]
        if not math.isclose(supply, served[t], abs_tol=1e-8, rel_tol=1e-9):
            raise RuntimeError(f"electricity supply/load balance failed at step {t}")
        if not math.isclose(ren, renewable_used[t] + charge[t] + curtailment[t], abs_tol=1e-8, rel_tol=1e-9):
            raise RuntimeError(f"renewable allocation balance failed at step {t}")
        if battery:
            expected = soc[t] + charge[t] * dt * battery.charge_efficiency - discharge[t] * dt / battery.discharge_efficiency
            if not math.isclose(soc[t + 1], expected, abs_tol=1e-8, rel_tol=1e-9):
                raise RuntimeError(f"battery state-of-charge balance failed at step {t}")

    renewable_total = float(np.sum(renewable) * dt)
    renewable_used_total = float(np.sum(renewable_used) * dt)
    return EnergyBalanceResult(
        renewable_available_kw=renewable.copy(), renewable_used_kw=renewable_used,
        curtailment_kw=curtailment, battery_charge_kw=charge,
        battery_discharge_kw=discharge, battery_soc_kwh=soc,
        grid_import_kw=grid, diesel_generation_kw=diesel, load_served_kw=served,
        unmet_load_kw=unmet, step_cost=cost, total_cost=float(np.sum(cost)),
        renewable_utilization_fraction=(renewable_used_total / renewable_total if renewable_total else 1.0),
        total_unmet_energy_kwh=float(np.sum(unmet) * dt),
        total_curtailment_kwh=float(np.sum(curtailment) * dt),
        total_grid_energy_kwh=float(np.sum(grid) * dt),
        total_diesel_energy_kwh=float(np.sum(diesel) * dt),
    )

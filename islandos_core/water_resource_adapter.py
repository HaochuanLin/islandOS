"""Water-demand to RO electrical-load coupling for offline resource coordination.

This adapter keeps water inventory and RO production feasibility explicit while
converting the required RO energy into the shared electrical demand model. It is
a conservative just-in-time production policy, not an RO price optimizer.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Real
from typing import Sequence


def _finite_nonnegative(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(float(value)):
        raise ValueError(f"{name} must be finite numeric data")
    normalized = float(value)
    if normalized < 0:
        raise ValueError(f"{name} must be non-negative")
    return normalized


@dataclass(frozen=True)
class WaterServiceSpec:
    """Declared RO and tank limits; values must come from a reviewed site source."""

    specific_energy_kwh_per_m3: float
    ro_capacity_m3_per_hour: float
    tank_capacity_m3: float
    initial_inventory_m3: float
    reserve_m3: float = 0.0

    def __post_init__(self) -> None:
        for name in (
            "specific_energy_kwh_per_m3",
            "ro_capacity_m3_per_hour",
            "tank_capacity_m3",
            "initial_inventory_m3",
            "reserve_m3",
        ):
            object.__setattr__(self, name, _finite_nonnegative(name, getattr(self, name)))
        if self.specific_energy_kwh_per_m3 <= 0:
            raise ValueError("specific_energy_kwh_per_m3 must be > 0")
        if self.ro_capacity_m3_per_hour <= 0:
            raise ValueError("ro_capacity_m3_per_hour must be > 0")
        if self.tank_capacity_m3 <= 0:
            raise ValueError("tank_capacity_m3 must be > 0")
        if self.reserve_m3 > self.tank_capacity_m3:
            raise ValueError("reserve_m3 cannot exceed tank_capacity_m3")
        if not self.reserve_m3 <= self.initial_inventory_m3 <= self.tank_capacity_m3:
            raise ValueError("initial_inventory_m3 must be within reserve and tank capacity")


@dataclass(frozen=True)
class WaterEnergyLoad:
    """Hourly water-service replay and its equivalent RO electrical demand."""

    production_m3: tuple[float, ...]
    inventory_after_demand_m3: tuple[float, ...]
    ro_power_kw: tuple[float, ...]
    total_demand_m3: float
    total_production_m3: float
    specific_energy_kwh_per_m3: float
    service_feasible: bool


def build_ro_energy_load(
    water_demand_m3_per_hour: Sequence[float],
    *,
    spec: WaterServiceSpec,
    dt_hours: float = 1.0,
) -> WaterEnergyLoad:
    """Build a feasible just-in-time RO production profile for forecast demand.

    Each time step produces only enough water to serve demand and restore the
    declared reserve. It fails closed when RO capacity or tank constraints
    cannot satisfy the forecast. RO electrical load is production × specific
    energy divided by the time-step duration.
    """
    if not isinstance(spec, WaterServiceSpec):
        raise TypeError("spec must be a WaterServiceSpec")
    dt = _finite_nonnegative("dt_hours", dt_hours)
    if dt <= 0:
        raise ValueError("dt_hours must be > 0")
    try:
        demand = [_finite_nonnegative(f"water_demand_m3_per_hour[{i}]", value)
                  for i, value in enumerate(water_demand_m3_per_hour)]
    except TypeError as exc:
        raise ValueError("water_demand_m3_per_hour must be a one-dimensional series") from exc
    if not demand:
        raise ValueError("water_demand_m3_per_hour must not be empty")

    inventory = spec.initial_inventory_m3
    production: list[float] = []
    inventory_trace: list[float] = []
    ro_power: list[float] = []
    max_step_production = spec.ro_capacity_m3_per_hour * dt
    for index, demand_rate in enumerate(demand):
        demand_volume = demand_rate * dt
        required_production = max(0.0, demand_volume + spec.reserve_m3 - inventory)
        if required_production > max_step_production + 1e-9:
            raise ValueError(
                f"water service infeasible at step {index}: required RO production "
                f"{required_production:.6g} m3 exceeds capacity {max_step_production:.6g} m3"
            )
        if inventory + required_production > spec.tank_capacity_m3 + 1e-9:
            raise ValueError(f"water tank capacity exceeded at step {index}")
        inventory += required_production
        if inventory + 1e-9 < demand_volume:
            raise ValueError(f"water demand cannot be served at step {index}")
        inventory -= demand_volume
        if inventory + 1e-9 < spec.reserve_m3:
            raise ValueError(f"water reserve violated at step {index}")
        production.append(required_production)
        inventory_trace.append(max(0.0, inventory))
        ro_power.append(required_production * spec.specific_energy_kwh_per_m3 / dt)

    return WaterEnergyLoad(
        production_m3=tuple(production),
        inventory_after_demand_m3=tuple(inventory_trace),
        ro_power_kw=tuple(ro_power),
        total_demand_m3=sum(demand) * dt,
        total_production_m3=sum(production),
        specific_energy_kwh_per_m3=spec.specific_energy_kwh_per_m3,
        service_feasible=True,
    )

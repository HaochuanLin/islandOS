"""Price-aware scheduling for continuous, deferrable electrical loads.

This is an independent IslandOS linear-programming building block inspired by
general demand-response patterns. It does not copy source code from another
repository.

The model schedules a fixed energy requirement across eligible time steps,
subject to per-step power availability and a nameplate limit. It supports
continuous loads only: minimum on/off times, startup costs, ramp limits, and
binary equipment states require a later MILP extension.

This is a planning aid, not a plant controller or a site-validated optimizer.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
from scipy.optimize import linprog


@dataclass(frozen=True)
class FlexibleLoadSchedule:
    """Auditable result for one price-aware flexible-load scheduling run."""

    power_kw: tuple[float, ...]
    energy_kwh: tuple[float, ...]
    total_energy_kwh: float
    total_cost: float
    energy_requirement_kwh: float
    energy_shortfall_kwh: float
    solver_status: str
    solver_message: str
    method: str = "continuous_linear_programming"
    scope: str = (
        "continuous deferrable electrical load; no minimum-run, startup, "
        "ramp, network, or equipment protection constraints"
    )

    def to_dict(self) -> dict:
        return {
            "power_kw": list(self.power_kw),
            "energy_kwh": list(self.energy_kwh),
            "total_energy_kwh": self.total_energy_kwh,
            "total_cost": self.total_cost,
            "energy_requirement_kwh": self.energy_requirement_kwh,
            "energy_shortfall_kwh": self.energy_shortfall_kwh,
            "solver_status": self.solver_status,
            "solver_message": self.solver_message,
            "method": self.method,
            "scope": self.scope,
        }


def _series(values: Sequence[float], name: str, length: int | None = None) -> np.ndarray:
    raw = np.asarray(values, dtype=object)
    if raw.dtype.kind == "b" or any(
        isinstance(value, (bool, np.bool_)) for value in raw.flat
    ):
        raise ValueError(f"{name} must contain numeric values, not booleans")
    try:
        result = np.asarray(values, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a numeric 1D series") from exc
    if result.ndim != 1 or result.size == 0:
        raise ValueError(f"{name} must be a non-empty 1D series")
    if not np.all(np.isfinite(result)):
        raise ValueError(f"{name} must contain only finite values")
    if length is not None and len(result) != length:
        raise ValueError(f"{name} must have the same horizon length as price_per_kwh")
    return result


def optimize_flexible_load(
    price_per_kwh: Sequence[float],
    energy_requirement_kwh: float,
    max_power_kw: float,
    available_power_kw: Sequence[float] | None = None,
    availability: Sequence[bool] | None = None,
    dt_hours: float = 1.0,
) -> FlexibleLoadSchedule:
    """Minimize energy cost while meeting a fixed, shiftable energy requirement.

    available_power_kw is the per-step power budget available to this load
    after essential demand and higher-priority reservations. If omitted, the
    nameplate rating is available at every step. availability can disable
    individual steps (for example, outside an operating window).

    A ValueError is raised when the requested energy cannot fit in the allowed
    horizon. The optimizer never silently relaxes the service requirement.
    """
    prices = _series(price_per_kwh, "price_per_kwh")
    horizon = len(prices)

    scalar_inputs = (
        ("energy_requirement_kwh", energy_requirement_kwh, 0.0, False),
        ("max_power_kw", max_power_kw, 0.0, True),
        ("dt_hours", dt_hours, 0.0, True),
    )
    normalized = {}
    for name, value, lower_bound, exclusive in scalar_inputs:
        if isinstance(value, (bool, np.bool_)) or not isinstance(
            value, (int, float, np.integer, np.floating)
        ):
            raise ValueError(f"{name} must be a finite numeric value")
        numeric = float(value)
        if not np.isfinite(numeric) or (numeric <= lower_bound if exclusive else numeric < lower_bound):
            qualifier = "positive" if exclusive else "non-negative"
            raise ValueError(f"{name} must be finite and {qualifier}")
        normalized[name] = numeric
    energy_requirement_kwh = normalized["energy_requirement_kwh"]
    max_power_kw = normalized["max_power_kw"]
    dt_hours = normalized["dt_hours"]

    if available_power_kw is None:
        power_budget = np.full(horizon, float(max_power_kw))
    else:
        power_budget = _series(available_power_kw, "available_power_kw", horizon)
        if np.any(power_budget < 0):
            raise ValueError("available_power_kw must be non-negative")
        power_budget = np.minimum(power_budget, float(max_power_kw))

    if availability is not None:
        raw_availability = np.asarray(availability)
        if raw_availability.ndim != 1 or len(raw_availability) != horizon:
            raise ValueError("availability must have the same horizon length as price_per_kwh")
        if raw_availability.dtype.kind != "b":
            raise ValueError("availability must contain boolean values only")
        power_budget = np.where(raw_availability, power_budget, 0.0)

    capacity_kwh = float(np.sum(power_budget) * dt_hours)
    tolerance = max(1e-8, float(energy_requirement_kwh) * 1e-9)
    if energy_requirement_kwh > capacity_kwh + tolerance:
        raise ValueError(
            "energy requirement is infeasible: "
            f"{energy_requirement_kwh:.6g} kWh requested but only "
            f"{capacity_kwh:.6g} kWh can be scheduled"
        )

    if energy_requirement_kwh == 0:
        powers = np.zeros(horizon, dtype=float)
        return FlexibleLoadSchedule(
            power_kw=tuple(powers.tolist()),
            energy_kwh=tuple(powers.tolist()),
            total_energy_kwh=0.0,
            total_cost=0.0,
            energy_requirement_kwh=0.0,
            energy_shortfall_kwh=0.0,
            solver_status="optimal",
            solver_message="Zero energy requirement; no optimization needed.",
        )

    result = linprog(
        c=prices * dt_hours,
        A_eq=np.ones((1, horizon), dtype=float) * dt_hours,
        b_eq=np.array([float(energy_requirement_kwh)]),
        bounds=[(0.0, float(limit)) for limit in power_budget],
        method="highs",
    )
    if not result.success or result.x is None:
        raise RuntimeError(f"Flexible-load optimization failed: {result.message}")

    powers = np.maximum(np.asarray(result.x, dtype=float), 0.0)
    energy = powers * dt_hours
    delivered = float(np.sum(energy))
    shortfall = max(0.0, float(energy_requirement_kwh) - delivered)
    if shortfall > tolerance:
        raise RuntimeError(
            "Solver returned a schedule that does not meet the energy requirement "
            f"(shortfall={shortfall:.9g} kWh)"
        )

    return FlexibleLoadSchedule(
        power_kw=tuple(float(v) for v in powers),
        energy_kwh=tuple(float(v) for v in energy),
        total_energy_kwh=delivered,
        total_cost=float(np.dot(prices, energy)),
        energy_requirement_kwh=float(energy_requirement_kwh),
        energy_shortfall_kwh=shortfall,
        solver_status="optimal",
        solver_message=str(result.message),
    )

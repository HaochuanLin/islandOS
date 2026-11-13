"""Price-aware, tank-constrained RO production planning.

This is a transparent deterministic look-ahead heuristic for offline planning.
It is not a global optimizer and never emits equipment commands.
"""
from __future__ import annotations

import math
from numbers import Real
from typing import Sequence

from .water_resource_adapter import WaterServiceSpec


def build_price_aware_ro_schedule(
    water_demand_m3_per_hour: Sequence[float],
    electricity_price_per_kwh: Sequence[float],
    *,
    spec: WaterServiceSpec,
    lookahead_hours: int = 6,
    dt_hours: float = 1.0,
) -> dict:
    """Pre-produce water in locally cheap hours while respecting tank/RO limits.

    At each step, compare the current tariff with the cheapest tariff in the
    look-ahead window. In a locally cheapest hour, target inventory sufficient
    for the window (bounded by tank capacity); otherwise produce only enough
    to serve current demand and restore reserve. The schedule is checked against
    every hourly inventory balance and fails closed on infeasibility.
    """
    if not isinstance(spec, WaterServiceSpec):
        raise TypeError("spec must be a WaterServiceSpec")
    if isinstance(lookahead_hours, bool) or not isinstance(lookahead_hours, int) or lookahead_hours < 1:
        raise ValueError("lookahead_hours must be a positive integer")
    if isinstance(dt_hours, bool) or not isinstance(dt_hours, Real) or not math.isfinite(float(dt_hours)) or dt_hours <= 0:
        raise ValueError("dt_hours must be finite and > 0")
    dt = float(dt_hours)

    def numeric_series(name: str, values: Sequence[float], *, nonnegative: bool) -> list[float]:
        try:
            items = list(values)
        except TypeError as exc:
            raise ValueError(f"{name} must be a one-dimensional series") from exc
        if not items:
            raise ValueError(f"{name} must not be empty")
        normalized = []
        for index, item in enumerate(items):
            if isinstance(item, bool) or not isinstance(item, Real) or not math.isfinite(float(item)):
                raise ValueError(f"{name}[{index}] must be finite numeric data")
            value = float(item)
            if nonnegative and value < 0:
                raise ValueError(f"{name}[{index}] must be non-negative")
            normalized.append(value)
        return normalized

    demand = numeric_series("water_demand_m3_per_hour", water_demand_m3_per_hour, nonnegative=True)
    prices = numeric_series("electricity_price_per_kwh", electricity_price_per_kwh, nonnegative=False)
    if len(demand) != len(prices):
        raise ValueError("water demand and electricity price series must have equal lengths")

    inventory = spec.initial_inventory_m3
    production, inventory_trace, power = [], [], []
    max_step = spec.ro_capacity_m3_per_hour * dt
    for i, rate in enumerate(demand):
        consumed = rate * dt
        available_after_demand = inventory - consumed
        if available_after_demand < spec.reserve_m3 - 1e-9:
            # Current production must cover demand and preserve the reserve.
            immediate_target = consumed + spec.reserve_m3
        else:
            immediate_target = 0.0

        end = min(len(demand), i + lookahead_hours)
        future_volume = sum(demand[i + 1:end]) * dt
        window_target = min(spec.tank_capacity_m3, future_volume + spec.reserve_m3)
        locally_cheapest = prices[i] <= min(prices[i:end]) + 1e-12
        target_inventory = window_target if locally_cheapest else immediate_target
        required = max(0.0, target_inventory - available_after_demand)
        # Always satisfy the current step first, even when current tariff is high.
        required = max(required, immediate_target - available_after_demand)
        immediate_required = max(0.0, immediate_target - available_after_demand)
        if immediate_required > max_step + 1e-9:
            raise ValueError(
                f"water service infeasible at step {i}: required RO production "
                f"{immediate_required:.6g} m3 exceeds capacity {max_step:.6g} m3"
            )
        # A larger look-ahead target may take several cheap periods to fill.
        required = min(required, max_step)
        if available_after_demand + required > spec.tank_capacity_m3 + 1e-9:
            required = max(0.0, spec.tank_capacity_m3 - available_after_demand)
        if available_after_demand + required < spec.reserve_m3 - 1e-9:
            raise ValueError(f"water reserve cannot be maintained at step {i}")
        inventory = available_after_demand + required
        production.append(required)
        inventory_trace.append(inventory)
        power.append(required * spec.specific_energy_kwh_per_m3 / dt)

    return {
        "production_m3": tuple(production),
        "inventory_end_m3": tuple(inventory_trace),
        "ro_power_kw": tuple(power),
        "total_production_m3": sum(production),
        "total_demand_m3": sum(demand) * dt,
        "total_ro_energy_kwh": sum(power) * dt,
        "estimated_ro_energy_cost": sum(p * kw * dt for p, kw in zip(prices, power)),
        "service_feasible": True,
        "method": "cheapest-hour-lookahead-heuristic",
        "lookahead_hours": lookahead_hours,
        "device_write_authorized": False,
    }

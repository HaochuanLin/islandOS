"""Auditable operating-cost accounting for RO production schedules.

This module compares operating plans on a like-for-like basis. It deliberately
excludes sunk capital expenditure from dispatch decisions. All prices and
quantities must be supplied by the caller; no site defaults are inferred.

Input series are aligned time steps. Energy is kWh per step, water is m3 per
step, tariff is currency/kWh, and start_events is a non-negative integer count.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Sequence


@dataclass(frozen=True)
class ROCostRates:
    """Customer-confirmed variable cost rates for RO operation."""

    currency: str
    electricity_price_per_kwh: float
    chemical_cost_per_m3: float = 0.0
    variable_om_cost_per_m3: float = 0.0
    maintenance_cost_per_runtime_hour: float = 0.0
    start_stop_cost_per_event: float = 0.0
    fixed_om_per_year: float = 0.0
    fixed_om_allocation_hours: float = 8760.0

    def validate(self) -> None:
        if not isinstance(self.currency, str) or not self.currency.strip():
            raise ValueError("currency must be a non-empty label")
        for name in (
            "electricity_price_per_kwh",
            "chemical_cost_per_m3",
            "variable_om_cost_per_m3",
            "maintenance_cost_per_runtime_hour",
            "start_stop_cost_per_event",
            "fixed_om_per_year",
            "fixed_om_allocation_hours",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be a finite non-negative number")
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be a finite non-negative number")
        if self.fixed_om_allocation_hours <= 0:
            raise ValueError("fixed_om_allocation_hours must be > 0")


@dataclass(frozen=True)
class ROCostReport:
    currency: str
    time_steps: int
    energy_kwh: float
    water_m3: float
    runtime_hours: float
    represented_hours: float
    time_step_hours: float
    start_stop_events: int
    electricity_cost: float
    chemical_cost: float
    variable_om_cost: float
    maintenance_cost: float
    start_stop_cost: float
    allocated_fixed_om_cost: float
    total_operating_cost: float
    cost_per_m3: float | None
    cost_breakdown: dict[str, float]
    provenance: str
    cost_basis_signature: str
    includes_sunk_capex: bool = False


def _numeric_series(values: Sequence[float], name: str) -> list[float]:
    try:
        items = list(values)
    except TypeError as exc:
        raise ValueError(f"{name} must be a one-dimensional numeric series") from exc
    if not items:
        raise ValueError(f"{name} must contain at least one time step")
    result = []
    for value in items:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name} must contain only numeric values")
        number = float(value)
        if not math.isfinite(number) or number < 0:
            raise ValueError(f"{name} must contain finite non-negative values")
        result.append(number)
    return result


def calculate_ro_operating_cost(
    energy_kwh: Sequence[float],
    water_m3: Sequence[float],
    electricity_price_per_kwh: Sequence[float] | float,
    rates: ROCostRates,
    *,
    runtime_hours: Sequence[float] | None = None,
    start_events: Sequence[int] | None = None,
    provenance: str = "unspecified",
    dt_hours: float = 1.0,
) -> ROCostReport:
    """Calculate an auditable operating-cost breakdown for one RO schedule.

    Electricity price may be a scalar or a per-step tariff series. If
    runtime_hours is omitted, runtime is not guessed and maintenance cost is
    zero unless the caller supplies runtime. Fixed O&M is allocated in
    proportion to represented hours, capped only by the caller's allocation
    convention (the caller should pass the actual period duration).
    """
    rates.validate()
    if isinstance(dt_hours, bool) or not isinstance(dt_hours, (int, float)) or not math.isfinite(dt_hours) or dt_hours <= 0:
        raise ValueError("dt_hours must be a finite number > 0")
    energy = _numeric_series(energy_kwh, "energy_kwh")
    water = _numeric_series(water_m3, "water_m3")
    if len(energy) != len(water):
        raise ValueError("energy_kwh and water_m3 must have the same number of steps")

    if isinstance(electricity_price_per_kwh, (int, float)) and not isinstance(electricity_price_per_kwh, bool):
        prices = [float(electricity_price_per_kwh)] * len(energy)
    else:
        prices = _numeric_series(electricity_price_per_kwh, "electricity_price_per_kwh")
    if len(prices) != len(energy):
        raise ValueError("electricity tariff series must match energy_kwh length")
    if any(not math.isfinite(p) or p < 0 for p in prices):
        raise ValueError("electricity prices must be finite and non-negative")

    if runtime_hours is None:
        runtime = 0.0
    else:
        runtime_series = _numeric_series(runtime_hours, "runtime_hours")
        if len(runtime_series) != len(energy):
            raise ValueError("runtime_hours must match energy_kwh length")
        runtime = sum(runtime_series)

    if start_events is None:
        starts = 0
    else:
        raw_starts = list(start_events)
        if len(raw_starts) != len(energy):
            raise ValueError("start_events must match energy_kwh length")
        if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in raw_starts):
            raise ValueError("start_events must contain non-negative integers")
        starts = sum(raw_starts)

    total_energy = sum(energy)
    total_water = sum(water)
    represented_hours = len(energy) * float(dt_hours)
    electricity = sum(kwh * price for kwh, price in zip(energy, prices))
    chemicals = total_water * rates.chemical_cost_per_m3
    variable_om = total_water * rates.variable_om_cost_per_m3
    maintenance = runtime * rates.maintenance_cost_per_runtime_hour
    start_stop = starts * rates.start_stop_cost_per_event
    fixed_om = rates.fixed_om_per_year * represented_hours / rates.fixed_om_allocation_hours
    components = {
        "electricity": electricity,
        "chemicals": chemicals,
        "variable_om": variable_om,
        "maintenance": maintenance,
        "start_stop": start_stop,
        "allocated_fixed_om": fixed_om,
    }
    total = sum(components.values())
    if not math.isfinite(total):
        raise ValueError("calculated operating cost is not finite")

    return ROCostReport(
        currency=rates.currency,
        time_steps=len(energy),
        energy_kwh=total_energy,
        water_m3=total_water,
        runtime_hours=runtime,
        represented_hours=represented_hours,
        time_step_hours=float(dt_hours),
        start_stop_events=starts,
        electricity_cost=electricity,
        chemical_cost=chemicals,
        variable_om_cost=variable_om,
        maintenance_cost=maintenance,
        start_stop_cost=start_stop,
        allocated_fixed_om_cost=fixed_om,
        total_operating_cost=total,
        cost_per_m3=(total / total_water) if total_water > 0 else None,
        cost_breakdown=components,
        provenance=provenance,
        cost_basis_signature=hashlib.sha256(
            json.dumps(
                {
                    "currency": rates.currency,
                    "chemical_cost_per_m3": rates.chemical_cost_per_m3,
                    "variable_om_cost_per_m3": rates.variable_om_cost_per_m3,
                    "maintenance_cost_per_runtime_hour": rates.maintenance_cost_per_runtime_hour,
                    "start_stop_cost_per_event": rates.start_stop_cost_per_event,
                    "fixed_om_per_year": rates.fixed_om_per_year,
                    "fixed_om_allocation_hours": rates.fixed_om_allocation_hours,
                    "electricity_prices_per_kwh": prices,
                },
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest(),
    )


def compare_ro_operating_plans(
    baseline: ROCostReport,
    candidate: ROCostReport,
    *,
    water_output_tolerance_fraction: float = 0.01,
) -> dict:
    """Compare plans; only qualify savings when service volume and period match.

    Water quality, reservoir state, demand satisfaction, equipment constraints,
    and tariff/cost-rate equivalence still require caller-side verification.
    """
    if baseline.currency != candidate.currency:
        raise ValueError("plans must use the same currency")
    if (
        isinstance(water_output_tolerance_fraction, bool)
        or not isinstance(water_output_tolerance_fraction, (int, float))
        or not math.isfinite(water_output_tolerance_fraction)
        or water_output_tolerance_fraction < 0
    ):
        raise ValueError("water_output_tolerance_fraction must be finite and non-negative")

    savings = baseline.total_operating_cost - candidate.total_operating_cost
    same_period = math.isclose(
        baseline.represented_hours,
        candidate.represented_hours,
        rel_tol=1e-9,
        abs_tol=1e-9,
    )
    same_sampling_grid = (
        baseline.time_steps == candidate.time_steps
        and math.isclose(
            baseline.time_step_hours,
            candidate.time_step_hours,
            rel_tol=1e-9,
            abs_tol=1e-9,
        )
    )
    if baseline.water_m3 == 0:
        water_delta_fraction = 0.0 if candidate.water_m3 == 0 else math.inf
    else:
        water_delta_fraction = abs(candidate.water_m3 - baseline.water_m3) / baseline.water_m3
    equivalent_water_volume = water_delta_fraction <= water_output_tolerance_fraction
    same_cost_basis = baseline.cost_basis_signature == candidate.cost_basis_signature
    service_volume_equivalent = same_period and equivalent_water_volume
    qualified_comparison = service_volume_equivalent and same_sampling_grid and same_cost_basis
    qualified_savings = savings if qualified_comparison else None
    savings_percent = (
        savings / baseline.total_operating_cost * 100.0
        if qualified_comparison and baseline.total_operating_cost > 0 else None
    )
    return {
        "currency": baseline.currency,
        "baseline_total_cost": baseline.total_operating_cost,
        "candidate_total_cost": candidate.total_operating_cost,
        "absolute_savings": savings,
        "qualified_savings": qualified_savings,
        "savings_percent": savings_percent,
        "baseline_represented_hours": baseline.represented_hours,
        "candidate_represented_hours": candidate.represented_hours,
        "same_time_coverage": same_period,
        "same_sampling_grid": same_sampling_grid,
        "baseline_time_steps": baseline.time_steps,
        "candidate_time_steps": candidate.time_steps,
        "baseline_time_step_hours": baseline.time_step_hours,
        "candidate_time_step_hours": candidate.time_step_hours,
        "baseline_water_m3": baseline.water_m3,
        "candidate_water_m3": candidate.water_m3,
        "water_output_change_m3": candidate.water_m3 - baseline.water_m3,
        "water_output_change_fraction": (
            water_delta_fraction if math.isfinite(water_delta_fraction) else None
        ),
        "water_output_tolerance_fraction": float(water_output_tolerance_fraction),
        "equivalent_water_volume": equivalent_water_volume,
        "service_volume_equivalent": service_volume_equivalent,
        "same_cost_basis": same_cost_basis,
        "qualified_comparison": qualified_comparison,
        "baseline_cost_per_m3": baseline.cost_per_m3,
        "candidate_cost_per_m3": candidate.cost_per_m3,
        "baseline_provenance": baseline.provenance,
        "candidate_provenance": candidate.provenance,
        "interpretation": (
            "Savings are qualified only for matching represented hours and "
            "water output within the configured tolerance, identical sampling grids, and identical recorded cost assumptions. This does not verify "
            "water quality, reservoir state, demand satisfaction, equipment "
            "constraints; confirm these "
            "before claiming achievable customer savings."
        ),
    }

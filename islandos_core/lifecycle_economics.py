"""Transparent project-level lifecycle economics for offline IslandOS studies.

All monetary inputs must use one consistent currency. Results are scenario estimates,
not quotes, financing advice, or guaranteed savings.
"""
from __future__ import annotations

from dataclasses import dataclass
import math


class LifecycleEconomicsError(ValueError):
    """Raised when lifecycle-economic assumptions are incomplete or invalid."""


def _finite(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LifecycleEconomicsError(f"{name} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise LifecycleEconomicsError(f"{name} must be finite")
    return number


def _finite_nonnegative(name: str, value: float) -> float:
    number = _finite(name, value)
    if number < 0:
        raise LifecycleEconomicsError(f"{name} must be >= 0")
    return number


@dataclass(frozen=True)
class LifecycleEconomicsInputs:
    """Annualized scenario inputs; costs are expressed in a common currency."""

    baseline_annual_energy_cost: float
    project_annual_energy_cost: float
    initial_capex: float
    project_years: int
    discount_rate: float = 0.08
    annual_fixed_om: float = 0.0
    annual_battery_efc: float | None = None
    battery_cycle_life_efc: float | None = None
    battery_capacity_kwh: float | None = None
    battery_replacement_cost_per_kwh: float | None = None

    def __post_init__(self) -> None:
        for name in (
            "baseline_annual_energy_cost", "project_annual_energy_cost",
            "initial_capex", "annual_fixed_om",
        ):
            (_finite(name, getattr(self, name)) if name.endswith("energy_cost")
             else _finite_nonnegative(name, getattr(self, name)))
        if isinstance(self.project_years, bool) or not isinstance(self.project_years, int):
            raise LifecycleEconomicsError("project_years must be an integer")
        if not 1 <= self.project_years <= 50:
            raise LifecycleEconomicsError("project_years must be between 1 and 50")
        rate = _finite_nonnegative("discount_rate", self.discount_rate)
        if rate >= 1:
            raise LifecycleEconomicsError("discount_rate must be < 1")
        battery_values = (
            self.annual_battery_efc, self.battery_cycle_life_efc,
            self.battery_capacity_kwh, self.battery_replacement_cost_per_kwh,
        )
        if any(value is not None for value in battery_values):
            if any(value is None for value in battery_values):
                raise LifecycleEconomicsError(
                    "battery replacement analysis requires annual EFC, cycle life, "
                    "capacity, and replacement cost per kWh"
                )
            for name, value in zip(
                ("annual_battery_efc", "battery_cycle_life_efc",
                 "battery_capacity_kwh", "battery_replacement_cost_per_kwh"),
                battery_values,
            ):
                _finite_nonnegative(name, value)
            if self.battery_cycle_life_efc <= 0:
                raise LifecycleEconomicsError("battery_cycle_life_efc must be > 0")
            if self.battery_capacity_kwh <= 0:
                raise LifecycleEconomicsError("battery_capacity_kwh must be > 0")


def evaluate_lifecycle_economics(inputs: LifecycleEconomicsInputs) -> dict:
    """Calculate project cashflows, NPV, simple payback and battery replacements.

    Battery replacements are modeled when cumulative annual equivalent full cycles
    reach the supplied cycle-life-to-end-of-life threshold. Replacement is charged
    at the end of the triggering year; the EFC counter then resets. This simple
    schedule excludes calendar aging, partial replacement, financing, taxes,
    inflation, degradation-driven dispatch changes and salvage value.
    """
    annual_savings_before_om = (
        inputs.baseline_annual_energy_cost - inputs.project_annual_energy_cost
    )
    annual_operating_savings = annual_savings_before_om - inputs.annual_fixed_om
    replacement_cost = 0.0
    replacements: list[int] = []
    cumulative_efc = 0.0
    if inputs.annual_battery_efc is not None:
        replacement_cost = (
            inputs.battery_capacity_kwh * inputs.battery_replacement_cost_per_kwh
        )

    cashflows = [-float(inputs.initial_capex)]
    cumulative_cashflow = cashflows[0]
    simple_payback_year = 0 if cumulative_cashflow >= 0 else None
    discounted_cashflows = [cashflows[0]]
    npv = cashflows[0]
    yearly_rows = []

    for year in range(1, inputs.project_years + 1):
        battery_replacement = 0.0
        if inputs.annual_battery_efc is not None:
            cumulative_efc += inputs.annual_battery_efc
            if cumulative_efc + 1e-12 >= inputs.battery_cycle_life_efc:
                battery_replacement = replacement_cost
                replacements.append(year)
                cumulative_efc = max(0.0, cumulative_efc - inputs.battery_cycle_life_efc)
        net_cashflow = annual_operating_savings - battery_replacement
        discount_factor = (1.0 + inputs.discount_rate) ** year
        discounted = net_cashflow / discount_factor
        cashflows.append(net_cashflow)
        discounted_cashflows.append(discounted)
        cumulative_cashflow += net_cashflow
        npv += discounted
        if simple_payback_year is None and cumulative_cashflow >= 0:
            simple_payback_year = year
        yearly_rows.append({
            "year": year,
            "baseline_annual_energy_cost": inputs.baseline_annual_energy_cost,
            "project_annual_energy_cost": inputs.project_annual_energy_cost,
            "annual_fixed_om": inputs.annual_fixed_om,
            "annual_operating_savings": annual_operating_savings,
            "battery_replacement_cost": battery_replacement,
            "battery_efc_at_year_end": cumulative_efc,
            "net_cashflow": net_cashflow,
            "discounted_cashflow": discounted,
            "cumulative_cashflow": cumulative_cashflow,
        })

    return {
        "currency_basis": "User-supplied common currency; no FX conversion performed",
        "project_years": inputs.project_years,
        "annual_savings_before_om": annual_savings_before_om,
        "annual_operating_savings": annual_operating_savings,
        "initial_capex": inputs.initial_capex,
        "battery_replacement_cost_per_event": replacement_cost,
        "battery_replacement_years": replacements,
        "battery_replacement_count": len(replacements),
        "simple_payback_year": simple_payback_year,
        "npv": npv,
        "cashflows": cashflows,
        "discounted_cashflows": discounted_cashflows,
        "yearly_rows": yearly_rows,
        "assumptions_and_exclusions": [
            "Annual energy costs are held constant across the project horizon",
            "Battery cycle aging is represented by an EFC threshold only",
            "Calendar and temperature aging are not modeled",
            "Battery degradation does not alter dispatch or annual energy costs",
            "Financing, taxes, inflation, salvage value and replacement downtime are excluded",
            "All monetary inputs must use the same currency and price basis",
        ],
    }

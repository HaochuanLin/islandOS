"""Transparent, assumption-led lifecycle economics for customer investment screening."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class InvestmentEconomics:
    service_equivalent: bool
    annual_energy_cost_saving: float | None
    annual_net_operating_benefit: float | None
    simple_payback_years: float | None
    discounted_payback_years: float | None
    net_present_value: float | None
    break_even_annual_energy_saving: float | None
    sensitivity_npv: dict[str, float] | None
    decision: str
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_investment_economics(
    *,
    baseline_annual_energy_cost: float,
    proposed_annual_energy_cost: float,
    annual_incremental_om_cost: float,
    upfront_capex: float,
    project_life_years: int,
    discount_rate: float,
    replacement_year: int | None = None,
    replacement_cost: float = 0.0,
    residual_value: float = 0.0,
    service_equivalent: bool,
) -> InvestmentEconomics:
    """Evaluate customer-entered annual costs; never annualize a single day.

    Annual incremental O&M is proposed O&M minus baseline O&M. Positive
    values increase operating cost. Energy bills must cover the same service.
    A non-equivalent service comparison is deliberately blocked.
    """
    values = {
        "baseline_annual_energy_cost": baseline_annual_energy_cost,
        "proposed_annual_energy_cost": proposed_annual_energy_cost,
        "annual_incremental_om_cost": annual_incremental_om_cost,
        "upfront_capex": upfront_capex,
        "discount_rate": discount_rate,
        "replacement_cost": replacement_cost,
        "residual_value": residual_value,
    }
    for name, value in values.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{name} must be a finite number")
    for name in (
        "baseline_annual_energy_cost",
        "proposed_annual_energy_cost",
        "upfront_capex",
        "replacement_cost",
        "residual_value",
    ):
        if values[name] < 0:
            raise ValueError(f"{name} cannot be negative")
    if not isinstance(service_equivalent, bool):
        raise ValueError("service_equivalent must be a boolean")
    if isinstance(project_life_years, bool) or not isinstance(project_life_years, int):
        raise ValueError("project_life_years must be an integer")
    if not 1 <= project_life_years <= 40:
        raise ValueError("project_life_years must be between 1 and 40")
    if not 0 <= discount_rate <= 0.5:
        raise ValueError("discount_rate must be between 0 and 0.5")
    if replacement_year is not None:
        if isinstance(replacement_year, bool) or not isinstance(replacement_year, int):
            raise ValueError("replacement_year must be an integer or None")
        if not 1 <= replacement_year <= project_life_years:
            raise ValueError("replacement_year must fall within the project life")
    if replacement_year is None and replacement_cost != 0:
        raise ValueError("replacement_cost requires replacement_year")

    if not service_equivalent:
        return InvestmentEconomics(
            service_equivalent=False,
            annual_energy_cost_saving=None,
            annual_net_operating_benefit=None,
            simple_payback_years=None,
            discounted_payback_years=None,
            net_present_value=None,
            break_even_annual_energy_saving=None,
            sensitivity_npv=None,
            decision="blocked",
            reasons=("Energy-cost comparison does not provide equivalent service; investment economics withheld.",),
        )

    annual_energy_saving = baseline_annual_energy_cost - proposed_annual_energy_cost
    annual_net = annual_energy_saving - annual_incremental_om_cost
    discount_factors = [
        1.0 / ((1.0 + discount_rate) ** year)
        for year in range(1, project_life_years + 1)
    ]
    annuity_factor = sum(discount_factors)
    replacement_pv = (
        replacement_cost / ((1.0 + discount_rate) ** replacement_year)
        if replacement_year is not None else 0.0
    )
    residual_pv = residual_value / ((1.0 + discount_rate) ** project_life_years)
    npv = -upfront_capex + annual_net * annuity_factor - replacement_pv + residual_pv

    simple_payback = upfront_capex / annual_net if annual_net > 0 else None
    discounted_cashflows = [-upfront_capex]
    for year, factor in enumerate(discount_factors, start=1):
        cashflow = annual_net
        if replacement_year == year:
            cashflow -= replacement_cost
        if year == project_life_years:
            cashflow += residual_value
        discounted_cashflows.append(cashflow * factor)
    cumulative = discounted_cashflows[0]
    discounted_payback = 0.0 if cumulative >= 0 else None
    for year in range(1, project_life_years + 1):
        previous = cumulative
        cumulative += discounted_cashflows[year]
        if discounted_payback is None and cumulative >= 0:
            increment = discounted_cashflows[year]
            fraction = (-previous / increment) if increment > 0 else 1.0
            discounted_payback = (year - 1) + min(1.0, max(0.0, fraction))

    break_even_saving = (
        (upfront_capex + replacement_pv - residual_pv) / annuity_factor
        + annual_incremental_om_cost
    )
    saving_delta = abs(annual_energy_saving) * 0.2
    low_saving = annual_energy_saving - saving_delta
    high_saving = annual_energy_saving + saving_delta
    sensitivity = {
        "low_20pct_energy_saving": -upfront_capex
        + (low_saving - annual_incremental_om_cost) * annuity_factor
        - replacement_pv + residual_pv,
        "base": npv,
        "high_20pct_energy_saving": -upfront_capex
        + (high_saving - annual_incremental_om_cost) * annuity_factor
        - replacement_pv + residual_pv,
    }
    reasons = []
    if annual_net <= 0:
        reasons.append("Annual energy saving does not cover incremental O&M cost.")
    if npv < 0:
        reasons.append("Net present value is negative under the entered assumptions.")
    if simple_payback is None or simple_payback > project_life_years:
        reasons.append("Simple payback is not achieved within the project life.")
    decision = "screen_positive" if npv >= 0 else "screen_negative"
    if annual_net <= 0:
        decision = "screen_negative"
    return InvestmentEconomics(
        service_equivalent=True,
        annual_energy_cost_saving=annual_energy_saving,
        annual_net_operating_benefit=annual_net,
        simple_payback_years=simple_payback,
        discounted_payback_years=discounted_payback,
        net_present_value=npv,
        break_even_annual_energy_saving=break_even_saving,
        sensitivity_npv=sensitivity,
        decision=decision,
        reasons=tuple(reasons) or ("Positive screening NPV under entered assumptions; validate all inputs before procurement.",),
    )

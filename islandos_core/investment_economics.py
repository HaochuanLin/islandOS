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
    annual_cashflows: tuple[dict[str, float], ...] | None
    decision: str
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _payback_year(cashflows: list[float], discount_rate: float | None = None) -> float | None:
    cumulative = -cashflows[0]
    if cumulative <= 0:
        return 0.0
    for year, amount in enumerate(cashflows[1:], start=1):
        discounted = amount / ((1.0 + discount_rate) ** year) if discount_rate is not None else amount
        previous = cumulative
        cumulative += discounted
        if cumulative >= 0:
            fraction = (-previous / discounted) if discounted > 0 else 1.0
            return (year - 1) + min(1.0, max(0.0, fraction))
    return None


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
    annual_energy_saving_escalation_rate: float = 0.0,
    annual_om_escalation_rate: float = 0.0,
    service_equivalent: bool,
) -> InvestmentEconomics:
    """Evaluate customer-entered annual costs with year-by-year cashflows.

    Energy-bill saving and incremental O&M are year-one values. Their
    escalation rates are explicit assumptions applied from year two onward.
    Annual bills must cover equivalent service; a failed service gate blocks
    every investment metric. A single simulated day is never annualized.
    """
    values = {
        "baseline_annual_energy_cost": baseline_annual_energy_cost,
        "proposed_annual_energy_cost": proposed_annual_energy_cost,
        "annual_incremental_om_cost": annual_incremental_om_cost,
        "upfront_capex": upfront_capex,
        "discount_rate": discount_rate,
        "replacement_cost": replacement_cost,
        "residual_value": residual_value,
        "annual_energy_saving_escalation_rate": annual_energy_saving_escalation_rate,
        "annual_om_escalation_rate": annual_om_escalation_rate,
    }
    for name, value in values.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{name} must be a finite number")
    for name in (
        "baseline_annual_energy_cost", "proposed_annual_energy_cost",
        "upfront_capex", "replacement_cost", "residual_value",
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
    for name in ("annual_energy_saving_escalation_rate", "annual_om_escalation_rate"):
        if not -0.5 <= values[name] <= 1.0:
            raise ValueError(f"{name} must be between -0.5 and 1.0")
    if replacement_year is not None:
        if isinstance(replacement_year, bool) or not isinstance(replacement_year, int):
            raise ValueError("replacement_year must be an integer or None")
        if not 1 <= replacement_year <= project_life_years:
            raise ValueError("replacement_year must fall within the project life")
    if replacement_year is None and replacement_cost != 0:
        raise ValueError("replacement_cost requires replacement_year")

    if not service_equivalent:
        return InvestmentEconomics(
            service_equivalent=False, annual_energy_cost_saving=None,
            annual_net_operating_benefit=None, simple_payback_years=None,
            discounted_payback_years=None, net_present_value=None,
            break_even_annual_energy_saving=None, sensitivity_npv=None,
            annual_cashflows=None, decision="blocked",
            reasons=("Energy-cost comparison does not provide equivalent service; investment economics withheld.",),
        )

    annual_energy_saving = baseline_annual_energy_cost - proposed_annual_energy_cost
    annual_net = annual_energy_saving - annual_incremental_om_cost
    cashflows = [-float(upfront_capex)]
    rows: list[dict[str, float]] = []
    pv_energy_factor = 0.0
    pv_om_factor = 0.0
    replacement_pv = 0.0
    for year in range(1, project_life_years + 1):
        energy_saving = annual_energy_saving * ((1.0 + annual_energy_saving_escalation_rate) ** (year - 1))
        om_cost = annual_incremental_om_cost * ((1.0 + annual_om_escalation_rate) ** (year - 1))
        replacement = replacement_cost if replacement_year == year else 0.0
        residual = residual_value if year == project_life_years else 0.0
        operating_benefit = energy_saving - om_cost
        net_cashflow = operating_benefit - replacement + residual
        factor = 1.0 / ((1.0 + discount_rate) ** year)
        pv_energy_factor += ((1.0 + annual_energy_saving_escalation_rate) ** (year - 1)) * factor
        pv_om_factor += ((1.0 + annual_om_escalation_rate) ** (year - 1)) * factor
        replacement_pv += replacement * factor
        cashflows.append(net_cashflow)
        rows.append({
            "year": float(year), "energy_bill_saving": energy_saving,
            "incremental_om_cost": om_cost, "replacement_cost": replacement,
            "residual_value": residual, "net_cashflow": net_cashflow,
            "discounted_net_cashflow": net_cashflow * factor,
        })
    residual_pv = residual_value / ((1.0 + discount_rate) ** project_life_years)
    npv = -upfront_capex + annual_energy_saving * pv_energy_factor - annual_incremental_om_cost * pv_om_factor - replacement_pv + residual_pv
    simple_payback = _payback_year(cashflows)
    discounted_payback = _payback_year(cashflows, discount_rate)
    break_even_saving = (upfront_capex + replacement_pv - residual_pv + annual_incremental_om_cost * pv_om_factor) / pv_energy_factor

    sensitivity = {}
    for label, multiplier in (("low_20pct_energy_saving", 0.8), ("base", 1.0), ("high_20pct_energy_saving", 1.2)):
        sensitivity[label] = (
            -upfront_capex + annual_energy_saving * multiplier * pv_energy_factor
            - annual_incremental_om_cost * pv_om_factor - replacement_pv + residual_pv
        )

    reasons = []
    if annual_net <= 0:
        reasons.append("Year-one energy saving does not cover year-one incremental O&M cost.")
    if npv < 0:
        reasons.append("Net present value is negative under the entered assumptions.")
    if simple_payback is None:
        reasons.append("Simple payback is not achieved within the project life.")
    decision = "screen_positive" if npv >= 0 and annual_net > 0 else "screen_negative"
    return InvestmentEconomics(
        service_equivalent=True, annual_energy_cost_saving=annual_energy_saving,
        annual_net_operating_benefit=annual_net, simple_payback_years=simple_payback,
        discounted_payback_years=discounted_payback, net_present_value=npv,
        break_even_annual_energy_saving=break_even_saving,
        sensitivity_npv=sensitivity, annual_cashflows=tuple(rows),
        decision=decision,
        reasons=tuple(reasons) or ("Positive screening NPV under entered assumptions; validate all inputs before procurement.",),
    )

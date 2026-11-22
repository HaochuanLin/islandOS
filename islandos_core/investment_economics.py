"""Transparent, assumption-led lifecycle economics for customer investment screening."""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from typing import Any, Mapping


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
    cumulative = cashflows[0]
    if cumulative >= 0:
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
    simple_payback = _payback_year(cashflows) if annual_net > 0 else None
    discounted_payback = _payback_year(cashflows, discount_rate) if annual_net > 0 else None
    break_even_saving = (upfront_capex + replacement_pv - residual_pv + annual_incremental_om_cost * pv_om_factor) / pv_energy_factor

    sensitivity = {}
    for label, delta in (("low_20pct_energy_saving", -0.2), ("base", 0.0), ("high_20pct_energy_saving", 0.2)):
        scenario_saving = annual_energy_saving + abs(annual_energy_saving) * delta
        sensitivity[label] = (
            -upfront_capex + scenario_saving * pv_energy_factor
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


MANIFEST_RECORD_TYPE = "islandos_canonical_run_manifest"
BINDING_RECORD_TYPE = "investment_economics_run_binding"


def _canonical(payload: Mapping) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def bind_annual_economics_to_run(
    economics: InvestmentEconomics,
    manifest: Mapping,
    *,
    annual_bill_source: str = "customer_entered_annual_bills",
    annual_bill_period_utc: tuple[str, str] | None = None,
) -> dict:
    """Attach an annual evaluation to the run whose equipment and service it describes.

    This is a citation, not a derivation: the annual bills are entered by the
    customer, so the binding records ``derived_from_run: false`` and keeps the
    run's digests only as the context a reader checks the figures against.
    """
    if not isinstance(economics, InvestmentEconomics):
        raise TypeError("economics must be an InvestmentEconomics result")
    if not isinstance(manifest, Mapping):
        raise TypeError("manifest must be the canonical run manifest mapping")
    if manifest.get("record_type") != MANIFEST_RECORD_TYPE:
        raise ValueError("manifest must be a canonical run manifest")
    for name in ("run_id", "site_ref", "manifest_sha256"):
        value = manifest.get(name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"manifest is missing {name}")
    dataset = manifest.get("dataset")
    if not isinstance(dataset, Mapping):
        raise ValueError("manifest is missing its dataset block")
    for name in ("sha256", "source_type"):
        value = dataset.get(name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"manifest dataset is missing {name}")
    if not isinstance(annual_bill_source, str) or not annual_bill_source.strip():
        raise ValueError("annual_bill_source must be a non-empty string")
    if annual_bill_period_utc is not None:
        if (not isinstance(annual_bill_period_utc, tuple) or len(annual_bill_period_utc) != 2
                or not all(isinstance(item, str) and item.strip() for item in annual_bill_period_utc)):
            raise ValueError("annual_bill_period_utc must be a pair of ISO-8601 timestamps")

    binding = {
        "schema_version": 1,
        "record_type": BINDING_RECORD_TYPE,
        "run_id": manifest["run_id"],
        "site_ref": manifest["site_ref"],
        "manifest_sha256": manifest["manifest_sha256"],
        "dataset_sha256": dataset["sha256"],
        "dataset_source_type": dataset["source_type"],
        "annual_basis": {
            "source": annual_bill_source,
            "period_utc": list(annual_bill_period_utc) if annual_bill_period_utc else None,
            "derived_from_run": False,
            "annualisation": (
                "customer-entered annual bills tied to this run's equipment and service scope; "
                "this screen never turns a simulated day into the bills it screens"
            ),
        },
        "service_equivalent": economics.service_equivalent,
        "withheld": economics.service_equivalent is False,
        "decision": economics.decision,
        "economics": economics.to_dict(),
        "device_write_authorized": False,
        "command_generated": False,
    }
    binding["binding_sha256"] = _sha256(_canonical(binding))
    return binding


def verify_investment_economics_binding(binding: Mapping) -> dict:
    """Fail-closed checks for a binding that a report or UI may quote."""
    errors: list[str] = []
    if not isinstance(binding, Mapping) or binding.get("record_type") != BINDING_RECORD_TYPE:
        return {"valid": False, "errors": ["binding is not an investment economics run binding"]}
    payload = {key: value for key, value in binding.items() if key != "binding_sha256"}
    digest = binding.get("binding_sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        errors.append("binding_sha256 must be a 64-character digest")
    else:
        try:
            if _sha256(_canonical(payload)) != digest:
                errors.append("binding_sha256 does not match the binding contents")
        except (TypeError, ValueError) as exc:
            errors.append(f"binding contents are not canonical JSON: {exc}")
    if binding.get("device_write_authorized") is not False:
        errors.append("binding must never authorize a device write")
    if binding.get("command_generated") is not False:
        errors.append("binding must never claim a generated command")
    basis = binding.get("annual_basis")
    if not isinstance(basis, Mapping) or basis.get("derived_from_run") is not False:
        errors.append("annual figures must be marked as entered, not derived from the run")
    if binding.get("withheld") is not True and binding.get("decision") == "blocked":
        errors.append("a blocked economics result must be marked withheld")
    return {"valid": not errors, "errors": errors}

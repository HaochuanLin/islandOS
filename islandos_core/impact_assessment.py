"""Paired, auditable impact assessment for existing energy dispatch policies.

This module is an evidence/reporting layer over the canonical energy-system
simulator. It does not implement another optimizer or cost engine. It runs
both supported policies on the exact same EnergySystemInputs and
EnergySystemConfig, audits returned dispatch rows, and withholds cost benefits
unless service equivalence and the supported equipment checks pass.
"""
from __future__ import annotations

import math
from numbers import Real
from typing import Mapping

from .energy_system import (
    EnergySystemConfig,
    EnergySystemInputs,
    compare_energy_policies,
)


class ImpactAssessmentError(ValueError):
    """Raised when paired impact inputs or dispatch evidence are invalid."""


def _finite_number(value: object, name: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ImpactAssessmentError(f"{name} must be a finite numeric value")
    number = float(value)
    if not math.isfinite(number):
        raise ImpactAssessmentError(f"{name} must be a finite numeric value")
    if minimum is not None and number < minimum:
        raise ImpactAssessmentError(f"{name} must be >= {minimum}")
    return number


def _audit_dispatch(dispatch: Mapping, config: EnergySystemConfig, label: str) -> dict:
    if not isinstance(dispatch, Mapping):
        raise ImpactAssessmentError(f"{label} dispatch must be a mapping")
    rows = dispatch.get("rows")
    summary = dispatch.get("summary")
    if not isinstance(rows, list) or not rows:
        raise ImpactAssessmentError(f"{label} dispatch must contain non-empty rows")
    if not isinstance(summary, Mapping):
        raise ImpactAssessmentError(f"{label} dispatch must contain a summary")
    if dispatch.get("time_steps") != len(rows):
        raise ImpactAssessmentError(f"{label} dispatch time_steps does not match rows")

    violations: list[str] = []
    dt = _finite_number(dispatch.get("dt_hours"), f"{label}.dt_hours", minimum=1e-12)
    tolerance = 1e-6
    previous_diesel_kw = 0.0
    required_row_fields = (
        "energy_balance_residual_kw",
        "grid_import_kw",
        "diesel_generation_kw",
        "renewable_curtailed_kw",
        "battery_charge_kw",
        "battery_discharge_kw",
        "battery_soc",
        "critical_unmet_kw",
        "flexible_load_shed_kw",
    )
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            violations.append(f"row {index}: not a mapping")
            continue
        values = {}
        for field in required_row_fields:
            try:
                values[field] = _finite_number(row.get(field), f"{label}.rows[{index}].{field}")
            except ImpactAssessmentError as exc:
                violations.append(str(exc))
        if len(values) != len(required_row_fields):
            continue

        if abs(values["energy_balance_residual_kw"]) > tolerance:
            violations.append(f"row {index}: energy balance residual exceeds tolerance")
        for field in (
            "grid_import_kw", "diesel_generation_kw", "renewable_curtailed_kw",
            "battery_charge_kw", "battery_discharge_kw",
            "critical_unmet_kw", "flexible_load_shed_kw",
        ):
            if values[field] < -tolerance:
                violations.append(f"row {index}: {field} is negative")

        if values["grid_import_kw"] > config.grid_import_limit_kw + tolerance:
            violations.append(f"row {index}: grid import exceeds configured limit")
        if config.battery is None:
            if values["battery_charge_kw"] > tolerance or values["battery_discharge_kw"] > tolerance:
                violations.append(f"row {index}: battery dispatch exists without a configured battery")
            if abs(values["battery_soc"]) > tolerance:
                violations.append(f"row {index}: battery SOC exists without a configured battery")
        else:
            battery = config.battery
            if values["battery_charge_kw"] > battery.max_charge_kw + tolerance:
                violations.append(f"row {index}: battery charge exceeds configured limit")
            if values["battery_discharge_kw"] > battery.max_discharge_kw + tolerance:
                violations.append(f"row {index}: battery discharge exceeds configured limit")
            if not battery.min_soc - tolerance <= values["battery_soc"] <= battery.max_soc + tolerance:
                violations.append(f"row {index}: battery SOC is outside configured bounds")

        diesel_kw = values["diesel_generation_kw"]
        if config.diesel is None:
            if diesel_kw > tolerance:
                violations.append(f"row {index}: diesel dispatch exists without a configured diesel unit")
        else:
            diesel = config.diesel
            if diesel_kw > diesel.rated_power_kw + tolerance:
                violations.append(f"row {index}: diesel output exceeds rated power")
            if tolerance < diesel_kw < diesel.min_stable_power_kw - tolerance:
                violations.append(f"row {index}: diesel output is below minimum stable power")
            if index > 0:
                if (
                    diesel.ramp_up_kw_per_hour is not None
                    and diesel_kw > previous_diesel_kw + diesel.ramp_up_kw_per_hour * dt + tolerance
                    and not bool(row.get("diesel_started"))
                ):
                    violations.append(f"row {index}: diesel ramp-up limit exceeded")
                if (
                    diesel.ramp_down_kw_per_hour is not None
                    and previous_diesel_kw > diesel_kw + diesel.ramp_down_kw_per_hour * dt + tolerance
                ):
                    violations.append(f"row {index}: diesel ramp-down limit exceeded")
        previous_diesel_kw = diesel_kw

    if not violations:
        # Summary aggregates used below must also be finite and non-negative.
        for key in (
            "load_energy_kwh", "critical_load_energy_kwh", "flexible_load_energy_kwh",
            "critical_unmet_load_kwh", "flexible_load_shed_kwh",
            "grid_import_kwh", "diesel_generation_kwh", "renewable_curtailed_kwh",
            "pv_energy_kwh", "wind_energy_kwh", "estimated_energy_cost",
        ):
            _finite_number(summary.get(key), f"{label}.summary.{key}", minimum=0.0)
    return {
        "passed": not violations,
        "violation_count": len(violations),
        "violations": violations,
        "checks": [
            "per-step energy balance residual",
            "grid import limit",
            "battery power and SOC limits",
            "diesel rating and configured ramp limits",
            "non-negative served-service and curtailment quantities",
        ],
        "scope_limit": (
            "This reporting audit covers the checks listed above. It does not "
            "replace independent site engineering review, protection studies, "
            "network power-flow analysis, or a complete asset-specific safety audit."
        ),
    }


def calculate_net_customer_value(
    gross_operating_benefit: float,
    commercial_costs: Mapping[str, object],
    *,
    currency: str,
    evaluation_period: str,
) -> dict:
    """Subtract customer-entered costs on the same currency and time basis."""
    gross = _finite_number(gross_operating_benefit, "gross_operating_benefit")
    if not isinstance(commercial_costs, Mapping):
        raise ImpactAssessmentError("commercial_costs must be a mapping")
    if not isinstance(currency, str) or not currency.strip():
        raise ImpactAssessmentError("currency must be a non-empty label")
    if not isinstance(evaluation_period, str) or not evaluation_period.strip():
        raise ImpactAssessmentError("evaluation_period must be a non-empty label")
    if commercial_costs.get("currency") != currency:
        raise ImpactAssessmentError("commercial costs must use the dispatch comparison currency")
    if commercial_costs.get("evaluation_period") != evaluation_period:
        raise ImpactAssessmentError("commercial costs must use the same evaluation period as gross benefit")

    fields = ("software_cost", "integration_cost", "maintenance_cost", "training_cost")
    amounts = {
        field: _finite_number(commercial_costs.get(field), field, minimum=0.0)
        for field in fields
    }
    total = sum(amounts.values())
    return {
        "currency": currency,
        "evaluation_period": evaluation_period,
        "gross_operating_benefit": gross,
        **amounts,
        "total_commercial_cost": total,
        "net_customer_value": gross - total,
        "calculation_status": "calculated_from_explicit_assumptions",
        "evidence_classification": "customer_cost_inputs_not_independently_verified",
    }


def assess_energy_policy_impact(
    inputs: EnergySystemInputs,
    config: EnergySystemConfig,
    *,
    currency: str,
    evaluation_period: str,
    data_provenance: str,
    commercial_costs: Mapping[str, object] | None = None,
) -> dict:
    """Run paired grid-first/battery-first dispatch and produce an impact report.

    Both policies are executed by compare_energy_policies() with the same input
    object and equipment configuration. Water-service metrics are omitted
    because this energy dispatch interface has no water-demand or tank state.
    """
    if not isinstance(currency, str) or not currency.strip():
        raise ImpactAssessmentError("currency must be a non-empty label")
    if not isinstance(evaluation_period, str) or not evaluation_period.strip():
        raise ImpactAssessmentError("evaluation_period must be a non-empty label")
    if not isinstance(data_provenance, str) or not data_provenance.strip():
        raise ImpactAssessmentError("data_provenance must be a non-empty label")

    comparison = compare_energy_policies(inputs, config)
    baseline = comparison["grid_first"]
    candidate = comparison["battery_first"]
    baseline_audit = _audit_dispatch(baseline, config, "baseline")
    candidate_audit = _audit_dispatch(candidate, config, "candidate")

    base = baseline["summary"]
    proposed = candidate["summary"]
    if baseline["time_steps"] != candidate["time_steps"] or not math.isclose(
        baseline["dt_hours"], candidate["dt_hours"], rel_tol=0.0, abs_tol=1e-12
    ):
        raise ImpactAssessmentError("paired policies do not share the same time horizon and timestep")

    equivalent_fields = (
        "load_energy_kwh",
        "critical_load_energy_kwh",
        "flexible_load_energy_kwh",
        "critical_unmet_load_kwh",
        "flexible_load_shed_kwh",
    )
    service_differences = {
        key: round(float(proposed[key]) - float(base[key]), 8)
        for key in equivalent_fields
    }
    service_equivalent = all(abs(value) <= 1e-6 for value in service_differences.values())
    audited = baseline_audit["passed"] and candidate_audit["passed"]
    gross_benefit = (
        round(float(base["estimated_energy_cost"]) - float(proposed["estimated_energy_cost"]), 8)
        if service_equivalent and audited else None
    )

    def metrics(dispatch: Mapping, summary: Mapping) -> dict:
        renewable = float(summary["pv_energy_kwh"]) + float(summary["wind_energy_kwh"])
        curtailed = float(summary["renewable_curtailed_kwh"])
        fuel_model = dispatch.get("model_scope", {}).get("diesel_fuel_consumption_model", "not_configured")
        return {
            "estimated_energy_cost": float(summary["estimated_energy_cost"]),
            "grid_import_kwh": float(summary["grid_import_kwh"]),
            "diesel_generation_kwh": float(summary["diesel_generation_kwh"]),
            "diesel_fuel_used_liters": (
                float(summary["diesel_fuel_used_liters"])
                if fuel_model != "not_configured" and summary.get("diesel_fuel_used_liters") is not None
                else None
            ),
            "renewable_generation_kwh": renewable,
            "renewable_utilised_kwh": max(0.0, renewable - curtailed),
            "renewable_utilisation_fraction": (
                max(0.0, renewable - curtailed) / renewable if renewable > 0 else None
            ),
            "renewable_curtailed_kwh": curtailed,
            "critical_load_energy_kwh": float(summary["critical_load_energy_kwh"]),
            "critical_unmet_load_kwh": float(summary["critical_unmet_load_kwh"]),
            "critical_service_reliability_fraction": (
                max(0.0, 1.0 - float(summary["critical_unmet_load_fraction"]))
                if summary["critical_load_energy_kwh"] > 0 else None
            ),
            "flexible_load_requested_kwh": float(summary["flexible_load_energy_kwh"]),
            "flexible_load_shed_kwh": float(summary["flexible_load_shed_kwh"]),
            "flexible_load_served_kwh": max(
                0.0,
                float(summary["flexible_load_energy_kwh"]) - float(summary["flexible_load_shed_kwh"]),
            ),
        }

    report = {
        "schema_version": "1.0",
        "method": "paired deterministic dispatch policy comparison",
        "baseline_policy": "grid_first",
        "candidate_policy": "battery_first",
        "candidate_is_optimizer": False,
        "same_inputs_and_equipment_configuration": True,
        "currency": currency,
        "evaluation_period": evaluation_period,
        "data_provenance": data_provenance,
        "evidence_classification": "synthetic_model_output" if "synthetic" in data_provenance.lower() else "modelled_output_from_caller_supplied_data",
        "baseline_metrics": metrics(baseline, base),
        "candidate_metrics": metrics(candidate, proposed),
        "service_equivalence": {
            "passed": service_equivalent,
            "tolerance": 1e-6,
            "differences": service_differences,
        },
        "equipment_constraint_audit": {
            "passed": audited,
            "baseline": baseline_audit,
            "candidate": candidate_audit,
        },
        "gross_operating_benefit": {
            "value": gross_benefit,
            "currency": currency,
            "evaluation_period": evaluation_period,
            "status": "qualified" if gross_benefit is not None else "withheld",
            "interpretation": (
                "Baseline estimated energy cost minus candidate estimated energy cost. "
                "This is a modelled comparison, not verified customer savings."
            ),
        },
        "commercial_costs": None,
        "net_customer_value": None,
        "not_evaluated_metrics": [
            "water production, water demand satisfaction and tank inventory (not present in this dispatch interface)",
            "emissions (no emissions factors are supplied to this dispatch interface)",
            "software, integration, maintenance and training costs (not supplied)",
        ],
        "interpretation_limits": [
            "The two policies are existing rule-based priorities, not optimized schedules.",
            "The reporting audit covers only the explicitly listed output checks and is not a site engineering approval.",
            "Diesel fuel litres are omitted when no fuel-consumption model is configured.",
            "Renewable utilised energy is calculated as renewable generation minus curtailment; it includes energy exported to the grid.",
            "A single scenario horizon is not annualized.",
            "Synthetic results do not establish customer demand, site performance, savings or willingness to pay.",
            "No water-service, network power-flow, emissions or live-control claim is made.",
        ],
    }
    if commercial_costs is not None:
        if gross_benefit is None:
            raise ImpactAssessmentError(
                "commercial net value cannot be calculated when service equivalence or equipment audit fails"
            )
        net_value = calculate_net_customer_value(
            gross_benefit,
            commercial_costs,
            currency=currency,
            evaluation_period=evaluation_period,
        )
        report["commercial_costs"] = dict(commercial_costs)
        report["net_customer_value"] = net_value
    return report

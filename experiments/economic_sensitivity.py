"""One-factor economic sensitivity for a fixed, audited Pareto candidate set.

This tool re-prices candidates from a completed annualized-cost optimization
report. It does not rerun the optimizer; that limitation is recorded explicitly.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime
from pathlib import Path
import statistics
from typing import Any

ECONOMIC_FIELDS = (
    ("electricity_price_per_kwh", "Electricity opportunity price"),
    ("ro_capex", "RO capital cost"),
    ("ro_fixed_om_per_year", "RO fixed O&M"),
    ("ro_variable_om_per_m3", "RO variable O&M per m³"),
    ("chiller_capex", "Chiller capital cost"),
    ("chiller_fixed_om_per_year", "Chiller fixed O&M"),
    ("analysis_years", "Analysis lifetime"),
    ("discount_rate", "Discount rate"),
)
REQUIRED_COST_FIELDS = tuple(field for field, _ in ECONOMIC_FIELDS)


def _capital_recovery_factor(rate: float, years: int) -> float:
    if years < 1:
        raise ValueError("analysis_years must be a positive integer")
    if not math.isfinite(rate) or not 0 <= rate < 1:
        raise ValueError("discount_rate must be finite and in [0, 1)")
    if rate == 0:
        return 1.0 / years
    growth = (1.0 + rate) ** years
    return rate * growth / (growth - 1.0)


def _annual_cost(candidate_breakdown: dict[str, Any], economics: dict[str, Any]) -> float:
    energy = float(candidate_breakdown["annual_energy_used_by_flexible_loads_kwh"])
    water = float(candidate_breakdown["annual_water_produced_m3"])
    years_value = economics["analysis_years"]
    if isinstance(years_value, bool) or not isinstance(years_value, int) or years_value < 1:
        raise ValueError("analysis_years must be a positive integer")
    rate = float(economics["discount_rate"])
    crf = _capital_recovery_factor(rate, years_value)
    capex = float(economics["ro_capex"]) + float(economics["chiller_capex"])
    fixed_om = (
        float(economics["ro_fixed_om_per_year"])
        + float(economics["chiller_fixed_om_per_year"])
    )
    variable_om = water * float(economics["ro_variable_om_per_m3"])
    electricity = energy * float(economics["electricity_price_per_kwh"])
    values = (capex * crf, fixed_om, variable_om, electricity)
    if any(not math.isfinite(value) or value < 0 for value in values):
        raise ValueError("cost components must be finite and non-negative")
    return sum(values)


def _summarize(values: list[float]) -> dict[str, float]:
    if not values:
        raise ValueError("at least one Pareto candidate with cost breakdown is required")
    return {
        "min": min(values),
        "median": statistics.median(values),
        "max": max(values),
    }


def run_economic_sensitivity(
    candidate_report_json: str | Path,
    output_json: str | Path,
    *,
    relative_change: float = 0.2,
) -> dict:
    """Re-price baseline Pareto candidates under one-at-a-time economic changes."""
    if not math.isfinite(relative_change) or not 0 < relative_change < 1:
        raise ValueError("relative_change must be finite and strictly between 0 and 1")

    source = Path(candidate_report_json)
    report = json.loads(source.read_text(encoding="utf-8"))
    configuration = report.get("parameter_configuration", {})
    economics = configuration.get("economics")
    optimization = report.get("optimization", {})
    candidates = optimization.get("pareto_front")
    if not isinstance(economics, dict) or not isinstance(candidates, list) or not candidates:
        raise ValueError("input must be a run_nsga2_from_csv report with a non-empty Pareto front")
    if configuration.get("economics_completeness", {}).get("complete_for_current_declared_fields") is not True:
        raise ValueError("base report must have the lifecycle-cost objective enabled")
    if optimization.get("cost_objective_enabled") is not True:
        raise ValueError("base report does not mark the lifecycle-cost objective as enabled")
    input_summary = report.get("input_summary", {})
    row_count = input_summary.get("row_count")
    if input_summary.get("quality_status") != "valid" or row_count not in (8760, 8784):
        raise ValueError("base report must contain a valid complete-calendar-year input summary")
    try:
        first = datetime.fromisoformat(
            input_summary["first_timestamp"].replace("Z", "+00:00")
        )
        last = __import__("datetime").datetime.fromisoformat(
            input_summary["last_timestamp"].replace("Z", "+00:00")
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("base report must include parseable first/last timestamps") from exc
    leap_year = first.year % 4 == 0 and (first.year % 100 != 0 or first.year % 400 == 0)
    expected_hours = 8784 if leap_year else 8760
    if (
        row_count != expected_hours
        or last.year != first.year
        or (first.month, first.day, first.hour, first.minute) != (1, 1, 0, 0)
        or (last.month, last.day, last.hour, last.minute) != (12, 31, 23, 0)
    ):
        raise ValueError("base report does not span one complete calendar year")
    missing = [key for key in REQUIRED_COST_FIELDS if economics.get(key) is None]
    if missing:
        raise ValueError("base report has missing economic fields: " + ", ".join(missing))
    if not isinstance(economics.get("currency"), str) or not economics["currency"].strip():
        raise ValueError("economics.currency must be a non-empty label")

    candidate_records = []
    for index, candidate in enumerate(candidates):
        breakdown = candidate.get("cost_breakdown")
        objective = candidate.get("objectives", {}).get("annualized_lifecycle_cost_per_year")
        if not isinstance(breakdown, dict) or objective is None:
            raise ValueError(f"Pareto candidate {index} lacks a lifecycle-cost breakdown")
        calculated = _annual_cost(breakdown, economics)
        if not math.isclose(calculated, float(objective), rel_tol=1e-8, abs_tol=1e-6):
            raise ValueError(
                f"Candidate {index} cost breakdown does not match its stored objective "
                f"({calculated} vs {objective})"
            )
        candidate_records.append({
            "candidate_index": index,
            "policy": candidate.get("parameters", {}).get("priority"),
            "ro_rated_power_kw": candidate.get("parameters", {}).get("ro_rated_power_kw"),
            "ice_rated_power_kw": candidate.get("parameters", {}).get("ice_rated_power_kw"),
            "breakdown": breakdown,
            "baseline_annual_cost": calculated,
        })

    baseline_costs = [item["baseline_annual_cost"] for item in candidate_records]
    scenarios = []
    skipped = []
    for field, label in ECONOMIC_FIELDS:
        baseline_value = economics[field]
        value = float(baseline_value)
        if value == 0:
            skipped.append({
                "parameter": field,
                "reason": "baseline value is zero; proportional perturbation would not change it",
            })
            continue
        if field == "analysis_years":
            low = max(1, int(round(value * (1.0 - relative_change))))
            high = max(1, int(round(value * (1.0 + relative_change))))
        else:
            low = max(0.0, value * (1.0 - relative_change))
            high = value * (1.0 + relative_change)
            if field == "discount_rate":
                high = min(high, 1.0 - 1e-9)

        for direction, tested_value in (("low", low), ("high", high)):
            if tested_value == baseline_value:
                skipped.append({
                    "parameter": field,
                    "direction": direction,
                    "reason": "rounded/clamped perturbation equals baseline",
                })
                continue
            variant = dict(economics)
            variant[field] = tested_value
            variant_costs = [
                _annual_cost(item["breakdown"], variant) for item in candidate_records
            ]
            deltas = [
                ((new - old_cost) / old_cost * 100.0) if old_cost > 0 else 0.0
                for old_cost, new in zip(baseline_costs, variant_costs)
            ]
            scenarios.append({
                "parameter": field,
                "label": label,
                "direction": direction,
                "baseline_value": baseline_value,
                "tested_value": tested_value,
                "currency": economics["currency"],
                "candidate_count": len(variant_costs),
                "annual_cost": _summarize(variant_costs),
                "delta_percent_from_baseline": _summarize(deltas),
                "candidate_costs": [
                    {
                        "candidate_index": item["candidate_index"],
                        "policy": item["policy"],
                        "annual_cost": cost,
                    }
                    for item, cost in zip(candidate_records, variant_costs)
                ],
            })

    result = {
        "project": "IslandOS",
        "method": "one-factor-at-a-time fixed-candidate economic sensitivity",
        "input_report": source.name,
        "currency": economics["currency"],
        "relative_change_requested": relative_change,
        "base_economic_assumptions": {key: economics[key] for key in REQUIRED_COST_FIELDS},
        "baseline_candidate_count": len(candidate_records),
        "baseline_annual_cost": _summarize(baseline_costs),
        "scenarios": scenarios,
        "skipped_scenarios": skipped,
        "interpretation_limits": [
            "Only candidates in the baseline report's Pareto front are re-priced; the optimizer is not rerun.",
            "Candidates that become non-dominated under alternate costs but were absent from the baseline front cannot appear in this report.",
            "The result is conditional on the input report, representative-year assumption, simplified cost formula, and supplied economic assumptions.",
            "This is not a bankable financial model; taxes, financing, replacements, backup generation, demand charges, emissions, and unmet-service penalties remain outside scope.",
            "Sensitivity shows how assumptions affect modeled annualized costs; it does not assign probabilities to assumptions or prove which value is correct.",
        ],
    }
    destination = Path(output_json)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate_report_json", help="JSON from run_nsga2_from_csv.py with lifecycle cost enabled")
    parser.add_argument("--relative-change", type=float, default=0.2, help="Proportional low/high perturbation, e.g. 0.2 for ±20%%")
    parser.add_argument("--output", default="build/economic-sensitivity.json")
    args = parser.parse_args()
    result = run_economic_sensitivity(
        args.candidate_report_json, args.output, relative_change=args.relative_change
    )
    print(json.dumps({
        "output": str(Path(args.output)),
        "method": result["method"],
        "baseline_candidate_count": result["baseline_candidate_count"],
        "scenario_count": len(result["scenarios"]),
        "skipped_scenario_count": len(result["skipped_scenarios"]),
        "baseline_annual_cost": result["baseline_annual_cost"],
        "limitations": result["interpretation_limits"],
    }, indent=2))


if __name__ == "__main__":
    main()

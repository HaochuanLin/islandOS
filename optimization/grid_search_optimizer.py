"""Small, transparent grid-search optimizer over dispatch-policy parameters.

This is an optimization baseline, not AI/ML and not a global search over all
possible hourly schedules. It evaluates every candidate with the same
shared-budget simulator, builds a Pareto archive from those evaluated results,
and chooses a recommendation from that archive using an explicit weighted
score. Inputs are synthetic; results are not field evidence.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dispatch_engine import dispatch_flexible_loads
from experiments.compare_dispatch_policies import (
    Scenario, build_scenarios, make_ice, summarize,
)
from flexible_loads import ROConfig, ROWaterLoad


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    priority: str
    ro_min_run_hours: int


def candidates() -> list[Candidate]:
    """Finite, explicit search space: two priorities x four RO minimum-run durations."""
    return [
        Candidate(
            candidate_id=f"{priority}_run{min_run}h",
            priority=priority,
            ro_min_run_hours=min_run,
        )
        for priority in ("ro_first", "ice_first")
        for min_run in (1, 2, 3, 4)
    ]


def evaluate_candidate(scenario: Scenario, candidate: Candidate) -> dict:
    ro = ROWaterLoad(ROConfig(
        rated_power_kw=400.0,
        specific_energy_kwh_m3=3.5,
        reservoir_capacity_m3=500.0,
        initial_water_m3=150.0,
        dead_storage_m3=20.0,
        min_run_hours=candidate.ro_min_run_hours,
        start_ratio=0.8,
        allow_backup_power=False,
    ))
    ice = make_ice()
    if candidate.priority == "ro_first":
        requests = [(ro, scenario.water_demand_m3_per_hour),
                    (ice, scenario.cooling_demand_kw_th)]
    else:
        requests = [(ice, scenario.cooling_demand_kw_th),
                    (ro, scenario.water_demand_m3_per_hour)]

    result = dispatch_flexible_loads(scenario.available_surplus_kw, requests)
    metrics = summarize(candidate.candidate_id, result, scenario)
    metrics["candidate_id"] = candidate.candidate_id
    metrics["priority"] = candidate.priority
    metrics["ro_min_run_hours"] = candidate.ro_min_run_hours
    metrics["objectives"] = {
        "water_unmet_m3": metrics["water_unmet_m3"],
        "cooling_unmet_kwh_th": metrics["cooling_unmet_kwh_th"],
        "remaining_surplus_kwh": metrics["remaining_surplus_kwh"],
    }
    # Re-audit aggregate power accounting independently before accepting a candidate.
    metrics["feasibility_audit"] = audit_dispatch_result(
        result, metrics["constraint_violation_hours"]
    )
    metrics["feasible"] = metrics["feasibility_audit"]["eligible_for_pareto"]
    return metrics



def audit_dispatch_result(result, constraint_violation_hours: int) -> dict:
    """Independently re-check aggregate power accounting before optimizer selection.

    This audit complements the dispatcher's fail-fast checks; it does not certify
    equipment safety, forecast accuracy, or field feasibility.
    """
    fields = (
        "initial_available_power_kw",
        "remaining_power_kw",
        "renewable_power_used_kw",
        "backup_power_kw",
    )
    arrays = {}
    errors = []
    for field in fields:
        try:
            values = np.asarray(getattr(result, field), dtype=float)
        except (AttributeError, TypeError, ValueError):
            errors.append(f"missing_or_invalid_{field}")
            continue
        if values.ndim != 1 or not np.all(np.isfinite(values)):
            errors.append(f"invalid_shape_or_nonfinite_{field}")
            continue
        if np.any(values < -1e-8):
            errors.append(f"negative_{field}")
        arrays[field] = values

    if len(arrays) == len(fields):
        lengths = {len(values) for values in arrays.values()}
        if len(lengths) != 1:
            errors.append("power_series_length_mismatch")
        else:
            available = arrays["initial_available_power_kw"]
            remaining = arrays["remaining_power_kw"]
            renewable = arrays["renewable_power_used_kw"]
            backup = arrays["backup_power_kw"]
            if not np.allclose(available, renewable + remaining, atol=1e-7, rtol=0):
                errors.append("shared_power_balance_failed")
            if np.any(renewable > available + 1e-7):
                errors.append("renewable_power_exceeds_available")
            if np.any(remaining > available + 1e-7):
                errors.append("remaining_power_exceeds_available")
            if np.any(backup < -1e-8):
                errors.append("negative_backup_power")

    hard_checks_passed = not errors
    component_constraints_passed = constraint_violation_hours == 0
    return {
        "dispatch_completed": True,
        "hard_dispatch_checks_passed": hard_checks_passed,
        "component_constraints_passed": component_constraints_passed,
        "eligible_for_pareto": hard_checks_passed and component_constraints_passed,
        "audit_errors": errors,
        "scope": (
            "independent aggregate power accounting and reported component constraint "
            "flags only; not field or safety validation"
        ),
    }

def dominates(a: dict, b: dict) -> bool:
    """Return True when a is no worse in every objective and better in one."""
    keys = ("water_unmet_m3", "cooling_unmet_kwh_th", "remaining_surplus_kwh")
    av = [float(a["objectives"][key]) for key in keys]
    bv = [float(b["objectives"][key]) for key in keys]
    return all(x <= y + 1e-9 for x, y in zip(av, bv)) and any(
        x < y - 1e-9 for x, y in zip(av, bv)
    )


def pareto_archive(evaluated: list[dict]) -> list[dict]:
    """Filter infeasible candidates, then return non-dominated evaluated rows."""
    feasible = [row for row in evaluated if row.get("feasible") is True and row.get("feasibility_audit", {}).get("eligible_for_pareto") is True]
    return [
        row for row in feasible
        if not any(other is not row and dominates(other, row) for other in feasible)
    ]


def recommend(archive: list[dict]) -> dict:
    """Select an evaluated Pareto candidate with disclosed normalized weights."""
    # Re-check eligibility here too: callers cannot accidentally recommend a
    # candidate merely by passing an unfiltered list as the archive.
    eligible = [
        row for row in archive
        if row.get("feasible") is True
        and row.get("feasibility_audit", {}).get("eligible_for_pareto") is True
    ]
    if not eligible:
        raise ValueError("No feasible candidate is available for recommendation")
    archive = eligible
    metric_keys = ("water_unmet_m3", "cooling_unmet_kwh_th", "remaining_surplus_kwh")
    weights = {
        "water_unmet_m3": 0.40,
        "cooling_unmet_kwh_th": 0.40,
        "remaining_surplus_kwh": 0.20,
    }
    maxima = {
        key: max(float(row["objectives"][key]) for row in archive)
        for key in metric_keys
    }

    def score(row: dict) -> float:
        total = 0.0
        for key, weight in weights.items():
            value = float(row["objectives"][key])
            scale = maxima[key]
            # If every candidate has zero for a metric, that metric contributes 0.
            total += weight * (value / scale if scale > 1e-12 else 0.0)
        return total

    # Stable tie-break by candidate id makes the choice reproducible.
    chosen = min(archive, key=lambda row: (score(row), row["candidate_id"]))
    answer = dict(chosen)
    answer["selection"] = {
        "method": "minimum weighted normalized score within evaluated Pareto archive",
        "weights": weights,
        "normalization": "divide each objective by its maximum among archive candidates",
        "score": round(score(chosen), 6),
    }
    return answer


def optimize_scenario(scenario: Scenario) -> dict:
    evaluated = [evaluate_candidate(scenario, candidate) for candidate in candidates()]
    archive = pareto_archive(evaluated)
    chosen = recommend(archive)
    return {
        "scenario": scenario.name,
        "data_status": "synthetic illustrative scenario; not field measurements",
        "search_method": "exhaustive grid search over 8 priority/RO-threshold candidates",
        "candidate_count": len(evaluated),
        "feasible_candidate_count": sum(row["feasible"] for row in evaluated),
        "pareto_candidate_count": len(archive),
        "objective_directions": {
            "water_unmet_m3": "minimize",
            "cooling_unmet_kwh_th": "minimize",
            "remaining_surplus_kwh": "minimize",
        },
        "evaluated_candidates": evaluated,
        "pareto_archive": archive,
        "recommendation": chosen,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    parser.add_argument("--scenario", choices=[s.name for s in build_scenarios()])
    args = parser.parse_args()
    scenarios = [s for s in build_scenarios() if args.scenario is None or s.name == args.scenario]
    output = [optimize_scenario(scenario) for scenario in scenarios]
    if args.json:
        print(json.dumps(output, indent=2))
        return

    print("IslandOS grid-search optimizer — synthetic scenarios only")
    print("Recommendation is selected from the same evaluated Pareto archive.")
    for result in output:
        rec = result["recommendation"]
        print(
            f"{result['scenario']}: candidates={result['candidate_count']}, "
            f"feasible={result['feasible_candidate_count']}, "
            f"Pareto={result['pareto_candidate_count']}, "
            f"recommended={rec['candidate_id']}, "
            f"water_unmet={rec['water_unmet_m3']} m3, "
            f"cooling_unmet={rec['cooling_unmet_kwh_th']} kWh_th, "
            f"remaining_surplus={rec['remaining_surplus_kwh']} kWh"
        )


if __name__ == "__main__":
    main()

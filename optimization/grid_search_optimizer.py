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
    # Re-audit aggregate power and each load's physical bookkeeping.
    demand_by_name = {
        "ro_desalination": np.asarray(scenario.water_demand_m3_per_hour, dtype=float),
        "ice_cold_storage": np.asarray(scenario.cooling_demand_kw_th, dtype=float),
    }
    metrics["feasibility_audit"] = audit_dispatch_result(
        result, requests, demand_by_name, dt_hours=1.0
    )
    metrics["feasible"] = metrics["feasibility_audit"]["eligible_for_pareto"]
    return metrics



def audit_dispatch_result(result, requests, demand_by_name: dict[str, np.ndarray], dt_hours: float = 1.0) -> dict:
    """Independently audit aggregate power, load balances, and configured bounds.

    This is a simulator consistency check, not certification of plant safety,
    forecast accuracy, or field feasibility.
    """
    errors: list[str] = []
    arrays: dict[str, np.ndarray] = {}
    fields = (
        "initial_available_power_kw",
        "remaining_power_kw",
        "renewable_power_used_kw",
        "backup_power_kw",
    )
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
            if not np.allclose(available, renewable + remaining, atol=1e-7, rtol=0):
                errors.append("shared_power_balance_failed")
            if np.any(renewable > available + 1e-7):
                errors.append("renewable_power_exceeds_available")
            if np.any(remaining > available + 1e-7):
                errors.append("remaining_power_exceeds_available")

    component_constraints_passed = True
    for load, demand in requests:
        name = load.name
        if name not in getattr(result, "loads", {}):
            errors.append(f"missing_load_result_{name}")
            component_constraints_passed = False
            continue
        load_result = result.loads[name]
        try:
            demand_series = np.asarray(demand_by_name[name], dtype=float)
            demand_series = np.asarray(demand_series, dtype=float)
            inventory = np.asarray(load_result.inventory, dtype=float)
            series = {
                field: np.asarray(getattr(load_result, field), dtype=float)
                for field in (
                    "power_used_kw", "backup_power_kw", "constraint_violation",
                    "resource_produced", "demand_served", "unmet_demand", "spill",
                )
            }
        except (KeyError, AttributeError, TypeError, ValueError):
            errors.append(f"invalid_load_audit_data_{name}")
            component_constraints_passed = False
            continue

        n = len(demand_series)
        if (demand_series.ndim != 1 or not np.all(np.isfinite(demand_series))
                or any(v.shape != (n,) or not np.all(np.isfinite(v)) for v in series.values())
                or inventory.shape != (n + 1,) or not np.all(np.isfinite(inventory))):
            errors.append(f"invalid_load_series_shape_or_values_{name}")
            component_constraints_passed = False
            continue
        if any(np.any(v < -1e-8) for v in series.values()) or np.any(inventory < -1e-8):
            errors.append(f"negative_load_value_{name}")
            component_constraints_passed = False
        if not np.allclose(
            series["demand_served"] + series["unmet_demand"],
            demand_series * dt_hours, atol=1e-7, rtol=1e-9
        ):
            errors.append(f"demand_balance_failed_{name}")
            component_constraints_passed = False
        if not np.allclose(
            inventory[1:],
            inventory[:-1] + series["resource_produced"] - series["spill"] - series["demand_served"],
            atol=1e-7, rtol=1e-9
        ):
            errors.append(f"inventory_balance_failed_{name}")
            component_constraints_passed = False
        if np.any(series["backup_power_kw"] - series["power_used_kw"] > 1e-7):
            errors.append(f"backup_exceeds_total_power_{name}")
            component_constraints_passed = False

        config = getattr(load, "config", None)
        if config is not None:
            if hasattr(config, "rated_power_kw") and np.any(
                series["power_used_kw"] > config.rated_power_kw + 1e-7
            ):
                errors.append(f"rated_power_exceeded_{name}")
                component_constraints_passed = False
            if hasattr(config, "reservoir_capacity_m3"):
                if (np.any(inventory < config.dead_storage_m3 - 1e-7)
                        or np.any(inventory > config.reservoir_capacity_m3 + 1e-7)):
                    errors.append(f"water_inventory_bounds_failed_{name}")
                    component_constraints_passed = False
            if hasattr(config, "storage_capacity_kwh_th"):
                if np.any(inventory > config.storage_capacity_kwh_th + 1e-7):
                    errors.append(f"thermal_inventory_capacity_failed_{name}")
                    component_constraints_passed = False
        if np.any(series["constraint_violation"] > 0):
            errors.append(f"reported_component_constraint_violation_{name}")
            component_constraints_passed = False

    hard_errors = [e for e in errors if e in {
        "shared_power_balance_failed", "renewable_power_exceeds_available",
        "remaining_power_exceeds_available", "power_series_length_mismatch",
    } or e.startswith(("missing_or_invalid_", "invalid_shape_or_nonfinite_", "negative_"))]
    hard_checks_passed = not hard_errors
    eligible = hard_checks_passed and component_constraints_passed and not errors
    return {
        "dispatch_completed": True,
        "hard_dispatch_checks_passed": hard_checks_passed,
        "component_constraints_passed": component_constraints_passed,
        "eligible_for_pareto": eligible,
        "audit_errors": errors,
        "scope": (
            "independent aggregate power, per-load demand/inventory balance, reported "
            "constraint flags, and configured rated-power/inventory bounds; not field or safety validation"
        ),
    }

OBJECTIVE_KEYS = ("water_unmet_m3", "cooling_unmet_kwh_th", "remaining_surplus_kwh")


def objective_validation_errors(row: dict) -> list[str]:
    """Return explicit reasons a candidate's objective vector cannot be compared."""
    objectives = row.get("objectives")
    if not isinstance(objectives, dict):
        return ["missing_objectives"]
    errors = []
    for key in OBJECTIVE_KEYS:
        if key not in objectives:
            errors.append(f"missing_objective_{key}")
            continue
        try:
            value = float(objectives[key])
        except (TypeError, ValueError):
            errors.append(f"invalid_objective_{key}")
            continue
        if not np.isfinite(value):
            errors.append(f"nonfinite_objective_{key}")
        elif value < 0:
            errors.append(f"negative_objective_{key}")
    return errors


def _eligible_candidate(row: dict) -> bool:
    return (
        row.get("feasible") is True
        and row.get("feasibility_audit", {}).get("eligible_for_pareto") is True
        and not objective_validation_errors(row)
    )


def dominates(a: dict, b: dict) -> bool:
    """Return True when a is no worse in every objective and better in one."""
    av = [float(a["objectives"][key]) for key in OBJECTIVE_KEYS]
    bv = [float(b["objectives"][key]) for key in OBJECTIVE_KEYS]
    return all(x <= y + 1e-9 for x, y in zip(av, bv)) and any(
        x < y - 1e-9 for x, y in zip(av, bv)
    )


def pareto_archive(evaluated: list[dict]) -> list[dict]:
    """Filter unaudited, infeasible, or invalid-objective rows before dominance."""
    feasible = [row for row in evaluated if _eligible_candidate(row)]
    return [
        row for row in feasible
        if not any(other is not row and dominates(other, row) for other in feasible)
    ]


def recommend(archive: list[dict]) -> dict:
    """Select an evaluated Pareto candidate with disclosed normalized weights."""
    # Re-check eligibility here too: callers cannot accidentally recommend a
    # candidate merely by passing an unfiltered list as the archive.
    eligible = [row for row in archive if _eligible_candidate(row)]
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
    archive_ids = {row["candidate_id"] for row in archive}
    recommended_id = chosen["candidate_id"]
    candidate_decisions = []
    for row in evaluated:
        audit = row.get("feasibility_audit", {})
        objective_errors = objective_validation_errors(row)
        eligible = _eligible_candidate(row)
        in_archive = row["candidate_id"] in archive_ids
        if not eligible:
            reasons = list(audit.get("audit_errors", [])) or objective_errors
            if not reasons:
                reasons = ["dispatch_feasibility_audit_not_eligible"]
        elif not in_archive:
            reasons = ["dominated_by_another_feasible_candidate"]
        elif row["candidate_id"] != recommended_id:
            reasons = ["eligible_pareto_candidate_not_selected_by_weighted_score"]
        else:
            reasons = []
        candidate_decisions.append({
            "candidate_id": row["candidate_id"],
            "feasible": bool(row.get("feasible") is True and audit.get("eligible_for_pareto") is True),
            "objective_validation_errors": objective_errors,
            "eligible_for_pareto": eligible,
            "in_pareto_archive": in_archive,
            "recommended": row["candidate_id"] == recommended_id,
            "decision_reasons": reasons,
        })
    return {
        "scenario": scenario.name,
        "data_status": "synthetic illustrative scenario; not field measurements",
        "search_method": "exhaustive grid search over 8 priority/RO-threshold candidates",
        "candidate_count": len(evaluated),
        "feasible_candidate_count": sum(_eligible_candidate(row) for row in evaluated),
        "pareto_candidate_count": len(archive),
        "objective_directions": {
            "water_unmet_m3": "minimize",
            "cooling_unmet_kwh_th": "minimize",
            "remaining_surplus_kwh": "minimize",
        },
        "evaluated_candidates": evaluated,
        "candidate_decisions": candidate_decisions,
        "decision_reason_legend": {
            "dominated_by_another_feasible_candidate": "Feasible objective vector is dominated by at least one other eligible candidate.",
            "eligible_pareto_candidate_not_selected_by_weighted_score": "Candidate is on the Pareto archive but lost the disclosed weighted normalized score/tie-break.",
            "dispatch_feasibility_audit_not_eligible": "Dispatch audit did not explicitly approve the candidate; inspect feasibility_audit.audit_errors.",
        },
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

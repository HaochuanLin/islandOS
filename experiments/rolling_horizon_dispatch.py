"""Receding-horizon dispatch prototype for IslandOS.

At each hour, evaluate the two load priorities over a finite forecast horizon,
execute only the first hour against realized surplus, carry inventories and RO
minimum-run commitment forward, and replan. Inputs are synthetic. This models
a simple run commitment, not plant interlocks or full operational feasibility.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dispatch_engine import dispatch_flexible_loads
from experiments.compare_dispatch_policies import (
    Scenario, build_scenarios, make_ice, make_ro,
)
from flexible_loads import IceStorageConfig, IceStorageLoad, ROConfig, ROWaterLoad


HORIZON_HOURS = 3


def _make_ro_with_inventory(water_m3: float) -> ROWaterLoad:
    base = make_ro().config
    return ROWaterLoad(replace(base, initial_water_m3=water_m3))


def _make_ice_with_inventory(cold_kwh_th: float) -> IceStorageLoad:
    base = make_ice().config
    return IceStorageLoad(replace(base, initial_storage_kwh_th=cold_kwh_th))


def _run_horizon(
    power, water_demand, cooling_demand, water_inventory, cold_inventory,
    priority, ro_run_hours_remaining=0, ro_fault_lockout_hours_remaining=0,
):
    ro = _make_ro_with_inventory(water_inventory)
    ice = _make_ice_with_inventory(cold_inventory)
    requests = (
        [(ro, water_demand), (ice, cooling_demand)]
        if priority == "ro_first"
        else [(ice, cooling_demand), (ro, water_demand)]
    )
    return dispatch_flexible_loads(
        power, requests,
        initial_ro_run_hours_remaining=ro_run_hours_remaining,
        initial_ro_fault_lockout_hours_remaining=ro_fault_lockout_hours_remaining,
    )


def _score(result, water_demand, cooling_demand) -> float:
    water_total = max(float(np.sum(water_demand)), 1e-9)
    cooling_total = max(float(np.sum(cooling_demand)), 1e-9)
    ro = result.loads.get("ro_desalination")
    ice = result.loads.get("ice_cold_storage")
    water_unmet = float(np.sum(ro.unmet_demand)) if ro else water_total
    cooling_unmet = float(np.sum(ice.unmet_demand)) if ice else cooling_total
    total_available = max(float(np.sum(result.initial_available_power_kw)), 1e-9)
    surplus_ratio = float(np.sum(result.remaining_power_kw)) / total_available
    return 0.45 * water_unmet / water_total + 0.45 * cooling_unmet / cooling_total + 0.10 * surplus_ratio

def _constraint_violation_hours(result) -> int:
    """Count distinct timesteps with at least one component constraint violation."""
    flags = [
        np.asarray(load.constraint_violation, dtype=int) > 0
        for load in result.loads.values()
    ]
    if not flags:
        return 0
    return int(np.count_nonzero(np.logical_or.reduce(flags)))


def _execute_one(
    actual_power, water_demand, cooling_demand, water_inventory, cold_inventory,
    priority, ro_run_hours_remaining=0, ro_fault_lockout_hours_remaining=0, start_ro=False,
):
    # A planned start commits the unit for its configured minimum run even
    # though this call executes only one realized hour.
    initial_commitment = ro_run_hours_remaining
    if start_ro and initial_commitment == 0:
        initial_commitment = make_ro().config.min_run_hours
    result = _run_horizon(
        [actual_power], [water_demand], [cooling_demand],
        water_inventory, cold_inventory, priority, initial_commitment,
        ro_fault_lockout_hours_remaining,
    )
    ro = result.loads.get("ro_desalination")
    ice = result.loads.get("ice_cold_storage")
    return {
        "water_inventory": float(ro.inventory[-1]) if ro else water_inventory,
        "cold_inventory": float(ice.inventory[-1]) if ice else cold_inventory,
        "water_unmet": float(ro.unmet_demand.sum()) if ro else water_demand,
        "cooling_unmet": float(ice.unmet_demand.sum()) if ice else cooling_demand,
        "renewable_used": float(result.renewable_power_used_kw.sum()),
        "remaining_surplus": float(result.remaining_power_kw.sum()),
        "constraint_violations": int(sum(np.sum(x.constraint_violation) for x in result.loads.values())),
        "ro_active": bool(ro is not None and ro.active[0]),
        "ro_operating_state": str(ro.operating_state[0]) if ro is not None and ro.operating_state is not None else "OFF",
        "ro_power_kw": float(ro.power_used_kw[0]) if ro else 0.0,
        "ro_constraint_violation": int(ro.constraint_violation[0]) if ro else 0,
        "ice_active": bool(ice is not None and ice.active[0]),
        "ice_power_kw": float(ice.power_used_kw[0]) if ice else 0.0,
        "ro_run_hours_remaining": int(ro.run_hours_remaining) if ro else ro_run_hours_remaining,
        "ro_fault_lockout_hours_remaining": int(ro.fault_lockout_hours_remaining) if ro else ro_fault_lockout_hours_remaining,
    }


def simulate_rolling(scenario: Scenario, forecast_surplus, policy: str = "rolling") -> dict:
    """Simulate one-hour commits with state carried between replanning steps."""
    actual = np.asarray(scenario.available_surplus_kw, dtype=float)
    forecast = np.asarray(forecast_surplus, dtype=float)
    water_demand = np.asarray(scenario.water_demand_m3_per_hour, dtype=float)
    cooling_demand = np.asarray(scenario.cooling_demand_kw_th, dtype=float)
    if forecast.shape != actual.shape:
        raise ValueError("forecast_surplus must match the scenario horizon")
    if not np.all(np.isfinite(forecast)) or np.any(forecast < 0):
        raise ValueError("forecast_surplus must be finite and non-negative")

    water_inventory = make_ro().config.initial_water_m3
    cold_inventory = make_ice().config.initial_storage_kwh_th
    ro_run_hours_remaining = 0
    ro_fault_lockout_hours_remaining = 0
    totals = {"water_unmet_m3": 0.0, "cooling_unmet_kwh_th": 0.0,
              "renewable_flexible_load_kwh": 0.0, "remaining_surplus_kwh": 0.0,
              "constraint_violation_hours": 0, "constraint_violation_count": 0}
    decisions = []
    hourly_audit = []
    violation_steps = []

    for t in range(len(actual)):
        end = min(len(actual), t + HORIZON_HOURS)
        if policy == "rolling":
            candidates = []
            for priority in ("ro_first", "ice_first"):
                predicted = _run_horizon(
                    forecast[t:end], water_demand[t:end], cooling_demand[t:end],
                    water_inventory, cold_inventory, priority,
                    ro_run_hours_remaining, ro_fault_lockout_hours_remaining,
                )
                candidates.append((
                    _constraint_violation_hours(predicted),
                    _score(predicted, water_demand[t:end], cooling_demand[t:end]),
                    priority, predicted,
                ))
            _, _, chosen, chosen_plan = min(
                candidates, key=lambda item: (item[0], item[1], item[2])
            )
            ro_plan = chosen_plan.loads.get("ro_desalination")
            start_ro = bool(ro_plan is not None and ro_plan.active[0] and ro_run_hours_remaining == 0)
        elif policy in ("ro_first", "ice_first", "perfect_information"):
            if policy == "perfect_information":
                candidates = []
                for priority in ("ro_first", "ice_first"):
                    predicted = _run_horizon(
                        actual[t:end], water_demand[t:end], cooling_demand[t:end],
                        water_inventory, cold_inventory, priority,
                        ro_run_hours_remaining, ro_fault_lockout_hours_remaining,
                    )
                    candidates.append((
                        _constraint_violation_hours(predicted),
                        _score(predicted, water_demand[t:end], cooling_demand[t:end]),
                        priority, predicted,
                    ))
                _, _, chosen, chosen_plan = min(
                    candidates, key=lambda item: (item[0], item[1], item[2])
                )
                ro_plan = chosen_plan.loads.get("ro_desalination")
                start_ro = bool(ro_plan is not None and ro_plan.active[0] and ro_run_hours_remaining == 0)
            else:
                chosen = policy
                plan = _run_horizon(
                    forecast[t:end], water_demand[t:end], cooling_demand[t:end],
                    water_inventory, cold_inventory, chosen, ro_run_hours_remaining,
                    ro_fault_lockout_hours_remaining,
                )
                ro_plan = plan.loads.get("ro_desalination")
                start_ro = bool(ro_plan is not None and ro_plan.active[0] and ro_run_hours_remaining == 0)
        else:
            raise ValueError("policy must be rolling, ro_first, ice_first, or perfect_information")

        step = _execute_one(
            actual[t], water_demand[t], cooling_demand[t],
            water_inventory, cold_inventory, chosen, ro_run_hours_remaining,
            ro_fault_lockout_hours_remaining, start_ro,
        )
        water_inventory = step["water_inventory"]
        cold_inventory = step["cold_inventory"]
        ro_run_hours_remaining = step["ro_run_hours_remaining"]
        ro_fault_lockout_hours_remaining = step["ro_fault_lockout_hours_remaining"]
        totals["water_unmet_m3"] += step["water_unmet"]
        totals["cooling_unmet_kwh_th"] += step["cooling_unmet"]
        totals["renewable_flexible_load_kwh"] += step["renewable_used"]
        totals["remaining_surplus_kwh"] += step["remaining_surplus"]
        totals["constraint_violation_hours"] += int(step["constraint_violations"] > 0)
        totals["constraint_violation_count"] += step["constraint_violations"]
        decisions.append(chosen)
        hourly_audit.append({
            "hour_index": t,
            "actual_surplus_kw": float(actual[t]),
            "forecast_surplus_kw": float(forecast[t]),
            "priority": chosen,
            "ro_active": step["ro_active"],
            "ro_operating_state": step["ro_operating_state"],
            "ro_power_kw": round(step["ro_power_kw"], 6),
            "ice_power_kw": round(step["ice_power_kw"], 6),
            "ro_constraint_violation": step["ro_constraint_violation"],
            "ro_run_hours_remaining": step["ro_run_hours_remaining"],
            "ro_fault_lockout_hours_remaining": step["ro_fault_lockout_hours_remaining"],
            "water_inventory_m3": round(water_inventory, 6),
            "cold_inventory_kwh_th": round(cold_inventory, 6),
            "total_constraint_violations": step["constraint_violations"],
        })
        if step["constraint_violations"]:
            violation_steps.append(t)

    return {
        "policy": policy,
        **{key: round(value, 3) for key, value in totals.items()},
        "final_water_inventory_m3": round(water_inventory, 3),
        "final_cold_inventory_kwh_th": round(cold_inventory, 3),
        "hourly_priority_decisions": decisions,
        "hourly_audit": hourly_audit,
        "constraint_violation_hour_indices": violation_steps,
    }


def run_experiment() -> list[dict]:
    rows = []
    for scenario in build_scenarios():
        actual = np.asarray(scenario.available_surplus_kw, dtype=float)
        error_profiles = {
            "perfect": np.zeros_like(actual),
            "overforecast_20pct": actual * 1.2,
            "underforecast_20pct": actual * 0.8,
            "alternating_pm20pct": actual * np.asarray(
                [1.2 if i % 2 == 0 else 0.8 for i in range(len(actual))]
            ),
        }
        for error_name, forecast in error_profiles.items():
            for policy in ("rolling", "ro_first", "ice_first", "perfect_information"):
                result = simulate_rolling(scenario, forecast, policy)
                rows.append({
                    "scenario": scenario.name,
                    "forecast_error_profile": error_name,
                    "result": result,
                    "data_status": "synthetic prototype; not field-validated",
                })
    return rows



def summarize_experiment(rows=None):
    """Compare rolling policy with fixed policies using one normalized score."""
    if rows is None:
        rows = run_experiment()
    scenarios = {scenario.name: scenario for scenario in build_scenarios()}
    grouped = {}
    for row in rows:
        key = (row["scenario"], row["forecast_error_profile"])
        grouped.setdefault(key, {})[row["result"]["policy"]] = row["result"]

    summaries = []
    for (scenario_name, error_name), policies in sorted(grouped.items()):
        scenario = scenarios[scenario_name]
        water_total = max(float(sum(scenario.water_demand_m3_per_hour)), 1e-9)
        cooling_total = max(float(sum(scenario.cooling_demand_kw_th)), 1e-9)
        power_total = max(float(sum(scenario.available_surplus_kw)), 1e-9)

        def score(result):
            return (0.45 * result["water_unmet_m3"] / water_total
                    + 0.45 * result["cooling_unmet_kwh_th"] / cooling_total
                    + 0.10 * result["remaining_surplus_kwh"] / power_total)

        rolling_score = score(policies["rolling"])
        fixed_scores = {name: score(policies[name]) for name in ("ro_first", "ice_first")}
        best_fixed_name = min(fixed_scores, key=lambda name: (fixed_scores[name], name))
        best_fixed_score = fixed_scores[best_fixed_name]
        summaries.append({
            "scenario": scenario_name,
            "forecast_error_profile": error_name,
            "rolling_score": round(rolling_score, 6),
            "ro_first_score": round(fixed_scores["ro_first"], 6),
            "ice_first_score": round(fixed_scores["ice_first"], 6),
            "best_fixed_policy": best_fixed_name,
            "best_fixed_score": round(best_fixed_score, 6),
            "rolling_minus_best_fixed": round(rolling_score - best_fixed_score, 6),
            "perfect_information_score": round(score(policies["perfect_information"]), 6),
            "interpretation": "case-specific comparison; no universal winner assumed",
        })
    return summaries

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    rows = run_experiment()
    summaries = summarize_experiment(rows)
    if args.json:
        print(json.dumps({
            "case_count": len(rows),
            "summary_case_count": len(summaries),
            "interpretation": "Finite-horizon policy selection; only first-hour priority is executed before replanning. Lower normalized score is better.",
            "limitations": [
                "Synthetic profiles only; no trained forecast model.",
                "RO minimum-run commitment is carried between hourly replans, but plant interlocks and startup/ramp dynamics are not modeled.",
                "Perfect-information policy is a hindsight reference, not deployable.",
                "Weights are illustrative and should be sensitivity-tested before decision use.",
            ],
            "summary": summaries,
            "rows": rows,
        }, indent=2))
    else:
        print("Synthetic rolling-horizon prototype — not field validated")
        print("Negative delta means rolling scored better than the best fixed priority.")
        print("scenario | forecast | rolling score | best fixed | fixed score | rolling - fixed")
        for row in summaries:
            print(f"{row['scenario']} | {row['forecast_error_profile']} | {row['rolling_score']:.4f} | "
                  f"{row['best_fixed_policy']} | {row['best_fixed_score']:.4f} | "
                  f"{row['rolling_minus_best_fixed']:+.4f}")


if __name__ == "__main__":
    main()

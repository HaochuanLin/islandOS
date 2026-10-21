"""Receding-horizon dispatch prototype for IslandOS.

At each hour, evaluate the two load priorities over a finite forecast horizon,
execute only the first hour against realized surplus, carry inventories forward,
and replan. Inputs are synthetic. RO minimum-run commitment is not modeled in
this prototype; use it to test the rolling decision loop, not plant feasibility.
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
    return ROWaterLoad(replace(base, initial_water_m3=water_m3, min_run_hours=1))


def _make_ice_with_inventory(cold_kwh_th: float) -> IceStorageLoad:
    base = make_ice().config
    return IceStorageLoad(replace(base, initial_storage_kwh_th=cold_kwh_th))


def _run_horizon(power, water_demand, cooling_demand, water_inventory, cold_inventory, priority):
    ro = _make_ro_with_inventory(water_inventory)
    ice = _make_ice_with_inventory(cold_inventory)
    requests = (
        [(ro, water_demand), (ice, cooling_demand)]
        if priority == "ro_first"
        else [(ice, cooling_demand), (ro, water_demand)]
    )
    return dispatch_flexible_loads(power, requests)


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


def _execute_one(actual_power, water_demand, cooling_demand, water_inventory, cold_inventory, priority):
    result = _run_horizon(
        [actual_power], [water_demand], [cooling_demand],
        water_inventory, cold_inventory, priority,
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
    totals = {"water_unmet_m3": 0.0, "cooling_unmet_kwh_th": 0.0,
              "renewable_flexible_load_kwh": 0.0, "remaining_surplus_kwh": 0.0,
              "constraint_violation_hours": 0}
    decisions = []

    for t in range(len(actual)):
        end = min(len(actual), t + HORIZON_HOURS)
        if policy == "rolling":
            candidates = []
            for priority in ("ro_first", "ice_first"):
                predicted = _run_horizon(
                    forecast[t:end], water_demand[t:end], cooling_demand[t:end],
                    water_inventory, cold_inventory, priority,
                )
                candidates.append((_score(predicted, water_demand[t:end], cooling_demand[t:end]), priority))
            chosen = min(candidates, key=lambda item: (item[0], item[1]))[1]
        elif policy in ("ro_first", "ice_first", "perfect_information"):
            if policy == "perfect_information":
                candidates = []
                for priority in ("ro_first", "ice_first"):
                    predicted = _run_horizon(
                        actual[t:end], water_demand[t:end], cooling_demand[t:end],
                        water_inventory, cold_inventory, priority,
                    )
                    candidates.append((_score(predicted, water_demand[t:end], cooling_demand[t:end]), priority))
                chosen = min(candidates, key=lambda item: (item[0], item[1]))[1]
            else:
                chosen = policy
        else:
            raise ValueError("policy must be rolling, ro_first, ice_first, or perfect_information")

        step = _execute_one(
            actual[t], water_demand[t], cooling_demand[t],
            water_inventory, cold_inventory, chosen,
        )
        water_inventory = step["water_inventory"]
        cold_inventory = step["cold_inventory"]
        totals["water_unmet_m3"] += step["water_unmet"]
        totals["cooling_unmet_kwh_th"] += step["cooling_unmet"]
        totals["renewable_flexible_load_kwh"] += step["renewable_used"]
        totals["remaining_surplus_kwh"] += step["remaining_surplus"]
        totals["constraint_violation_hours"] += step["constraint_violations"]
        decisions.append(chosen)

    return {
        "policy": policy,
        **{key: round(value, 3) for key, value in totals.items()},
        "final_water_inventory_m3": round(water_inventory, 3),
        "final_cold_inventory_kwh_th": round(cold_inventory, 3),
        "hourly_priority_decisions": decisions,
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    rows = run_experiment()
    if args.json:
        print(json.dumps({
            "case_count": len(rows),
            "interpretation": "Finite-horizon policy selection; only first-hour action is executed before replanning.",
            "limitations": [
                "Synthetic profiles only; no trained forecast model.",
                "RO minimum-run commitment is not modeled in this rolling prototype.",
                "Perfect-information policy is a hindsight reference, not deployable.",
            ],
            "rows": rows,
        }, indent=2))
    else:
        print("Synthetic rolling-horizon prototype — not field validated")
        print("scenario | forecast | policy | water unmet | cooling unmet | remaining surplus")
        for row in rows:
            r = row["result"]
            print(f"{row['scenario']} | {row['forecast_error_profile']} | {r['policy']} | "
                  f"{r['water_unmet_m3']} | {r['cooling_unmet_kwh_th']} | {r['remaining_surplus_kwh']}")


if __name__ == "__main__":
    main()

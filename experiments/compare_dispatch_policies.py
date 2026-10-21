"""Reproducible baseline comparison for the experimental IslandOS dispatcher.

Run from the repository root:
    python experiments/compare_dispatch_policies.py

All input profiles are synthetic and intentionally transparent. This script
compares dispatch policies; it does not prove real-world savings or establish
that one priority order is universally better.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
import sys

import numpy as np

# Allow direct execution of this file from the repository root.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dispatch_engine import dispatch_flexible_loads
from flexible_loads import IceStorageConfig, IceStorageLoad, ROConfig, ROWaterLoad


@dataclass(frozen=True)
class Scenario:
    name: str
    available_surplus_kw: tuple[float, ...]
    water_demand_m3_per_hour: tuple[float, ...]
    cooling_demand_kw_th: tuple[float, ...]


def build_scenarios() -> list[Scenario]:
    """Return fixed, synthetic scenarios with documented units."""
    return [
        Scenario(
            name="steady_surplus",
            available_surplus_kw=(0, 0, 500, 550, 500, 450, 0, 0),
            water_demand_m3_per_hour=(25, 25, 25, 25, 25, 25, 25, 25),
            cooling_demand_kw_th=(50, 50, 50, 50, 50, 50, 50, 50),
        ),
        Scenario(
            name="intermittent_surplus",
            available_surplus_kw=(450, 0, 450, 0, 450, 0, 450, 0),
            water_demand_m3_per_hour=(20, 20, 20, 20, 20, 20, 20, 20),
            cooling_demand_kw_th=(80, 80, 80, 80, 80, 80, 80, 80),
        ),
        Scenario(
            name="surplus_peak_and_shortage",
            available_surplus_kw=(0, 650, 650, 100, 0, 600, 200, 0),
            water_demand_m3_per_hour=(35, 35, 35, 35, 35, 35, 35, 35),
            cooling_demand_kw_th=(100, 100, 100, 100, 100, 100, 100, 100),
        ),
    ]


def make_ro() -> ROWaterLoad:
    return ROWaterLoad(ROConfig(
        rated_power_kw=400.0,
        specific_energy_kwh_m3=3.5,
        reservoir_capacity_m3=500.0,
        initial_water_m3=150.0,
        dead_storage_m3=20.0,
        min_run_hours=2,
        start_ratio=0.8,
        allow_backup_power=False,
    ))


def make_ice() -> IceStorageLoad:
    return IceStorageLoad(IceStorageConfig(
        rated_power_kw=100.0,
        coefficient_of_performance=2.5,
        storage_capacity_kwh_th=400.0,
        initial_storage_kwh_th=100.0,
    ))


def summarize(policy: str, result, scenario: Scenario, dt_hours: float = 1.0) -> dict:
    ro = result.loads.get("ro_desalination")
    ice = result.loads.get("ice_cold_storage")
    water_produced = float(np.sum(ro.resource_produced)) if ro else 0.0
    water_unmet = float(np.sum(ro.unmet_demand)) if ro else float(sum(scenario.water_demand_m3_per_hour) * dt_hours)
    cooling_served = float(np.sum(ice.demand_served)) if ice else 0.0
    cooling_unmet = float(np.sum(ice.unmet_demand)) if ice else float(sum(scenario.cooling_demand_kw_th) * dt_hours)
    return {
        "scenario": scenario.name,
        "policy": policy,
        "renewable_flexible_load_kwh": round(float(np.sum(result.renewable_power_used_kw) * dt_hours), 3),
        "remaining_surplus_kwh": round(float(np.sum(result.remaining_power_kw) * dt_hours), 3),
        "backup_energy_kwh": round(float(np.sum(result.backup_power_kw) * dt_hours), 3),
        "water_produced_m3": round(water_produced, 3),
        "water_unmet_m3": round(water_unmet, 3),
        "cooling_served_kwh_th": round(cooling_served, 3),
        "cooling_unmet_kwh_th": round(cooling_unmet, 3),
        "constraint_violation_hours": int(sum(
            np.sum(load.constraint_violation) for load in result.loads.values()
        )),
    }


def run_comparison() -> list[dict]:
    rows: list[dict] = []
    for scenario in build_scenarios():
        available = scenario.available_surplus_kw
        water = scenario.water_demand_m3_per_hour
        cooling = scenario.cooling_demand_kw_th
        policies = [
            ("ro_only", [(make_ro(), water)]),
            ("ice_only", [(make_ice(), cooling)]),
            ("ro_first", [(make_ro(), water), (make_ice(), cooling)]),
            ("ice_first", [(make_ice(), cooling), (make_ro(), water)]),
        ]
        for policy_name, requests in policies:
            result = dispatch_flexible_loads(available, requests)
            row = summarize(policy_name, result, scenario)
            if not np.allclose(
                result.initial_available_power_kw,
                result.renewable_power_used_kw + result.remaining_power_kw,
                atol=1e-7,
                rtol=0,
            ):
                raise RuntimeError(f"Power balance failed for {scenario.name}/{policy_name}")
            if np.any(result.renewable_power_used_kw > result.initial_available_power_kw + 1e-7):
                raise RuntimeError(f"Renewable budget exceeded for {scenario.name}/{policy_name}")
            rows.append(row)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print JSON instead of a readable table")
    args = parser.parse_args()
    rows = run_comparison()
    if args.json:
        print(json.dumps({
            "data_status": "synthetic illustrative scenarios; not field measurements",
            "dt_hours": 1.0,
            "rows": rows,
        }, indent=2))
        return

    columns = list(rows[0])
    widths = {key: max(len(key), *(len(str(row[key])) for row in rows)) for key in columns}
    print("Synthetic policy comparison — not field-validated results")
    print("Units: energy=kWh; water=m3; cooling=kWh_th; time step=1 hour")
    print(" | ".join(key.ljust(widths[key]) for key in columns))
    print("-+-".join("-" * widths[key] for key in columns))
    for row in rows:
        print(" | ".join(str(row[key]).ljust(widths[key]) for key in columns))


if __name__ == "__main__":
    main()

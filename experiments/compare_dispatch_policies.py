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
    # End-of-horizon inventories matter: two policies can serve the same demand
    # while leaving very different amounts of water or stored cooling for later.
    # Use null when a resource was not part of that policy, rather than implying
    # that an unmodeled asset had zero inventory.
    water_inventory_initial = float(ro.inventory[0]) if ro else None
    water_inventory_final = float(ro.inventory[-1]) if ro else None
    cooling_storage_initial = float(ice.inventory[0]) if ice else None
    cooling_storage_final = float(ice.inventory[-1]) if ice else None
    return {
        "scenario": scenario.name,
        "policy": policy,
        "renewable_flexible_load_kwh": round(float(np.sum(result.renewable_power_used_kw) * dt_hours), 3),
        "remaining_surplus_kwh": round(float(np.sum(result.remaining_power_kw) * dt_hours), 3),
        "backup_energy_kwh": round(float(np.sum(result.backup_power_kw) * dt_hours), 3),
        "water_produced_m3": round(water_produced, 3),
        "water_unmet_m3": round(water_unmet, 3),
        "water_inventory_initial_m3": round(water_inventory_initial, 3) if water_inventory_initial is not None else None,
        "water_inventory_final_m3": round(water_inventory_final, 3) if water_inventory_final is not None else None,
        "cooling_served_kwh_th": round(cooling_served, 3),
        "cooling_unmet_kwh_th": round(cooling_unmet, 3),
        "cooling_storage_initial_kwh_th": round(cooling_storage_initial, 3) if cooling_storage_initial is not None else None,
        "cooling_storage_final_kwh_th": round(cooling_storage_final, 3) if cooling_storage_final is not None else None,
        "constraint_violation_hours": int(sum(
            np.sum(load.constraint_violation) for load in result.loads.values()
        )),
    }


def run_comparison(audit_records: list[dict] | None = None) -> list[dict]:
    """Run all synthetic policy cases and optionally collect hourly audit records."""
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
            if audit_records is not None:
                audit_records.extend(_audit_timestep_records(scenario, policy_name, result))
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


def _audit_timestep_records(scenario: Scenario, policy: str, result) -> list[dict]:
    """Create transparent, machine-readable per-hour accounting records."""
    records: list[dict] = []
    for t, available_kw in enumerate(result.initial_available_power_kw):
        power_residual = float(
            available_kw - result.renewable_power_used_kw[t] - result.remaining_power_kw[t]
        )
        load_audits: dict[str, dict] = {}
        any_failure = abs(power_residual) > 1e-7
        for name, load in result.loads.items():
            inventory = np.asarray(load.inventory, dtype=float)
            produced = float(load.resource_produced[t])
            served = float(load.demand_served[t])
            unmet = float(load.unmet_demand[t])
            spill = float(load.spill[t])
            inventory_residual = float(
                inventory[t] + produced - spill - served - inventory[t + 1]
            )
            demand_residual = float(
                served + unmet - (
                    scenario.water_demand_m3_per_hour[t]
                    if name == "ro_desalination"
                    else scenario.cooling_demand_kw_th[t]
                )
            )
            capacity_violation = False
            if name == "ro_desalination":
                cfg = make_ro().config
                capacity_violation = bool(
                    inventory[t + 1] < cfg.dead_storage_m3 - 1e-7
                    or inventory[t + 1] > cfg.reservoir_capacity_m3 + 1e-7
                )
            elif name == "ice_cold_storage":
                cfg = make_ice().config
                capacity_violation = bool(
                    inventory[t + 1] < -1e-7
                    or inventory[t + 1] > cfg.storage_capacity_kwh_th + 1e-7
                )
            constraint_violation = int(load.constraint_violation[t])
            load_failed = (
                abs(inventory_residual) > 1e-7
                or abs(demand_residual) > 1e-7
                or capacity_violation
                or constraint_violation > 0
            )
            any_failure = any_failure or load_failed
            load_audits[name] = {
                "power_used_kw": float(load.power_used_kw[t]),
                "backup_power_kw": float(load.backup_power_kw[t]),
                "renewable_power_kw": float(load.power_used_kw[t] - load.backup_power_kw[t]),
                "inventory_before": float(inventory[t]),
                "resource_produced": produced,
                "demand_served": served,
                "unmet_demand": unmet,
                "spill": spill,
                "inventory_after": float(inventory[t + 1]),
                "inventory_balance_residual": inventory_residual,
                "demand_balance_residual": demand_residual,
                "capacity_violation": capacity_violation,
                "constraint_violation": constraint_violation,
                "active": int(load.active[t]),
                "status": "fail" if load_failed else "pass",
            }
        records.append({
            "scenario": scenario.name,
            "policy": policy,
            "timestep": t,
            "time_step_hours": 1.0,
            "available_renewable_power_kw": float(available_kw),
            "renewable_power_used_kw": float(result.renewable_power_used_kw[t]),
            "remaining_power_kw": float(result.remaining_power_kw[t]),
            "backup_power_kw": float(result.backup_power_kw[t]),
            "power_balance_residual_kw": power_residual,
            "loads": load_audits,
            "status": "fail" if any_failure else "pass",
        })
    return records


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

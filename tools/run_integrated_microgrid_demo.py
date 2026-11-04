"""Generate a reproducible synthetic benchmark for the integrated microgrid model.

Example:
  python tools/run_integrated_microgrid_demo.py --hours 168 --seed 20261104
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from islandos_core.microgrid_model import MicrogridConfig, MicrogridInputs, simulate_microgrid


def build_synthetic_inputs(hours: int, seed: int) -> MicrogridInputs:
    if isinstance(hours, bool) or not isinstance(hours, int) or hours < 1:
        raise ValueError("hours must be an integer >= 1")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    rng = np.random.default_rng(seed)
    t = np.arange(hours)
    hour_of_day = t % 24
    daylight = np.maximum(0.0, np.sin(np.pi * (hour_of_day - 6) / 12))
    pv = 115.0 * daylight
    wind = np.clip(rng.normal(24.0, 9.0, hours), 0.0, 48.0)
    essential = np.clip(48.0 + 8.0 * np.sin(2 * np.pi * (hour_of_day - 7) / 24)
                        + rng.normal(0.0, 3.0, hours), 30.0, 75.0)
    water_demand = np.clip(2.6 + 0.35 * np.sin(2 * np.pi * (hour_of_day - 5) / 24)
                           + rng.normal(0.0, 0.12, hours), 1.8, 3.5)
    grid_available = np.ones(hours, dtype=bool)
    # A deterministic 4-hour outage block every 72 hours, starting at hour 20.
    for start in range(20, hours, 72):
        grid_available[start:min(start + 4, hours)] = False
    price = np.where((hour_of_day >= 0) & (hour_of_day < 7), 0.18, 0.42)
    return MicrogridInputs(
        pv_power_kw=pv,
        wind_power_kw=wind,
        essential_load_kw=essential,
        ro_requested_power_kw=np.zeros(hours),
        water_demand_m3=water_demand,
        grid_available=grid_available,
        grid_price_per_kwh=price,
        diesel_cost_per_kwh=0.85,
        diesel_emissions_kg_per_kwh=0.72,
        grid_emissions_kg_per_kwh=np.full(hours, 0.43),
    )


def run_demo(hours: int, seed: int, output_dir: str | Path) -> dict:
    base = build_synthetic_inputs(hours, seed)
    config = MicrogridConfig(
        battery_capacity_kwh=240.0,
        battery_initial_soc_kwh=120.0,
        battery_min_soc_kwh=36.0,
        battery_max_charge_kw=60.0,
        battery_max_discharge_kw=60.0,
        battery_charge_efficiency=0.94,
        battery_discharge_efficiency=0.94,
        grid_import_limit_kw=75.0,
        diesel_capacity_kw=80.0,
        ro_rated_power_kw=35.0,
        ro_specific_energy_kwh_per_m3=4.0,
        water_tank_capacity_m3=260.0,
        water_initial_inventory_m3=110.0,
    )
    no_ro = simulate_microgrid(base, config)
    with_ro = simulate_microgrid(
        MicrogridInputs(
            **{**base.__dict__, "ro_requested_power_kw": np.full(hours, 35.0)}
        ),
        config,
    )
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    hourly_path = output / "hourly_comparison.csv"
    fields = [
        "hour", "pv_kw", "wind_kw", "essential_load_kw", "grid_available",
        "ro_requested_kw", "ro_served_kw", "battery_soc_kwh", "grid_import_kw",
        "diesel_kw", "unserved_essential_kw", "water_produced_m3",
        "water_served_m3", "unmet_water_demand_m3", "water_inventory_m3",
        "renewable_curtailed_kw",
    ]
    with hourly_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for i in range(hours):
            writer.writerow({
                "hour": i,
                "pv_kw": base.pv_power_kw[i],
                "wind_kw": base.wind_power_kw[i],
                "essential_load_kw": base.essential_load_kw[i],
                "grid_available": bool(base.grid_available[i]),
                "ro_requested_kw": with_ro.ro_requested_power_kw[i],
                "ro_served_kw": with_ro.ro_power_served_kw[i],
                "battery_soc_kwh": with_ro.battery_soc_kwh[i + 1],
                "grid_import_kw": with_ro.grid_import_kw[i],
                "diesel_kw": with_ro.diesel_generation_kw[i],
                "unserved_essential_kw": with_ro.unserved_essential_kw[i],
                "water_produced_m3": with_ro.water_produced_m3[i],
                "water_served_m3": with_ro.water_served_m3[i],
                "unmet_water_demand_m3": with_ro.unmet_water_demand_m3[i],
                "water_inventory_m3": with_ro.water_inventory_m3[i + 1],
                "renewable_curtailed_kw": with_ro.renewable_curtailed_kw[i],
            })
    report = {
        "schema_version": "1.0",
        "project": "IslandOS",
        "experiment": "integrated_microgrid_ro_flex_load_screening",
        "data_provenance": "synthetic_demo_data_not_measured_site_data",
        "seed": seed,
        "hours": hours,
        "time_step_hours": 1.0,
        "policy": "essential_load_first_battery_grid_diesel_then_renewable_only_ro_then_battery_charge",
        "assumptions": {
            "battery_capacity_kwh": config.battery_capacity_kwh,
            "battery_charge_efficiency": config.battery_charge_efficiency,
            "battery_discharge_efficiency": config.battery_discharge_efficiency,
            "ro_rated_power_kw": config.ro_rated_power_kw,
            "ro_specific_energy_kwh_per_m3": config.ro_specific_energy_kwh_per_m3,
            "water_tank_capacity_m3": config.water_tank_capacity_m3,
            "grid_price_and_emissions_are_synthetic": True,
            "grid_outage_pattern": "4 hours from hour 20 every 72 hours",
        },
        "no_ro_baseline": no_ro.summary(),
        "renewable_only_ro_flex_load": with_ro.summary(),
        "interpretation": "Paired synthetic policy comparison. It demonstrates model behavior, not forecast skill, optimized performance, site savings, or field validation.",
        "hourly_csv": hourly_path.name,
    }
    report_path = output / "benchmark_report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=int, default=168)
    parser.add_argument("--seed", type=int, default=20261104)
    parser.add_argument("--output-dir", default="build/integrated-microgrid-demo")
    args = parser.parse_args()
    report = run_demo(args.hours, args.seed, args.output_dir)
    print(json.dumps({
        "data_provenance": report["data_provenance"],
        "hours": report["hours"],
        "baseline": report["no_ro_baseline"],
        "renewable_only_ro": report["renewable_only_ro_flex_load"],
        "output_dir": str(Path(args.output_dir)),
    }, indent=2))


if __name__ == "__main__":
    main()

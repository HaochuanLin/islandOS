#!/usr/bin/env python3
# IslandOS Nan‑ao emergency resilience pilot
# Single‑scenario simulation: valley‑hour power + wind curtailment surplus
# Pre‑existing RO as sunk asset; only operating‑cost calculation
# Simulation‑only result, not field‑calibrated
"""Single-scenario Nan'ao hybrid emergency-water simulation."""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
from pathlib import Path
from statistics import median

DEFAULT_SEED = 20261027
DEFAULT_RUNS = 1000
VALLEY_WATER_M3_PER_YEAR = 33650.0
RO_RATED_POWER_KW = 50.0
RO_SPECIFIC_ENERGY_KWH_PER_M3 = 4.0
VALLEY_ELECTRICITY_PRICE_RMB_PER_KWH = 0.272
ANNUAL_NON_ELECTRIC_OPEX_MIN_RMB = 8000.0
ANNUAL_NON_ELECTRIC_OPEX_MAX_RMB = 18000.0
PERSON_WATER_M3_PER_DAY = 0.05
DAYS_PER_YEAR = 365
DEFAULT_OUTPUT_DIR = Path("outputs")


def simulate_wind_curtailment_water(runs: int, seed: int) -> list[float]:
    """Simulate annual water yields from assumed wind-surplus events."""
    if runs < 1:
        raise ValueError("runs must be >= 1")
    rng = random.Random(seed)
    annual_yields: list[float] = []
    for _ in range(runs):
        event_count = max(0, int(round(rng.triangular(4, 12, 8))))
        annual_energy_kwh = 0.0
        for _ in range(event_count):
            duration_h = min(24.0, max(2.0, rng.lognormvariate(math.log(8.0), 0.5)))
            surplus_power_kw = rng.triangular(5.0, RO_RATED_POWER_KW, 25.0)
            ro_availability = rng.uniform(0.85, 1.0)
            annual_energy_kwh += duration_h * min(surplus_power_kw, RO_RATED_POWER_KW) * ro_availability
        annual_yields.append(annual_energy_kwh / RO_SPECIFIC_ENERGY_KWH_PER_M3)
    return annual_yields


def build_hybrid_result(runs: int = DEFAULT_RUNS, seed: int = DEFAULT_SEED) -> tuple[dict, dict]:
    wind_yields = simulate_wind_curtailment_water(runs, seed)
    wind_water_m3 = float(median(wind_yields))
    total_water_m3 = VALLEY_WATER_M3_PER_YEAR + wind_water_m3
    valley_electricity_cost_rmb = (
        VALLEY_WATER_M3_PER_YEAR
        * RO_SPECIFIC_ENERGY_KWH_PER_M3
        * VALLEY_ELECTRICITY_PRICE_RMB_PER_KWH
    )
    annual_cost_min_rmb = valley_electricity_cost_rmb + ANNUAL_NON_ELECTRIC_OPEX_MIN_RMB
    annual_cost_max_rmb = valley_electricity_cost_rmb + ANNUAL_NON_ELECTRIC_OPEX_MAX_RMB
    result = {
        "scenario": "IslandOS_hybrid_clean_energy",
        "total_annual_water_m³": round(total_water_m3, 3),
        "unit_op_cost_min_rmb": round(annual_cost_min_rmb / total_water_m3, 4),
        "unit_op_cost_max_rmb": round(annual_cost_max_rmb / total_water_m3, 4),
        "supported_population_50L": round(total_water_m3 / (PERSON_WATER_M3_PER_DAY * DAYS_PER_YEAR), 2),
    }
    metadata = {
        "project": "IslandOS Nan'ao emergency resilience pilot",
        "scenario": "IslandOS_hybrid_clean_energy",
        "seed": seed,
        "run_count": runs,
        "wind_curtailment_water_m3_per_year": {
            "median": round(wind_water_m3, 3),
            "minimum": round(min(wind_yields), 3),
            "maximum": round(max(wind_yields), 3),
        },
        "key_assumptions": {
            "valley_power_annual_water_yield_m3": VALLEY_WATER_M3_PER_YEAR,
            "ro_rated_power_kw": RO_RATED_POWER_KW,
            "ro_asset": "pre-existing 50 kW RO unit; sunk asset",
            "ro_purchase_capex_rmb": 0,
            "ro_specific_energy_kwh_per_m3": RO_SPECIFIC_ENERGY_KWH_PER_M3,
            "valley_electricity_price_rmb_per_kwh": VALLEY_ELECTRICITY_PRICE_RMB_PER_KWH,
            "annual_non_electric_operating_cost_range_rmb": [ANNUAL_NON_ELECTRIC_OPEX_MIN_RMB, ANNUAL_NON_ELECTRIC_OPEX_MAX_RMB],
            "non_electric_cost_scope": "chemical reagents and routine O&M; unverified screening assumption",
            "curtailed_wind_marginal_electricity_cost_rmb": 0,
            "supported_population_water_litres_per_person_day": 50,
            "hybrid_water_formula": "33650 m3/year + median of simulated annual wind-curtailment water yields",
            "unit_cost_formula": "(valley electricity cost + annual non-electric operating cost) / total annual hybrid water",
        },
        "limitations": [
            "Simulation-only output; not field-calibrated or a validated forecast.",
            "Wind event count, duration, surplus power, RO availability, specific energy, and operating costs are assumptions, not measured Nan'ao data.",
            "Valley-power annual water yield is fixed at 33650 m3/year and is not derived from hourly dispatch.",
            "Wind-curtailment electricity is assigned zero marginal energy cost; connection, treatment, and operational costs may still apply.",
            "The non-electric operating-cost range is unverified and must be replaced with site records.",
            "Population is an annual 50 L/person/day supply equivalent, not proof of safe water quality, storage, distribution, or continuous access."
        ],
    }
    return result, metadata


def write_outputs(output_dir: Path, result: dict, metadata: dict) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "scenario_result.csv").open("w", newline="", encoding="utf-8") as handle:
        fields = ["scenario", "total_annual_water_m³", "unit_op_cost_min_rmb", "unit_op_cost_max_rmb", "supported_population_50L"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow(result)
    (output_dir / "sim_meta.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    result, metadata = build_hybrid_result(runs=args.runs, seed=args.seed)
    write_outputs(args.output_dir, result, metadata)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

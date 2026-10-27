#!/usr/bin/env python3
"""Compare wind-only, valley-price, and hybrid emergency-water scenarios.

The existing RO unit is treated as a sunk asset (purchase CAPEX = RMB 0).
Reported costs are operating-cost screening assumptions only, not field-validated
economics. Valley-hour output is a fixed scenario assumption, not hourly dispatch.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from nan_ao_scenario import DEFAULT_RUNS, DEFAULT_SEED, run_simulation

RO_SEC_KWH_PER_M3 = 4.0
VALLEY_PRICE_RMB_PER_KWH = 0.272
VALLEY_WATER_M3_YEAR = 33_650.0
ANNUAL_OPEX_LOW_RMB = 8_000.0
ANNUAL_OPEX_HIGH_RMB = 18_000.0
EMERGENCY_WATER_M3_PER_PERSON_PER_DAY = 0.05
DAYS_PER_YEAR = 365
DEFAULT_OUTPUT = Path("outputs/nan_ao_three_scenarios.json")


def run_scenarios(runs: int = DEFAULT_RUNS, seed: int = DEFAULT_SEED) -> dict:
    """Return auditable screening fields for wind-only, valley-price, and hybrid."""
    _rows, wind_summary = run_simulation(runs=runs, seed=seed)
    wind = wind_summary["scenario_water_produced_m3_per_year"]
    wind_p05 = float(wind["p05"])
    wind_median = float(wind["p50_median"])
    wind_p95 = float(wind["p95"])
    valley_energy_cost = VALLEY_WATER_M3_YEAR * RO_SEC_KWH_PER_M3 * VALLEY_PRICE_RMB_PER_KWH
    definitions = [
        ("wind_only", "Wind-curtailment-only emergency production", wind_p05, wind_median, wind_p95, 0.0),
        ("valley_price", "Valley-price electricity-only production", VALLEY_WATER_M3_YEAR, VALLEY_WATER_M3_YEAR, VALLEY_WATER_M3_YEAR, valley_energy_cost),
        ("hybrid", "Wind-curtailment + valley-price hybrid", VALLEY_WATER_M3_YEAR + wind_p05, VALLEY_WATER_M3_YEAR + wind_median, VALLEY_WATER_M3_YEAR + wind_p95, valley_energy_cost),
    ]
    scenarios = []
    for key, name, p05, median, p95, electricity_cost in definitions:
        low_total_cost = ANNUAL_OPEX_LOW_RMB + electricity_cost
        high_total_cost = ANNUAL_OPEX_HIGH_RMB + electricity_cost
        scenarios.append({
            "scenario_key": key,
            "scenario_name": name,
            "ro_purchase_capex_rmb": 0.0,
            "annual_water_p05_m3": round(p05, 3),
            "annual_water_median_m3": round(median, 3),
            "annual_water_p95_m3": round(p95, 3),
            "valley_electricity_cost_rmb_per_year": round(electricity_cost, 2),
            "annual_operating_cost_low_rmb": round(low_total_cost, 2),
            "annual_operating_cost_high_rmb": round(high_total_cost, 2),
            "unit_operating_cost_low_rmb_per_m3": round(low_total_cost / p95, 4) if p95 else None,
            "unit_operating_cost_high_rmb_per_m3": round(high_total_cost / p05, 4) if p05 else None,
        })
    median_hybrid_water = VALLEY_WATER_M3_YEAR + wind_median
    return {
        "title": "Nan'ao emergency-resilience operating-cost scenario screen",
        "runs": runs,
        "seed": seed,
        "ro_purchase_capex_rmb": 0.0,
        "assumptions": {
            "ro_asset": "pre-existing sunk asset; purchase CAPEX excluded",
            "scope": "emergency resilience pilot, not full-island daily water supply",
            "ro_specific_energy_kwh_per_m3": RO_SEC_KWH_PER_M3,
            "valley_price_rmb_per_kwh": VALLEY_PRICE_RMB_PER_KWH,
            "valley_water_m3_per_year": VALLEY_WATER_M3_YEAR,
            "annual_opex_assumption_rmb": [ANNUAL_OPEX_LOW_RMB, ANNUAL_OPEX_HIGH_RMB],
            "emergency_benchmark_litres_per_person_day": 50,
        },
        "scenarios": scenarios,
        "hybrid_emergency_population_annual_supply_equivalent": int(
            median_hybrid_water / (EMERGENCY_WATER_M3_PER_PERSON_PER_DAY * DAYS_PER_YEAR)
        ),
        "limitations": [
            "Monte Carlo wind-curtailment yield is assumption-driven and not field-validated.",
            "Valley-hour production is a fixed screening assumption, not derived from hourly Nan'ao wind/load data.",
            "The model assumes valley-price and curtailed-wind production windows do not overlap.",
            "Annual O&M values are draft assumptions; electricity, chemicals, membrane maintenance and routine O&M require site records.",
            "Population is an annual-supply equivalent and does not establish water quality, storage, distribution, or emergency access.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args()
    report = run_scenarios(runs=args.runs, seed=args.seed)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

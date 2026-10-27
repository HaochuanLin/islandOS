#!/usr/bin/env python3
# IslandOS Nan‑ao emergency resilience pilot
# Single‑scenario simulation: valley‑hour power + wind curtailment surplus
# Pre‑existing RO as sunk asset; only operating‑cost calculation
# Simulation‑only result, not field‑calibrated
# System setup: Two local standby 50 kW RO skid-mounted units are coordinated in parallel.
# The competition submission documented multiple existing small-scale RO desalination units across Nan'ao island. This solution aggregates these distributed emergency assets under our scheduling platform.
# Exact hardware inventory will be confirmed during on-site pilot investigation.
# All RO hardware are existing island assets, no new-equipment capital expenditure.
# Valley-power yield is calculated from hardware rating, daily valley window and equipment availability factor.
# Wind-curtailment water yield comes from 1000-time Monte-Carlo stochastic event simulation; annual curtailment hours are simulated output statistics, not pre-set input.
"""Single-scenario Nan'ao hybrid emergency-water simulation."""
from __future__ import annotations
import argparse, csv, json, math, random
from pathlib import Path
from statistics import median

DEFAULT_SEED = 20261028
DEFAULT_RUNS = 1000
RO_UNIT_COUNT = 2
RO_UNIT_POWER_KW = 50.0
RO_RATED_POWER_KW = RO_UNIT_COUNT * RO_UNIT_POWER_KW
RO_SPECIFIC_ENERGY_KWH_PER_M3 = 4.0
VALLEY_WINDOW_H_PER_DAY = 8.0
RO_AVAILABILITY_FACTOR = 0.925
VALLEY_ELECTRICITY_PRICE_RMB_PER_KWH = 0.272
ANNUAL_NON_ELECTRIC_OPEX_MIN_RMB = 8000.0
ANNUAL_NON_ELECTRIC_OPEX_MAX_RMB = 18000.0
PERSON_WATER_M3_PER_DAY = 0.05
DAYS_PER_YEAR = 365
DEFAULT_OUTPUT_DIR = Path("outputs")


def simulate_wind_curtailment(runs: int, seed: int) -> tuple[list[float], list[float]]:
    """Return wind-water yields and simulated annual curtailment hours for each run."""
    if runs < 1:
        raise ValueError("runs must be >= 1")
    rng = random.Random(seed)
    yields, hours = [], []
    for _ in range(runs):
        count = max(0, int(round(rng.triangular(4, 12, 8))))
        event_hours = energy = 0.0
        for _ in range(count):
            duration = min(24.0, max(2.0, rng.lognormvariate(math.log(8.0), 0.5)))
            surplus_kw = rng.triangular(5.0, RO_RATED_POWER_KW, RO_RATED_POWER_KW / 2.0)
            event_hours += duration
            energy += duration * min(surplus_kw, RO_RATED_POWER_KW) * RO_AVAILABILITY_FACTOR
        yields.append(energy / RO_SPECIFIC_ENERGY_KWH_PER_M3)
        hours.append(event_hours)
    return yields, hours


def build_hybrid_result(runs: int = DEFAULT_RUNS, seed: int = DEFAULT_SEED) -> tuple[dict, dict]:
    wind_yields, wind_hours = simulate_wind_curtailment(runs, seed)
    wind_water = float(median(wind_yields))
    m3_per_hour = RO_RATED_POWER_KW / RO_SPECIFIC_ENERGY_KWH_PER_M3
    valley_water = m3_per_hour * VALLEY_WINDOW_H_PER_DAY * DAYS_PER_YEAR * RO_AVAILABILITY_FACTOR
    total_water = valley_water + wind_water
    valley_electricity_cost = valley_water * RO_SPECIFIC_ENERGY_KWH_PER_M3 * VALLEY_ELECTRICITY_PRICE_RMB_PER_KWH
    result = {
        "scenario": "IslandOS_hybrid_clean_energy",
        "total_annual_water_m³": round(total_water, 3),
        "unit_op_cost_min_rmb": round((valley_electricity_cost + ANNUAL_NON_ELECTRIC_OPEX_MIN_RMB) / total_water, 4),
        "unit_op_cost_max_rmb": round((valley_electricity_cost + ANNUAL_NON_ELECTRIC_OPEX_MAX_RMB) / total_water, 4),
        "supported_population_50L": round(total_water / (PERSON_WATER_M3_PER_DAY * DAYS_PER_YEAR), 2),
    }
    meta = {
        "project": "IslandOS Nan'ao emergency resilience pilot",
        "scenario": result["scenario"], "seed": seed, "run_count": runs,
        "parameters": {
            "ro_unit_count": RO_UNIT_COUNT, "ro_unit_power_kw": RO_UNIT_POWER_KW,
            "ro_rated_power_kw": RO_RATED_POWER_KW,
            "ro_specific_energy_kwh_per_m3": RO_SPECIFIC_ENERGY_KWH_PER_M3,
            "valley_window_h_per_day": VALLEY_WINDOW_H_PER_DAY,
            "ro_availability_factor": RO_AVAILABILITY_FACTOR,
            "valley_electricity_price_rmb_per_kwh": VALLEY_ELECTRICITY_PRICE_RMB_PER_KWH,
            "annual_non_electric_opex_min_rmb": ANNUAL_NON_ELECTRIC_OPEX_MIN_RMB,
            "annual_non_electric_opex_max_rmb": ANNUAL_NON_ELECTRIC_OPEX_MAX_RMB,
            "ro_purchase_capex_rmb": 0,
            "wind_event_count_distribution": "round(triangular(4, 12, mode=8)), minimum 0",
            "wind_event_duration_distribution": "lognormal(median=8 h, sigma=0.5), clipped to 2-24 h",
            "wind_surplus_power_distribution": "triangular(5 kW, 100 kW, mode=50 kW)",
            "non_electric_cost_scope": "chemical reagents and routine O&M; unverified screening assumptions",
            "asset_inventory_note": "Multiple existing small-scale RO units are documented in the competition submission; exact inventory to be confirmed on site.",
        },
        "calculated_values": {
            "m3_per_hour": round(m3_per_hour, 6), "valley_annual_water_m3": round(valley_water, 3),
            "wind_water_m3_median": round(wind_water, 3),
            "wind_water_m3_min": round(min(wind_yields), 3), "wind_water_m3_max": round(max(wind_yields), 3),
            "simulated_annual_wind_curtailment_hours_median": round(float(median(wind_hours)), 3),
            "simulated_annual_wind_curtailment_hours_min": round(min(wind_hours), 3),
            "simulated_annual_wind_curtailment_hours_max": round(max(wind_hours), 3),
            "valley_electricity_cost_rmb_per_year": round(valley_electricity_cost, 2),
        },
        "calculation_notes": [
            "Valley annual water = (total rated RO kW / specific energy) * valley hours/day * 365 * availability factor.",
            "Total water = calculated valley water + median simulated annual wind-curtailment water.",
            "Annual wind-curtailment hours are stochastic output statistics, not pre-set input.",
            "Unit operating cost = (valley electricity cost + annual non-electric OPEX bound) / total hybrid water.",
            "Existing RO assets have zero new-equipment CAPEX; wind-surplus marginal electricity is assumed to cost zero.",
            "Annual non-electric OPEX range is unverified and must be replaced with site records.",
        ],
        "limitations": [
            "Simulation-only; not field-calibrated or a validated forecast.",
            "Event count, duration and surplus power distributions are assumptions, not measured Nan'ao data.",
            "Exact installed inventory and actual availability require on-site confirmation.",
            "Population is a 50 L/person/day annual supply equivalent, not proof of water quality or distribution access.",
        ],
    }
    return result, meta


def write_outputs(output_dir: Path, result: dict, metadata: dict) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    fields = ["scenario", "total_annual_water_m³", "unit_op_cost_min_rmb", "unit_op_cost_max_rmb", "supported_population_50L"]
    with (output_dir / "scenario_result.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerow(result)
    (output_dir / "sim_meta.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    result, meta = build_hybrid_result(args.runs, args.seed)
    write_outputs(args.output_dir, result, meta)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

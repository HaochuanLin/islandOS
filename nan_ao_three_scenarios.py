#!/usr/bin/env python3
"""Economic screening for the Nan'ao valley-hour + curtailed-wind scenario.

The physical Monte Carlo model remains in nan_ao_scenario.py and is imported
without modification. This script runs its fixed-seed 1,000-run simulation,
then adds the explicitly hypothetical valley-hour production assumption.

All results are assumption-driven screening outputs, not measured field data.
"""
from __future__ import annotations

import csv
from pathlib import Path

from nan_ao_scenario import DEFAULT_RUNS, DEFAULT_SEED, run_simulation

# Existing RO is assumed to be safely reusable; purchase CAPEX is zero and is
# excluded. New-RO procurement is retained only as a reference consideration:
# if no suitable existing unit can be verified, a separately costed fallback
# procurement case would be required; it is not part of this primary result.

# Fixed screening assumptions retained from the existing economic model.
VALLEY_WATER_M3_YEAR = 33_650.0
RO_SEC_KWH_PER_M3 = 4.0  # Do not change: original RO specific-energy assumption.
VALLEY_PRICE_RMB_PER_KWH = 0.272
ANNUAL_OPEX_LOW_RMB = 8_000.0
ANNUAL_OPEX_HIGH_RMB = 18_000.0
EMERGENCY_WATER_M3_PER_PERSON_PER_DAY = 0.05  # User-specified 50 L/person/day.
DAYS_PER_YEAR = 365
OUTPUT_CSV = Path("nan_ao_hybrid_scenario_results.csv")


def fmt(value: float) -> str:
    return f"{value:,.2f}"


def main() -> int:
    # Reuse the unchanged Nan'ao Monte Carlo implementation, including its
    # stochastic event counts, wind-surplus power limits, event duration,
    # RO availability, SEC, fixed seed, and risk/boundary assumptions.
    _run_rows, summary = run_simulation(runs=DEFAULT_RUNS, seed=DEFAULT_SEED)
    curtailment = summary["scenario_water_produced_m3_per_year"]
    p05 = float(curtailment["p05"])
    median = float(curtailment["p50_median"])
    p95 = float(curtailment["p95"])

    # Valley-hour electricity is charged only to water produced during valley
    # hours. Curtailment-window water is assumed to use otherwise-curtailed
    # power and therefore carries no purchased-electricity charge in this screen.
    valley_electricity_rmb_year = (
        VALLEY_WATER_M3_YEAR * RO_SEC_KWH_PER_M3 * VALLEY_PRICE_RMB_PER_KWH
    )
    annual_water_p05 = VALLEY_WATER_M3_YEAR + p05
    annual_water_median = VALLEY_WATER_M3_YEAR + median
    annual_water_p95 = VALLEY_WATER_M3_YEAR + p95

    # Conservative cross-range: low O&M with P95 water for the lower unit-cost
    # bound; high O&M with P05 water for the upper bound.
    unit_cost_low = (
        ANNUAL_OPEX_LOW_RMB + valley_electricity_rmb_year
    ) / annual_water_p95
    unit_cost_high = (
        ANNUAL_OPEX_HIGH_RMB + valley_electricity_rmb_year
    ) / annual_water_p05

    supported_population = int(
        annual_water_median
        / (EMERGENCY_WATER_M3_PER_PERSON_PER_DAY * DAYS_PER_YEAR)
    )
    per_person_annual_water = (
        EMERGENCY_WATER_M3_PER_PERSON_PER_DAY * DAYS_PER_YEAR
    )

    print("Nan'ao Island — Valley-Hour + Curtailed-Wind Hybrid Scenario")
    print("=" * 68)
    print(f"Monte Carlo runs:              {summary['runs']:,}")
    print(f"Fixed random seed:             {summary['seed']}")
    print("Existing RO purchase CAPEX:    RMB 0.00 (treated as sunk cost)")
    print(f"Annual operating cost range:   RMB {ANNUAL_OPEX_LOW_RMB:,.0f}–{ANNUAL_OPEX_HIGH_RMB:,.0f}")
    print(f"Valley-hour electricity cost:  RMB {VALLEY_PRICE_RMB_PER_KWH:.3f}/kWh")
    print(f"RO specific energy:            {RO_SEC_KWH_PER_M3:.2f} kWh/m³")
    print()
    print("PRIMARY RESULT")
    print("-" * 68)
    print(f"Unit water operating cost:     RMB {fmt(unit_cost_low)}–{fmt(unit_cost_high)}/m³")
    print(f"Annual freshwater yield:       {fmt(annual_water_median)} m³/year (median scenario)")
    print(
        f"Emergency-water population:    {supported_population:,} people "
        f"at 50 L/person/day, sustained for 365 days"
    )
    print()
    print("MONTE CARLO WATER-YIELD RANGE")
    print("-" * 68)
    print(f"Combined annual yield P05:     {fmt(annual_water_p05)} m³/year")
    print(f"Combined annual yield median:  {fmt(annual_water_median)} m³/year")
    print(f"Combined annual yield P95:     {fmt(annual_water_p95)} m³/year")
    print()
    print("BOUNDARIES AND LIMITATIONS")
    print("-" * 68)
    print("- Existing RO purchase cost is excluded; electricity, membrane/chemical costs and routine O&M should be verified against site records.")
    print("- Valley-hour production is a fixed screening assumption, not derived from hourly Nan'ao load or wind time-series data.")
    print("- The hybrid calculation assumes valley-hour and curtailed-wind operating windows do not overlap.")
    print("- Curtailment production is simulated from the unchanged assumption-driven model; it is not measured Nan'ao output or a calibrated forecast.")
    print("- The cost range combines low O&M with P95 output and high O&M with P05 output; it is a screening envelope, not a confidence interval.")
    print("- The 50 L/person/day benchmark is applied as specified by the user; the population figure is a theoretical annual-supply equivalent and does not establish potable-water quality, storage, distribution, or emergency access.")
    print()

    # Export a compact, readable summary table for reuse in reports and slides.
    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "scenario",
                "monte_carlo_runs",
                "seed",
                "existing_ro_purchase_capex_rmb",
                "unit_cost_low_rmb_per_m3",
                "unit_cost_high_rmb_per_m3",
                "annual_water_p05_m3",
                "annual_water_median_m3",
                "annual_water_p95_m3",
                "emergency_population_at_50_l_per_person_day",
                "annual_opex_low_rmb",
                "annual_opex_high_rmb",
                "valley_electricity_price_rmb_per_kwh",
                "ro_specific_energy_kwh_per_m3",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "scenario": "Valley-hour + curtailed-wind hybrid (IslandOS screening)",
                "monte_carlo_runs": summary["runs"],
                "seed": summary["seed"],
                "existing_ro_purchase_capex_rmb": 0,
                "unit_cost_low_rmb_per_m3": round(unit_cost_low, 4),
                "unit_cost_high_rmb_per_m3": round(unit_cost_high, 4),
                "annual_water_p05_m3": round(annual_water_p05, 3),
                "annual_water_median_m3": round(annual_water_median, 3),
                "annual_water_p95_m3": round(annual_water_p95, 3),
                "emergency_population_at_50_l_per_person_day": supported_population,
                "annual_opex_low_rmb": ANNUAL_OPEX_LOW_RMB,
                "annual_opex_high_rmb": ANNUAL_OPEX_HIGH_RMB,
                "valley_electricity_price_rmb_per_kwh": VALLEY_PRICE_RMB_PER_KWH,
                "ro_specific_energy_kwh_per_m3": RO_SEC_KWH_PER_M3,
            }
        )

    print(f"CSV summary exported to:       {OUTPUT_CSV.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

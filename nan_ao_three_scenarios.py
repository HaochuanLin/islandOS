#!/usr/bin/env python3
# Important
# nan_ao_three_scenarios.py is post-hoc economic screening script ONLY.
# Physical water-yield Monte-Carlo is from nan_ao_scenario.py seed=20261021, UNCHANGED.
# Scenario-1 is judging baseline (new-procurement RO).
# Scenario2-4 are hypothetical exploratory cases. Scenario-4 requires purchasing valley-hour grid-power and is NOT part of July-03 submission pilot scope.
# Assumption for scenario2-4: RO hardware & land treated as sunk-cost, no capital charge.
# Scenario-4 assumption: all curtailment events occur outside valley-hour windows, no time-overlap. Real-world occasional overlap may exist.
"""Post-hoc financial screening for four Nan'ao RO operating scenarios.

This script does not import, execute, or modify nan_ao_scenario.py. It reuses
only the frozen physical-yield summary values supplied for this screening:
P5=237.6, median=442.7, P95=693.2 m³/year.

All costs are assumption-based screening estimates, not measured site results.
Run: python nan_ao_three_scenarios.py
"""
from __future__ import annotations

from dataclasses import dataclass

# Frozen physical simulation summary; do not rerun Monte Carlo here.
WATER_P5_M3_YEAR = 237.6
WATER_MEDIAN_M3_YEAR = 442.7
WATER_P95_M3_YEAR = 693.2

RO_SEC_KWH_PER_M3 = 4.0
VALLEY_PRICE_RMB_PER_KWH = 0.272
ANNUAL_OPEX_LOW_RMB = 8_000.0
ANNUAL_OPEX_HIGH_RMB = 18_000.0
RO_CAPEX_LOW_RMB = 1_600_000.0
RO_CAPEX_HIGH_RMB = 3_300_000.0
CAPEX_AMORTIZATION_YEARS = 10
VALLEY_HOURS_PER_DAY_MAX = 8
RO_AVAILABILITY = 0.925
SCENARIO_3_VALLEY_WATER_M3_YEAR = 33_650.0


@dataclass(frozen=True)
class Scenario:
    name: str
    description: str
    annual_water_m3: float
    capital_included: str
    opex_per_m3: tuple[float, float]
    electricity_per_m3: tuple[float, float]
    total_per_m3: tuple[float, float]


def _range(low: float, high: float) -> tuple[float, float]:
    return (min(low, high), max(low, high))


def _fmt(value: float) -> str:
    return f"{value:,.2f}"


def _fmt_range(values: tuple[float, float]) -> str:
    return f"{_fmt(values[0])}–{_fmt(values[1])}"


def build_scenarios() -> list[Scenario]:
    # Baseline comparisons use the stated median annual yield as the common
    # denominator. P5/P95 are shown in the explanation as physical uncertainty,
    # not silently mixed into the cost range.
    baseline_water = WATER_MEDIAN_M3_YEAR
    s1_capital_per_year = (
        RO_CAPEX_LOW_RMB / CAPEX_AMORTIZATION_YEARS,
        RO_CAPEX_HIGH_RMB / CAPEX_AMORTIZATION_YEARS,
    )
    s1_opex = _range(
        ANNUAL_OPEX_LOW_RMB / baseline_water,
        ANNUAL_OPEX_HIGH_RMB / baseline_water,
    )
    s1_capital = _range(
        s1_capital_per_year[0] / baseline_water,
        s1_capital_per_year[1] / baseline_water,
    )
    s1_total = (
        s1_capital[0] + s1_opex[0],
        s1_capital[1] + s1_opex[1],
    )

    # S2: sunk RO/land, curtailment-only; no purchased electricity.
    s2_opex = _range(
        ANNUAL_OPEX_LOW_RMB / baseline_water,
        ANNUAL_OPEX_HIGH_RMB / baseline_water,
    )

    # S3: timer-only, 0–8 scheduled valley hours/day, 92.5% availability.
    # The user-specified annual production of 33,650 m³ is authoritative for
    # this financial screen; hours/availability are recorded as assumptions.
    s3_water = SCENARIO_3_VALLEY_WATER_M3_YEAR
    s3_opex = _range(
        ANNUAL_OPEX_LOW_RMB / s3_water,
        ANNUAL_OPEX_HIGH_RMB / s3_water,
    )
    s3_electricity = RO_SEC_KWH_PER_M3 * VALLEY_PRICE_RMB_PER_KWH
    s3_total = (
        s3_opex[0] + s3_electricity,
        s3_opex[1] + s3_electricity,
    )

    # S4: hypothetical disjoint windows. Add timer-based valley production to
    # each supplied physical curtailment-yield percentile. Electricity is paid
    # only for the valley-produced water; fixed O&M is spread over total water.
    s4_water_low = s3_water + WATER_P5_M3_YEAR
    s4_water_high = s3_water + WATER_P95_M3_YEAR
    s4_water_mid = s3_water + WATER_MEDIAN_M3_YEAR
    s4_opex = _range(
        ANNUAL_OPEX_LOW_RMB / s4_water_high,
        ANNUAL_OPEX_HIGH_RMB / s4_water_low,
    )
    s4_electricity = (
        s3_water * RO_SEC_KWH_PER_M3 * VALLEY_PRICE_RMB_PER_KWH / s4_water_high,
        s3_water * RO_SEC_KWH_PER_M3 * VALLEY_PRICE_RMB_PER_KWH / s4_water_low,
    )
    s4_total = (
        s4_opex[0] + s4_electricity[0],
        s4_opex[1] + s4_electricity[1],
    )

    return [
        Scenario(
            "Judgement Baseline",
            "Newly procured 50 kW RO; curtailment-only operation; RO capital amortized straight-line over 10 years; no electricity cost",
            baseline_water,
            "Yes (RMB 1.6–3.3 million, amortized over 10 years)",
            s1_opex,
            (0.0, 0.0),
            s1_total,
        ),
        Scenario(
            "Hypothetical-A",
            "RO and land treated as sunk costs; curtailment-only operation; fixed annual O&M; no electricity cost",
            baseline_water,
            "No (treated as sunk cost)",
            s2_opex,
            (0.0, 0.0),
            s2_opex,
        ),
        Scenario(
            "Hypothetical-B",
            "No capital charge for RO or land; timer-based valley-hour operation for 0–8 h/day at 92.5% availability; annual output fixed at the specified 33,650 m³",
            s3_water,
            "否（沉没资产）",
            s3_opex,
            (s3_electricity, s3_electricity),
            s3_total,
        ),
        Scenario(
            "Hypothetical-C (IslandOS)",
            "Assumes no overlap between curtailment and valley-power windows; uses both windows; 33,650 m³/year from valley power plus additional curtailment-powered water",
            s4_water_mid,
            "否（沉没资产）",
            s4_opex,
            s4_electricity,
            s4_total,
        ),
    ]


def render_markdown_table(scenarios: list[Scenario]) -> str:
    lines = [
        "| Scenario | Description | Annual water output (m³) | RO capital included? | Allocated O&M (RMB/m³) | Electricity cost (RMB/m³) | Total screening cost (RMB/m³) |",
        "|---|---|---:|---|---:|---:|---:|",
    ]
    for s in scenarios:
        water = f"{s.annual_water_m3:,.1f}"
        lines.append(
            f"| {s.name} | {s.description} | {water} | {s.capital_included} "
            f"| {_fmt_range(s.opex_per_m3)} | {_fmt_range(s.electricity_per_m3)} "
            f"| {_fmt_range(s.total_per_m3)} |"
        )
    return "\n".join(lines)


def main() -> int:
    scenarios = build_scenarios()
    print("# Nan'ao Four-Scenario Post-Hoc Financial Screening")
    print()
    print(render_markdown_table(scenarios))
    print()
    print("## Emergency Water Supply Benchmarks (user-provided ranges; not independently verified by this script)")
    print("- Water delivery by boat: RMB 20–35/m³ (post-disaster; constrained by typhoon sea conditions)")
    print("- Bottled mineral water: RMB 2,000–4,000/m³ (post-disaster; logistics are weather-dependent)")
    print("- IslandOS hybrid operation is positioned for pre-disaster water storage. Pre-stored water can reduce post-disaster dependence on sea conditions and just-in-time logistics; actual resilience depends on storage capacity and operating conditions.")
    print()
    print("## Methodology and Limitations")
    print(
        f"- Reused physical-yield statistics: P5={WATER_P5_M3_YEAR:.1f}, "
        f"median={WATER_MEDIAN_M3_YEAR:.1f}, P95={WATER_P95_M3_YEAR:.1f} m³/year; "
        "this script does not run Monte Carlo simulation."
    )
    print("- Scenarios 1–2 use median annual output (442.7 m³/year) as a common denominator. Their costs are screening estimates at median output, not P5/P95 cost ranges.")
    print("- Fixed annual O&M is divided by annual water output; it is not modeled as a variable cost that scales linearly with production.")
    print("- Scenario 3 uses the specified annual output of 33,650 m³/year. SEC multiplied by the valley electricity tariff equals RMB 1.088/m³, before allocated fixed annual O&M.")
    print("- Scenario 4 assumes non-overlapping operating windows and adds valley-power water to curtailment-powered water. Electricity cost is charged only for valley-power production, while fixed O&M is allocated across total output. Occasional overlap may occur in real operation.")
    print("- Scenario 4's displayed annual output uses median curtailment yield plus valley-power production; its cost range is estimated using P5–P95 curtailment yield.")
    print("- Scenarios 2–4 are hypothetical exploratory cases. Scenario 4 requires purchasing valley-hour grid electricity and is outside the July 3 submission pilot scope.")
    print("- Scenarios excluding RO capital may still incur membrane replacement, chemicals, civil works, intake/discharge, brine treatment, and demand charges; these costs are outside this screening scope.")
    print()
    print("Note: The output table can be copied into docs/COST_TRADEOFFS.md, a presentation, or a Word document. This script does not modify the original physical simulation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

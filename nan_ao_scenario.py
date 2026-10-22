#!/usr/bin/env python3
"""Nan'ao Island RO flexibility scenario model.

This is an assumption-driven annual event-energy model, not a grid-flow model
and not a reconstruction of measured Nan'ao curtailment. All distributions are
explicit scenario inputs and should be replaced with validated local data.
Uses only the Python standard library.
"""
from __future__ import annotations

import argparse
import csv
import itertools
import json
import math
import random
from pathlib import Path
from statistics import median

DEFAULT_SEED = 20261021
DEFAULT_RUNS = 1000

ASSUMPTIONS = {
    "site": "Nan'ao Island, Guangdong, China",
    "model_type": "scenario-based annual export-limitation event-energy abstraction",
    "ro_rated_power_kw": 50.0,
    "ro_specific_energy_kwh_per_m3": 4.0,
    "annual_events_distribution": "triangular integer approximation: round(Triangular(4, 12, mode=8))",
    "event_duration_hours_distribution": "lognormal with median 8 h and sigma=0.5, clipped to [2, 24] h",
    "available_surplus_power_kw_distribution": "triangular(5, 50, mode=25) kW during an event",
    "ro_availability_distribution": "uniform(0.85, 1.00) per event",
    "water_yield_formula": "sum(event_hours * min(available_surplus_kw, RO_rated_power_kw) * RO_availability) / SEC",
    "standby_ro_status": (
        "No publicly accessible official documentation reviewed by the team confirms an "
        "operable standby seawater RO unit on Nan'ao main island. The pilot assumes a modular "
        "50 kW RO unit would be procured, installed and owned by the local water authority, "
        "subject to site verification, approval and budget."
    ),
    "data_status": "assumptions only; no measured Nan'ao curtailment time series supplied",
    "exclusions": [
        "No hourly grid power-flow, network congestion, export-limit or dispatch simulation",
        "No measured renewable generation, demand, curtailment or outage-event dataset",
        "No water demand, reservoir constraints, water-quality approval or plant ramp/flush model",
        "No CAPEX/OPEX, savings, ROI, emissions or avoided-outage claims",
        "No claim that the modeled events actually occurred on Nan'ao",
    ],
}


def triangular_integer(rng: random.Random, low: int, high: int, mode: int) -> int:
    return max(0, int(round(rng.triangular(low, high, mode))))


def simulate_one_year(rng: random.Random, run_id: int) -> dict:
    event_count = triangular_integer(rng, 4, 12, 8)
    total_hours = 0.0
    total_energy_kwh = 0.0
    for _ in range(event_count):
        duration_h = min(24.0, max(2.0, rng.lognormvariate(math.log(8.0), 0.5)))
        available_kw = rng.triangular(5.0, 50.0, 25.0)
        ro_availability = rng.uniform(0.85, 1.0)
        usable_kw = min(available_kw, ASSUMPTIONS["ro_rated_power_kw"])
        total_hours += duration_h
        total_energy_kwh += duration_h * usable_kw * ro_availability

    water_m3 = total_energy_kwh / ASSUMPTIONS["ro_specific_energy_kwh_per_m3"]
    return {
        "run_id": run_id,
        "assumed_events_per_year": event_count,
        "event_hours_total": round(total_hours, 3),
        "usable_ro_energy_kwh": round(total_energy_kwh, 3),
        "scenario_water_produced_m3_per_year": round(water_m3, 3),
    }


def percentile(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        raise ValueError("values must not be empty")
    position = (len(sorted_values) - 1) * p
    lo = math.floor(position)
    hi = math.ceil(position)
    if lo == hi:
        return sorted_values[lo]
    return sorted_values[lo] * (hi - position) + sorted_values[hi] * (position - lo)


def run_simulation(runs: int = DEFAULT_RUNS, seed: int = DEFAULT_SEED) -> tuple[list[dict], dict]:
    if runs < 1:
        raise ValueError("runs must be >= 1")
    rng = random.Random(seed)
    rows = [simulate_one_year(rng, i + 1) for i in range(runs)]
    values = sorted(row["scenario_water_produced_m3_per_year"] for row in rows)
    summary = {
        "title": "Nan'ao Island RO flexibility — illustrative scenario simulation",
        "seed": seed,
        "runs": runs,
        "assumptions": ASSUMPTIONS,
        "scenario_water_produced_m3_per_year": {
            "p05": round(percentile(values, 0.05), 3),
            "p50_median": round(percentile(values, 0.50), 3),
            "p95": round(percentile(values, 0.95), 3),
            "mean": round(sum(values) / len(values), 3),
        },
        "interpretation": (
            "Scenario-based simulation assumption, not measured real-world data. "
            "Percentiles describe only the stated assumptions; they are not a forecast, "
            "guarantee, validated water yield, or evidence of actual Nan'ao curtailment."
        ),
        "limitations": ASSUMPTIONS["exclusions"],
    }
    return rows, summary


def run_sensitivity_analysis() -> list[dict]:
    """Return a deterministic one-factor-at-a-time grid of scenario assumptions.

    These representative combinations are a sensitivity screen, not a probability
    distribution, calibrated forecast, or substitute for measured curtailment data.
    """
    event_counts = (4, 8, 12)
    event_durations_h = (4.0, 8.0, 12.0)
    surplus_power_kw_values = (10.0, 25.0, 40.0)
    availability_values = (0.85, 0.925, 1.0)
    sec_values = (3.5, 4.0, 5.0)

    rows: list[dict] = []
    for events, duration_h, surplus_kw, availability, sec in itertools.product(
        event_counts, event_durations_h, surplus_power_kw_values,
        availability_values, sec_values,
    ):
        usable_power_kw = min(surplus_kw, ASSUMPTIONS["ro_rated_power_kw"])
        annual_energy_kwh = events * duration_h * usable_power_kw * availability
        rows.append({
            "assumed_events_per_year": events,
            "representative_event_duration_h": duration_h,
            "available_surplus_power_kw": surplus_kw,
            "ro_availability_fraction": availability,
            "specific_energy_kwh_per_m3": sec,
            "scenario_usable_energy_kwh_per_year": round(annual_energy_kwh, 3),
            "scenario_water_m3_per_year": round(annual_energy_kwh / sec, 3),
            "interpretation": "deterministic sensitivity combination; not a probability or field prediction",
        })
    return rows



def calculate_capital_cost_screen(
    annual_water_output_m3: float,
    capex_low_rmb: float = 1_600_000.0,
    capex_high_rmb: float = 3_300_000.0,
    equipment_life_years: float = 10.0,
) -> dict:
    """Return an illustrative capital-only cost screen, not ROI or payback.

    Costs and lifetime are user-supplied screening assumptions. The calculation
    excludes O&M, site/civil works, outfall, replacements, financing and downtime.
    """
    values = {
        "annual_water_output_m3": annual_water_output_m3,
        "capex_low_rmb": capex_low_rmb,
        "capex_high_rmb": capex_high_rmb,
        "equipment_life_years": equipment_life_years,
    }
    if any(not math.isfinite(value) for value in values.values()):
        raise ValueError("all financial screen inputs must be finite")
    if annual_water_output_m3 <= 0:
        raise ValueError("annual_water_output_m3 must be > 0")
    if capex_low_rmb <= 0 or capex_high_rmb < capex_low_rmb:
        raise ValueError("CAPEX must be positive and capex_high_rmb >= capex_low_rmb")
    if equipment_life_years <= 0:
        raise ValueError("equipment_life_years must be > 0")

    return {
        "status": "illustrative capital-only screen; not ROI, payback, tariff, or investment advice",
        "annual_water_output_m3": round(annual_water_output_m3, 3),
        "capex_low_rmb": round(capex_low_rmb, 2),
        "capex_high_rmb": round(capex_high_rmb, 2),
        "equipment_life_years_assumed": equipment_life_years,
        "capital_only_cost_rmb_per_m3_low": round(
            capex_low_rmb / equipment_life_years / annual_water_output_m3, 2
        ),
        "capital_only_cost_rmb_per_m3_high": round(
            capex_high_rmb / equipment_life_years / annual_water_output_m3, 2
        ),
        "excludes": [
            "site preparation and civil works",
            "marine intake/outfall and environmental approvals",
            "electricity, consumables, staffing and routine maintenance",
            "membrane replacement, financing, discounting and downtime",
        ],
        "interpretation": (
            "Uses a synthetic scenario output and unverified draft CAPEX assumptions. "
            "It does not establish positive ROI, payback, actual water yield, or local feasibility."
        ),
    }


def write_outputs(output_dir: Path, runs: int, seed: int) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows, summary = run_simulation(runs, seed)
    with (output_dir / "nan_ao_annual_runs.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    (output_dir / "nan_ao_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    financial_screen = calculate_capital_cost_screen(
        summary["scenario_water_produced_m3_per_year"]["p50_median"]
    )
    (output_dir / "nan_ao_financial_screen.json").write_text(
        json.dumps(financial_screen, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8"
    )
    sensitivity_rows = run_sensitivity_analysis()
    with (output_dir / "nan_ao_sensitivity.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(sensitivity_rows[0].keys()))
        writer.writeheader()
        writer.writerows(sensitivity_rows)
    with (output_dir / "nan_ao_percentiles.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["metric", "p05", "p50_median", "p95", "mean", "unit"])
        writer.writeheader()
        y = summary["scenario_water_produced_m3_per_year"]
        writer.writerow({
            "metric": "scenario_water_produced_m3_per_year",
            "p05": y["p05"], "p50_median": y["p50_median"], "p95": y["p95"],
            "mean": y["mean"], "unit": "m3/year (scenario only)",
        })
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/nan_ao"))
    args = parser.parse_args()
    summary = write_outputs(args.output_dir, args.runs, args.seed)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

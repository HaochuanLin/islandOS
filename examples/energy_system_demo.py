"""Run a transparent synthetic multi-resource IslandOS energy-screening example.

Usage:
    python examples/energy_system_demo.py
"""
from __future__ import annotations

import json

from islandos_core.application import run_energy_policy_comparison
from islandos_core.energy_system import (
    BatterySpec,
    DieselSpec,
    EnergySystemConfig,
    EnergySystemInputs,
)


def build_demo_case() -> tuple[EnergySystemInputs, EnergySystemConfig]:
    """Create a deterministic 24-step example; values are not site measurements."""
    inputs = EnergySystemInputs(
        pv_generation_kw=[
            0, 0, 0, 0, 0, 5, 18, 35, 52, 65, 72, 76,
            74, 68, 55, 38, 20, 5, 0, 0, 0, 0, 0, 0,
        ],
        wind_generation_kw=[
            18, 20, 22, 19, 17, 16, 15, 14, 16, 18, 20, 22,
            24, 26, 25, 23, 22, 24, 27, 28, 25, 22, 20, 19,
        ],
        load_kw=[
            42, 40, 39, 38, 38, 40, 45, 50, 54, 58, 60, 62,
            61, 60, 58, 57, 60, 66, 70, 68, 60, 52, 47, 44,
        ],
        grid_price_per_kwh=[
            0.25, 0.25, 0.25, 0.25, 0.25, 0.25,
            0.45, 0.45, 0.65, 0.65, 0.65, 0.65,
            0.65, 0.65, 0.45, 0.45, 0.65, 0.85,
            0.85, 0.85, 0.65, 0.45, 0.35, 0.25,
        ],
        grid_available=[
            True, True, True, True, True, True,
            True, True, True, True, True, True,
            True, True, True, True, False, False,
            True, True, True, True, True, True,
        ],
        diesel_available=[True] * 24,
    )
    config = EnergySystemConfig(
        pv_rated_kw=80,
        wind_rated_kw=40,
        grid_import_limit_kw=75,
        dt_hours=1.0,
        battery=BatterySpec(
            capacity_kwh=160,
            max_charge_kw=45,
            max_discharge_kw=45,
            initial_soc=0.55,
            min_soc=0.2,
            max_soc=0.9,
            charge_efficiency=0.94,
            discharge_efficiency=0.94,
        ),
        diesel=DieselSpec(
            rated_power_kw=50,
            variable_cost_per_kwh=1.45,
        ),
    )
    return inputs, config


def main() -> None:
    inputs, config = build_demo_case()
    comparison = run_energy_policy_comparison(inputs, config)
    report = {
        "data_provenance": "synthetic_demo_data_not_measured_site_data",
        "time_steps": 24,
        "policy_summaries": {
            policy: result["summary"]
            for policy, result in (
                ("battery_first", comparison["battery_first"]),
                ("grid_first", comparison["grid_first"]),
            )
        },
        "difference_battery_first_minus_grid_first": comparison[
            "difference_battery_first_minus_grid_first"
        ],
        "interpretation": comparison["interpretation"],
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

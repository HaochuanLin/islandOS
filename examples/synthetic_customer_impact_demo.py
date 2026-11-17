"""Reproducible synthetic customer-impact example using existing dispatch policies.

Run:
    python examples/synthetic_customer_impact_demo.py

The example compares grid-first and battery-first using the same 24 hourly
synthetic inputs and asset configuration. It is not an optimizer or a customer
site study. Commercial costs are intentionally not invented, so net customer
value is withheld until same-period customer/supplier costs are supplied.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from islandos_core.energy_system import (
    BatterySpec,
    DieselSpec,
    EnergySystemConfig,
    EnergySystemInputs,
)
from islandos_core.impact_assessment import assess_energy_policy_impact


def build_synthetic_case() -> tuple[EnergySystemInputs, EnergySystemConfig]:
    """Return a fixed, transparent 24-hour example; units are kW and currency/kWh."""
    pv = [
        0, 0, 0, 0, 2, 10, 18, 25, 30, 30, 25, 20,
        15, 10, 4, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    ]
    wind = [
        10, 12, 11, 9, 8, 7, 8, 9, 10, 12, 14, 16,
        18, 20, 18, 16, 14, 12, 10, 9, 8, 9, 10, 11,
    ]
    base_load = [
        30, 29, 28, 28, 29, 30, 32, 34, 35, 34, 33, 32,
        32, 33, 35, 38, 40, 42, 41, 39, 36, 34, 32, 31,
    ]
    flexible_load = [
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 2, 4, 4, 4, 3, 2, 0, 0, 0,
    ]
    critical_load = [25.0] * 24
    grid_price = [
        0.12, 0.12, 0.12, 0.12, 0.12, 0.12, 0.14, 0.14,
        0.14, 0.14, 0.14, 0.14, 0.14, 0.14, 0.16, 0.22,
        0.30, 0.35, 0.35, 0.32, 0.28, 0.20, 0.16, 0.14,
    ]
    grid_available = [True] * 24
    grid_available[18] = False
    grid_available[19] = False

    inputs = EnergySystemInputs(
        pv_generation_kw=pv,
        wind_generation_kw=wind,
        load_kw=base_load,
        grid_price_per_kwh=grid_price,
        grid_available=grid_available,
        diesel_available=[True] * 24,
        flexible_load_kw=flexible_load,
        critical_load_kw=critical_load,
    )
    config = EnergySystemConfig(
        pv_rated_kw=40.0,
        wind_rated_kw=25.0,
        grid_import_limit_kw=50.0,
        dt_hours=1.0,
        battery=BatterySpec(
            capacity_kwh=60.0,
            max_charge_kw=18.0,
            max_discharge_kw=18.0,
            initial_soc=0.45,
            min_soc=0.15,
            max_soc=0.95,
            charge_efficiency=0.95,
            discharge_efficiency=0.95,
            throughput_cost_per_kwh=0.04,
        ),
        diesel=DieselSpec(
            rated_power_kw=30.0,
            variable_cost_per_kwh=0.0,
            min_stable_power_kw=5.0,
            start_cost_per_start=2.0,
            stop_cost_per_stop=1.0,
            fuel_consumption_l_per_kwh=0.28,
            initial_fuel_liters=70.0,
            fuel_tank_capacity_liters=80.0,
            fuel_price_per_liter=1.30,
        ),
        grid_demand_charge_per_kw=7.0,
    )
    return inputs, config


def main() -> None:
    inputs, config = build_synthetic_case()
    report = assess_energy_policy_impact(
        inputs,
        config,
        currency="USD",
        evaluation_period="24-hour synthetic scenario",
        data_provenance="synthetic_demo_data — not measured site data",
        commercial_costs=None,
    )
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()

"""Run a transparent synthetic example of tariff-aware load shifting.

The numbers are illustrative only; they are not a customer tariff or measured
site profile.
"""
from __future__ import annotations

import json

from optimization.price_aware_load_optimizer import optimize_flexible_load


def build_demo_result() -> dict:
    prices = [0.31, 0.27, 0.13, 0.09, 0.11, 0.24]
    available_power = [3.0, 3.0, 2.0, 3.0, 3.0, 3.0]
    schedule = optimize_flexible_load(
        price_per_kwh=prices,
        energy_requirement_kwh=10.0,
        max_power_kw=3.0,
        available_power_kw=available_power,
    )
    baseline_power = [2.0, 2.0, 2.0, 2.0, 1.0, 1.0]
    baseline_cost = sum(
        price * power for price, power in zip(prices, baseline_power)
    )
    return {
        "data_provenance": "Synthetic illustrative demo inputs; not measured site data",
        "units": {
            "price_per_kwh": "currency/kWh (illustrative)",
            "power_kw": "kW",
            "energy_kwh": "kWh per one-hour interval",
        },
        "price_per_kwh": prices,
        "baseline_power_kw": baseline_power,
        "baseline_cost": baseline_cost,
        "optimized_schedule": schedule.to_dict(),
        "baseline_vs_optimized_cost_difference": baseline_cost - schedule.total_cost,
        "interpretation": (
            "Cost difference is a mathematical comparison under the synthetic "
            "tariff and equal-energy example; it is not a verified customer saving."
        ),
    }


if __name__ == "__main__":
    print(json.dumps(build_demo_result(), indent=2))

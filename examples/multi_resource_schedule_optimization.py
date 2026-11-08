"""Reproducible 24-hour synthetic example for multi-resource schedule optimization."""
from __future__ import annotations

import json
import math

from islandos_core.energy_system import (
    BatterySpec, EnergySystemConfig, EnergySystemInputs, dispatch_energy_system,
)
from optimization.energy_system_optimizer import (
    OptimizationWeights, optimize_energy_system_schedule,
)


def build_demo_case() -> tuple[EnergySystemInputs, EnergySystemConfig]:
    """Build a transparent illustrative profile; no site measurements are used."""
    pv = [
        round(20.0 * max(0.0, math.sin(math.pi * (hour - 6) / 12.0)), 4)
        for hour in range(24)
    ]
    wind = [
        round(5.0 + 2.0 * math.sin(2.0 * math.pi * hour / 24.0), 4)
        for hour in range(24)
    ]
    load = [
        round(22.0 + 3.0 * math.sin(2.0 * math.pi * (hour - 7) / 24.0), 4)
        for hour in range(24)
    ]
    price = [
        0.12 if hour < 7 or hour >= 23
        else 0.38 if 17 <= hour < 21
        else 0.20
        for hour in range(24)
    ]
    inputs = EnergySystemInputs(
        pv_generation_kw=pv,
        wind_generation_kw=wind,
        load_kw=load,
        grid_price_per_kwh=price,
        grid_available=[True] * 24,
    )
    config = EnergySystemConfig(
        pv_rated_kw=20.0,
        wind_rated_kw=8.0,
        grid_import_limit_kw=40.0,
        battery=BatterySpec(
            capacity_kwh=100.0,
            max_charge_kw=20.0,
            max_discharge_kw=20.0,
            initial_soc=0.55,
            min_soc=0.15,
            max_soc=0.95,
            charge_efficiency=0.95,
            discharge_efficiency=0.95,
            throughput_cost_per_kwh=0.015,
        ),
    )
    return inputs, config


def run_demo(*, seed: int = 20261108) -> dict:
    inputs, config = build_demo_case()
    baselines = {
        policy: dispatch_energy_system(inputs, config, policy=policy)["summary"]
        for policy in ("battery_first", "grid_first")
    }
    optimized = optimize_energy_system_schedule(
        inputs,
        config,
        weights=OptimizationWeights(cost=0.65, reliability=0.25, curtailment=0.10),
        population_size=24,
        generations=16,
        mutation_rate=0.08,
        seed=seed,
    )
    recommended_objectives = optimized["recommendation"]["objectives"]
    comparison_deltas = {
        policy: {
            key: round(recommended_objectives[key] - float(summary[key]), 8)
            for key in (
                "estimated_energy_cost", "unmet_load_kwh",
                "renewable_curtailed_kwh", "battery_throughput_kwh",
            )
        }
        for policy, summary in baselines.items()
    }
    return {
        "data_status": "synthetic illustrative 24-hour profile; not measured site data",
        "seed": seed,
        "baselines": baselines,
        "recommended_minus_baseline_deltas": comparison_deltas,
        "delta_interpretation": "Negative values are lower than the named baseline for that metric; these are synthetic model comparisons, not measured savings.",
        "optimizer": {
            "algorithm": optimized["algorithm"],
            "candidate_count": optimized["candidate_count"],
            "pareto_count": optimized["pareto_count"],
            "recommendation": {
                "policy_schedule": optimized["recommendation"]["policy_schedule"],
                "objectives": optimized["recommendation"]["objectives"],
                "weights": optimized["recommendation"]["weights"],
            },
            "pareto_schedules": optimized["pareto_schedules"],
        },
        "scope": {
            "offline_decision_support_only": True,
            "not_global_kw_setpoint_optimization": True,
            "not_a_controller": True,
            "no_field_savings_claim": True,
        },
    }


def main() -> None:
    print(json.dumps(run_demo(), indent=2))


if __name__ == "__main__":
    main()

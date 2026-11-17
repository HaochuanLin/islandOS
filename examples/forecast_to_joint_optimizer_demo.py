"""Reproducible synthetic demo: forecast -> joint resource optimization -> audit.

Run from the repository root:
    python examples/forecast_to_joint_optimizer_demo.py

All inputs are synthetic. This demonstrates software behavior, not site performance,
validated savings, or a globally optimal schedule.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from islandos_core.energy_system import BatterySpec, DieselSpec, EnergySystemConfig
from islandos_core.forecast_signal_catalog import forecast_site_signals
from islandos_core.prediction_dispatch_adapter import optimize_prediction_resource_schedule
from islandos_core.water_resource_adapter import WaterServiceSpec


def build_synthetic_history():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    timestamps = tuple(start + timedelta(hours=i) for i in range(96))
    history = {
        "pv_power_kw": [
            max(0.0, 8.0 * __import__("math").sin((i % 24 - 6) * __import__("math").pi / 12))
            for i in range(96)
        ],
        "wind_power_kw": [3.0 + 1.2 * ((i % 8) / 7) for i in range(96)],
        "load_kw": [7.0 + (2.0 if i % 24 in range(17, 22) else 0.0) for i in range(96)],
        "tariff_per_kwh": [0.07 if i % 24 < 6 else (0.22 if i % 24 in range(17, 22) else 0.13) for i in range(96)],
        "water_demand_m3_per_hour": [0.5 + 0.05 * (i % 4) for i in range(96)],
    }
    units = {
        "pv_power_kw": "kW",
        "wind_power_kw": "kW",
        "load_kw": "kW",
        "tariff_per_kwh": "USD/kWh",
        "water_demand_m3_per_hour": "m3/h",
    }
    return timestamps, history, units


def main() -> None:
    timestamps, history, units = build_synthetic_history()
    forecasts = forecast_site_signals(
        timestamps,
        history,
        units,
        horizon=8,
        backtest_horizon=8,
        season_length=24,
    )

    config = EnergySystemConfig(
        pv_rated_kw=10.0,
        wind_rated_kw=6.0,
        grid_import_limit_kw=20.0,
        battery=BatterySpec(
            capacity_kwh=24.0,
            max_charge_kw=6.0,
            max_discharge_kw=6.0,
            initial_soc=0.65,
        ),
        diesel=DieselSpec(
            rated_power_kw=12.0,
            variable_cost_per_kwh=0.35,
            ramp_up_kw_per_hour=12.0,
        ),
    )
    water_service = WaterServiceSpec(
        specific_energy_kwh_per_m3=2.0,
        ro_capacity_m3_per_hour=3.0,
        tank_capacity_m3=12.0,
        initial_inventory_m3=6.0,
        reserve_m3=2.0,
    )

    result = optimize_prediction_resource_schedule(
        forecasts.results,
        config,
        history_start_utc=forecasts.history_start_utc,
        history_end_utc=forecasts.history_end_utc,
        grid_available=[True] * 8,
        diesel_available=[True] * 8,
        price_unit="USD/kWh",
        population_size=12,
        generations=4,
        seed=20261117,
        max_unmet_load_kwh=0.0,
        max_critical_unmet_load_kwh=0.0,
        terminal_battery_soc_min=0.20,
        water_service=water_service,
        water_schedule_mode="price_aware",
        water_lookahead_hours=6,
    )

    recommendation = result["recommendation"]
    baseline = result["baseline_comparison"]["policies"]
    output = {
        "data_provenance": "synthetic_demo_data",
        "method": result["algorithm"],
        "method_scope": result["decision_scope"],
        "forecast_models": result["generic_prediction_handoff"]["forecast_model_versions"],
        "optimization": {
            "seed": result["seed"],
            "population_size": result["population_size"],
            "generations": result["generations"],
            "candidate_count": result["candidate_count"],
            "feasible_count": result["feasible_count"],
            "pareto_count": result["pareto_count"],
            "scenario_names": result["scenario_names"],
        },
        "recommended_schedule": {
            "battery_setpoints_kw": recommendation["battery_setpoints_kw"],
            "diesel_commitment_schedule": recommendation["diesel_commitment_schedule"],
            "diesel_power_setpoint_kw": recommendation["diesel_power_setpoint_kw"],
            "objectives_worst_case": recommendation["objectives"],
            "scenario_results": recommendation["scenario_results"],
        },
        "baseline_worst_case_objectives": {
            name: row["worst_case_objectives"] for name, row in baseline.items()
        },
        "robust_customer_economics": result["robust_customer_economics"],
        "water_service": result.get("water_service"),
        "constraint_diagnostics": result["constraint_diagnostics"],
        "device_write_authorized": result["generic_prediction_handoff"]["device_write_authorized"],
        "global_optimum_claimed": result["model_scope"]["stochastic_heuristic_not_global_optimum"] is False,
    }
    print(json.dumps(output, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()

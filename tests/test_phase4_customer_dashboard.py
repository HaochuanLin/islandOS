from datetime import datetime, timedelta, timezone
import math

from islandos_core.energy_system import BatterySpec, EnergySystemConfig
from islandos_core.forecast_engine import forecast_signals
from islandos_core.forecast_optimizer_adapter import (
    build_coordination_inputs,
    build_service_equivalent_economics,
    evaluate_forecast_stress_scenarios,
)
from optimization.energy_system_optimizer import OptimizationWeights, optimize_energy_system


def test_customer_dashboard_pipeline_preserves_forecast_provenance_and_audit():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    stamps = [start + timedelta(hours=index) for index in range(168)]
    history = {"pv_power": [], "wind_power": [], "essential_load": [], "electricity_price": []}
    for index, stamp in enumerate(stamps):
        hour = stamp.hour
        history["pv_power"].append(max(0.0, 30.0 * math.sin(math.pi * (hour - 6) / 12.0)))
        history["wind_power"].append(6.0 + 2.0 * math.sin(index * 0.2) ** 2)
        history["essential_load"].append(20.0 + 4.0 * (hour in range(17, 22)))
        history["electricity_price"].append(0.10 if hour < 6 else 0.28 if hour >= 17 else 0.18)

    units = {
        "pv_power": "kW",
        "wind_power": "kW",
        "essential_load": "kW",
        "electricity_price": "USD/kWh",
    }
    bundle = forecast_signals(
        stamps, history, units, horizon=24, non_negative_signals=tuple(history)
    )
    coordinated = build_coordination_inputs(
        bundle, grid_available=[True] * 24, price_unit="USD/kWh"
    )
    config = EnergySystemConfig(
        pv_rated_kw=40.0,
        wind_rated_kw=15.0,
        grid_import_limit_kw=80.0,
        battery=BatterySpec(
            capacity_kwh=40.0, max_charge_kw=10.0,
            max_discharge_kw=10.0, initial_soc=0.6,
        ),
    )
    result = optimize_energy_system(
        coordinated.inputs,
        config,
        weights=OptimizationWeights(cost=0.7, reliability=0.3, curtailment=0.0),
    )
    economics = build_service_equivalent_economics(result)
    stress = evaluate_forecast_stress_scenarios(coordinated, config)

    assert len(coordinated.timestamps_utc) == 24
    assert len(bundle.input_history_sha256) == 64
    assert set(bundle.forecasts) == set(units)
    assert result["candidate_count"] == 2
    assert result["recommendation"]["policy"] in {"battery_first", "grid_first"}
    assert isinstance(economics["service_equivalent"], bool)
    assert economics["cost_comparison_valid"] == economics["service_equivalent"]
    if not economics["service_equivalent"]:
        assert economics["estimated_cost_reduction"] is None
    assert stress["scenario_count"] == 4
    assert stress["method_scope"]["scenario_probabilities_assigned"] is False
    for policy_result in stress["policy_results"].values():
        assert policy_result["all_scenarios_passed_physical_audit"] is True

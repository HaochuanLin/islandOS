from datetime import datetime, timedelta, timezone

import pytest

from islandos_core.energy_system import (
    BatterySpec, EnergySystemConfig, EnergySystemInputs,
)
from islandos_core.multisignal_forecasting import (
    SignalForecastPoint, SignalForecastResult,
)
from optimization.energy_system_optimizer import (
    OptimizationError, OptimizationWeights, forecast_results_to_energy_inputs,
    optimize_energy_system,
)


def forecast(signal_id, values, *, unit="kW", start=None, cadence=3600):
    start = start or datetime(2026, 1, 1, tzinfo=timezone.utc)
    return SignalForecastResult(
        signal_id=signal_id, unit=unit, cadence_seconds=cadence,
        model_id="test-model", model_version="1",
        input_history_sha256="a" * 64,
        points=tuple(
            SignalForecastPoint(start + timedelta(seconds=cadence * i), value)
            for i, value in enumerate(values)
        ),
    )


def test_forecast_adapter_aligns_pv_wind_load_into_shared_physical_inputs():
    pv = forecast("pv_generation", [10, 0])
    wind = forecast("wind_generation", [2, 3])
    load = forecast("electrical_load", [8, 9])
    inputs, timestamps = forecast_results_to_energy_inputs(
        pv, wind, load, [0.2, 0.3], [True, True]
    )
    assert inputs.pv_generation_kw == [10.0, 0.0]
    assert inputs.wind_generation_kw == [2.0, 3.0]
    assert inputs.load_kw == [8.0, 9.0]
    assert timestamps == tuple(point.timestamp for point in pv.points)


def test_forecast_adapter_rejects_misaligned_timestamps():
    pv = forecast("pv_generation", [10, 0])
    wind = forecast(
        "wind_generation", [2, 3],
        start=datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
    )
    load = forecast("electrical_load", [8, 9])
    with pytest.raises(OptimizationError, match="timestamps must match"):
        forecast_results_to_energy_inputs(pv, wind, load, [0.2, 0.3], [True, True])


def test_forecast_adapter_rejects_wrong_signal_unit_and_horizon():
    pv = forecast("pv_generation", [10, 0], unit="MW")
    wind = forecast("wind_generation", [2, 3])
    load = forecast("electrical_load", [8, 9])
    with pytest.raises(OptimizationError, match="unit"):
        forecast_results_to_energy_inputs(pv, wind, load, [0.2, 0.3], [True, True])
    with pytest.raises(OptimizationError, match="exactly 2"):
        forecast_results_to_energy_inputs(
            forecast("pv_generation", [10, 0]), wind, load, [0.2], [True, True]
        )


def test_optimizer_evaluates_both_policies_on_identical_physical_inputs():
    inputs = EnergySystemInputs(
        pv_generation_kw=[8, 0, 0],
        wind_generation_kw=[0, 0, 0],
        load_kw=[2, 8, 8],
        grid_price_per_kwh=[0.2, 0.4, 0.1],
        grid_available=[True, True, True],
    )
    config = EnergySystemConfig(
        pv_rated_kw=10, wind_rated_kw=0, grid_import_limit_kw=10,
        battery=BatterySpec(
            capacity_kwh=10, max_charge_kw=5, max_discharge_kw=5,
            initial_soc=0.8, min_soc=0.1, max_soc=0.95,
        ),
    )
    result = optimize_energy_system(inputs, config)
    assert result["candidate_count"] == 2
    assert result["feasible_count"] == 2
    assert result["pareto_count"] >= 1
    assert result["recommendation"]["policy"] in {"battery_first", "grid_first"}
    assert all(row["audit"]["passed"] for row in result["candidates"])
    assert result["model_scope"]["uses_shared_physical_dispatch_engine"] is True


def test_optimizer_rejects_invalid_objective_weights():
    with pytest.raises(OptimizationError, match="non-negative"):
        OptimizationWeights(cost=-1, reliability=1, curtailment=1)
    with pytest.raises(OptimizationError, match="at least one"):
        OptimizationWeights(cost=0, reliability=0, curtailment=0)


def test_optimizer_preserves_unmet_load_as_an_objective_not_a_hidden_claim():
    inputs = EnergySystemInputs(
        pv_generation_kw=[0], wind_generation_kw=[0], load_kw=[5],
        grid_price_per_kwh=[0.2], grid_available=[False],
    )
    config = EnergySystemConfig(
        pv_rated_kw=0, wind_rated_kw=0, grid_import_limit_kw=0,
    )
    result = optimize_energy_system(inputs, config)
    assert result["recommendation"]["objectives"]["unmet_load_kwh"] == 5
    assert all(row["summary"]["unmet_load_kwh"] == 5 for row in result["candidates"])


def test_timestep_policy_schedule_is_applied_by_shared_physical_engine():
    from islandos_core.energy_system import dispatch_energy_system, EnergyModelError

    inputs = EnergySystemInputs(
        pv_generation_kw=[0, 0], wind_generation_kw=[0, 0],
        load_kw=[5, 5], grid_price_per_kwh=[1.0, 0.1],
        grid_available=[True, True],
    )
    config = EnergySystemConfig(
        pv_rated_kw=0, wind_rated_kw=0, grid_import_limit_kw=10,
        battery=BatterySpec(
            capacity_kwh=10, max_charge_kw=5, max_discharge_kw=5,
            initial_soc=0.9, min_soc=0.1, max_soc=0.95,
        ),
    )
    result = dispatch_energy_system(
        inputs, config, policy_schedule=["battery_first", "grid_first"]
    )
    assert [row["dispatch_priority"] for row in result["rows"]] == [
        "battery_first", "grid_first"
    ]
    assert result["policy"] == "time_varying_priority_schedule"
    with pytest.raises(EnergyModelError, match="exactly 2"):
        dispatch_energy_system(inputs, config, policy_schedule=["battery_first"])
    with pytest.raises(EnergyModelError, match="entries"):
        dispatch_energy_system(inputs, config, policy_schedule=["unknown", "grid_first"])


def test_evolutionary_schedule_optimizer_is_repeatable_and_audited():
    from optimization.energy_system_optimizer import optimize_energy_system_schedule

    inputs = EnergySystemInputs(
        pv_generation_kw=[0, 0, 0, 0],
        wind_generation_kw=[0, 0, 0, 0],
        load_kw=[5, 5, 5, 5],
        grid_price_per_kwh=[1.0, 0.8, 0.2, 0.1],
        grid_available=[True, True, True, True],
    )
    config = EnergySystemConfig(
        pv_rated_kw=0, wind_rated_kw=0, grid_import_limit_kw=10,
        battery=BatterySpec(
            capacity_kwh=20, max_charge_kw=5, max_discharge_kw=5,
            initial_soc=0.9, min_soc=0.1, max_soc=0.95,
        ),
    )
    kwargs = {"population_size": 8, "generations": 4, "seed": 77}
    first = optimize_energy_system_schedule(inputs, config, **kwargs)
    second = optimize_energy_system_schedule(inputs, config, **kwargs)
    assert first == second
    assert first["candidate_count"] >= 2
    assert first["pareto_count"] >= 1
    assert len(first["recommendation"]["policy_schedule"]) == 4
    assert all(
        set(row["policy_schedule"]) <= {"battery_first", "grid_first"}
        for row in first["pareto_schedules"]
    )
    assert first["recommendation"]["dispatch"]["summary"]["unmet_load_kwh"] == 0
    assert first["model_scope"]["not_arbitrary_kw_setpoint_optimization"] is True


def test_evolutionary_schedule_optimizer_handles_one_step_horizon():
    from optimization.energy_system_optimizer import optimize_energy_system_schedule

    inputs = EnergySystemInputs(
        pv_generation_kw=[0], wind_generation_kw=[0], load_kw=[1],
        grid_price_per_kwh=[0.2], grid_available=[True],
    )
    config = EnergySystemConfig(
        pv_rated_kw=0, wind_rated_kw=0, grid_import_limit_kw=2,
    )
    result = optimize_energy_system_schedule(
        inputs, config, population_size=8, generations=2
    )
    assert result["candidate_count"] == 2
    assert len(result["recommendation"]["policy_schedule"]) == 1


def test_evolutionary_schedule_optimizer_enforces_horizon_limit():
    from optimization.energy_system_optimizer import optimize_energy_system_schedule

    inputs = EnergySystemInputs(
        pv_generation_kw=[0, 0], wind_generation_kw=[0, 0],
        load_kw=[1, 1], grid_price_per_kwh=[0.2, 0.2],
        grid_available=[True, True],
    )
    config = EnergySystemConfig(
        pv_rated_kw=0, wind_rated_kw=0, grid_import_limit_kw=2,
    )
    with pytest.raises(OptimizationError, match="maximum"):
        optimize_energy_system_schedule(
            inputs, config, max_horizon_steps=1
        )


def test_synthetic_24_hour_optimizer_example_is_reproducible():
    from examples.multi_resource_schedule_optimization import run_demo

    first = run_demo(seed=2026)
    second = run_demo(seed=2026)
    assert first == second
    assert first["data_status"].startswith("synthetic")
    assert len(first["optimizer"]["recommendation"]["policy_schedule"]) == 24
    assert first["optimizer"]["candidate_count"] >= 2
    assert first["scope"]["not_a_controller"] is True

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
    assert len(first["battery_power_optimizer"]["recommendation"]["setpoints_kw"]) == 24
    assert first["battery_power_optimizer"]["decision_variable"] == "signed battery power set-point in kW per timestep"
    assert len(first["joint_battery_diesel_optimizer"]["recommendation"]["battery_setpoints_kw"]) == 24
    assert len(first["joint_battery_diesel_optimizer"]["recommendation"]["diesel_commitment_schedule"]) == 24
    assert first["optimizer"]["candidate_count"] >= 2
    assert set(first["recommended_minus_baseline_deltas"]) == {"battery_first", "grid_first"}
    assert all(
        set(delta) == {
            "estimated_energy_cost", "unmet_load_kwh",
            "renewable_curtailed_kwh", "battery_throughput_kwh",
        }
        for delta in first["recommended_minus_baseline_deltas"].values()
    )
    assert "not measured savings" in first["delta_interpretation"]
    assert first["scope"]["not_a_controller"] is True



def test_battery_power_setpoints_are_signed_bounded_and_audited():
    from islandos_core.energy_system import dispatch_energy_system, EnergyModelError

    inputs = EnergySystemInputs(
        pv_generation_kw=[10, 0],
        wind_generation_kw=[0, 0],
        load_kw=[2, 8],
        grid_price_per_kwh=[0.2, 0.2],
        grid_available=[True, True],
        battery_power_setpoint_kw=[-3, 2],
    )
    config = EnergySystemConfig(
        pv_rated_kw=10,
        wind_rated_kw=0,
        grid_import_limit_kw=10,
        battery=BatterySpec(
            capacity_kwh=10,
            max_charge_kw=5,
            max_discharge_kw=5,
            initial_soc=0.5,
            min_soc=0.1,
            max_soc=0.95,
            charge_efficiency=1.0,
            discharge_efficiency=1.0,
        ),
    )
    result = dispatch_energy_system(inputs, config)
    assert [row["battery_power_setpoint_kw"] for row in result["rows"]] == [-3, 2]
    assert result["rows"][0]["battery_charge_kw"] == pytest.approx(3)
    assert result["rows"][1]["battery_discharge_kw"] == pytest.approx(2)
    assert result["rows"][1]["grid_import_kw"] == pytest.approx(6)
    assert all(abs(row["energy_balance_residual_kw"]) < 1e-8 for row in result["rows"])

    with pytest.raises(EnergyModelError, match="exactly 2"):
        dispatch_energy_system(
            EnergySystemInputs(
                pv_generation_kw=[10, 0], wind_generation_kw=[0, 0],
                load_kw=[2, 8], grid_price_per_kwh=[0.2, 0.2],
                grid_available=[True, True], battery_power_setpoint_kw=[-2],
            ),
            config,
        )
    with pytest.raises(EnergyModelError, match="power limits"):
        dispatch_energy_system(
            EnergySystemInputs(
                pv_generation_kw=[10, 0], wind_generation_kw=[0, 0],
                load_kw=[2, 8], grid_price_per_kwh=[0.2, 0.2],
                grid_available=[True, True], battery_power_setpoint_kw=[-6, 0],
            ),
            config,
        )


def test_continuous_battery_schedule_optimizer_is_reproducible_and_physical():
    from optimization.energy_system_optimizer import optimize_battery_power_schedule

    inputs = EnergySystemInputs(
        pv_generation_kw=[8, 0, 0, 4],
        wind_generation_kw=[0, 0, 0, 0],
        load_kw=[3, 8, 8, 3],
        grid_price_per_kwh=[0.1, 0.5, 0.4, 0.1],
        grid_available=[True, True, True, True],
    )
    config = EnergySystemConfig(
        pv_rated_kw=10,
        wind_rated_kw=0,
        grid_import_limit_kw=10,
        battery=BatterySpec(
            capacity_kwh=12,
            max_charge_kw=4,
            max_discharge_kw=4,
            initial_soc=0.65,
            min_soc=0.1,
            max_soc=0.95,
            charge_efficiency=0.95,
            discharge_efficiency=0.95,
            throughput_cost_per_kwh=0.01,
        ),
    )
    kwargs = {"population_size": 8, "generations": 3, "seed": 91}
    first = optimize_battery_power_schedule(inputs, config, **kwargs)
    second = optimize_battery_power_schedule(inputs, config, **kwargs)
    assert first == second
    assert first["candidate_count"] >= 8
    assert first["pareto_count"] >= 1
    setpoints = first["recommendation"]["setpoints_kw"]
    assert len(setpoints) == 4
    assert all(-4 <= value <= 4 for value in setpoints)
    dispatch = first["recommendation"]["dispatch"]
    assert all(abs(row["energy_balance_residual_kw"]) < 1e-7 for row in dispatch["rows"])
    assert all(0.1 - 1e-9 <= row["battery_soc"] <= 0.95 + 1e-9 for row in dispatch["rows"])
    assert first["model_scope"]["grid_charging_not_modeled"] is True
    assert first["model_scope"]["not_a_controller"] is True


def test_continuous_battery_optimizer_requires_battery_and_bounds_horizon():
    from optimization.energy_system_optimizer import optimize_battery_power_schedule

    inputs = EnergySystemInputs(
        pv_generation_kw=[0, 0], wind_generation_kw=[0, 0],
        load_kw=[1, 1], grid_price_per_kwh=[0.2, 0.2],
        grid_available=[True, True],
    )
    no_battery = EnergySystemConfig(
        pv_rated_kw=0, wind_rated_kw=0, grid_import_limit_kw=2,
    )
    with pytest.raises(OptimizationError, match="configured battery"):
        optimize_battery_power_schedule(inputs, no_battery)

    with_battery = EnergySystemConfig(
        pv_rated_kw=0, wind_rated_kw=0, grid_import_limit_kw=2,
        battery=BatterySpec(
            capacity_kwh=5, max_charge_kw=2, max_discharge_kw=2,
        ),
    )
    with pytest.raises(OptimizationError, match="maximum"):
        optimize_battery_power_schedule(inputs, with_battery, max_horizon_steps=1)



def test_diesel_commitment_schedule_is_explicit_and_enforced():
    from islandos_core.energy_system import DieselSpec, EnergyModelError, dispatch_energy_system

    config = EnergySystemConfig(
        pv_rated_kw=0,
        wind_rated_kw=0,
        grid_import_limit_kw=0,
        diesel=DieselSpec(
            rated_power_kw=10,
            variable_cost_per_kwh=0.2,
            min_stable_power_kw=2,
            ramp_up_kw_per_hour=10,
        ),
    )
    off = dispatch_energy_system(
        EnergySystemInputs(
            pv_generation_kw=[0], wind_generation_kw=[0], load_kw=[5],
            grid_price_per_kwh=[0.2], grid_available=[True],
            diesel_available=[True], diesel_commitment_schedule=[False],
        ),
        config,
    )
    on = dispatch_energy_system(
        EnergySystemInputs(
            pv_generation_kw=[0], wind_generation_kw=[0], load_kw=[5],
            grid_price_per_kwh=[0.2], grid_available=[True],
            diesel_available=[True], diesel_commitment_schedule=[True],
        ),
        config,
    )
    assert off["rows"][0]["diesel_committed"] is False
    assert off["summary"]["unmet_load_kwh"] == 5
    assert on["rows"][0]["diesel_committed"] is True
    assert on["summary"]["unmet_load_kwh"] == 0
    assert on["rows"][0]["diesel_generation_kw"] == 5

    with pytest.raises(EnergyModelError, match="boolean values"):
        dispatch_energy_system(
            EnergySystemInputs(
                pv_generation_kw=[0], wind_generation_kw=[0], load_kw=[5],
                grid_price_per_kwh=[0.2], grid_available=[True],
                diesel_available=[True], diesel_commitment_schedule=[1],
            ),
            config,
        )


def test_joint_battery_diesel_optimizer_is_reproducible_and_audited():
    from islandos_core.energy_system import DieselSpec
    from optimization.energy_system_optimizer import optimize_battery_and_diesel_schedule

    inputs = EnergySystemInputs(
        pv_generation_kw=[0, 0, 2, 0],
        wind_generation_kw=[0, 0, 0, 0],
        load_kw=[7, 7, 7, 7],
        grid_price_per_kwh=[0.2, 0.4, 0.3, 0.1],
        grid_available=[True, True, True, True],
        diesel_available=[True, True, True, True],
    )
    config = EnergySystemConfig(
        pv_rated_kw=2,
        wind_rated_kw=0,
        grid_import_limit_kw=0,
        battery=BatterySpec(
            capacity_kwh=8,
            max_charge_kw=2,
            max_discharge_kw=2,
            initial_soc=0.6,
            min_soc=0.1,
            max_soc=0.95,
        ),
        diesel=DieselSpec(
            rated_power_kw=10,
            variable_cost_per_kwh=0.25,
            min_stable_power_kw=2,
            ramp_up_kw_per_hour=10,
            start_cost_per_start=0.2,
            stop_cost_per_stop=0.1,
        ),
    )
    kwargs = {"population_size": 8, "generations": 3, "seed": 2026}
    first = optimize_battery_and_diesel_schedule(inputs, config, **kwargs)
    second = optimize_battery_and_diesel_schedule(inputs, config, **kwargs)
    assert first == second
    assert first["candidate_count"] >= 8
    assert first["pareto_count"] >= 1
    rec = first["recommendation"]
    assert len(rec["battery_setpoints_kw"]) == 4
    assert len(rec["diesel_commitment_schedule"]) == 4
    assert all(isinstance(value, bool) for value in rec["diesel_commitment_schedule"])
    assert all(-2 <= value <= 2 for value in rec["battery_setpoints_kw"])
    assert all(abs(row["energy_balance_residual_kw"]) < 1e-7 for row in rec["dispatch"]["rows"])
    assert first["model_scope"]["diesel_minimum_load_ramp_up_fuel_and_availability_enforced"] is True


def test_joint_optimizer_requires_both_resources_and_diesel_availability():
    from islandos_core.energy_system import DieselSpec
    from optimization.energy_system_optimizer import optimize_battery_and_diesel_schedule

    inputs = EnergySystemInputs(
        pv_generation_kw=[0], wind_generation_kw=[0], load_kw=[1],
        grid_price_per_kwh=[0.2], grid_available=[True],
    )
    battery_only = EnergySystemConfig(
        pv_rated_kw=0, wind_rated_kw=0, grid_import_limit_kw=1,
        battery=BatterySpec(capacity_kwh=5, max_charge_kw=2, max_discharge_kw=2),
    )
    with pytest.raises(OptimizationError, match="battery and diesel"):
        optimize_battery_and_diesel_schedule(inputs, battery_only)

    config = EnergySystemConfig(
        pv_rated_kw=0, wind_rated_kw=0, grid_import_limit_kw=1,
        battery=BatterySpec(capacity_kwh=5, max_charge_kw=2, max_discharge_kw=2),
        diesel=DieselSpec(rated_power_kw=2, variable_cost_per_kwh=0.2),
    )
    with pytest.raises(OptimizationError, match="diesel_available"):
        optimize_battery_and_diesel_schedule(inputs, config)


def test_battery_wear_is_an_explicit_validated_recommendation_weight():
    from optimization.energy_system_optimizer import OptimizationWeights

    weights = OptimizationWeights(
        cost=0.5, reliability=0.2, curtailment=0.1, battery_wear=0.2
    )
    assert weights.battery_wear == pytest.approx(0.2)
    from optimization.energy_system_optimizer import optimize_battery_power_schedule
    inputs = EnergySystemInputs(
        pv_generation_kw=[5, 0], wind_generation_kw=[0, 0],
        load_kw=[2, 4], grid_price_per_kwh=[0.2, 0.4],
        grid_available=[True, True],
    )
    config = EnergySystemConfig(
        pv_rated_kw=5, wind_rated_kw=0, grid_import_limit_kw=5,
        battery=BatterySpec(capacity_kwh=6, max_charge_kw=2, max_discharge_kw=2),
    )
    result = optimize_battery_power_schedule(
        inputs, config, weights=weights, population_size=4, generations=1, seed=5
    )
    assert result["recommendation"]["weights"]["battery_wear"] == pytest.approx(0.2)
    with pytest.raises(OptimizationError, match="finite and non-negative"):
        OptimizationWeights(battery_wear=-0.1)
    with pytest.raises(OptimizationError, match="at least one objective"):
        OptimizationWeights(cost=0, reliability=0, curtailment=0, battery_wear=0)


def test_joint_optimizer_searches_and_returns_diesel_power_setpoints():
    from optimization.energy_system_optimizer import optimize_battery_and_diesel_schedule
    from islandos_core.energy_system import DieselSpec

    inputs = EnergySystemInputs(
        pv_generation_kw=[0, 0, 0], wind_generation_kw=[0, 0, 0],
        load_kw=[4, 6, 3], grid_price_per_kwh=[0.5, 0.5, 0.5],
        grid_available=[False, False, False], diesel_available=[True, True, True],
    )
    config = EnergySystemConfig(
        pv_rated_kw=0, wind_rated_kw=0, grid_import_limit_kw=0,
        battery=BatterySpec(capacity_kwh=4, max_charge_kw=2, max_discharge_kw=2),
        diesel=DieselSpec(rated_power_kw=8, variable_cost_per_kwh=0.2, min_stable_power_kw=2),
    )
    result = optimize_battery_and_diesel_schedule(
        inputs, config, population_size=4, generations=1, seed=17,
    )
    recommendation = result["recommendation"]
    assert len(recommendation["diesel_power_setpoint_kw"]) == 3
    assert all(0 <= value <= 8 for value in recommendation["diesel_power_setpoint_kw"])
    assert result["model_scope"]["diesel_power_setpoint_optimized"] is True
    assert result["model_scope"]["not_a_controller"] is True


def test_multi_scenario_robustness_replays_same_schedule_and_reports_worst_case():
    from optimization.energy_system_optimizer import evaluate_schedule_robustness

    config = EnergySystemConfig(
        pv_rated_kw=2,
        wind_rated_kw=0,
        grid_import_limit_kw=2,
        battery=BatterySpec(
            capacity_kwh=4, max_charge_kw=2, max_discharge_kw=2,
            initial_soc=0.5, min_soc=0.1, max_soc=0.9,
        ),
    )
    common = {
        "pv_generation_kw": [0, 0],
        "wind_generation_kw": [0, 0],
        "load_kw": [2, 2],
        "grid_price_per_kwh": [0.2, 0.3],
    }
    scenarios = {
        "normal_grid": EnergySystemInputs(
            **common, grid_available=[True, True],
        ),
        "grid_outage": EnergySystemInputs(
            **common, grid_available=[False, False],
        ),
    }
    result = evaluate_schedule_robustness(
        scenarios, config, battery_power_setpoint_kw=[0, 0],
    )
    assert result["scenario_count"] == 2
    assert result["all_physical_audits_passed"] is True
    assert result["all_scenarios_fully_served"] is False
    assert result["robust_service_feasible"] is False
    assert result["scenario_results"]["normal_grid"]["objectives"]["unmet_load_kwh"] == 0
    assert result["scenario_results"]["grid_outage"]["objectives"]["unmet_load_kwh"] == 4
    assert result["worst_case_objectives"]["unmet_load_kwh"] == 4
    assert result["mean_case_objectives"]["unmet_load_kwh"] == 2
    assert result["model_scope"]["same_schedule_replayed_in_every_scenario"] is True
    assert result["model_scope"]["not_a_stochastic_or_global_robust_optimizer"] is True


def test_multi_scenario_robustness_rejects_empty_or_misaligned_scenarios():
    from optimization.energy_system_optimizer import evaluate_schedule_robustness

    config = EnergySystemConfig(
        pv_rated_kw=0, wind_rated_kw=0, grid_import_limit_kw=1,
    )
    one_step = EnergySystemInputs(
        pv_generation_kw=[0], wind_generation_kw=[0], load_kw=[1],
        grid_price_per_kwh=[0.2], grid_available=[True],
    )
    two_steps = EnergySystemInputs(
        pv_generation_kw=[0, 0], wind_generation_kw=[0, 0], load_kw=[1, 1],
        grid_price_per_kwh=[0.2, 0.2], grid_available=[True, True],
    )
    with pytest.raises(OptimizationError, match="non-empty"):
        evaluate_schedule_robustness({}, config)
    with pytest.raises(OptimizationError, match="same horizon"):
        evaluate_schedule_robustness(
            {"short": one_step, "long": two_steps}, config
        )
    with pytest.raises(OptimizationError, match="exactly 1"):
        evaluate_schedule_robustness(
            {"normal": one_step}, config, battery_power_setpoint_kw=[0, 0]
        )


def test_robustness_report_identifies_likely_grid_and_battery_limits():
    from optimization.energy_system_optimizer import evaluate_schedule_robustness

    config = EnergySystemConfig(
        pv_rated_kw=0, wind_rated_kw=0, grid_import_limit_kw=0,
        battery=BatterySpec(
            capacity_kwh=4, max_charge_kw=2, max_discharge_kw=2,
            initial_soc=0.5, min_soc=0.1, max_soc=0.9,
        ),
    )
    scenario = EnergySystemInputs(
        pv_generation_kw=[0], wind_generation_kw=[0], load_kw=[2],
        grid_price_per_kwh=[0.2], grid_available=[False],
    )
    result = evaluate_schedule_robustness(
        {"islanded_outage": scenario},
        config,
        battery_power_setpoint_kw=[0],
    )
    factors = result["scenario_results"]["islanded_outage"]["shortfall_diagnostics"][0]["likely_limiting_factors"]
    assert "grid_unavailable" in factors
    assert "battery_setpoint_restricts_discharge" in factors


def test_flexible_load_optimizer_conserves_energy_and_shifts_toward_cheaper_periods():
    from optimization.energy_system_optimizer import optimize_flexible_load_schedule
    from islandos_core.energy_system import dispatch_energy_system

    inputs = EnergySystemInputs(
        pv_generation_kw=[0, 0, 0],
        wind_generation_kw=[0, 0, 0],
        load_kw=[1, 1, 1],
        grid_price_per_kwh=[1.0, 0.1, 1.0],
        grid_available=[True, True, True],
    )
    config = EnergySystemConfig(
        pv_rated_kw=0, wind_rated_kw=0, grid_import_limit_kw=5,
    )
    kwargs = {
        "energy_required_kwh": 2.0,
        "available_steps": [True, True, True],
        "max_power_kw": 2.0,
        "weights": OptimizationWeights(cost=1, reliability=0, curtailment=0, battery_wear=0),
        "population_size": 16,
        "generations": 20,
        "mutation_rate": 0.8,
        "seed": 20261109,
    }
    first = optimize_flexible_load_schedule(inputs, config, **kwargs)
    second = optimize_flexible_load_schedule(inputs, config, **kwargs)
    assert first == second
    schedule = first["recommendation"]["flexible_load_power_kw"]
    assert sum(schedule) == pytest.approx(2.0, abs=1e-6)
    assert all(0 <= value <= 2.0 for value in schedule)
    assert len(schedule) == 3
    baseline = EnergySystemInputs(
        pv_generation_kw=[0, 0, 0], wind_generation_kw=[0, 0, 0],
        load_kw=[3, 1, 1], grid_price_per_kwh=[1.0, 0.1, 1.0],
        grid_available=[True, True, True],
    )
    baseline_cost = dispatch_energy_system(baseline, config)["summary"]["estimated_energy_cost"]
    assert first["recommendation"]["objectives"]["estimated_energy_cost"] <= baseline_cost
    assert first["model_scope"]["required_flexible_energy_conserved"] is True
    assert first["model_scope"]["not_jointly_optimized_with_battery_or_diesel_decisions"] is True
    assert first["model_scope"]["critical_vs_flexible_load_priority_modeled"] is True
    assert first["model_scope"]["flexible_load_shedding_modeled"] is True


def test_flexible_load_optimizer_enforces_availability_and_capacity():
    from optimization.energy_system_optimizer import optimize_flexible_load_schedule

    inputs = EnergySystemInputs(
        pv_generation_kw=[0, 0], wind_generation_kw=[0, 0],
        load_kw=[1, 1], grid_price_per_kwh=[0.2, 0.3],
        grid_available=[True, True],
    )
    config = EnergySystemConfig(
        pv_rated_kw=0, wind_rated_kw=0, grid_import_limit_kw=3,
    )
    result = optimize_flexible_load_schedule(
        inputs, config,
        energy_required_kwh=1,
        available_steps=[False, True],
        max_power_kw=2,
        population_size=4,
        generations=1,
    )
    assert result["recommendation"]["flexible_load_power_kw"] == pytest.approx([0, 1])
    with pytest.raises(OptimizationError, match="exceeds available-window"):
        optimize_flexible_load_schedule(
            inputs, config,
            energy_required_kwh=3,
            available_steps=[False, True],
            max_power_kw=2,
        )
    with pytest.raises(OptimizationError, match="boolean values"):
        optimize_flexible_load_schedule(
            inputs, config,
            energy_required_kwh=1,
            available_steps=[0, True],
            max_power_kw=2,
        )


def test_joint_battery_diesel_optimizer_can_jointly_schedule_flexible_load():
    from islandos_core.energy_system import DieselSpec
    from optimization.energy_system_optimizer import optimize_battery_and_diesel_schedule

    inputs = EnergySystemInputs(
        pv_generation_kw=[0, 2, 0],
        wind_generation_kw=[0, 0, 0],
        load_kw=[4, 4, 4],
        grid_price_per_kwh=[0.4, 0.1, 0.3],
        grid_available=[True, True, True],
        diesel_available=[True, True, True],
    )
    config = EnergySystemConfig(
        pv_rated_kw=2,
        wind_rated_kw=0,
        grid_import_limit_kw=2,
        battery=BatterySpec(
            capacity_kwh=6, max_charge_kw=2, max_discharge_kw=2,
            initial_soc=0.6, min_soc=0.1, max_soc=0.95,
        ),
        diesel=DieselSpec(
            rated_power_kw=5, variable_cost_per_kwh=0.3,
            min_stable_power_kw=1, ramp_up_kw_per_hour=5,
        ),
    )
    kwargs = {
        "population_size": 8,
        "generations": 2,
        "seed": 303,
        "flexible_load_energy_kwh": 1.5,
        "flexible_load_available_steps": [True, False, True],
        "flexible_load_max_power_kw": 1.0,
    }
    first = optimize_battery_and_diesel_schedule(inputs, config, **kwargs)
    second = optimize_battery_and_diesel_schedule(inputs, config, **kwargs)
    assert first == second
    recommendation = first["recommendation"]
    flexible = recommendation["flexible_load_power_kw"]
    assert len(flexible) == 3
    assert flexible[1] == 0
    assert all(0 <= value <= 1 for value in flexible)
    assert sum(flexible) == pytest.approx(1.5, abs=1e-6)
    assert len(recommendation["battery_setpoints_kw"]) == 3
    assert len(recommendation["diesel_commitment_schedule"]) == 3
    assert len(recommendation["diesel_power_setpoint_kw"]) == 3
    assert recommendation["dispatch"]["summary"]["load_energy_kwh"] == pytest.approx(13.5)
    assert first["decision_variables"]["flexible_load"] != "disabled"
    assert first["model_scope"]["flexible_load_schedule_jointly_optimized"] is True


def test_joint_optimizer_validates_flexible_load_parameters_as_a_complete_contract():
    from islandos_core.energy_system import DieselSpec
    from optimization.energy_system_optimizer import optimize_battery_and_diesel_schedule

    inputs = EnergySystemInputs(
        pv_generation_kw=[0], wind_generation_kw=[0], load_kw=[1],
        grid_price_per_kwh=[0.2], grid_available=[True], diesel_available=[True],
    )
    config = EnergySystemConfig(
        pv_rated_kw=0, wind_rated_kw=0, grid_import_limit_kw=1,
        battery=BatterySpec(capacity_kwh=4, max_charge_kw=1, max_discharge_kw=1),
        diesel=DieselSpec(rated_power_kw=2, variable_cost_per_kwh=0.2),
    )
    with pytest.raises(OptimizationError, match="supplied together"):
        optimize_battery_and_diesel_schedule(
            inputs, config, flexible_load_energy_kwh=1,
        )
    with pytest.raises(OptimizationError, match="exceeds available-window"):
        optimize_battery_and_diesel_schedule(
            inputs, config,
            flexible_load_energy_kwh=2,
            flexible_load_available_steps=[True],
            flexible_load_max_power_kw=1,
        )


def test_joint_optimizer_uses_worst_case_objectives_across_scenarios():
    from islandos_core.energy_system import DieselSpec
    from optimization.energy_system_optimizer import optimize_battery_and_diesel_schedule

    nominal = EnergySystemInputs(
        pv_generation_kw=[0, 2], wind_generation_kw=[0, 0],
        load_kw=[4, 4], grid_price_per_kwh=[0.2, 0.1],
        grid_available=[True, True], diesel_available=[True, True],
    )
    outage = EnergySystemInputs(
        pv_generation_kw=[0, 0], wind_generation_kw=[0, 0],
        load_kw=[5, 5], grid_price_per_kwh=[0.2, 0.1],
        grid_available=[False, False], diesel_available=[True, True],
    )
    config = EnergySystemConfig(
        pv_rated_kw=2, wind_rated_kw=0, grid_import_limit_kw=2,
        battery=BatterySpec(
            capacity_kwh=8, max_charge_kw=2, max_discharge_kw=2,
            initial_soc=0.7, min_soc=0.1, max_soc=0.95,
        ),
        diesel=DieselSpec(
            rated_power_kw=6, variable_cost_per_kwh=0.3,
            min_stable_power_kw=1, ramp_up_kw_per_hour=6,
        ),
    )
    kwargs = {
        "population_size": 8,
        "generations": 2,
        "seed": 20261110,
        "additional_scenarios": {"grid_outage": outage},
        "flexible_load_energy_kwh": 1,
        "flexible_load_available_steps": [True, True],
        "flexible_load_max_power_kw": 1,
    }
    first = optimize_battery_and_diesel_schedule(nominal, config, **kwargs)
    second = optimize_battery_and_diesel_schedule(nominal, config, **kwargs)
    assert first == second
    assert first["scenario_count"] == 2
    assert first["scenario_names"] == ["nominal", "grid_outage"]
    assert first["model_scope"]["robust_optimization_enabled"] is True
    assert first["model_scope"]["same_decisions_replayed_across_all_scenarios"] is True
    scenario_rows = first["recommendation"]["scenario_results"]
    assert set(scenario_rows) == {"nominal", "grid_outage"}
    for metric in (
        "estimated_energy_cost", "unmet_load_kwh",
        "renewable_curtailed_kwh", "battery_throughput_kwh",
    ):
        assert first["recommendation"]["objectives"][metric] == pytest.approx(
            max(row["objectives"][metric] for row in scenario_rows.values())
        )
    assert sum(first["recommendation"]["flexible_load_power_kw"]) == pytest.approx(1)


def test_joint_optimizer_rejects_misaligned_robust_scenario_horizon():
    from islandos_core.energy_system import DieselSpec
    from optimization.energy_system_optimizer import optimize_battery_and_diesel_schedule

    nominal = EnergySystemInputs(
        pv_generation_kw=[0], wind_generation_kw=[0], load_kw=[1],
        grid_price_per_kwh=[0.2], grid_available=[True], diesel_available=[True],
    )
    other = EnergySystemInputs(
        pv_generation_kw=[0, 0], wind_generation_kw=[0, 0],
        load_kw=[1, 1], grid_price_per_kwh=[0.2, 0.2],
        grid_available=[True, True], diesel_available=[True, True],
    )
    config = EnergySystemConfig(
        pv_rated_kw=0, wind_rated_kw=0, grid_import_limit_kw=1,
        battery=BatterySpec(capacity_kwh=4, max_charge_kw=1, max_discharge_kw=1),
        diesel=DieselSpec(rated_power_kw=2, variable_cost_per_kwh=0.2),
    )
    with pytest.raises(OptimizationError, match="same horizon"):
        optimize_battery_and_diesel_schedule(
            nominal, config, additional_scenarios={"longer": other},
        )


def test_joint_optimizer_includes_grid_export_caps_in_shared_decision_vector():
    from islandos_core.energy_system import DieselSpec
    from optimization.energy_system_optimizer import optimize_battery_and_diesel_schedule

    inputs = EnergySystemInputs(
        pv_generation_kw=[5, 5, 5], wind_generation_kw=[0, 0, 0],
        load_kw=[1, 1, 1], grid_price_per_kwh=[0.2, 0.2, 0.2],
        grid_available=[True, True, True], diesel_available=[True, True, True],
        grid_export_price_per_kwh=[0.05, 0.05, 0.05],
        grid_export_available=[True, True, True],
    )
    config = EnergySystemConfig(
        pv_rated_kw=5, wind_rated_kw=0, grid_import_limit_kw=2,
        grid_export_limit_kw=4, grid_demand_charge_per_kw=8,
        battery=BatterySpec(
            capacity_kwh=4, max_charge_kw=1, max_discharge_kw=1,
            initial_soc=0.5, min_soc=0.1, max_soc=0.9,
        ),
        diesel=DieselSpec(rated_power_kw=2, variable_cost_per_kwh=0.3),
    )
    kwargs = {"population_size": 8, "generations": 2, "seed": 441}
    first = optimize_battery_and_diesel_schedule(inputs, config, **kwargs)
    second = optimize_battery_and_diesel_schedule(inputs, config, **kwargs)
    assert first == second
    export = first["recommendation"]["grid_export_power_setpoint_kw"]
    assert len(export) == 3
    assert all(0 <= value <= 4 for value in export)
    assert first["decision_variables"]["grid_export"].startswith("continuous")
    assert first["model_scope"]["grid_export_setpoint_optimized"] is True
    assert first["recommendation"]["dispatch"]["summary"]["grid_demand_charge"] >= 0
    comparison = first["baseline_comparison"]
    assert comparison["same_inputs_config_and_scenarios"] is True
    assert comparison["flexible_load_profile_held_equal"] is True
    assert set(comparison["policies"]) == {"battery_first", "grid_first"}
    for policy in comparison["policies"].values():
        assert set(policy["scenario_results"]) == {"nominal"}
        assert policy["all_scenarios_passed_audit"] is True
        assert set(policy["recommended_minus_baseline"]) == {
            "estimated_energy_cost", "unmet_load_kwh",
            "renewable_curtailed_kwh", "battery_throughput_kwh",
        }
    assert first["recommendation"]["objectives"]["estimated_energy_cost"] == pytest.approx(
        max(
            row["objectives"]["estimated_energy_cost"]
            for row in first["recommendation"]["scenario_results"].values()
        )
    )


def test_robustness_reports_critical_service_and_flexible_shedding_separately():
    from optimization.energy_system_optimizer import evaluate_schedule_robustness

    config = EnergySystemConfig(
        pv_rated_kw=0, wind_rated_kw=0, grid_import_limit_kw=3,
    )
    scenario = EnergySystemInputs(
        pv_generation_kw=[0], wind_generation_kw=[0], load_kw=[3],
        grid_price_per_kwh=[0.2], grid_available=[True],
        critical_load_kw=[2],
    )
    result = evaluate_schedule_robustness(
        {"constrained_grid": scenario},
        config,
        flexible_load_kw=[2],
    )
    row = result["scenario_results"]["constrained_grid"]
    diagnostic = row["shortfall_diagnostics"][0]
    assert row["critical_service_shortfall"] is False
    assert row["flexible_load_shed"] is True
    assert diagnostic["service_classification"] == "flexible_load_shed_only"
    assert "flexible_load_shed_before_critical_load" in diagnostic["likely_limiting_factors"]
    assert result["all_scenarios_fully_served"] is False
    assert result["all_critical_loads_fully_served"] is True
    assert result["robust_critical_service_feasible"] is True
    assert result["worst_case_critical_unmet_load_kwh"] == pytest.approx(0)
    assert result["worst_case_flexible_load_shed_kwh"] == pytest.approx(1)


def test_robustness_replays_explicit_grid_export_caps_and_flexible_load_profile():
    from optimization.energy_system_optimizer import evaluate_schedule_robustness

    config = EnergySystemConfig(
        pv_rated_kw=8, wind_rated_kw=0, grid_import_limit_kw=0,
        grid_export_limit_kw=6,
    )
    scenario = EnergySystemInputs(
        pv_generation_kw=[8], wind_generation_kw=[0], load_kw=[1],
        grid_price_per_kwh=[0.2], grid_available=[True],
        grid_export_price_per_kwh=[0.05], grid_export_available=[True],
    )
    result = evaluate_schedule_robustness(
        {"sunny": scenario},
        config,
        flexible_load_kw=[2],
        grid_export_power_setpoint_kw=[3],
    )
    dispatch = result["scenario_results"]["sunny"]["dispatch"]
    assert dispatch["rows"][0]["load_kw"] == pytest.approx(3)
    assert dispatch["rows"][0]["grid_export_kw"] == pytest.approx(3)
    assert dispatch["summary"]["flexible_load_energy_kwh"] == pytest.approx(2)


def test_joint_optimizer_enforces_hard_critical_load_service_constraint():
    from islandos_core.energy_system import DieselSpec
    from optimization.energy_system_optimizer import optimize_battery_and_diesel_schedule

    inputs = EnergySystemInputs(
        pv_generation_kw=[0, 0], wind_generation_kw=[0, 0],
        load_kw=[5, 5], grid_price_per_kwh=[0.2, 0.2],
        grid_available=[True, True], diesel_available=[True, True],
    )
    config = EnergySystemConfig(
        pv_rated_kw=0, wind_rated_kw=0, grid_import_limit_kw=6,
        battery=BatterySpec(
            capacity_kwh=4, max_charge_kw=1, max_discharge_kw=1,
            initial_soc=0.5, min_soc=0.1, max_soc=0.9,
        ),
        diesel=DieselSpec(rated_power_kw=2, variable_cost_per_kwh=0.3),
    )
    result = optimize_battery_and_diesel_schedule(
        inputs, config, population_size=8, generations=2, seed=881,
        max_unmet_load_kwh=0,
        max_critical_unmet_load_kwh=0,
    )
    constraints = result["constraint_diagnostics"]
    assert constraints["configured_max_unmet_load_kwh"] == 0
    assert constraints["configured_max_critical_unmet_load_kwh"] == 0
    assert constraints["fully_feasible_candidate_count"] > 0
    assert result["model_scope"]["optional_hard_total_unmet_constraint"] is True
    assert result["model_scope"]["optional_hard_critical_unmet_constraint"] is True


def test_joint_optimizer_explains_when_hard_critical_service_is_infeasible():
    from islandos_core.energy_system import DieselSpec
    from optimization.energy_system_optimizer import optimize_battery_and_diesel_schedule

    inputs = EnergySystemInputs(
        pv_generation_kw=[0], wind_generation_kw=[0], load_kw=[5],
        grid_price_per_kwh=[0.2], grid_available=[False],
        diesel_available=[True],
    )
    config = EnergySystemConfig(
        pv_rated_kw=0, wind_rated_kw=0, grid_import_limit_kw=0,
        battery=BatterySpec(
            capacity_kwh=4, max_charge_kw=1, max_discharge_kw=1,
            initial_soc=0.1, min_soc=0.1, max_soc=0.9,
        ),
        diesel=DieselSpec(
            rated_power_kw=2, variable_cost_per_kwh=0.3,
            min_stable_power_kw=0.5,
        ),
    )
    with pytest.raises(OptimizationError, match="critical_unmet_load_exceeds_limit") as caught:
        optimize_battery_and_diesel_schedule(
            inputs, config, population_size=8, generations=2, seed=882,
            max_critical_unmet_load_kwh=0,
        )
    assert "best_candidate_scenarios" in caught.value.diagnostics
    scenario = caught.value.diagnostics["best_candidate_scenarios"]["nominal"]
    assert scenario["constraint_violations"] == ["critical_unmet_load_exceeds_limit"]
    assert scenario["shortfall_diagnostics"][0]["service_classification"] == "critical_load_shortfall"


def test_joint_optimizer_rejects_negative_hard_service_thresholds():
    from islandos_core.energy_system import DieselSpec
    from optimization.energy_system_optimizer import optimize_battery_and_diesel_schedule

    inputs = EnergySystemInputs(
        pv_generation_kw=[0], wind_generation_kw=[0], load_kw=[1],
        grid_price_per_kwh=[0.2], grid_available=[True], diesel_available=[True],
    )
    config = EnergySystemConfig(
        pv_rated_kw=0, wind_rated_kw=0, grid_import_limit_kw=2,
        battery=BatterySpec(capacity_kwh=2, max_charge_kw=1, max_discharge_kw=1),
        diesel=DieselSpec(rated_power_kw=2, variable_cost_per_kwh=0.2),
    )
    with pytest.raises(OptimizationError, match="max_unmet_load_kwh must be finite and non-negative"):
        optimize_battery_and_diesel_schedule(
            inputs, config, max_unmet_load_kwh=-1,
        )


def test_joint_optimizer_enforces_terminal_battery_soc_reserve():
    from islandos_core.energy_system import DieselSpec
    from optimization.energy_system_optimizer import optimize_battery_and_diesel_schedule

    inputs = EnergySystemInputs(
        pv_generation_kw=[0, 0], wind_generation_kw=[0, 0],
        load_kw=[1, 1], grid_price_per_kwh=[0.2, 0.2],
        grid_available=[True, True], diesel_available=[True, True],
    )
    config = EnergySystemConfig(
        pv_rated_kw=0, wind_rated_kw=0, grid_import_limit_kw=4,
        battery=BatterySpec(
            capacity_kwh=4, max_charge_kw=1, max_discharge_kw=1,
            initial_soc=0.5, min_soc=0.1, max_soc=0.9,
        ),
        diesel=DieselSpec(rated_power_kw=2, variable_cost_per_kwh=0.3),
    )
    result = optimize_battery_and_diesel_schedule(
        inputs, config, population_size=8, generations=2, seed=991,
        terminal_battery_soc_min=0.4,
    )
    assert result["constraint_diagnostics"]["configured_terminal_battery_soc_min"] == 0.4
    assert result["constraint_diagnostics"]["fully_feasible_candidate_count"] > 0
    assert result["model_scope"]["optional_terminal_battery_soc_reserve_constraint"] is True


def test_joint_optimizer_explains_unreachable_terminal_battery_soc_reserve():
    from islandos_core.energy_system import DieselSpec
    from optimization.energy_system_optimizer import optimize_battery_and_diesel_schedule

    inputs = EnergySystemInputs(
        pv_generation_kw=[0], wind_generation_kw=[0], load_kw=[1],
        grid_price_per_kwh=[0.2], grid_available=[True], diesel_available=[True],
    )
    config = EnergySystemConfig(
        pv_rated_kw=0, wind_rated_kw=0, grid_import_limit_kw=3,
        battery=BatterySpec(
            capacity_kwh=4, max_charge_kw=1, max_discharge_kw=1,
            initial_soc=0.5, min_soc=0.1, max_soc=0.9,
        ),
        diesel=DieselSpec(rated_power_kw=2, variable_cost_per_kwh=0.3),
    )
    with pytest.raises(OptimizationError, match="terminal_battery_soc_below_minimum") as caught:
        optimize_battery_and_diesel_schedule(
            inputs, config, population_size=8, generations=2, seed=992,
            terminal_battery_soc_min=0.6,
        )
    assert caught.value.diagnostics["configured_terminal_battery_soc_min"] == 0.6



def test_joint_optimizer_rejects_unimplemented_diesel_ramp_down_search():
    from islandos_core.energy_system import DieselSpec
    from optimization.energy_system_optimizer import (
        OptimizationError,
        optimize_battery_and_diesel_schedule,
    )

    inputs = EnergySystemInputs(
        pv_generation_kw=[0], wind_generation_kw=[0], load_kw=[1],
        grid_price_per_kwh=[0.2], grid_available=[True],
        diesel_available=[True],
    )
    config = EnergySystemConfig(
        pv_rated_kw=0, wind_rated_kw=0, grid_import_limit_kw=5,
        battery=BatterySpec(
            capacity_kwh=4, max_charge_kw=2, max_discharge_kw=2,
        ),
        diesel=DieselSpec(
            rated_power_kw=5, variable_cost_per_kwh=0.3,
            ramp_down_kw_per_hour=2,
        ),
    )
    with pytest.raises(OptimizationError, match="does not yet generate ramp-down/minimum-time"):
        optimize_battery_and_diesel_schedule(inputs, config)



def test_joint_optimizer_rejects_minimum_up_down_time_until_search_supports_it():
    from islandos_core.energy_system import DieselSpec
    from optimization.energy_system_optimizer import (
        OptimizationError,
        optimize_battery_and_diesel_schedule,
    )

    inputs = EnergySystemInputs(
        pv_generation_kw=[0], wind_generation_kw=[0], load_kw=[1],
        grid_price_per_kwh=[0.2], grid_available=[True],
        diesel_available=[True],
    )
    config = EnergySystemConfig(
        pv_rated_kw=0, wind_rated_kw=0, grid_import_limit_kw=5,
        battery=BatterySpec(
            capacity_kwh=4, max_charge_kw=2, max_discharge_kw=2,
        ),
        diesel=DieselSpec(
            rated_power_kw=5, variable_cost_per_kwh=0.3,
            min_up_time_hours=2,
        ),
    )
    with pytest.raises(OptimizationError, match="ramp-down/minimum-time feasible"):
        optimize_battery_and_diesel_schedule(inputs, config)

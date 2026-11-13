from datetime import datetime, timedelta, timezone

from islandos_core.energy_system import BatterySpec, DieselSpec, EnergySystemConfig
from islandos_core.forecast_signal_catalog import forecast_site_signals
from islandos_core.prediction_dispatch_adapter import optimize_prediction_resource_schedule
from islandos_core.water_resource_adapter import WaterServiceSpec


def test_canonical_catalog_forecasts_feed_joint_optimizer_end_to_end():
    start = datetime(2026, 11, 1, tzinfo=timezone.utc)
    timestamps = tuple(start + timedelta(hours=index) for index in range(96))
    history = {
        "pv_power_kw": [max(0.0, 5.0 + 3.0 * ((i % 24) / 24)) for i in range(96)],
        "wind_power_kw": [3.0 + (i % 5) * 0.2 for i in range(96)],
        "load_kw": [8.0 + (2.0 if i % 24 in range(17, 22) else 0.0) for i in range(96)],
        "tariff_per_kwh": [0.08 if i % 24 < 6 else 0.20 for i in range(96)],
    }
    units = {
        "pv_power_kw": "kW",
        "wind_power_kw": "kW",
        "load_kw": "kW",
        "tariff_per_kwh": "USD/kWh",
    }
    bundle = forecast_site_signals(
        timestamps, history, units, horizon=6, backtest_horizon=6, season_length=24
    )
    config = EnergySystemConfig(
        pv_rated_kw=10.0,
        wind_rated_kw=8.0,
        grid_import_limit_kw=20.0,
        battery=BatterySpec(
            capacity_kwh=20.0, max_charge_kw=5.0, max_discharge_kw=5.0,
            initial_soc=0.6,
        ),
        diesel=DieselSpec(
            rated_power_kw=10.0, variable_cost_per_kwh=0.3,
            ramp_up_kw_per_hour=10.0,
        ),
    )
    result = optimize_prediction_resource_schedule(
        bundle.results,
        config,
        history_start_utc=bundle.history_start_utc,
        history_end_utc=bundle.history_end_utc,
        grid_available=[True] * 6,
        diesel_available=[True] * 6,
        price_unit="USD/kWh",
        population_size=4,
        generations=1,
        seed=31,
    )
    assert len(bundle.input_history_sha256) == 64
    assert set(result["generic_prediction_handoff"]["forecast_model_versions"]) == set(history)
    assert result["generic_prediction_handoff"]["device_write_authorized"] is False
    assert len(result["recommendation"]["battery_setpoints_kw"]) == 6


def test_water_and_energy_policy_selection_compares_both_ro_modes_under_same_stress_cases():
    start = datetime(2026, 11, 1, tzinfo=timezone.utc)
    timestamps = tuple(start + timedelta(hours=index) for index in range(96))
    history = {
        "pv_power_kw": [5.0] * 96,
        "wind_power_kw": [3.0] * 96,
        "load_kw": [8.0] * 96,
        "tariff_per_kwh": [0.08 if index % 24 < 6 else 0.20 for index in range(96)],
        "water_demand_m3_per_hour": [1.5] * 96,
    }
    units = {
        "pv_power_kw": "kW",
        "wind_power_kw": "kW",
        "load_kw": "kW",
        "tariff_per_kwh": "USD/kWh",
        "water_demand_m3_per_hour": "m3/h",
    }
    bundle = forecast_site_signals(
        timestamps, history, units, horizon=6, backtest_horizon=6, season_length=24
    )
    config = EnergySystemConfig(
        pv_rated_kw=10.0,
        wind_rated_kw=8.0,
        grid_import_limit_kw=20.0,
        battery=BatterySpec(
            capacity_kwh=20.0, max_charge_kw=5.0, max_discharge_kw=5.0,
            initial_soc=0.6,
        ),
        diesel=DieselSpec(
            rated_power_kw=10.0, variable_cost_per_kwh=0.3,
            ramp_up_kw_per_hour=10.0,
        ),
    )
    water = WaterServiceSpec(
        specific_energy_kwh_per_m3=2.0,
        ro_capacity_m3_per_hour=10.0,
        tank_capacity_m3=20.0,
        initial_inventory_m3=6.0,
        reserve_m3=2.0,
    )
    result = optimize_prediction_resource_schedule(
        bundle.results,
        config,
        history_start_utc=bundle.history_start_utc,
        history_end_utc=bundle.history_end_utc,
        grid_available=[True] * 6,
        diesel_available=[True] * 6,
        price_unit="USD/kWh",
        population_size=4,
        generations=1,
        seed=41,
        water_service=water,
        water_schedule_mode="auto",
        water_lookahead_hours=6,
    )

    comparison = result["water_policy_comparison"]
    assert comparison["selected_mode"] in {"just_in_time", "price_aware"}
    assert comparison["candidates"]["just_in_time"]["feasible"] is True
    assert comparison["candidates"]["price_aware"]["feasible"] is True
    assert result["water_service"]["selected_schedule_mode"] == comparison["selected_mode"]
    assert comparison["device_write_authorized"] is False
    assert comparison["scenario_probabilities_assigned"] is False
    assert len(result["recommendation"]["battery_setpoints_kw"]) == 6

from datetime import datetime, timedelta, timezone

import pytest

from islandos_core.energy_system import BatterySpec, DieselSpec, EnergySystemConfig
from islandos_core.forecast_signal_catalog import forecast_site_signals
from islandos_core.prediction_dispatch_adapter import optimize_prediction_resource_schedule
from islandos_core.water_resource_adapter import WaterServiceSpec, build_ro_energy_load


def test_water_demand_and_flexible_load_join_forecasted_energy_optimizer():
    start = datetime(2026, 10, 1, tzinfo=timezone.utc)
    timestamps = tuple(start + timedelta(hours=i) for i in range(96))
    history = {
        "pv_power_kw": [max(0.0, 8.0 + 3.0 * ((i % 24) / 24)) for i in range(96)],
        "wind_power_kw": [4.0 + 0.2 * (i % 5) for i in range(96)],
        "load_kw": [7.0 + (1.0 if i % 24 in range(17, 22) else 0.0) for i in range(96)],
        "tariff_per_kwh": [0.08 if i % 24 < 6 else 0.20 for i in range(96)],
        "flexible_load_kw": [1.0 if i % 24 in range(0, 8) else 0.0 for i in range(96)],
        "critical_load_kw": [5.0] * 96,
        "water_demand_m3_per_hour": [0.5 + 0.05 * (i % 3) for i in range(96)],
    }
    units = {
        "pv_power_kw": "kW",
        "wind_power_kw": "kW",
        "load_kw": "kW",
        "tariff_per_kwh": "USD/kWh",
        "flexible_load_kw": "kW",
        "critical_load_kw": "kW",
        "water_demand_m3_per_hour": "m3/h",
    }
    forecasts = forecast_site_signals(
        timestamps, history, units, horizon=4, backtest_horizon=4, season_length=24,
    )
    config = EnergySystemConfig(
        pv_rated_kw=20.0,
        wind_rated_kw=10.0,
        grid_import_limit_kw=20.0,
        battery=BatterySpec(
            capacity_kwh=20.0, max_charge_kw=5.0, max_discharge_kw=5.0,
            initial_soc=0.6,
        ),
        diesel=DieselSpec(
            rated_power_kw=15.0, variable_cost_per_kwh=0.3,
            ramp_up_kw_per_hour=15.0,
        ),
    )
    result = optimize_prediction_resource_schedule(
        forecasts.results,
        config,
        history_start_utc=forecasts.history_start_utc,
        history_end_utc=forecasts.history_end_utc,
        grid_available=[True] * 4,
        diesel_available=[True] * 4,
        price_unit="USD/kWh",
        population_size=4,
        generations=1,
        seed=41,
        water_service=WaterServiceSpec(
            specific_energy_kwh_per_m3=4.0,
            ro_capacity_m3_per_hour=5.0,
            tank_capacity_m3=10.0,
            initial_inventory_m3=2.0,
            reserve_m3=0.5,
        ),
    )

    assert result["water_service"]["service_feasible"] is True
    assert len(result["water_service"]["ro_power_kw_added_to_essential_load"]) == 4
    assert result["water_service"]["total_ro_production_m3"] >= 0
    assert result["model_scope"]["flexible_load_schedule_jointly_optimized"] is True
    assert result["model_scope"]["flexible_load_energy_conserved"] is True
    assert result["generic_prediction_handoff"]["device_write_authorized"] is False
    assert set(result["generic_prediction_handoff"]["source_signal_ids"]) == set(history)


def test_water_service_adapter_rejects_ro_capacity_shortfall():
    spec = WaterServiceSpec(
        specific_energy_kwh_per_m3=4.0,
        ro_capacity_m3_per_hour=0.2,
        tank_capacity_m3=2.0,
        initial_inventory_m3=0.5,
        reserve_m3=0.5,
    )
    with pytest.raises(ValueError, match="water service infeasible"):
        build_ro_energy_load([1.0], spec=spec)


def test_water_service_spec_rejects_invalid_tank_reserve():
    with pytest.raises(ValueError, match="reserve_m3 cannot exceed"):
        WaterServiceSpec(
            specific_energy_kwh_per_m3=4.0,
            ro_capacity_m3_per_hour=1.0,
            tank_capacity_m3=1.0,
            initial_inventory_m3=1.0,
            reserve_m3=2.0,
        )

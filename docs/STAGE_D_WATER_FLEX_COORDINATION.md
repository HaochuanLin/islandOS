# Stage D — Water and flexible-load coordination slice

## What is now connected

The canonical site forecast catalog can now pass optional flexible-load and critical-load forecasts into the forecast-to-resource optimizer. The existing battery/diesel search derives the flexible-load energy budget and availability window from the supplied forecast profile, then jointly schedules that energy with battery and diesel decisions while conserving the requested flexible energy.

The water_resource_adapter.py connects hourly water-demand forecasts to the electrical system. The price-aware planner in water_dispatch.py is now callable from optimize_prediction_resource_schedule using water_schedule_mode="price_aware":
- It validates a declared RO specific energy, production capacity, tank capacity, initial inventory, and reserve.
- It replays water demand against tank inventory and produces only enough water to serve demand and restore the declared reserve.
- It fails closed when RO capacity or tank constraints cannot satisfy the forecast.
- It converts RO production into kW and adds that demand to the essential electrical load before joint battery/diesel optimization.
- When a critical-load forecast is supplied, the RO load is added to the critical subset as well.

The generic forecast hand-off preserves the water and flexible-load model identities and source-history digests. The device-write boundary remains disabled.

## How to use

~~~python
from islandos_core.forecast_signal_catalog import forecast_site_signals
from islandos_core.prediction_dispatch_adapter import optimize_prediction_resource_schedule
from islandos_core.water_resource_adapter import WaterServiceSpec

forecasts = forecast_site_signals(timestamps, history, units, horizon=24)
result = optimize_prediction_resource_schedule(
    forecasts.results,
    energy_system_config,
    history_start_utc=forecasts.history_start_utc,
    history_end_utc=forecasts.history_end_utc,
    grid_available=grid_available,
    diesel_available=diesel_available,
    price_unit="USD/kWh",
    water_service=WaterServiceSpec(
        specific_energy_kwh_per_m3=4.0,
        ro_capacity_m3_per_hour=20.0,
        tank_capacity_m3=100.0,
        initial_inventory_m3=40.0,
        reserve_m3=15.0,
    ),
)
~~~

Include water_demand_m3_per_hour in the forecast history and flexible_load_kw when shiftable demand is present. A water forecast requires an explicit WaterServiceSpec; a water-service configuration without a water forecast is rejected.

## Deliberate limitations

- The default RO policy remains reserve-constrained just-in-time. An opt-in tariff-look-ahead heuristic can pre-produce in locally cheaper periods and exposes an hourly tank trajectory, but it is not a globally optimized tank trajectory or joint RO/battery/diesel mathematical program.
- The water service replay uses the empirical upper planning bound of the water-demand forecast. That band is not a calibrated probability interval.
- RO operating modes, startup/shutdown, cleaning/CIP, brine handling, recovery ratio, salinity/temperature effects, pump curves, and water quality are not yet modeled.
- The flexible-load optimizer conserves forecast energy within its declared availability window and maximum power. It does not yet represent every process-specific precedence, batch, thermal, or production constraint.
- The tariff-look-ahead RO planner is a deterministic heuristic, not a global optimum. The joint battery/diesel optimizer remains a seeded heuristic and does not claim global optimality.
- The result is offline decision support only; it does not issue commands to RO equipment, batteries, generators, or grid assets.

## Validation

tests/test_stage_d_water_coordination.py covers the forecast-to-water-to-electrical-load path, flexible-load joint scheduling, RO capacity rejection, and tank-reserve validation. These synthetic tests validate software behavior only, not a real plant's water or electrical performance.
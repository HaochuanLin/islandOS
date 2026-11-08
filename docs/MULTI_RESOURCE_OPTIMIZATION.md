# Multi-resource dispatch optimization (first increment)

IslandOS now has a forecast-connected optimization entry point:

- `forecast_results_to_energy_inputs` aligns PV, wind, and electrical-load forecasts from the multi-signal forecasting engine and converts them to the shared physical simulator input contract.
- `optimize_energy_system` evaluates the existing `battery_first` and `grid_first` dispatch policies against exactly the same forecast horizon, tariffs, availability flags, and equipment configuration.
- Each candidate is independently audited for per-step energy-balance residuals and finite summary metrics. Failed candidates are excluded from the Pareto set.
- The Pareto objectives are estimated energy cost, unmet load, renewable curtailment, and battery throughput. An explicit weighted score selects one recommendation from the Pareto set; weights express user priorities, not probabilities or tariff coefficients.

## Example

```python
from optimization.energy_system_optimizer import (
    OptimizationWeights,
    forecast_results_to_energy_inputs,
    optimize_energy_system,
)

inputs, forecast_timestamps = forecast_results_to_energy_inputs(
    pv_forecast,
    wind_forecast,
    load_forecast,
    grid_price_per_kwh=tariff,
    grid_available=grid_uptime,
    diesel_available=diesel_uptime,  # required if diesel is configured
)
result = optimize_energy_system(
    inputs,
    energy_system_config,
    weights=OptimizationWeights(cost=0.7, reliability=0.2, curtailment=0.1),
)
print(result["recommendation"])
```

## Scope and limitations

This is the first integration step for Stage 4, not a finished general-purpose optimizer. It searches two existing transparent dispatch policies; it does **not** optimize arbitrary per-timestep battery set-points, diesel commitment schedules, or grid import/export schedules. It does not yet expose a full infeasibility explanation engine, multi-scenario stochastic optimization, or customer-specific economic objective configuration. The shared simulator enforces its configured physical limits, but its own documented modeling simplifications still apply.

A recommendation is a model result, not a command. The optimizer is offline decision support only: it does not connect to or control equipment, certify electrical safety, establish grid-export permission, or prove field savings. Use synthetic or authorized customer data, retain source provenance, and obtain qualified engineering review before any operational use.

The bundled tests validate software contracts and simulator accounting with synthetic inputs. They are not evidence of performance at a real site.

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


## Timestep-varying schedule search (experimental Stage 4 increment)

The shared physical simulator also accepts an explicit `policy_schedule`: one
`battery_first` or `grid_first` priority per time step. The experimental
`optimize_energy_system_schedule` function searches these binary schedules
with a seeded evolutionary Pareto heuristic. It evaluates each candidate by
calling the same physical simulator, keeps only candidates that pass the
energy-balance audit, and returns the Pareto archive plus a weighted-score
recommendation.

Example:

```python
from optimization.energy_system_optimizer import (
    OptimizationWeights,
    optimize_energy_system_schedule,
)

result = optimize_energy_system_schedule(
    inputs,
    energy_system_config,
    weights=OptimizationWeights(cost=0.7, reliability=0.2, curtailment=0.1),
    population_size=32,
    generations=20,
    seed=20261108,
)
print(result["recommendation"]["policy_schedule"])
```

This is a meaningful horizon-dependent schedule search, but the decision
variable is deliberately limited to choosing between the simulator's two
priority rules at each time step. It does **not** directly optimize battery
charge/discharge kW, diesel on/off and power set-points, grid import/export
set-points, or flexible-load service schedules. It is stochastic and does not
guarantee a global optimum. The default maximum horizon is 168 steps to keep
the search bounded; adjust only after performance testing. The evolutionary
result remains offline decision support, not a controller.


## Reproducible synthetic demonstration

Run the 24-hour end-to-end example from the repository root:

```bash
python examples/multi_resource_schedule_optimization.py
```

It compares both fixed-policy baselines with the evolutionary schedule search
using identical PV, wind, load, tariff, battery, diesel, and grid-availability inputs.
The synthetic case includes a two-step grid outage so the diesel commitment
choice is exercised rather than remaining an unused variable. It reports the
binary policy schedule, continuous battery power schedule, and joint battery-
and-diesel schedule separately.
The JSON includes recommended-minus-baseline deltas for estimated energy cost,
unmet load, renewable curtailment, and battery throughput. Negative deltas mean
the recommended schedule is lower on that metric in this synthetic run; they
are not measured savings or a guarantee. The output explicitly labels the
profile as synthetic. It is a software demonstration, not a customer-site
result.


## Continuous battery power schedule search (experimental)

The next optimizer increment adds signed, timestep-aligned battery power
set-points to the shared physical simulator:

- Negative kW requests charging, limited to available renewable surplus.
- Positive kW requests discharge to serve load.
- The simulator clips actual dispatch to SOC, efficiency, configured power,
  and effective-capacity limits. Grid and configured diesel supply any residual
  demand using their existing physical and availability constraints.
- \`optimize_battery_power_schedule\` searches bounded real-valued schedules
  using a seeded evolutionary Pareto heuristic and returns the objective
  archive plus a weighted-score recommendation.

Example:

\`\`\`python
from optimization.energy_system_optimizer import (
    OptimizationWeights,
    optimize_battery_power_schedule,
)

result = optimize_battery_power_schedule(
    inputs,
    energy_system_config,
    weights=OptimizationWeights(cost=0.7, reliability=0.2, curtailment=0.1),
    population_size=32,
    generations=20,
    seed=20261108,
)
print(result["recommendation"]["setpoints_kw"])
\`\`\`

This is the first continuous decision-variable increment, not a complete
mixed-integer multi-resource optimizer. It does not optimize grid charging,
diesel commitment or diesel power set-points, grid import/export set-points,
or flexible-load service. It is a stochastic heuristic, not a guaranteed
global optimum. All candidates are evaluated through the same physical
simulator and its configured constraints. Results remain offline decision
support, not a controller or a claim of measured savings.


## Joint battery and diesel commitment search (experimental)

The simulator now accepts an explicit \`diesel_commitment_schedule\`, a
horizon-aligned boolean series. A false value prevents the generator from
starting or remaining online for that timestep. A true value permits the
existing residual-load dispatch rule to use the generator, subject to its
availability, minimum stable load, ramp-up, fuel inventory, and startup/stop
cost assumptions.

\`optimize_battery_and_diesel_schedule\` jointly searches:

- A continuous signed battery power set-point in kW at each timestep.
- A binary diesel on/off commitment decision at each timestep.

Both decision families are evaluated in the same physical simulator. Diesel
power output remains residual-load-driven; this increment does not optimize
diesel kW set-points. Grid import/export and flexible-load schedules also
remain outside the decision vector. The evolutionary method is stochastic and
does not guarantee a global optimum.


## Explicit battery-wear preference in recommendation scoring

All optimizer variants expose four independently weighted objectives:
estimated operating cost, unmet load (reliability), renewable curtailment,
and battery throughput (a wear proxy). Configure `OptimizationWeights.battery_wear`
to express a preference for lower battery throughput. Its default remains
zero for backward compatibility; this is a normalized decision preference,
not a currency-valued degradation model. When a provenance-backed battery
throughput cost is configured in the physical simulator, that cost is also
included in estimated operating cost. Do not interpret the normalized wear
weight as a measured replacement cost.


## Explicit diesel power set-points (physical engine interface)

The shared dispatch input now accepts an optional horizon-aligned
`diesel_power_setpoint_kw` series. Each request is capped by residual load,
the generator rating, confirmed availability/commitment, minimum stable load,
ramp-up behavior, and available fuel. A request below minimum stable output
keeps the unit off rather than forcing an unstable partial-load point. The
requested set-point is retained in each audit row and the run scope metadata.

This is an input contract for explicit schedules; it does not yet mean the
optimizer searches diesel kW set-points. Ramp-down and minimum up/down-time
constraints remain outside the physical model. The interface is offline
planning only and cannot command a real generator.

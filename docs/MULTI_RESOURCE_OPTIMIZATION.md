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

This remains an experimental Stage 4 optimizer, not a finished general-purpose product. In addition to the earlier transparent policy search, the current joint optimizer searches per-timestep battery power, diesel commitment and power, optional flexible-load timing, and grid-export caps in one seeded evolutionary Pareto search. It can replay one common schedule across caller-supplied same-horizon scenarios and rank candidates by worst-case cost, unmet load, curtailment, and battery throughput. The physical simulator also includes an optional horizon peak-import demand charge.

Grid import is still determined by physical residual balance rather than an independent import set-point. The demand-charge model is a single maximum-import proxy over the simulation horizon, not a complete utility tariff engine. Critical-load priority and flexible-load shedding are now accounted for at aggregate level: served power is allocated to critical base demand first, with flexible demand reported as shed before critical unmet load. This is not yet device-level control or process precedence. Minimum up/down times, full network power-flow constraints, and a complete infeasibility proof remain outside the model. Scenario coverage depends on caller-supplied cases; the stochastic heuristic does not guarantee a global optimum.

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
ramp-up/ramp-down behavior, and available fuel. A request below minimum stable output
keeps the unit off rather than forcing an unstable partial-load point. The
requested set-point is retained in each audit row and the run scope metadata.

This is an input contract for explicit schedules; it does not by itself mean
the optimizer searches diesel kW set-points. The physical engine enforces
configured ramp-down limits, including surplus routing and rejection of
incompatible forced stops. The joint optimizer currently rejects ramp-down or
minimum up/down-time configurations because its stochastic commitment generator
does not yet construct schedules that satisfy those constraints. The interface
is offline planning only and cannot command a real generator.


## Joint continuous diesel power and commitment optimization

The joint battery/diesel evolutionary search now includes three aligned
schedule families: signed battery kW set-points, binary diesel commitment,
and continuous requested diesel kW set-points. The shared physical engine
still applies residual-load caps, minimum stable output, ramp-up, availability,
rated power, fuel inventory, and start/stop costs before a candidate can enter
the feasible Pareto archive. The recommendation and Pareto rows expose the
requested diesel kW schedule for audit.

The physical dispatch engine now supports optional ramp-down constraints, but
this joint optimizer deliberately rejects such configurations until its
candidate generator can produce ramp-down-feasible schedules. Minimum up/down
time constraints are also not yet supported by the joint search, and the
heuristic is not a global optimum. A requested diesel set-point is not a
control command. All results remain offline decision support.


## Joint battery and diesel set-point optimization (current experimental increment)

`optimize_battery_and_diesel_schedule` now searches three aligned decision
families in one seeded evolutionary Pareto search:

- Signed battery charge/discharge power set-points (kW per timestep).
- Binary diesel commitment (on/off per timestep).
- Continuous requested diesel power set-points (kW per timestep).

Every candidate is replayed through the shared physical simulator. The
simulator applies SOC and battery power limits, diesel availability,
commitment, minimum stable output, ramp-up, rated power, fuel inventory,
and start/stop costs. The selected next-generation genomes retain exactly
these three decision schedules; the diesel power schedule is not duplicated.

The physical dispatch engine supports optional ramp-down limits, but this
joint optimizer rejects configurations that enable ramp-down or minimum
up/down-time constraints until the candidate generator can construct feasible
commitment schedules. The method remains a bounded stochastic heuristic,
not a guaranteed global optimum.

## Multi-scenario schedule robustness and shortfall diagnosis

`evaluate_schedule_robustness` replays one common schedule across multiple
same-horizon `EnergySystemInputs` scenarios. It reports per-scenario cost,
unmet load, renewable curtailment, battery throughput, physical audit status,
mean-case metrics, and worst-case metrics. It assumes no scenario probabilities:
the worst-case result is a maximum over the supplied cases, not a probability
quantile or forecast confidence bound.

When a scenario has unmet load, the report also includes timestep-level
potential limiting factors, such as grid unavailability/import capacity,
battery minimum SOC/power limits/set-point restrictions, and diesel
availability, commitment, minimum stable output, fuel, ramp-up, or rated-power
limits. These are diagnostic clues, not a unique causal determination; they
must be reviewed against the configured assumptions and source data.

This closes an important robustness-screening gap, but it is not yet a
multi-scenario optimizer that searches one globally robust schedule, nor does
it replace a full infeasibility proof for arbitrary network constraints.
Results are offline decision support only.


## Flexible-load time-shift scheduling (experimental)

`optimize_flexible_load_schedule` allocates one aggregate shiftable electrical
load across a caller-supplied availability window. The caller specifies the
required energy (kWh), per-step maximum power (kW), and a boolean availability
series. Every candidate conserves the requested flexible energy within a
numerical tolerance, obeys the per-step power/window bounds, and is evaluated
through the shared physical dispatch engine against cost, unmet load,
renewable curtailment, and battery throughput.

Example:

```python
from optimization.energy_system_optimizer import optimize_flexible_load_schedule

result = optimize_flexible_load_schedule(
    inputs,
    energy_system_config,
    energy_required_kwh=120.0,
    available_steps=flexible_load_window,
    max_power_kw=20.0,
    population_size=32,
    generations=20,
    seed=20261109,
)
print(result["recommendation"]["flexible_load_power_kw"])
```

This is a bounded single-aggregate-load scheduling increment. Any battery or
diesel schedules already present in the input are held fixed; they are not
jointly optimized with the flexible-load profile. The current physical model
also does not prioritize critical load over flexible load or automatically
shed flexible demand when supply is insufficient. Unmet load remains visible
as an objective and must be reviewed. Per-device task precedence, minimum
run/off times, process constraints, and multi-load coordination remain future
work. The search is stochastic and does not guarantee a global optimum.


## Unified joint decision vector with flexible load (experimental Stage 4 increment)

The joint `optimize_battery_and_diesel_schedule` function now optionally
accepts all three flexible-load contract fields together:

- `flexible_load_energy_kwh`: total shiftable energy that must be scheduled.
- `flexible_load_available_steps`: horizon-aligned boolean operating window.
- `flexible_load_max_power_kw`: per-step upper power bound.

When supplied, the optimizer adds a fourth decision family to the same
mixed-real/binary genome: flexible-load kW allocation at each timestep.
Battery power, diesel commitment, diesel power, and flexible-load allocation
are then evolved and evaluated together through the shared physical simulator.
The required flexible energy is conserved, and availability/power bounds are
enforced before a candidate is evaluated. Omitting all three optional fields
preserves the battery/diesel-only call shape.

This is a meaningful unified decision-vector increment, but it is not yet a
complete plant-wide optimizer. Grid import/export remains determined by the
physical residual balance rather than explicit market set-points. Critical
loads are not prioritized over flexible loads, flexible demand is not
automatically shed under shortage, and device-specific process precedence,
minimum up/down times, and network power-flow constraints remain outside the
model. The evolutionary search is stochastic and does not guarantee a global
optimum. All results remain offline decision support.


## Worst-case multi-scenario joint optimization (experimental)

The joint optimizer also accepts an optional `additional_scenarios` mapping.
The positional `inputs` remain the nominal case; every additional scenario
must use the same horizon and provide explicit diesel availability. Each
candidate genome—including battery, diesel, and optional flexible-load
decisions—is replayed unchanged through the physical simulator for every
scenario. Candidate feasibility requires every scenario's physical audit to
pass.

The Pareto objectives use the maximum (worst supplied case) of estimated
energy cost, unmet load, renewable curtailment, and battery throughput across
the scenario set. The recommendation reports each scenario's own summary and
audit alongside the worst-case objective vector. No scenario probabilities
are assumed, so this is not a probability-weighted expectation, confidence
interval, or forecast quantile.

Example:

```python
result = optimize_battery_and_diesel_schedule(
    nominal_inputs,
    energy_system_config,
    additional_scenarios={
        "low_renewables": low_renewables_inputs,
        "grid_outage": grid_outage_inputs,
    },
    flexible_load_energy_kwh=120.0,
    flexible_load_available_steps=flexible_load_window,
    flexible_load_max_power_kw=20.0,
)
print(result["recommendation"]["scenario_results"])
```

This is a bounded worst-case search over the supplied scenarios, not a proof
of global robust optimality. Scenario quality and coverage depend on the
caller; omitted weather, load, outage, equipment-failure, or tariff cases are
not protected against. The same flexible-load schedule is used in every case,
and critical-load priority/shedding remains unmodeled. Outputs remain offline
decision support, not a controller.


## Grid export dispatch and peak-demand charges

The physical simulator accepts an optional `grid_export_power_setpoint_kw`
series. It is a per-timestep export cap, not a command to force export:
actual export remains limited by renewable surplus, the configured
interconnection limit, and grid/export availability. The joint evolutionary
optimizer includes this cap as a decision family and replays the same schedule
across all supplied robust scenarios. This lets the search avoid uneconomic
exports (for example, negative feed-in prices) while retaining
renewable-curtailment as a separate Pareto objective.

`EnergySystemConfig.grid_demand_charge_per_kw` adds a horizon-level demand
charge calculated as:

```text
demand charge = maximum timestep grid import (kW) × demand charge rate
```

The charge is included in `estimated_energy_cost`, so the optimizer's cost
objective reflects both volumetric energy charges and the modeled peak-demand
charge. The billing window is exactly the simulation horizon; users must
choose a horizon that matches the tariff's actual demand-measurement window.
This is a single-peak proxy, not a full tariff engine: ratchets, coincident
peak windows, time-of-use demand periods, taxes, power-factor penalties, and
contracted-capacity charges are not modeled.


## Critical demand priority and flexible-load shedding accounting

`EnergySystemInputs` now optionally separates the base demand into a
`critical_load_kw` subset and adds a separate `flexible_load_kw` profile.
Critical demand cannot exceed the base `load_kw`; when omitted, all base
demand is treated as critical. Flexible demand is additional and remains
separately visible in the hourly audit.

When total served power is insufficient, the simulator allocates service to
critical demand first. It reports `critical_unmet_kw` and
`flexible_load_shed_kw` separately, while retaining the total
`unmet_load_kw` and energy-balance accounting. The joint optimizer passes its
flexible-load schedule as a separate profile, so scenario reports can show
whether shortages affect critical service or only shiftable demand.

This is aggregate priority accounting, not per-device control. It does not
yet model individual device precedence, minimum run/off times, process
interlocks, or automatic commands to shed physical equipment. The flexible
schedule's required energy remains an optimization contract; any shortfall
must be reviewed in the returned shedding metrics.


## Fair rule-based baseline comparison

The joint optimizer now replays two transparent baselines,
`battery_first` and `grid_first`, across the same supplied scenario set.
Both baselines use the same equipment configuration, source inputs, selected
flexible-load profile (when enabled), and selected grid-export cap schedule
as the evolutionary recommendation. Only their dispatch priority and
absence of explicit optimized battery/diesel schedules differ.

The result includes each baseline's per-scenario physical audit and summary,
worst-case objective vector, and recommended-minus-baseline deltas for cost,
unmet load, renewable curtailment, and battery throughput. Negative deltas
mean the recommendation is lower on that metric for the supplied scenarios.
This is a transparent benchmark, not proof that the evolutionary search
beats every possible operating policy; conclusions remain limited to the
provided scenarios and model assumptions.


## Robustness diagnostics for critical and flexible service

`evaluate_schedule_robustness` can now replay a shared flexible-load profile
and grid-export cap schedule across the supplied scenarios. Each replay
preserves scenario-specific critical-load definitions and reports total
service shortfall separately from critical-load shortfall and flexible-load
shedding. Its aggregate result includes whether all critical loads were
served, plus worst-case critical unmet energy and flexible energy shed.

Timestep diagnostics classify a shortfall as `flexible_load_shed_only` when
critical demand was fully served but flexible demand was not; otherwise a
critical deficit is identified as `critical_load_shortfall`. The listed
physical limiting factors remain potential contributors, not a unique causal
proof. These diagnostics are intended to help explain infeasible or
service-deficient schedules, not to authorize automatic load shedding.


## Optional hard service constraints and infeasibility explanations

The joint optimizer accepts optional hard constraints:
`max_unmet_load_kwh`, `max_critical_unmet_load_kwh`, and
`terminal_battery_soc_min`. The two unmet-energy limits are applied
separately to every supplied scenario. The terminal SOC reserve is also
checked in every scenario. A candidate enters the feasible Pareto archive
only when its physical energy-balance audits pass and all configured
constraints are respected. Leave an unmet-energy threshold as `None` to
retain soft-objective behavior for that metric; set it to `0.0` to require
zero unmet energy. The terminal SOC reserve must be within the battery's
configured SOC limits.

The result's `constraint_diagnostics` reports configured limits, physical
audit pass counts, service-constraint pass counts, and rejection counts. If
no candidate is feasible, the optimizer raises `OptimizationError` with a
`diagnostics` attribute containing the best candidate's per-scenario
shortfalls, violated constraints, and likely limiting factors from
`diagnose_dispatch_shortfalls`. These are model-based explanations, not a
mathematical infeasibility certificate or a unique causal diagnosis.

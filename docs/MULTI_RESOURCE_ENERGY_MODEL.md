# Multi-resource energy balance model

The shared core now includes `islandos_core.energy_system`, a deterministic
offline model for hourly (or fixed-step) energy balancing across:

- PV and wind generation inputs;
- site electrical load;
- battery charge/discharge with SOC and efficiency limits;
- grid imports with an import-power limit and availability flag;
- diesel generation with a rated-power limit and explicit variable energy cost;
- renewable curtailment and unmet load.

## Explicit dispatch policies

Two transparent rule-based policies are currently available:

1. `battery_first`: renewable generation, battery discharge, grid imports, then diesel.
2. `grid_first`: renewable generation, grid imports, battery discharge, then diesel.

Both policies charge the battery from renewable surplus before curtailing it.
These are comparison baselines, not an optimizer. The model does not claim that
either policy is globally cost-optimal.

## Physics and accounting

At each timestep, the model checks:

```text
PV + wind + battery discharge + grid import + diesel
= load served + battery charge + renewable curtailment
```

Battery state of charge is updated with separate charge and discharge
efficiencies and is constrained by configured minimum and maximum SOC. PV and
wind inputs above their configured nameplate ratings are rejected rather than
silently clipped. Missing availability is not inferred: grid and diesel
availability are explicit boolean series (grid defaults available only when
the caller omits the optional diesel series; grid availability is required).

The output includes per-step audit rows and aggregate energy, cost, curtailment,
unmet-load and ending-SOC metrics. Grid and diesel costs are estimates from
user-supplied prices/cost assumptions; they are not a tariff settlement.

## Important limitations before site use

This first increment does not yet model grid export, network voltage/frequency,
power factor, generator minimum stable loading, ramp/start constraints, fuel
inventory, battery degradation/replacement, demand charges, tariff calendars,
forecast uncertainty, equipment outages beyond availability flags, or safety
interlocks. It is not connected to devices and cannot issue commands.

All examples and tests use synthetic fixtures. Passing tests demonstrates
software consistency against those fixtures, not field validation, measured
savings, equipment compatibility, or operational readiness. Critical missing
site parameters must remain explicit blockers in a future site-readiness gate.

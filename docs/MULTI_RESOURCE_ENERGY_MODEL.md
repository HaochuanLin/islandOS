# Multi-resource energy balance model

The shared core now includes `islandos_core.energy_system`, a deterministic
offline model for hourly (or fixed-step) energy balancing across:

- PV and wind generation inputs;
- site electrical load;
- battery charge/discharge with SOC and efficiency limits;
- grid imports with an import-power limit and availability flag;
- optional grid exports with a separately configured export-power limit, explicit
  feed-in price series, and grid-availability gating;
- diesel generation with a rated-power limit and explicit variable energy cost;
- renewable curtailment and unmet load.

## Explicit dispatch policies

Two transparent rule-based policies are currently available:

1. `battery_first`: renewable generation, battery discharge, grid imports, then diesel.
2. `grid_first`: renewable generation, grid imports, battery discharge, then diesel.

Both policies charge the battery from renewable surplus first. If grid export
is enabled and the grid is available, remaining surplus is exported up to the
configured export limit; anything left is curtailed.
These are comparison baselines, not an optimizer. The model does not claim that
either policy is globally cost-optimal.

## Physics and accounting

At each timestep, the model checks:

```text
PV + wind + battery discharge + grid import + diesel
= load served + battery charge + grid export + renewable curtailment
```

Battery state of charge is updated with separate charge and discharge
efficiencies and is constrained by configured minimum and maximum SOC. PV and
wind inputs above their configured nameplate ratings are rejected rather than
silently clipped. Grid availability must always be supplied as an explicit boolean series.
When a diesel generator is configured, diesel availability must also be
supplied explicitly. An unconfigured diesel unit is never treated as available.
Missing availability is rejected rather than silently assumed.

The output includes per-step audit rows and aggregate energy, import cost,
export revenue, net estimated energy cost, curtailment, unmet-load and ending-SOC
metrics. Export is disabled by default. Enabling it requires a positive explicit
grid export limit and a same-length feed-in price series and export-permission series;
negative feed-in prices
are allowed and correctly increase net cost. Export is blocked whenever the grid
availability flag or the separate explicit export-permission flag is false.
A grid that is online is not automatically assumed to permit reverse power
flow. Export requires both a same-length feed-in price series and a same-length
`grid_export_available` boolean series. These are estimates from user-supplied assumptions,
not a tariff settlement or proof of interconnection permission.

## Important limitations before site use

This increment models bounded grid export in the energy balance, but does not
validate interconnection permission, anti-islanding protection, export
certification, or settlement rules. It also does not model network
voltage/frequency, power factor, generator minimum stable loading, ramp/start
constraints, fuel inventory, battery degradation/replacement, demand charges,
tariff calendars, forecast uncertainty, equipment outages beyond availability
flags, or safety interlocks. It is not connected to devices and cannot issue
commands.

All examples and tests use synthetic fixtures. Passing tests demonstrates
software consistency against those fixtures, not field validation, measured
savings, equipment compatibility, or operational readiness. Critical missing
site parameters must remain explicit blockers in a future site-readiness gate.

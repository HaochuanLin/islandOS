# Multi-resource energy balance model

The shared core now includes `islandos_core.energy_system`, a deterministic
offline model for hourly (or fixed-step) energy balancing across:

- PV and wind generation inputs;
- site electrical load;
- battery charge/discharge with SOC and efficiency limits;
- grid imports with an import-power limit and availability flag;
- optional grid exports with a separately configured export-power limit, explicit
  feed-in price series, and grid-availability gating;
- diesel generation with rated and minimum-stable power limits, explicit availability,
  optional ramp-up limit, variable energy cost, per-start/per-stop costs,
  and optional finite fuel-inventory accounting;
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
efficiencies and is constrained by configured minimum and maximum SOC. An
optional user-supplied throughput wear-cost rate prices each kWh charged plus
each kWh discharged; the resulting estimate is included in timestep audit rows,
policy comparisons, and gross/estimated energy cost. This is a transparent
cost proxy only: it does not calculate physical capacity fade, cycle-life,
calendar aging, temperature effects, or replacement timing. The default rate is
zero, which means battery wear cost is not included unless explicitly supplied.
PV and wind inputs above their configured nameplate ratings are rejected rather
than silently clipped. Grid availability must always be supplied as an explicit boolean series.
When a diesel generator is configured, diesel availability must also be
supplied explicitly. An unconfigured diesel unit is never treated as available.
Missing availability is rejected rather than silently assumed.

A diesel unit starts only when the residual demand can accept at least its
configured minimum stable output; otherwise that residual remains unmet rather
than operating the generator below its declared stable limit. Optional ramp-up
limits constrain upward changes after the initial stable startup point. Start/stop events and
their fixed costs are recorded per timestep and included in estimated energy
cost. Ramp-down dynamics are not yet modeled; when demand falls or availability
is lost, the unit is stopped immediately. Multiple diesel units are still
rejected by the asset adapter until per-device commitment is supported.

When both a confirmed initial tank inventory and a fuel-consumption rate are
provided, diesel output is capped by the remaining fuel in each timestep.
An optional `diesel_fuel_delivery_liters` series can add explicitly scheduled
fuel at the start of each timestep; deliveries are non-negative, horizon-aligned,
and rejected unless the diesel fuel-inventory model is enabled. An optional
confirmed tank-capacity assumption bounds initial inventory and rejects any
scheduled delivery that would overfill the tank. Delivered, consumed, and
remaining fuel are retained in per-step audit rows and aggregate summary values. This is a user-supplied schedule, not a delivery forecast or
proof that a supplier can fulfil it. The model does not simulate tank
measurement error, fuel-quality effects, or nonlinear fuel curves; a constant
L/kWh rate is a screening assumption and must be explicitly supplied.

The output includes per-step audit rows and aggregate energy, import cost,
export revenue, net estimated energy cost, curtailment, unmet-load and ending-SOC
metrics. Export is disabled by default. Enabling it requires all three of:
(1) a positive explicit grid export limit, (2) a same-length feed-in price
series, and (3) a same-length `grid_export_available` boolean series. Grid
uptime does not imply permission to export. Export is blocked whenever either
the grid-availability flag or the separate export-permission flag is false.
Negative feed-in prices are allowed and correctly increase net cost. Grid,
diesel, export, and battery wear-cost inputs must use a consistent currency and
energy basis; no foreign-exchange conversion is performed. These are estimates
from user-supplied assumptions, not a tariff settlement or proof of
interconnection permission.

## Important limitations before site use

This increment models bounded grid export in the energy balance, but does not
validate interconnection permission, anti-islanding protection, export
certification, or settlement rules. It also does not model network
voltage/frequency, power factor, diesel ramp-down dynamics, nonlinear fuel
curves, fuel-delivery reliability, tank measurement error, physical battery
capacity fade/replacement, demand charges,
tariff calendars, forecast uncertainty, equipment outages beyond availability
flags, or safety interlocks. It is not connected to devices and cannot issue
commands.

All examples and tests use synthetic fixtures. Passing tests demonstrates
software consistency against those fixtures, not field validation, measured
savings, equipment compatibility, or operational readiness. Critical missing
site parameters must remain explicit blockers in a future site-readiness gate.

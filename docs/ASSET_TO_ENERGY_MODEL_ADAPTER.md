# Asset-to-energy-model integration

## What this adds

`islandos_core.asset_energy_adapter` converts confirmed asset records from
`islandos_core.assets` into an `EnergySystemConfig` for the deterministic
offline energy model.

This closes the first explicit data hand-off between the asset registry and
the energy simulation engine. It is not a live connector, device discovery
mechanism, optimizer, compatibility certification, or control interface.

## Fail-closed behavior

The adapter requires:
- all assets to belong to one site;
- supported asset types only (PV, wind, battery, grid connection, diesel generator);
- unique asset IDs within the site;
- PV, wind, and grid-connection assets may be aggregated by summing each
  individually validated effective capacity;
- battery and diesel assets remain single-instance until per-device state and
  unit-commitment constraints are represented;
- each asset to pass the existing confirmed-installed-parameter and confirmed
  hard-constraint readiness gate;
- canonical units for installed ratings and operating limits;
- explicit battery initial SOC and charge/discharge efficiencies when a battery
  is present;
- explicit diesel variable energy cost when a diesel generator is present;
- optional diesel fuel model plus initial inventory: either a legacy constant
  consumption rate (L/kWh), or a piecewise curve recorded as indexed confirmed
  `diesel_fuel_curve_N_power_kw` (kW) and
  `diesel_fuel_curve_N_fuel_l_per_hour` (L/h) assumptions. Curves require
  contiguous point indices from zero and at least two points. An optional
  confirmed tank capacity (L) can additionally bound inventory and deliveries.
  An optional `diesel_fuel_price_per_liter` assumption accepts an ISO
  currency-per-liter unit (for example CNY/L or USD/L) and separates fuel
  expenditure from non-fuel variable O&M in the model cost breakdown.

A single diesel generator's confirmed minimum stable loading is mapped into the
energy model. Flexible loads are rejected until their dispatch semantics are
integrated into the multi-resource model. Multiple PV, wind, and grid-connection
assets are summed only after each asset independently passes readiness and
hard-constraint validation. The
effective contribution of each asset is the lower of its confirmed installed
power and its confirmed hard upper limit. Unavailable or incomplete assets
block the whole site conversion rather than silently disappearing. Batteries
cannot yet be aggregated because individual SOC and efficiency states must be
preserved. Multiple diesel units also remain blocked until per-unit commitment,
minimum loading, ramping, and start behavior are modeled.

## Parameter interpretation

- PV/wind model ratings are capped at the lower of confirmed installed power
  and the confirmed hard maximum-power constraint.
- Grid import capacity is capped at the lower of confirmed installed power
  and the confirmed hard import limit.
- Grid export is disabled unless a grid connection also carries exactly one
  confirmed hard `export_limit_kw` maximum constraint in kW. Its effective
  contribution is capped at the lower of confirmed installed power and that
  export limit. Missing export constraints contribute zero export capacity;
  present but unconfirmed, duplicated, or malformed export constraints block
  conversion rather than being guessed. Until a shared point-of-connection
  capacity model exists, more than one export-capable grid connection blocks
  conversion rather than having its limits summed and potentially overstated.
- Battery capacity comes from confirmed usable installed energy capacity;
  charge/discharge limits and SOC bounds come from confirmed hard constraints.
- Diesel rated power comes from the lower of confirmed installed power and
  confirmed hard maximum power; minimum stable output comes from its confirmed
  hard minimum constraint.

Battery efficiencies, initial SOC, and diesel variable cost are explicit
operating assumptions passed by the caller as provenance-bearing
`AssetParameter` records. An optional battery throughput wear-cost rate is
mapped only when supplied as a confirmed currency-per-kWh assumption; absent
means the wear-cost proxy remains disabled at zero. Optional battery lifecycle
assumptions include confirmed `battery_initial_state_of_health` (fraction),
`battery_cycle_life_efc` (EFC), and
`battery_end_of_life_capacity_fraction` (fraction). Cycle life enables the
simplified throughput-driven capacity-fade model; absent cycle-life data, the
physical aging model remains disabled. An optional diesel tank capacity is
likewise accepted only as a confirmed liter-valued assumption.
Each supplied assumption must have a unit, source type, source reference, and
explicit confirmation. They are not invented from the asset registry. The
caller must carry these records into the future run manifest.

## Example

```python
from islandos_core.asset_energy_adapter import build_energy_system_config_from_assets
from islandos_core.assets import AssetParameter

def assumption(value, unit, reference):
    return AssetParameter(
        value=value, unit=unit, source_type="customer_provided",
        source_reference=reference, confirmed=True,
    )

config = build_energy_system_config_from_assets(
    confirmed_assets,
    dt_hours=1.0,
    operating_assumptions={
        "battery_initial_soc": assumption(0.50, "fraction", "operator confirmation"),
        "battery_charge_efficiency": assumption(0.95, "fraction", "battery datasheet"),
        "battery_discharge_efficiency": assumption(0.95, "fraction", "battery datasheet"),
        "diesel_variable_cost_per_kwh": assumption(1.20, "USD/kWh", "fuel cost model"),
        "diesel_fuel_consumption_l_per_kwh": assumption(0.25, "L/kWh", "generator datasheet"),
        "diesel_initial_fuel_liters": assumption(500, "L", "operator tank reading"),
    },
)
```

Only assumptions relevant to assets present in the site are required.

## Remaining work

Before this becomes a general site model, IslandOS still needs:
- versioned multi-instance aggregation provenance retained in immutable run
  manifests, plus per-device battery states;
- electrical topology and connection constraints;
- flexible-load adapters and scheduling semantics;
- diesel ramp-down dynamics, per-unit commitment for multiple generators,
  tank-capacity checks, nonlinear fuel curves, and provenance-bearing asset
  assumptions for ramp/start costs (explicit delivery series are supplied as
  time-series inputs to each dispatch run, not inferred by this adapter);
- grid export settlement, tariff calendars, and interconnection validation;
- explicit provenance records for every operating assumption;
- model-specific readiness gates and tests against public/field data.

A successful conversion means only that the provided records are structurally
compatible with the currently implemented offline model. It does not establish
that the records are accurate, the equipment is electrically compatible, or
the model is safe for operational use.

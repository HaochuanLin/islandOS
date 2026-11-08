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
- no more than one asset of each supported type in this first adapter version;
- each asset to pass the existing confirmed-installed-parameter and confirmed
  hard-constraint readiness gate;
- canonical units for installed ratings and operating limits;
- explicit battery initial SOC and charge/discharge efficiencies when a battery
  is present;
- explicit diesel variable energy cost when a diesel generator is present.

It rejects diesel generators with a non-zero minimum stable loading because
the current energy dispatch model does not yet represent that constraint.
Flexible loads are also rejected until their dispatch semantics are integrated
into the multi-resource model. Multiple same-type assets are not silently
summed: batteries in particular cannot safely be aggregated without preserving
individual SOC, efficiency, and operating limits.

## Parameter interpretation

- PV/wind model ratings are capped at the lower of confirmed installed power
  and the confirmed hard maximum-power constraint.
- Grid import capacity is capped at the lower of confirmed installed power
  and the confirmed hard import limit.
- Battery capacity comes from confirmed usable installed energy capacity;
  charge/discharge limits and SOC bounds come from confirmed hard constraints.
- Diesel rated power comes from the lower of confirmed installed power and
  confirmed hard maximum power.

Battery efficiencies, initial SOC, and diesel variable cost are explicit
operating assumptions passed by the caller. They are not invented from the
asset registry and must retain their own provenance in a future run manifest.

## Example

```python
from islandos_core.asset_energy_adapter import build_energy_system_config_from_assets

config = build_energy_system_config_from_assets(
    confirmed_assets,
    dt_hours=1.0,
    operating_assumptions={
        "battery_initial_soc": 0.50,
        "battery_charge_efficiency": 0.95,
        "battery_discharge_efficiency": 0.95,
        "diesel_variable_cost_per_kwh": 1.20,
    },
)
```

Only assumptions relevant to assets present in the site are required.

## Remaining work

Before this becomes a general site model, IslandOS still needs:
- versioned multi-instance asset aggregation with per-device battery states;
- electrical topology and connection constraints;
- flexible-load adapters and scheduling semantics;
- diesel minimum stable output, ramp/start constraints and fuel inventory;
- grid export and tariff structures;
- explicit provenance records for every operating assumption;
- model-specific readiness gates and tests against public/field data.

A successful conversion means only that the provided records are structurally
compatible with the currently implemented offline model. It does not establish
that the records are accurate, the equipment is electrically compatible, or
the model is safe for operational use.

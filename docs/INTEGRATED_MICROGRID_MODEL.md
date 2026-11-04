# Integrated Microgrid Model — first system-level physics milestone

**Status:** implemented simulation baseline; not a forecast, optimizer, live controller, or field-validated digital twin.

## Why this module exists

The existing RO and flexible-load workflows are useful experiments, but a system-level platform also needs one auditable place to account for PV, wind, essential electricity demand, battery energy, grid imports, diesel backup, flexible RO consumption, renewable curtailment, water production, and tank inventory.

`islandos_core/microgrid_model.py` adds that deterministic accounting layer. It is intentionally small and explicit so that later forecast and optimization modules can call the same physical evaluator rather than implement competing energy balances.

## Dispatch policy implemented

For each constant-length time step:

1. PV and wind are combined as available renewable generation.
2. Renewable generation serves essential electricity demand first.
3. A battery may discharge to cover the remaining essential demand, subject to SOC, discharge-power, and efficiency limits.
4. Grid imports serve the remaining essential demand when the grid is available and within its import limit.
5. Diesel generation serves the remaining essential demand within its rated limit. Any residual is reported as unserved essential load; it is never hidden.
6. Scheduled RO load may use renewable power left after essential demand only. It cannot draw from the battery, grid, or diesel in this first policy.
7. RO power is clipped by its rated power and water-tank headroom. Water production follows the configured specific energy.
8. Remaining renewable power charges the battery within charge-power and SOC limits. Any remainder is reported as curtailment.
9. Water demand is served from opening inventory plus same-step production; unmet demand and closing inventory are reported.

This is a transparent priority policy, not an optimal dispatch algorithm. Changing the priority order can change outcomes.

## Equations and accounting

Let (P_{ren}=P_{PV}+P_{wind}). Renewable allocation must satisfy:

`P_ren = P_essential,ren + P_RO + P_battery,charge + P_curtailed`

Essential electricity accounting must satisfy:

`P_essential = P_essential,ren + P_battery,discharge + P_grid + P_diesel + P_unserved`

Battery state of charge uses charge/discharge efficiencies and is bounded by configured minimum and maximum energy. The water balance is:

`V[t+1] = V[t] + water_produced[t] - water_served[t]`

RO production is:

`water_produced = P_RO × Δt / specific_energy`

The simulator validates these balances and equipment limits before returning a result.

## Minimal reproducible example

```python
from islandos_core.microgrid_model import (
    MicrogridConfig, MicrogridInputs, simulate_microgrid,
)

config = MicrogridConfig(
    battery_capacity_kwh=200,
    battery_initial_soc_kwh=100,
    battery_min_soc_kwh=20,
    battery_max_charge_kw=50,
    battery_max_discharge_kw=50,
    battery_charge_efficiency=0.95,
    battery_discharge_efficiency=0.95,
    grid_import_limit_kw=100,
    diesel_capacity_kw=80,
    ro_rated_power_kw=30,
    ro_specific_energy_kwh_per_m3=4.0,
    water_tank_capacity_m3=500,
    water_initial_inventory_m3=200,
)
inputs = MicrogridInputs(
    pv_power_kw=[80, 10, 0],
    wind_power_kw=[20, 30, 10],
    essential_load_kw=[60, 55, 70],
    ro_requested_power_kw=[30, 0, 0],
    water_demand_m3=[5, 5, 5],
    grid_available=[True, True, False],
    grid_price_per_kwh=[0.2, 0.2, 0.2],
    diesel_cost_per_kwh=0.8,
    diesel_emissions_kg_per_kwh=0.7,
)
result = simulate_microgrid(inputs, config)
print(result.summary())
```

Run the regression tests:

```bash
python -m unittest tests.test_microgrid_model -v
```

## What this milestone proves

- A single deterministic scenario can account for renewable generation, essential load, battery, grid, diesel, RO, and water inventory together.
- Essential electricity demand is prioritized over discretionary RO demand.
- Battery SOC and water inventory are checked against configured bounds.
- Grid outage, diesel limits, unmet essential demand, and unmet water demand are explicit outputs.
- Energy and water balances are automatically checked.
- Operating cost and emissions are calculated only from user-supplied price/emission factors; defaults are zero and therefore must not be interpreted as real-world costs or emissions.

## What it does not prove

- It does not forecast PV, wind, electricity demand, or water demand.
- It does not optimize the schedule or prove global optimality.
- It does not model battery degradation, generator start-up/fuel curves, grid export, reactive power, network voltage/frequency, ramp rates, reserve services, or equipment faults.
- It does not model RO minimum up/down time, membrane recovery, water quality, pumps, pressure, or treatment constraints.
- It is not a validated digital twin and does not communicate with PLCs or actuators.
- Same-step water production is available to serve same-step demand; sub-hourly or site-specific chronology may require a more detailed event model.
- Synthetic inputs validate software behavior, not field performance.

## Next engineering steps

1. Add scenario fixtures and a reproducible benchmark against explicit baseline policies.
2. Connect forecast contracts for PV, wind, essential load, and water demand without leakage.
3. Add rolling-horizon scheduling that re-simulates candidate actions through this same model.
4. Add multi-objective evaluation only after objective units, weights, hard constraints, and Pareto selection are independently tested.
5. Keep telemetry read-only and advisory until site-specific engineering review and operator acceptance.

# Diesel-surplus sensitivity experiment

## Question

Under which synthetic operating conditions does the existing IslandOS joint water-energy MILP reduce diesel use beyond a fixed RO timetable and a simple surplus rule?

## Design

The experiment reuses `IslandSiteConfig`, `generate_synthetic_inputs`, and `compare_with_optimizer` from `islandos_core/impact_scenario.py`. It does not introduce a second dispatch model.

Four controlled cases are compared:

| Case | PV | Wind | Tank capacity | Other equipment and demand |
|---|---:|---:|---:|---|
| A baseline | 60 kW | 40 kW | 80 m³ | Held at existing defaults |
| B more wind | 60 kW | 70 kW | 80 m³ | Held at existing defaults |
| C larger tank | 60 kW | 40 kW | 120 m³ | Held at existing defaults |
| D combined | 60 kW | 70 kW | 120 m³ | Held at existing defaults |

The 70 kW wind and 120 m³ tank values are exploratory sensitivity assumptions, not measured site values or literature-validated recommendations. PV, diesel rating, battery, RO rating, water demand, initial tank level, and operating rules remain unchanged. The same seed is used across cases; each case is generated deterministically from its own site configuration.

## Strategies

- Fixed RO timetable
- Simple renewable-surplus rule
- Forecast-based rule (perfect forecast)
- Forecast-based rule with 20% renewable forecast error and a 3-hour minimum run
- Joint water-energy MILP
- Joint MILP with a 20 m³ reserve

The joint MILP must satisfy the existing model's terminal tank constraint. All strategies are evaluated through the shared energy-system dispatch model.

## Run

```bash
python experiments/run_diesel_surplus_sensitivity.py --seeds 10 --days 3
```

For a larger run, after the initial run is reviewed:

```bash
python experiments/run_diesel_surplus_sensitivity.py --seeds 30 --days 7
```

Outputs are written to `results/diesel_surplus_sensitivity/`.

## Metrics and limitations

The primary metric is tank-adjusted diesel litres, using the repository's constant `diesel_litres_per_kwh` conversion. The CSV also records diesel generation, water shortage, unmet essential electricity, terminal tank level, and solver optimality status.

This is not yet a physical diesel fuel-curve model. It does not establish real generator fuel savings, because nonlinear fuel-rate behaviour, minimum stable loading, start fuel, and unit commitment constraints are not represented in this experiment. Results must be described as synthetic model estimates only.

A case is not considered a credible improvement if it achieves lower diesel use by increasing unmet water, unmet essential electricity, or drawing down the terminal water tank. Compare the MILP against the surplus rule, not only against the fixed timetable. Report all cases, seeds, and failed/infeasible solves; do not select only the best run.

## Decision rule

The experiment can support a stronger diesel-saving claim only if the joint MILP repeatedly improves on the surplus rule across seeds, maintains service constraints, and the solver proves optimality for the declared MILP. Even then, the claim is limited to this synthetic model until generator fuel curves and site data are incorporated.

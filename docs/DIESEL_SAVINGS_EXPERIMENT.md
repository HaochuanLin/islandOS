# Diesel-savings experiment

## Purpose

Test when IslandOS' existing coordinated water-energy dispatch can reduce diesel use in an off-grid hybrid microgrid. The experiment deliberately compares the joint MILP with both a fixed RO timetable and a reasonable renewable-surplus rule. A result against the fixed timetable alone is not sufficient evidence of product value.

## Reused implementation

The runner does not implement a second microgrid simulator. It reuses:

- `islandos_core.impact_scenario.generate_synthetic_inputs` for deterministic synthetic weather, essential load and water demand;
- `islandos_core.impact_scenario.compare_with_optimizer` for the existing fixed, surplus, forecast-based and joint-MILP policy comparisons;
- `islandos_core.energy_system` for shared electrical dispatch replay;
- `optimization.milp_dispatch_optimizer` through the existing comparison function for joint water-energy optimization.

## Scenarios

| Scenario | Controlled change | Question |
|---|---|---|
| A — Reference | Existing default site configuration | Reproduce the existing baseline |
| B — Diesel dependent | Higher essential load, smaller PV/wind fleet, larger diesel unit | Does flexible RO scheduling matter more when diesel supplies a larger share? |
| C — Variable renewables / limited storage | Larger PV/wind fleet and smaller battery | Does timing matter when renewable surplus and storage capacity are mismatched? |
| D — Larger flexible water load | Larger RO, tank and daily water demand | Does a material flexible load create additional coordination value? |

These are intentionally synthetic stress scenarios, not representative customer data. All parameter changes are recorded in `manifest.json`.

## Policies

- Fixed RO timetable (07:00–19:00).
- Simple renewable-surplus rule.
- Forecast-based rule with 20% seeded multiplicative renewable forecast error and a 3-hour RO minimum run.
- IslandOS joint water-energy MILP.

All policies in a given seed use the same synthetic input arrays. The MILP is optimal only for its declared mathematical model; it is not evidence of a trained forecast model or field controller.

## Fairness and metrics

The headline is diesel litres adjusted for the energy needed to restore the water tank to its initial inventory. This prevents a policy from appearing to save diesel merely by ending with less stored water.

The output includes diesel generation, estimated diesel litres, renewable availability/use/curtailment, water production, unmet water, ending tank inventory and unserved electricity. Water and electricity service must be checked before comparing savings.

Diesel litres use the current constant litres-per-kWh factor in `IslandSiteConfig`. The model does not currently represent a nonlinear part-load generator fuel curve. This limitation is disclosed rather than hidden.

## Reproduction

Quick smoke run:

```bash
python experiments/run_diesel_savings_sweep.py --seeds 1 --days 1 --output-dir build/diesel-sweep-smoke
```

Standard run:

```bash
python experiments/run_diesel_savings_sweep.py --seeds 10 --days 7
```

Larger repeatability run:

```bash
python experiments/run_diesel_savings_sweep.py --seeds 30 --days 7
```

The output directory contains:

- `per_seed.csv`: policy-level results for every scenario and seed;
- `aggregate.json`: means, ranges, shortage checks and comparisons against both baselines;
- `manifest.json`: command, package versions, seeds, scenario parameters and model-scope disclosures;
- `summary.md`: human-readable comparison.

## Interpretation rules

1. Compare IslandOS against the simple renewable-surplus rule, not only the fixed timetable.
2. Do not call a policy superior if it leaves more unmet water or unserved electricity.
3. Report all four scenarios, including negative or negligible savings.
4. Treat synthetic results as model evidence only, not measured site performance.
5. Do not transfer a best-case scenario percentage into the GSC Proposal without explaining the scenario and its assumptions.

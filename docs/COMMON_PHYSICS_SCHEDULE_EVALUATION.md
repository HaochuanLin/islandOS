# Common-physics schedule evaluation

The `islandos_core.schedule_evaluator` module evaluates supplied flexible RO power schedules through the same chronological physical simulator (`islandos_core.microgrid_model`). A candidate schedule is replayed against renewable availability, essential electricity demand, battery/grid/diesel limits, tank headroom, water demand, and the simulator's accounting invariants.

## What it produces

For each candidate: feasibility, essential electricity not served, unmet water demand, operating cost, emissions, renewable curtailment, water produced, and RO electricity consumed. Hourly arrays remain available on the evaluation result for audit and plotting.

## Ranking rule

1. Feasible candidates rank before infeasible candidates.
2. Then minimize unmet essential electricity and unmet water.
3. Then minimize operating cost, emissions, and renewable curtailment.
4. A stable schedule ID breaks exact ties.

This is a transparent lexicographic screening rule. It is **not** a weighted multi-objective optimizer, NSGA-II implementation, forecast model, or autonomous controller. It ranks only schedules supplied by a caller; schedule generation and forecast uncertainty remain separate tasks.

## Built-in candidate generation

`generate_renewable_surplus_candidates(inputs, config)` creates three deterministic request schedules: no RO, 50% of estimated instantaneous renewable surplus, and 100% of estimated instantaneous renewable surplus (all capped at RO nameplate rating). `screen_renewable_surplus_candidates(inputs, config)` sends all three through the same physical evaluator and returns the ranked results.

The generator uses supplied PV, wind, and essential-load time series; it does not forecast them. The simulator remains authoritative for actual service, battery/grid/diesel interactions, tank headroom, water balance, and feasibility. These simple rules are candidate baselines for comparison, not a claim of globally optimal scheduling.

## Example

```python
from islandos_core.schedule_evaluator import screen_renewable_surplus_candidates

ranked = screen_renewable_surplus_candidates(inputs, config)
for item in ranked:
    print(item.to_dict())
```

## Evidence boundary

Use synthetic scenarios to test code paths and invariants, clearly labelled as synthetic. A real-world saving claim requires site data, matched service coverage, equivalent water output and quality, confirmed cost assumptions, and field validation. The evaluator does not issue equipment commands.


## Reproducible exported comparison

Run `python tools/run_schedule_screening_demo.py --hours 168 --seed 20261105` to export a provenance-labelled JSON report and ranked CSV. The report records the candidate rules, common scenario, model assumptions, ranking order, and metrics. It is an auditable synthetic demonstration, not site validation.

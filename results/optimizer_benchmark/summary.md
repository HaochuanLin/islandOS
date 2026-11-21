# Optimizer benchmark (synthetic inputs)

Input seeds: 3. Evolutionary seeds per input: 3. Evolutionary budget: population 48, 60 generations. Evolutionary runs must keep unmet load at or below 0.01 kWh.

Gap is the energy cost of a method minus the MILP cost on the same inputs, as a percentage of the MILP cost. The evolutionary search is scored by the cheapest feasible schedule on its Pareto front. Seed spread is the largest cost range across evolutionary seeds on one input.

| Case | Diesel | Horizon | Method | Runs | Failed | Mean gap | Worst gap | Matches MILP | Mean runtime (s) | Seed spread |
|---|---|---|---|---|---|---|---|---|---|---|
| island | plain | 24 h | Rule dispatch (battery first) | 3 | 0 | 0.0% | 0.0% | 3 | 0.0 | n/a |
| island | plain | 24 h | MILP (HiGHS) | 3 | 0 | 0.0% | 0.0% | 3 | 0.021 | n/a |
| island | plain | 24 h | Evolutionary, random start | 9 | 0 | 44.136% | 123.741% | 1 | 1.382 | 123.744% |
| island | plain | 24 h | Evolutionary, warm start | 9 | 0 | -0.0% | 0.0% | 9 | 1.281 | 0.0% |
| island | plain | 168 h | Rule dispatch (battery first) | 3 | 0 | 0.0% | 0.0% | 3 | 0.001 | n/a |
| island | plain | 168 h | MILP (HiGHS) | 3 | 0 | 0.0% | 0.0% | 3 | 0.063 | n/a |
| island | plain | 168 h | Evolutionary, random start | 9 | 0 | 32.805% | 38.755% | 0 | 7.822 | 0.0% |
| island | plain | 168 h | Evolutionary, warm start | 9 | 0 | -0.0% | -0.0% | 9 | 7.636 | 0.0% |
| island | constrained | 24 h | Rule dispatch (battery first) | 3 | 0 | 0.214% | 0.521% | 1 | 0.0 | n/a |
| island | constrained | 24 h | MILP (HiGHS) | 3 | 0 | 0.0% | 0.0% | 3 | 0.014 | n/a |
| island | constrained | 24 h | Evolutionary, random start | 9 | 0 | 1.985% | 17.798% | 8 | 3.565 | 17.798% |
| island | constrained | 24 h | Evolutionary, warm start | 9 | 0 | -0.002% | 0.0% | 9 | 4.044 | 0.008% |
| island | constrained | 168 h | Rule dispatch (battery first) | 3 | 0 | 0.348% | 0.593% | 0 | 0.001 | n/a |
| island | constrained | 168 h | MILP (HiGHS) | 3 | 0 | 0.0% | 0.0% | 3 | 0.132 | n/a |
| island | constrained | 168 h | Evolutionary, random start | 9 | 0 | 4.167% | 12.661% | 0 | 8.289 | 6.395% |
| island | constrained | 168 h | Evolutionary, warm start | 9 | 0 | 0.348% | 0.593% | 0 | 8.053 | 0.0% |
| hybrid_tou | plain | 24 h | Rule dispatch (battery first) | 3 | 0 | 41.692% | 66.088% | 0 | 0.0 | n/a |
| hybrid_tou | plain | 24 h | MILP (HiGHS) | 3 | 0 | 0.0% | 0.0% | 3 | 0.012 | n/a |
| hybrid_tou | plain | 24 h | Evolutionary, random start | 9 | 0 | 0.0% | 0.0% | 9 | 12.071 | 0.0% |
| hybrid_tou | plain | 24 h | Evolutionary, warm start | 9 | 0 | 0.0% | 0.0% | 9 | 12.118 | 0.0% |
| hybrid_tou | plain | 168 h | Rule dispatch (battery first) | 3 | 0 | 11.855% | 12.532% | 0 | 0.001 | n/a |
| hybrid_tou | plain | 168 h | MILP (HiGHS) | 3 | 0 | 0.0% | 0.0% | 3 | 0.068 | n/a |
| hybrid_tou | plain | 168 h | Evolutionary, random start | 9 | 0 | 4.698% | 12.661% | 0 | 10.686 | 9.921% |
| hybrid_tou | plain | 168 h | Evolutionary, warm start | 9 | 0 | 2.765% | 4.74% | 0 | 10.648 | 2.759% |
| hybrid_tou | constrained | 24 h | Rule dispatch (battery first) | 3 | 0 | 41.692% | 66.088% | 0 | 0.0 | n/a |
| hybrid_tou | constrained | 24 h | MILP (HiGHS) | 3 | 0 | 0.0% | 0.0% | 3 | 0.013 | n/a |
| hybrid_tou | constrained | 24 h | Evolutionary, random start | 9 | 0 | 0.0% | 0.0% | 9 | 12.095 | 0.0% |
| hybrid_tou | constrained | 24 h | Evolutionary, warm start | 9 | 0 | 0.0% | 0.0% | 9 | 12.792 | 0.0% |
| hybrid_tou | constrained | 168 h | Rule dispatch (battery first) | 3 | 0 | 11.855% | 12.532% | 0 | 0.001 | n/a |
| hybrid_tou | constrained | 168 h | MILP (HiGHS) | 3 | 0 | 0.0% | 0.0% | 3 | 0.077 | n/a |
| hybrid_tou | constrained | 168 h | Evolutionary, random start | 9 | 0 | 4.361% | 8.653% | 0 | 12.24 | 1.955% |
| hybrid_tou | constrained | 168 h | Evolutionary, warm start | 9 | 0 | 1.948% | 3.686% | 0 | 11.729 | 2.02% |
| grid_tou | plain | 24 h | Rule dispatch (battery first) | 3 | 0 | 38.809% | 66.088% | 0 | 0.0 | n/a |
| grid_tou | plain | 24 h | MILP (HiGHS) | 3 | 0 | 0.0% | 0.0% | 3 | 0.011 | n/a |
| grid_tou | plain | 24 h | Evolutionary, random start | 9 | 0 | 0.0% | 0.001% | 9 | 12.493 | 0.001% |
| grid_tou | plain | 24 h | Evolutionary, warm start | 9 | 0 | 0.0% | 0.0% | 9 | 13.145 | 0.0% |
| grid_tou | plain | 168 h | Rule dispatch (battery first) | 3 | 0 | 7.105% | 7.718% | 0 | 0.001 | n/a |
| grid_tou | plain | 168 h | MILP (HiGHS) | 3 | 0 | 0.0% | 0.0% | 3 | 0.045 | n/a |
| grid_tou | plain | 168 h | Evolutionary, random start | 9 | 0 | 1.603% | 3.603% | 0 | 12.495 | 1.431% |
| grid_tou | plain | 168 h | Evolutionary, warm start | 9 | 0 | 1.18% | 2.678% | 1 | 12.304 | 1.431% |

On grid_tou the diesel unit is unavailable, so only the plain diesel variant is run there.

## Solver timeout probe

7-day joint water-energy MILP on grid_tou with a 0.05 s time limit:

```
{
  "raised": true,
  "message": "MILP did not produce a feasible schedule: Time limit reached. (HiGHS Status 13: model_status is Time limit reached; primal_status is None)",
  "optimality_proven": false,
  "runtime_s": 0.076
}
```

The run either stops with a clear error or returns a schedule marked as not proven optimal.

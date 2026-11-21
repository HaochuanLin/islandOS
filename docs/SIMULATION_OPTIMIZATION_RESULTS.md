# Simulation and optimization results (synthetic)

Status date: 2026-11-21. Everything in this note is a simulation result on
synthetic inputs. Nothing here is a measurement, a site study or a savings
claim. The time-of-use tariff (0.12 / 0.20 / 0.38 USD per kWh), the grid
limits and the stress bands are illustrative assumptions.

## What was added

| Area | Code | Experiment and results |
|---|---|---|
| Rule strategies vs joint water-energy MILP | `islandos_core/impact_scenario.py` (`compare_with_optimizer`, `flexible_load_study`) | `experiments/run_optimizer_impact.py`, `results/optimizer_impact/` |
| Evolutionary search vs MILP, timeout probe | `optimization/energy_system_optimizer.py`, `optimization/milp_dispatch_optimizer.py` | `experiments/run_optimizer_benchmark.py`, `results/optimizer_benchmark/` |
| Forecast stress and water-shortage stress | `islandos_core/stress_dispatch.py` | `experiments/run_stress_tests.py`, `results/stress_tests/` |
| Regression tests | `tests/test_optimizer_extensions.py` | 31 tests |

The site is the generic synthetic island (60 kW PV, 40 kW wind, 120 kWh
battery, 80 kW diesel, 15 kW RO, 80 m3 tank, 40 m3 of water a day) in three
cases: `island` (off-grid, diesel), `grid_tou` (80 kW grid on the tariff, no
diesel) and `hybrid_tou` (30 kW grid on the tariff plus diesel with a start cost).

## Model changes

- Joint MILP: terminal tank level, RO minimum production rate (semi-continuous),
  one aggregate flexible load (energy budget, availability window, power limit),
  tariff-look-ahead rule baseline, grid used before diesel, and binary
  "curtail allowed" variables so the MILP curtails only when the battery is
  charging at its limit or ends the step full. The last two make every solution
  replay exactly through `dispatch_energy_system`.
- A rule baseline that cannot serve the water demand is reported as infeasible
  instead of failing the solve.
- Evolutionary search: diesel ramp-down and minimum up/down times are handled by
  repairing each candidate; schedules the simulator still rejects are kept as
  infeasible candidates. `warm_start_from_rule_dispatch=True` seeds the search
  with the rule dispatch schedule.
- Impact scenario: `forecast_coordinated` strategy with seeded forecast error,
  `ro_min_run_hours`, and the `hybrid_tou` case.

## Findings

1. Off-grid island, 30 weeks: joint MILP 316.7 L of diesel per week against
   318.5 L for the fixed RO timetable (-0.7%). There is almost nothing to shift.
2. Time-of-use tariff, 30 weeks: joint MILP 134.5 USD per week against 239.5 USD
   for the fixed timetable (about -44%, range -37% to -49%, better in 30 of 30
   weeks). Simple surplus rule -15.5%, tariff look-ahead -10.1%, battery-only
   MILP -6.4%. No strategy had a water shortage. A 20 m3 tank reserve changes
   the MILP result by 0.1 USD per week.
3. The forecast-based rule does not beat the simple surplus rule, and is worse
   on tariff cases because it ignores prices.
4. Flexible load (40 kWh per day, 30 days): -4.4% daily cost on the island;
   on the tariff case -19.9% in total, of which -17.4% is battery scheduling.
5. Benchmark (30 instances): the MILP was proven optimal every time in under
   0.15 s. The evolutionary search took 1 to 13 s; on 168 h tariff cases it
   ended 1.2% to 4.7% above the MILP on average. With a random start and a hard
   "serve all load" constraint on the island it ended 33% to 44% above the
   optimum; the warm start removes that.
6. Forecast stress (10 weeks): the MILP changes its schedule in 10 of 10 weeks
   under low renewables with high demand. A plan made on the central forecast
   and held leaves 335 m3 (island) or 201 m3 (grid tariff) of water undelivered
   over 10 weeks when that stress case happens. Planning on the stress case
   removes the shortage and costs 16% more diesel or 52% more money in a
   normal week.
7. Water-shortage events (10 weeks): a low-renewable week causes no shortage
   for any strategy. An unforecast two-day +60% demand spike leaves 477 m3
   (island) undelivered for a held MILP plan, 278 m3 with a 20 m3 reserve, and
   0 m3 when the spike is forecast. Rule strategies that react to the tank
   level deliver all or nearly all of the water.

## Consequences

- Use the MILP as the planning reference. Keep the evolutionary search for
  multi-objective or non-linear questions.
- Do not run an optimized water plan open-loop. A tank reserve and regular
  re-planning with the real tank level are required before any field use.
- Scheduling value depends on the site: it needs wasted renewable power or
  time-varying prices.

## Limits

One-hour steps, single site, no battery ageing, one flexible load, no RO start
cost in the MILP, perfect one-week foresight unless a stress test says
otherwise. A diesel minimum stable output can make the MILP infeasible because
unserved load and dumping diesel surplus are not allowed.

## Reproduce

```
python experiments/run_optimizer_impact.py --seeds 30 --output-dir results/optimizer_impact
python experiments/run_optimizer_benchmark.py --input-seeds 3 --ea-seeds 3 --workers 2
python experiments/run_stress_tests.py --seeds 10
python -m pytest tests/test_optimizer_extensions.py -q
```

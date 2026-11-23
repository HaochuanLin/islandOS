# Annual cost trace for page 06

This directory holds the evidence behind the two annual numbers recorded for
page 06 (`Forecast Led Joint Resource Optimizer`):

- `186,150 kWh / 7,709.55 USD / 0.00 / 0 h`
- `186,150 kWh / 5,332.57 USD / 0.00 / 0 h`

Both are real outputs of the same page path. The difference is the synthetic
history window, not a different formula and not a tariff change.

## Files

- `h14.json` — one run anchored at `2026-11-22T14:00Z`; annual energy cost
  `7,709.553484 USD`.
- `h02.json` — one run anchored at `2026-11-22T02:00Z`; annual energy cost
  `5,332.569196 USD`.
- `sweep-h0-23.json` — all 24 anchor hours on `2026-11-22`; annual energy cost
  ranges from `4,548.683071` to `8,631.338277 USD`.

The annual load is `186,150 kWh` in every one of the 26 runs, and the annual
equipment operating cost and diesel run hours are `0.00` / `0 h` in every run.
The target 24-hour tariff sum is `3.91` in both the 14:00Z and 02:00Z runs, so
the `2,376.98 USD/year` gap is not a tariff rescaling. It comes from the daily
grid import: `138.387 kWh` at 14:00Z versus `93.688 kWh` at 02:00Z. Moving the
anchor moves the synthetic PV/wind ripple relative to the fixed daily load and
tariff shape, so the dispatch (and therefore grid import) changes while the load
total does not.

Each record's `identity` block re-adds the annual cost from the run summary's
daily parts, scaled by 365. Every non-grid component is zero in these runs, so
the identity reduces to `365 x grid energy cost`.

## Reproduce

From the repository root, with the same single-thread knobs used by the page
checks:

```powershell
$env:OPENBLAS_NUM_THREADS="1"; $env:OMP_NUM_THREADS="1"
.\.venv\Scripts\python.exe scripts\trace_annual_energy_cost.py --anchor 2026-11-22T14:00Z --out results\annual-cost-trace\h14.json
.\.venv\Scripts\python.exe scripts\trace_annual_energy_cost.py --anchor 2026-11-22T02:00Z --out results\annual-cost-trace\h02.json
.\.venv\Scripts\python.exe scripts\trace_annual_energy_cost.py --sweep-hours --date 2026-11-22 --out results\annual-cost-trace\sweep-h0-23.json
```

The script uses `islandos_core.demo_site_history.build_synthetic_site_history`
and the page's defaults, then runs the same `run_joint_optimizer` and
`annualise_run_summary` path as page 06. It does not keep a second copy of the
synthetic formulas. `tests/test_trace_annual_energy_cost.py` pins the 14:00Z and
02:00Z results.

## Scope

These runs use the synthetic demo site, not a field measurement. They show that
the two recorded numbers are reproducible from the code and that the gap is a
window-phase effect. They do not claim that either number is the "correct" annual
cost for a real site.

# Nan'ao emergency-resilience scenario: flexible RO load

> **Scenario-based Monte Carlo simulation, not field-validated performance.** This document records assumptions for an emergency-resilience pilot. It does not claim measured Nan'ao curtailment, verified site feasibility, or demonstrated operating savings.

## Purpose and asset boundary

The pilot explores using otherwise-curtailed wind power and valley-price electricity to support supplementary emergency freshwater reserves. It is **not intended to provide the full island's daily water supply**.

The primary case assumes the RO desalination unit is already installed and reusable. Its purchase CAPEX is treated as a sunk cost and set to RMB 0 for this scenario. Only operating costs belong in the economic screen: electricity, chemicals, membrane maintenance, and routine O&M. Annual O&M values in the economic script are draft screening assumptions, not site-verified quotations or accounting records.

## Core simulation assumptions

The default run uses 1,000 Monte Carlo scenario years and a fixed reproducibility seed defined by `DEFAULT_SEED` in `nan_ao_scenario.py`. The seed is not encoded in output filenames.

| Input | Assumption | Interpretation |
|---|---|---|
| Annual export-limitation events | Rounded triangular distribution, 4–12 events, mode 8 | Assumed potential surplus-energy events |
| Event duration | Lognormal, median 8 h, sigma 0.5, clipped to 2–24 h | Assumed event duration |
| Available surplus power | Triangular distribution, 5–50 kW, mode 25 kW | Assumed power during an event |
| RO rated power | 50 kW | Scenario rating; does not prove installed equipment |
| RO availability per event | Uniform from 0.85 to 1.00 | Assumed operational availability |
| Specific energy consumption | 4.0 kWh/m³ | Assumed energy per cubic metre |
| Simulation size | 1,000 runs by default | Simulated scenario years |

For each event, usable power is the lesser of sampled surplus power and the 50 kW RO rating. The event's theoretical water volume is event duration multiplied by usable power and RO availability, divided by specific energy consumption. Event volumes are summed to estimate a scenario-year yield.

## Three-scenario comparison

`nan_ao_three_scenarios.py` exposes `run_scenarios()` and reports:
- `wind_only`: simulated water yield from assumed curtailment events;
- `valley_price`: fixed annual screening water volume at the assumed valley electricity price;
- `hybrid`: the sum of valley-price water and simulated wind-curtailment water.

The report provides P05, median, and P95 annual water volumes, valley electricity cost, annual operating-cost screening bounds, unit operating-cost bounds, and an annual-supply population equivalent using 50 L/person/day. No RO purchase CAPEX is included.

The valley-water amount (33,650 m³/year), valley price (RMB 0.272/kWh), specific energy (4.0 kWh/m³), and annual operating-cost bounds (RMB 8,000–18,000) are explicit screening assumptions. They are not derived from measured hourly Nan'ao demand, wind output, or audited O&M records. The hybrid assumes valley-price and curtailed-wind windows do not overlap.

## Reproducible outputs

Run:

```bash
python nan_ao_scenario.py --runs 1000 --output-dir build/nan_ao
python nan_ao_three_scenarios.py --output-json build/nan_ao_three_scenarios/summary.json
```

The simulation writes `nan_ao_annual_runs.csv`, `nan_ao_percentiles.csv`, `nan_ao_summary.json`, and `nan_ao_sensitivity.csv`. The comparison script writes a JSON report to the requested path. Generated build outputs are intended as CI artifacts rather than committed results.

## Limitations and evidence required

- The wind model is an annual event-energy abstraction, not an hourly grid-flow model, measured curtailment reconstruction, or calibrated forecast.
- No measured local renewable-generation, load, export-limit, or curtailment time series is supplied.
- No actual RO installation, operational readiness, capacity, water quality, intake/outfall, storage, distribution, permits, or staffing has been verified.
- O&M costs are assumptions. Actual electricity, chemical, membrane, and routine-maintenance records are required for credible unit-cost estimates.
- The population figure is an annual-supply equivalent only; it does not prove safe delivery, continuous supply, or emergency accessibility.
- Results do not establish savings, ROI, emissions reductions, avoided outages, or commercial readiness.

Before field use, verify the existing RO asset and operating envelope, obtain measured hourly energy/load/curtailment records, confirm emergency storage and distribution, and replace draft O&M values with site evidence.

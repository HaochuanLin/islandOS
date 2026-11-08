# Multi-Resource Energy System Lab

The Streamlit page `pages/5_Energy_System_Lab.py` exposes the shared energy-system engine through a reproducible synthetic scenario.

## What the page demonstrates

- Adjustable PV and wind nameplate capacities and renewable profiles.
- Adjustable essential-load and grid-tariff multipliers.
- Optional battery storage with SOC and power limits.
- Optional diesel backup with minimum stable output, post-start ramp-up limit, and start/stop costs.
- Side-by-side comparison of the `battery_first` and `grid_first` rule-based policies.
- Hourly dispatch audit, energy-balance residual, unmet load, and downloadable CSV/JSON reports.

## Interpretation

The two policies are transparent dispatch baselines, not an optimizer. A lower estimated energy cost must be assessed alongside unmet load, diesel starts, renewable curtailment, and other operating indicators. The demo does not establish that either policy is universally preferable.

The built-in 24-hour profiles and all default tariff/cost values are synthetic illustrative assumptions. They are not measured customer data, supplier quotations, or evidence of savings. The diesel cost field is a non-fuel variable-cost assumption; fuel consumption and fuel-price modeling are available in the underlying engine but are not inferred by this page.

## Model boundaries

This page does not perform forecasting, global optimization, network power-flow analysis, equipment certification, lifecycle NPV/payback, or physical control. The model assumes a one-hour time step and uses the same deterministic energy-balance evaluator for both policies. Real site use requires validated time-series inputs, source provenance, confirmed installed equipment limits, and engineering review.

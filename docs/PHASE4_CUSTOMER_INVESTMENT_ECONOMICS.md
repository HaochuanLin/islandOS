# Phase 4 — Customer investment economics

The Customer Decision Dashboard includes an assumption-led lifecycle investment screen. It is deliberately separate from the 24-hour dispatch comparison.

## Required customer / supplier inputs

- Baseline annual energy bill and proposed annual energy bill, in the same currency and covering equivalent service.
- Installed equipment CAPEX from a supplier quote or customer estimate.
- Annual incremental O&M cost, defined as proposed O&M minus baseline O&M (positive means more cost; negative means a saving).
- Project evaluation life and discount rate.
- Optional replacement year and replacement cost.
- Optional residual value at the end of the evaluation period.

The dashboard does not annualize a single simulated day. Annual energy bills and supplier costs are explicit user-entered assumptions and are not independently verified.

## Calculations

- Annual energy-bill saving = baseline annual bill − proposed annual bill.
- Annual net operating benefit = annual energy-bill saving − incremental annual O&M.
- NPV = − upfront CAPEX + discounted annual net operating benefits − discounted replacement cost + discounted residual value.
- Simple payback = upfront CAPEX / annual net operating benefit, when the annual net benefit is positive.
- Discounted payback is interpolated within the year in which cumulative discounted cash flow becomes non-negative.
- Break-even annual energy saving is the annual saving required for NPV = 0 under the entered assumptions.
- Sensitivity varies annual energy-bill saving by ±20%, holding all other assumptions fixed.

## Decision gates and limitations

If the upstream dispatch comparison does not pass the service-equivalence gate, all lifecycle investment metrics are withheld. Negative NPV or no payback within the project life is shown as a negative screening result, not hidden behind a positive recommendation.

This is a simplified screening model. It does not currently model taxes, debt financing, escalation, inflation, degradation, tax credits, demand charges unless included in the annual bill, fuel-price volatility, stochastic replacement timing, salvage uncertainty, or project-specific accounting treatment. Users must avoid double-counting costs between annual energy bills and O&M. A positive screen is not a bankable business case or procurement recommendation; validate inputs with the customer, supplier, and qualified financial reviewer.

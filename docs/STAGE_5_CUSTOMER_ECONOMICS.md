# Stage 5 — Customer economics and decision evidence

## Goal

Turn the existing forecast-led decision dashboard and simplified investment screen into a more useful, auditable customer business-case workflow. This stage extends the existing feature; it does not claim verified customer savings or a bankable investment case.

## Delivered increment

- Replaces the constant annual-benefit assumption with explicit year-by-year cashflows.
- Adds separately entered annual energy-saving escalation and incremental O&M escalation assumptions.
- Calculates NPV from the annual cashflow schedule, simple and discounted payback from cumulative cashflows, and break-even year-one energy saving.
- Adds ±20% sensitivity on year-one energy-bill saving while holding the other assumptions fixed.
- Includes each year's energy saving, incremental O&M, replacement, residual value, net cashflow and discounted cashflow in the decision report.
- Preserves the service-equivalence gate: when the proposed schedule does not deliver equivalent service, all investment metrics and cashflows are withheld.

## Customer inputs and boundaries

Annual bills, CAPEX, O&M, replacement cost, residual value, project life, discount rate and escalation rates are user-entered assumptions. They must be supported by customer bills, supplier quotations or an explicitly identified estimate. Escalation rates are not forecasts unless independently sourced and validated. Avoid double-counting fuel, demand charges or maintenance already included in annual bills or O&M.

## Exit evidence

- Unit tests cover flat and escalated cashflows, NPV, payback, sensitivity, invalid assumptions and blocked non-equivalent service.
- The dashboard exports the complete annual cashflow schedule and its assumptions in JSON.
- Results remain labelled as screening estimates; a positive NPV is not procurement approval or verified savings.

## Not included

Taxes, debt financing, inflation accounting, demand-charge decomposition, fuel-price scenario distributions, equipment degradation, probabilistic replacement timing, supplier quote verification, site-specific forecast accuracy, customer usability evidence and live control remain separate work.

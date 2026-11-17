# Economic Value Framework

**Status:** FRAMEWORK IMPLEMENTED; CUSTOMER COST INPUTS AND WILLINGNESS TO PAY NOT VALIDATED

## 1. Required value equation

For one explicitly defined evaluation period and one currency:

`Gross Operating Benefit - Software Cost - Integration Cost - Maintenance Cost - Training Cost = Net Customer Value`

The Stage 8 impact layer implements this arithmetic in `islandos_core/impact_assessment.py`. All four commercial cost inputs must be finite, non-negative, and expressed in the same currency and evaluation period as gross operating benefit.

A cost from a different period (for example annual software subscription against a one-day modeled benefit) is rejected. Do not mix one-time and recurring costs without converting them to a common, explicitly stated evaluation period.

## 2. Gross operating benefit

`Gross Operating Benefit = Baseline Estimated Operating Cost - Candidate Estimated Operating Cost`

The current minimal case uses the canonical energy dispatch accounting, whose estimated energy cost includes supported grid and diesel energy costs, diesel fuel/start/stop costs, battery throughput cost, grid demand charge and grid export revenue.

This is a modelled difference, not a customer saving. It is only reported when:
- both policies use the same input series, equipment configuration and time horizon;
- critical and flexible service quantities are equivalent within the declared tolerance;
- both dispatch results pass the reporting-layer checks.

If these gates fail, gross operating benefit is `null` / withheld.

## 3. Net customer value

The function `calculate_net_customer_value()` subtracts:
- software cost;
- integration cost;
- maintenance cost;
- training cost.

The values are caller-supplied assumptions, not guessed defaults. The synthetic example supplies no commercial costs, so it deliberately returns no net customer value.

## 4. Existing lifecycle economics — reuse, do not duplicate

The repository already contains `islandos_core/investment_economics.py` and its tests. `evaluate_investment_economics()` supports customer-entered annual baseline/proposed energy costs, incremental O&M, upfront CAPEX, project life, discount rate, replacement and residual value, NPV, payback and sensitivity. It blocks all investment metrics when service equivalence is false.

That lifecycle screen remains the correct place for annual cashflow, NPV and payback calculations. Stage 8 does not create a second NPV, CAPEX recovery or payback engine. The 24-hour synthetic dispatch case is not annualized or passed into the annual investment screen.

The repository also retains `ro_costing.py` for RO-specific electricity, chemicals, variable O&M, runtime maintenance, start/stop and allocated fixed O&M. The present Stage 8 energy-policy example does not contain water service, so it does not call RO costing or report water economics.

## 5. Cost boundary and double-counting controls

Before a customer case is calculated:
1. Define currency and evaluation period.
2. Identify whether the baseline and candidate cover equivalent service.
3. Confirm which costs are already included in energy bills or operating cost.
4. Separate fuel, demand charges, battery degradation and export revenue where the dispatch model supports them.
5. Do not add the same fuel, maintenance or demand-charge cost again under commercial O&M.
6. Obtain software, integration, maintenance and training values from a customer, supplier quote or clearly labelled estimate.
7. Preserve the source, date, scope and confidence for each cost input.

If a metric is not supported by the model or input data, omit it or mark it unavailable. Do not replace missing data with zero.

## 6. Evidence classification

- **Synthetic model output:** generated from fixed illustrative inputs; tests software behavior only.
- **Customer-supplied input:** provided by a site/customer but not independently verified.
- **Supplier quotation:** traceable quote with date, scope, currency and validity.
- **Measured site evidence:** authorized, timestamped records with data-quality review.
- **Verified customer outcome:** independently reviewed before/after or replay evidence under a documented protocol.

These classes must not be collapsed into one "savings" claim.

## 7. Current limitations and next gates

- The current case compares two rule-based dispatch priorities, not an optimized candidate.
- Water service and emissions are not evaluated by this case.
- The commercial cost values are absent; net customer value is not calculated.
- A 24-hour horizon cannot establish annual savings.
- No customer cost, customer feedback, willingness-to-pay or verified benefit is recorded.

Next: connect a stable, independently audited optimization output only after the Engineering Track provides it; obtain authorized historical data; define equivalent-service metrics with the customer; and use the existing annual investment economics module for a separately evidenced annual case.

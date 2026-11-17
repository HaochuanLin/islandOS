# Stage 8 — Synthetic Customer Impact Case

**Status:** IMPLEMENTED AS A SMALL, REPRODUCIBLE SOFTWARE DEMONSTRATION; NOT CUSTOMER-VALIDATED  
**Data provenance:** Synthetic demo data — not measured site data  
**Run:** `python examples/synthetic_customer_impact_demo.py`

## 1. Purpose and scope

This case demonstrates how IslandOS can compare two existing energy dispatch policies on the same input series and equipment configuration, then produce a transparent impact summary.

It is intentionally a bounded comparison, not a new optimizer:
- Baseline: `grid_first` dispatch priority.
- Candidate: `battery_first` dispatch priority.
- Both policies are run through the existing `compare_energy_policies()` implementation in `islandos_core/energy_system.py`.
- The candidate is a rule-based alternative, **not an optimized schedule**.
- The case is 24 hourly synthetic steps. It is not annualized.

## 2. Synthetic scenario inputs

The example contains 24 hourly steps for:
- PV generation (kW);
- wind generation (kW);
- base electrical load (kW);
- flexible electrical load (kW);
- critical load (kW);
- grid electricity price (USD/kWh);
- grid availability.

The synthetic asset configuration includes:
- a battery with 60 kWh nominal capacity, 18 kW charge/discharge limits, declared initial/minimum/maximum SOC and efficiencies;
- a diesel generator with 30 kW rating, 5 kW minimum stable output, constant fuel use of 0.28 L/kWh, 70 L initial fuel, 80 L tank capacity and USD 1.30/L fuel price;
- a 50 kW grid import limit and a USD 7/kW demand-charge assumption for this scenario horizon.

These are test assumptions selected to exercise the accounting paths. They are not vendor specifications, site measurements, tariff quotations or recommended equipment sizes.

## 3. Comparison and evidence gates

The two policies receive the same `EnergySystemInputs` and `EnergySystemConfig`. The impact layer checks:
- matching time-step count and duration;
- matching total, critical and flexible demand;
- matching critical unmet energy and flexible-load shed energy;
- per-step energy-balance residual;
- grid import limit;
- battery charge/discharge power and SOC limits;
- diesel rated power, minimum stable output and configured ramp limits;
- non-negative reported service and curtailment quantities.

Gross operating benefit is withheld unless the baseline and candidate pass the reporting audit and the service-equivalence gate.

## 4. Metrics reported

Where present in the canonical dispatch output:
- estimated energy cost (grid energy, diesel variable cost, diesel fuel, starts/stops, battery throughput cost, demand charge, less export revenue);
- grid imports (kWh);
- diesel generation (kWh) and diesel fuel (litres only when a fuel model is configured);
- renewable generation, renewable energy not curtailed and renewable curtailment (kWh);
- critical-load unmet energy and calculated service reliability;
- flexible-load requested, served and shed energy.

Renewable energy "utilised" is defined here as renewable generation minus curtailment. It includes exports and battery charging; it is not synonymous with on-site renewable self-consumption.

## 5. Deliberately omitted metrics

- **Water service:** omitted because this paired dispatch API does not accept water demand, RO production or tank inventory. No water production or water-service claim is made.
- **Emissions:** omitted because this interface does not receive grid and diesel emissions factors.
- **Software, integration, maintenance and training costs:** not invented. Net customer value remains null until explicit cost inputs are supplied on the same currency and evaluation-period basis.
- **Annual savings, ROI, NPV and payback:** not calculated from this 24-hour scenario. Do not annualize this case.

## 6. How to interpret the output

A positive gross operating benefit means only that the candidate's modelled energy cost is lower than the baseline's for this exact synthetic horizon, after the stated modeled costs, and subject to the service and reporting audit gates. It is not a verified customer saving, a forecast of annual benefit, a purchase recommendation or evidence of willingness to pay.

If service equivalence or the reporting audit fails, the gross benefit is withheld. If commercial costs are absent, net customer value is withheld. Negative net value is allowed and must not be hidden.

## 7. Reproducibility and limitations

The example uses a fixed, literal input profile and deterministic rule-based policies. No random sampling, external data or new runtime dependency is required. The result should be reproducible under the repository's pinned runtime.

The reporting audit is deliberately scoped. It does not prove network power-flow feasibility, protection coordination, equipment transient behavior, water quality, fuel logistics, site-specific operating procedures or regulatory approval. An independent engineering review is required before any real-site evaluation.

**Validation status:** software behavior can be tested; customer impact and site performance remain **NOT VALIDATED**.

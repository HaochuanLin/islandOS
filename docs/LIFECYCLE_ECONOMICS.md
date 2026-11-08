# Lifecycle economics (scenario estimate)

`islandos_core.lifecycle_economics` adds a transparent project-level cashflow
model for comparing a baseline operating-cost scenario with a proposed project.
It reports annual energy-cost savings, fixed O&M, initial CAPEX, simple payback,
NPV, yearly cashflows, and optional battery replacement events.

## Inputs and interpretation

All monetary values must use the same user-supplied currency and price basis.
The caller supplies baseline and project annual energy costs, initial CAPEX,
project horizon, discount rate, and annual fixed O&M. The model does not perform
currency conversion or infer tariff, financing, tax, inflation, maintenance, or
equipment prices.

Battery replacement analysis is optional. If enabled, all four assumptions are
required: annual equivalent full cycles (EFC), cycle-life EFC threshold, installed
battery capacity, and replacement cost per kWh. A replacement event is charged
at the end of the year in which cumulative EFC reaches the supplied threshold.
The EFC threshold should be taken from the exact battery model's datasheet or
validated operating history; replacement cost should come from a customer quote
or clearly labeled estimate.

## Limitations

This is a screening-level scenario model, not a bankable financial model. Annual
energy costs are held constant; battery degradation does not feed back into
dispatch or energy costs. Calendar/temperature aging, financing, taxes, inflation,
salvage value, replacement downtime, demand charges not present in the supplied
annual energy cost, and uncertainty distributions are excluded. Results are
simulated estimates, not realized customer savings or guaranteed payback.

The module is UI-independent and can be called by Streamlit or desktop
application services. It does not alter or claim to optimize dispatch.

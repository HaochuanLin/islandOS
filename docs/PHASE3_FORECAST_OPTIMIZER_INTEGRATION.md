# Phase 3 — Forecast-to-resource coordination adapter

## Delivered seam

`islandos_core/forecast_optimizer_adapter.py` connects the Phase 2
`ForecastBundle` to the existing shared physical dispatch model and bounded
multi-resource policy optimizer.

The adapter requires four explicitly named forecasts:

| Phase 2 signal | Required unit | Physical meaning |
|---|---|---|
| `pv_power` | kW | Available PV generation |
| `wind_power` | kW | Available wind generation |
| `essential_load` | kW | Base electrical demand (treated as critical by the current model) |
| `electricity_price` | caller-declared, e.g. USD/kWh | Grid import price |
| `flexible_load` | kW, optional | Additive deferrable demand |
| `critical_load` | kW, optional | Critical subset of base/essential demand; cannot exceed it |

All forecast signals must have identical contiguous hourly target timestamps.
The adapter delegates timestamp, bounds, finite-value, and provenance checks to
the Phase 2 forecast planning contract. It does not silently convert units.
Negative electricity prices are preserved. Optional flexible and critical load
forecasts are mapped to the physical model's dedicated inputs; when omitted,
the model treats the entire essential load as critical and assumes no additional
flexible demand.

## Decision path

1. Phase 2 produces forecast values, bounds, model IDs, and source-history hash.
2. The planning contract validates signal names, units, target alignment, and bounds.
3. This adapter converts the three physical power forecasts into the existing
   `SignalForecastResult` interface and passes the tariff forecast separately.
4. The shared physical simulator evaluates energy balance under its existing
   battery-first and grid-first policies.
5. The optimizer reports candidate costs, unmet load, renewable curtailment,
   battery throughput, and an auditable recommendation with forecast provenance.

## Important limits

- The current policy optimizer compares two operating priorities; it is not a
  globally optimal arbitrary set-point optimizer.
- Forecast point predictions are used. Prediction bounds are preserved in the
  hand-off objects but are **not yet evaluated as robust/stress scenarios**.
- The energy model uses the existing supported asset constraints only. It does
  not prove voltage, frequency, protection, transient stability, or device safety.
- Cost outputs depend on supplied tariffs and equipment configuration; no
  customer savings are claimed without an equivalent-service baseline and
  site-authorized data.
- This is offline decision support. It does not issue commands to devices.

## Validation

The adapter tests cover a complete four-signal hand-off, negative tariff
preservation, unit mismatch rejection, availability horizon mismatch, optional
flexible/critical load mapping, critical-load bounds, four-case stress replay,
physical audit passage, optimizer execution, and forecast provenance.


## Customer economics guardrail

The adapter now compares the recommended policy with the explicit `grid_first`
reference policy using the same forecasts, tariffs, availability, and equipment
configuration. It reports a modeled cost delta only when total served energy,
total unmet energy, critical unmet energy, and flexible-load shedding are all
equivalent within tolerance. Otherwise the cost-reduction field is null and the
result explicitly withholds a savings claim. The reference is a modeled policy,
not measured site operation or a customer's actual bill.


## Joint battery–diesel schedule search

For sites with both a configured battery and diesel generator, the adapter now
exposes `optimize_forecasted_resource_schedule`. It forwards Phase 2 forecasts
into the existing mixed real/binary evolutionary optimizer and supplies the
conservative forecast envelope, grid-outage, and combined-stress cases as
additional scenarios. The same candidate schedule is replayed in all cases;
the optimizer aggregates objectives by worst case and can enforce explicit
maximum total/critical unmet-energy and terminal battery SOC constraints.
Diesel availability is mandatory. The optimizer rejects configurations whose
ramp-down or minimum up/down constraints it cannot safely generate. It remains
a seeded heuristic, not a global optimum or device controller.


## Site asset and operating-state gate

The Phase 3 branch now includes the versioned asset registry, provenance-bearing
parameters, confirmed hard-constraint readiness, declared electrical topology
validation, and timestamped operational-state checks. The new
`build_site_energy_configuration` helper fails closed unless static asset
readiness and fresh, confirmed online-state readiness both pass. It then maps
the confirmed installed capacities and supported constraints into the shared
energy-system configuration. A declared topology is checked structurally only;
this is not load-flow, protection, electrical-safety, or equipment certification.
A readiness snapshot does not predict future availability; the dispatch horizon
still requires explicit availability inputs.

# Stage D — Price-aware RO planning slice

## Delivered

`islandos_core.water_dispatch.build_price_aware_ro_schedule` adds a transparent, deterministic look-ahead heuristic for scheduling RO production against a supplied electricity-price forecast. It:
- compares each tariff with the cheapest tariff in a configurable look-ahead window;
- uses locally cheaper periods to gradually build tank inventory for upcoming demand;
- prioritizes current water service and the declared reserve;
- enforces RO hourly production capacity and tank capacity;
- returns hourly production, tank inventory, RO kW, energy and modeled energy cost;
- marks the result as offline-only with `device_write_authorized=false`.

## Scope and limitations

This is a first price-aware scheduling primitive, not a global optimum and not yet wired into the forecast-to-resource adapter or Streamlit customer workflow. It uses the supplied tariff and water-demand series directly; it does not yet co-optimize RO, battery, diesel, grid import/export, and process operating modes in one mathematical program. The current forecast adapter continues to use the existing reserve-constrained just-in-time RO policy.

The heuristic assumes a constant RO specific energy and a single usable-water tank. Startup/shutdown, minimum run time, CIP, brine/recovery constraints, water quality, variable pump efficiency, demand charges, and tariff uncertainty are outside this slice.

## Validation

`tests/test_water_dispatch.py` covers low-price pre-production, hourly RO capacity, tank bounds, aligned series, invalid numeric inputs, and the non-command boundary. Synthetic unit tests validate software behavior only; they do not establish real-site savings or plant performance.

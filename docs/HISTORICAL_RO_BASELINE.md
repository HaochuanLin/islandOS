# Historical RO baseline data contract

## Customer value

Before asking a plant to trust an optimizer, IslandOS should first reconstruct what
the plant actually spent during a known operating period. This makes the first
deliverable auditable: measured energy, measured water, supplied tariff and
explicitly entered operating-cost rates.

## CSV format

One row per fixed-duration interval. Required columns:

| Column | Unit | Meaning |
|---|---:|---|
| `timestamp` | ISO-8601 | Interval start; include timezone when available |
| `energy_kwh` | kWh | RO electricity consumed during this interval |
| `water_produced_m3` | m³ | Permeate produced during this interval |
| `electricity_price_per_kwh` | currency/kWh | Applicable energy tariff for this interval |
| `runtime_hours` | h | RO runtime during this interval |
| `start_events` | count | Number of RO start events in this interval |

Set `dt_hours` to the duration represented by each row. Optionally provide
`expected_interval_hours` to reject missing or irregular timestamps. The parser
does not interpolate gaps, fill missing values, or annualize short periods.

## Cost inputs

The caller must separately provide currency, chemical cost per m³, variable O&M
per m³, maintenance per runtime hour, start/stop cost per event, and fixed O&M
allocation assumptions. Do not enter zero merely because a cost is unknown:
zero means a confirmed zero only if the customer says so.

## What the first version can and cannot prove

It can calculate the supplied period's electricity, chemical, variable O&M,
maintenance, start/stop and allocated fixed-O&M costs, with a cost per m³.

It cannot by itself establish full plant cost or savings. Demand charges, taxes,
backup fuel, renewable-energy opportunity cost, brine handling, water-quality
penalties, membrane replacement and other missing items must be added where
material. A historical cost report is not an optimized counterfactual.

## Commercial validation gate

Do not sell a savings claim until IslandOS can compare a candidate schedule with
the customer's actual baseline over the same time horizon, delivered water
quantity and quality, reservoir/service conditions, tariff, and equipment
constraints. Then calculate net customer benefit after software, integration,
and operating-change costs. If net benefit is not positive and repeatable, the
customer has no economic reason to buy.


## Streamlit workflow

The app includes a **Historical RO baseline** page. A customer can upload the CSV,
enter confirmed cost rates and interval duration, optionally enforce regular
timestamp spacing, inspect the actual-period cost breakdown, and export a CSV
report. The upload is processed in the current app session; it is not sent to a
plant controller or stored as a verified customer record. The page labels
customer-supplied measurements as not independently verified and does not
produce an optimizer counterfactual or savings claim.

# Phase 4 — Customer data onboarding

The Customer Decision Dashboard now accepts an optional customer CSV instead of relying only on its synthetic example.

## Required CSV schema

One row per hour, in strictly increasing contiguous UTC instants:

| Column | Unit / meaning |
|---|---|
| `timestamp_utc` | ISO-8601 timestamp including timezone, e.g. `2026-01-01T00:00:00Z` |
| `pv_power_kw` | PV generation / available power, kW; non-negative |
| `wind_power_kw` | Wind generation / available power, kW; non-negative |
| `essential_load_kw` | Essential electrical load, kW; non-negative |
| `electricity_price_per_kwh` | Electricity tariff in the currency selected in the dashboard; negative prices are allowed |

At least 72 hourly observations are required. The adapter rejects missing columns, duplicate headers, naive timestamps, irregular or duplicate timestamps, non-numeric/non-finite values, and negative physical power/load values. It does not fill missing rows, infer timezone, convert units, or independently verify uploaded data.

## Provenance

- The dashboard records the SHA-256 hash of the exact uploaded CSV and the normalized forecast-history hash separately.
- The downloadable decision report records the data source label, row count, equipment capacity assumptions, battery assumptions, and objective weights.
- The source filename is shown as provenance metadata; the raw CSV is not intentionally written to the project workspace by this page.
- Public hosted uploads are processed by the Streamlit app server. Upload only data the user is authorized to share; redact sensitive site/customer details where possible.

## Limits

CSV data is user-supplied and not independently verified. The upload path supports hourly PV, wind, essential load, and tariff histories only; it does not yet ingest asset registers, topology, confirmed operating states, fuel inventory, or all Phase 3 equipment constraints. Capacity and battery settings remain user-entered screening assumptions. Forecast and dispatch results remain offline decision support, not live control or verified savings.

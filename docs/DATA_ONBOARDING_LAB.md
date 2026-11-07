# IslandOS Data Onboarding Lab

## Purpose

The Data Onboarding Lab is a Streamlit experiment over the UI-independent
`islandos_core.onboarding` service. It tests whether a new operator can import
an existing energy time series with minimal manual work while preserving
traceability and refusing unsafe assumptions.

## Current scope

- UTF-8 CSV and UTF-8-with-BOM input.
- Excel `.xlsx` worksheet extraction with bounded archive expansion and row scanning, visible-sheet preference, automatic header-row detection, and cached formula values only.
- Original workbook SHA-256 provenance; formulas are never evaluated. Naive Excel timestamps require an explicit IANA timezone, and ambiguous/nonexistent daylight-saving times are rejected.
- Automatic recognition of common timestamp and energy-signal headers.
- Explicit, limited unit conversion (W to kW and MW to kW).
- Manual mapping for unrecognized source columns.
- Explicit unit confirmation when the source header does not state a unit.
- Detection of malformed timestamps, duplicate/non-monotonic timestamps,
  missing/non-numeric/non-finite values, negative power/energy-like signals,
  out-of-range battery SOC, and sampling-interval mismatches.
- Exact source-file SHA-256, file name, source classification, and ingestion time.
- Task-specific screening gates for exploration, forecasting baselines, and
  dispatch-optimization readiness.
- JSON export of the import review and readiness result.

## Safety and trust behavior

- The importer never fills missing values, clips values, removes outliers, or
  silently repairs timestamps.
- A recognized column name does not prove sensor calibration or measurement
  accuracy.
- Missing units require operator confirmation; ambiguous unit conversions fail.
- Multiple source columns mapping to one canonical signal block the import.
- A structurally valid import does not mean every analysis task is ready.
- Dispatch optimization screening requires explicit confirmation of asset
  limits, critical-load policy, and grid-import limits.
- Readiness is not a safety approval and does not authorize hardware control.
- Files are processed in the Streamlit session; this lab does not create a
  persistent customer workspace or send data to a device.

## Canonical signals in this first CSV / Excel path

| Canonical field | Unit |
|---|---|
| `load_kw` | kW |
| `pv_power_kw` | kW |
| `wind_power_kw` | kW |
| `grid_import_kw` / `grid_export_kw` | kW |
| `battery_charge_kw` / `battery_discharge_kw` | kW |
| `battery_soc_pct` | % |
| `tariff_per_kwh` | currency/kWh |
| `diesel_power_kw` | kW |
| `diesel_fuel_lph` | L/h |
| `temperature_c` | degC |

## Run locally

```bash
streamlit run pages/3_Data_Onboarding_Lab.py
```

The core service can be imported without Streamlit:

```python
from islandos_core.onboarding import inspect_csv_bytes, evaluate_task_readiness

report = inspect_csv_bytes(
    csv_bytes,
    source_type="customer_provided",
    source_name="site-export.csv",
)
readiness = evaluate_task_readiness(report, "forecasting")
```

## Known limitations and next increments

This is an initial generic CSV and Excel onboarding path, not a universal importer.
PDF/OCR extraction, device discovery, Modbus/OPC UA/API connectors,
asset-constraint forms, multi-file joins, timezone inference, and persistent
local customer projects are not implemented by this page yet. The next
increments should be added as independent adapters/services and tested here
before any desktop UI adopts them.

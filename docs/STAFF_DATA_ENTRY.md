# Staff data-entry workflow

## Purpose

`tools/site_data_entry.html` is a small, local browser form for a site operator to enter or import hourly observations and export a CSV plus a provenance sidecar. It exists because IslandOS currently has no verified Nan'ao or other island operations dataset. It does **not** synthesize observations, call a remote service, run dispatch, or prove that a measurement is correct.

## How staff use it

1. Download or clone the repository, then open `tools/site_data_entry.html` in a modern browser. It can be opened directly from disk and does not require a server.
2. Enter the site name, source type, operator/team if appropriate, timezone offset, interval, period description, and source reference.
3. Add rows manually, add empty rows for a known period, or import a CSV with the expected column names. Empty rows are intentionally not filled with zeros.
4. Check every timestamp and unit against the original meter/export. The form requires finite, non-negative values and strictly increasing timestamps at the selected interval.
5. Choose **Check data**. If checks pass, choose **Download CSV**. The form also downloads a JSON metadata sidecar; keep both files together.
6. Run the repository's stricter CLI quality gate before any experiment.

For hourly data with real measurements, for example:

```bash
python data_quality.py path/to/site_hourly_input.csv --source-type measured --interval-minutes 60 --json
```

For public, forecast, or synthetic data, set `--source-type` to the matching type. For a 30-minute series use `--interval-minutes 30`. The CLI returns a non-zero exit code when the CSV is invalid.

## CSV fields and units

| Field | Meaning | Unit |
|---|---|---|
| `timestamp` | Time of the interval, including UTC offset | ISO-8601 |
| `wind_kw` | Average wind generation during the interval | kW |
| `pv_kw` | Average PV generation during the interval | kW |
| `critical_load_kw` | Average essential electrical load | kW |
| `water_demand_m3` | Water demand for the interval | m³ per interval |
| `cooling_demand_kw_th` | Average cooling demand | kW thermal |

The schema is intentionally small. It does not currently collect battery state of charge, freshwater-tank level, equipment status, backup-generator availability, grid export limits, tariffs, water quality, or RO start/stop constraints. Those values must not be inferred from this CSV; a later schema revision should add them explicitly if a validated model needs them.

## Provenance and data-handling rules

- Keep the original source file/export and record its name, source link or meter identifier, reporting period, units, and timezone.
- Do not label an estimate as `measured`. Use `public`, `forecast`, or `synthetic` when appropriate.
- Do not replace missing or invalid measurements with zero. Investigate gaps with the data owner; if a gap cannot be resolved, preserve the original file and record the limitation rather than silently interpolating it.
- A format check is not a sensor calibration or physical plausibility review. Staff should compare values with meter ranges, outages, and operating logs.
- The form works locally and has no login, shared database, or server-side access control. Store and transfer exported files according to the site owner's data-handling policy. Do not enter credentials or personal data.
- The CSV and sidecar are not automatically uploaded to GitHub. Do not commit confidential operational data to a public repository.

## Current limitation

The form is an **input-capture prototype**, not a complete staff operations console. It does not yet save submissions to a central service, enforce user roles, execute the dispatch engine, or generate an operational recommendation. The current optimizer is a separate offline step, and its simplified outputs remain decision-support simulations rather than a validated operating schedule.

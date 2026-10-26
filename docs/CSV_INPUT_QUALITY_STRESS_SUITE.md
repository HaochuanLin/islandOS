# CSV input-quality stress suite

The input-quality suite checks the rolling-dispatch CSV parser against one valid synthetic baseline and 14 deliberately malformed fixtures. It is designed for the no-site-data development phase: malformed cases are created from a generated CSV, not from field measurements.

## Run

```bash
python -m experiments.run_input_quality_stress_suite --hours 4
```

The default writes `build/input-quality-stress/report.json`. The suite requires at least two rows so timestamp-order and hourly-gap faults can be exercised. It records each fixture's SHA-256, expected/actual rejection, parsed row count, and any parser error. The report itself includes a deterministic digest and explicit simulation-only flags.

## Faults covered

- Empty input and header-only CSV.
- Missing required column.
- Blank, malformed, timezone-naive, duplicate, out-of-order, or non-hourly timestamps.
- NaN/infinite surplus values.
- Negative water demand.
- Nonnumeric cooling demand.
- Blank optional forecast-water demand when that column is present.

The valid baseline is expected to parse; all other cases are expected to fail. A failed expectation makes the CLI exit nonzero. This is a regression test for the current parser contract, not a claim that the parser can detect every possible bad sensor or measurement.

## Limits

These fixtures establish only that the tested input conditions are accepted or rejected as expected. They do not authenticate the source of a CSV, validate units against a real site, measure forecast accuracy, or prove physical safety. Before using measured data, preserve its source, license/permissions, units, timezone, interval definition, missingness audit, and provenance separately.

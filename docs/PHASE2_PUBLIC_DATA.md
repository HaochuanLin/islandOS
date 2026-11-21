# Phase 2 — Public historical data adapter

## Purpose

`islandos_core/opsd_adapter.py` provides a strict, local-file adapter for the hourly Open Power System Data (OPSD) time-series package. It converts a selected region's public historical series into the same aligned UTC timestamps, numeric history mapping, and explicit units expected by the generic IslandOS forecast engine.

This is a reusable data-ingestion component, not an IslandOS site integration. No competition-specific scenario or site assumptions are involved.

## Source and limitations

- Dataset: Open Power System Data, Time series package, version 2020-10-06.
- Source page: https://data.open-power-system-data.org/time_series/2020-10-06/
- Coverage: 32 European countries; the package version documents data from 2015 to mid-2020.
- Available signals include electricity load, day-ahead prices, solar generation, and wind generation.
- Data is aggregated by country, control area, or bidding zone; it is not representative of an individual facility or microgrid.
- The package is historical and must not be described as live/current market data.
- Preserve the package attribution and check the source's per-variable provenance and license conditions when redistributing derived datasets.

OPSD's published field documentation specifies UTC timestamps and names the underlying load, solar, wind, and day-ahead price fields. The adapter accepts a local 60-minute single-index CSV; it does not download the 124 MB source file automatically. It records two different SHA-256 values: the exact input file's byte-level digest and a normalized digest of the selected region/signals/time slice.

## Supported mapping

| IslandOS signal | OPSD source field | Unit |
|---|---|---|
| `load` | `{region}_load_actual_entsoe_transparency` | MW |
| `solar` | `{region}_solar_generation_actual` | MW |
| `wind` | `{region}_wind_generation_actual`, or onshore field fallback | MW |
| `price` | `{region}_price_day_ahead` | EUR/MWh |

The total-wind field is preferred when present. If it is absent, the adapter uses the onshore generation field and records the exact source column. It does not add onshore and offshore values together, avoiding accidental double counting.

Use a region code such as `AT` or `DE` only when the corresponding columns exist in the downloaded file. Some regions do not publish every signal. Select a smaller `required_signals` tuple when needed. Water demand is not present in this source and is not synthesized.

## Data-quality contract

- Reads only the selected columns and timestamp from the local CSV.
- Hashes and parses the same opened file descriptor, then re-checks the byte-level digest after ingestion; if the source changes during the read, ingestion fails rather than returning mismatched provenance.
- Normalizes timestamps to timezone-aware UTC.
- Supports the compact timestamp format documented by OPSD and ISO-8601 UTC variants.
- Supports an optional half-open UTC time window: `[start_utc, end_utc)`.
- Rejects missing columns, missing values, non-numeric or non-finite values, negative physical generation/load values, duplicate or out-of-order timestamps, and gaps in the selected hourly sequence.
- Does not impute, interpolate, resample, or silently drop incomplete rows.
- Preserves negative day-ahead prices.
- Returns source version, exact source-column mapping and attribution, plus both `source_file_sha256` (the exact CSV bytes) and `selected_history_sha256` (the normalized selected observations used by the run).
- Returns immutable timestamp/history/unit/source-column collections so callers cannot mutate selected observations after their digest has been computed.

A caller should choose a complete contiguous time range before passing the returned history to `forecast_signals`. The forecast engine independently enforces its own minimum-history requirement.

The generic `ForecastRequest` is an immutable point-in-time input snapshot. It copies caller-provided history and target-timestamp iterables into tuples before validating them, so later mutation of an input list cannot silently change the observations or forecast horizon after validation. The request contains historical observations and future timestamps only; holdout actuals belong in a separate scoring step and must never be passed into forecast generation. Downstream dispatch code should consume the typed forecast result and its declared unit/time axis, not mutate or reconstruct the request history.

## Example

```python
from islandos_core.opsd_adapter import load_opsd_singleindex_csv
from islandos_core.forecast_engine import forecast_signals

dataset = load_opsd_singleindex_csv(
    "time_series_60min_singleindex.csv",
    "AT",
    required_signals=("load", "solar", "wind", "price"),
)

bundle = forecast_signals(
    timestamps=dataset.timestamps,
    history=dataset.history,
    units=dataset.units,
    horizon=24,
    non_negative_signals=("load", "solar", "wind"),
)
print(dataset.source_version, dataset.source_file_sha256, dataset.selected_history_sha256)
```

## Reproducible command-line evaluation

After downloading the OPSD 60-minute single-index CSV from the source page, run:

```bash
python examples/phase2_opsd_backtest.py \
  --csv ./time_series_60min_singleindex.csv \
  --region AT \
  --signals load solar wind price \
  --horizon 24 \
  --rolling-validation \
  --rolling-horizons 1 6 24 168 \
  --max-rolling-folds 168
```

The JSON report includes the exact source columns, selected region, history window, observation count, raw `source_file_sha256`, normalized `selected_history_sha256`, baseline comparisons, holdout metrics, and forecast output. It now contains two clearly separated evaluation paths:

- **Legacy Phase 2 engine:** persistence, 24-hour seasonal-naive, and Ridge autoregression, including its original chronological holdout and optional evenly sampled expanding-window comparison (up to 168 folds per horizon).
- **Canonical prediction service:** the current `forecast_site_signals(...)` / `PredictionEngine` path used by the mainline workflow. It reports the selected model and rolling-origin candidate metrics for the same public history. The built-in candidates include persistence, seasonal-naive, recent mean, and linear trend.

The canonical path selects its candidate using the same rolling-validation horizon and fold cap as the requested forecast horizon, propagating that cap through forecast_site_signals and ForecastService into PredictionEngine; the untouched final holdout is scored separately. It records explicit unit scaling from OPSD MW to IslandOS kW (×1000) and EUR/MWh to EUR/kWh (×0.001). Its `source_file_sha256` identifies the exact downloaded CSV bytes; `selected_history_sha256` identifies the normalized rows after region, signal, and time-window selection. The latter is intentionally independent of unrelated CSV columns and formatting, while the former changes whenever the source file bytes change. These are unit conversions only; country-level values are not scaled into facility values. Its candidate reports include aggregate and per-fold MAE, RMSE, signed bias (prediction minus actual), WAPE where defined, each fold's training/validation sample counts, and exact UTC training/validation boundaries. The report records the initial-history interval, first validation timestamp, last scored timestamp, and each fold's train/validation start and end instants so the scored window can be independently audited against the source-data digest. Add `--rolling-validation` to evaluate both paths at the requested horizons. The rolling report is evidence for model review, not automatic model promotion. Use `--start-utc` and `--end-utc` to restrict ingestion to a chosen contiguous interval, or omit unavailable signals with `--signals`. The legacy Ridge evaluator now samples up to 168 complete folds per signal/horizon across the full chronology, including the first and last complete blocks. The CLI records each fold's original index, training/validation sample counts, and UTC boundaries. The public-data workflow requires at least 912 contiguous observations (a 168-hour final holdout plus 72 initial rows and four 168-hour validation blocks) so a 168-hour horizon has at least four complete validation blocks. The canonical rolling evaluator uses only the pre-holdout training prefix; the GitHub OPSD evidence workflow uses a separate 168-hour final chronological holdout. To keep long public histories computationally bounded, it evaluates at most 168 complete folds per signal/horizon by default, sampled deterministically and evenly across the available chronological blocks with the first and last blocks always included. Set `--max-rolling-folds` (2–1000) to change this cap. Both rolling paths distinguish all available complete folds, evaluated folds, skipped complete folds, scored samples, skipped validation samples, and any incomplete trailing samples; it also records the exact original fold indices and UTC boundaries. Every sampled fold trains only on observations before its own validation block. This is a reproducible temporal sample of the available rolling origins, not an exhaustive score over every hour.

For the canonical prediction-service report, `--horizon` also sets one final chronological holdout: the last N observations are removed before model selection, rolling-origin candidate evaluation, and empirical error-band calibration. Every registered canonical candidate is now forecast from the same pre-holdout history and scored on the exact same final timestamps. The report exposes `holdout_candidate_evaluations.models`, including model/version, whether it was selected by the training-only process, per-candidate MAE/RMSE/signed bias/WAPE, and timestamped forecast values. Candidate output failures are recorded under `excluded_candidates`. The actual holdout values are used only to calculate these scores; they cannot affect candidate forecasts or selection. The existing `holdout_metrics` field remains the selected model's score for compatibility. At least 72 training observations plus N holdout observations are required. This is a single historical holdout, not repeated validation across seasons, sites, or operating regimes, and the same-block comparison is descriptive rather than a deployment promotion gate. The legacy forecast report remains a separate evaluation path; do not conflate its metrics with the canonical final-holdout scores.

Running the CLI on a real downloaded OPSD file is still required before claiming public-data backtest results. Synthetic adapter/CLI tests verify software behavior only.

## Attribution

Open Power System Data. 2020. Data Package Time series. Version 2020-10-06. https://doi.org/10.25832/time_series/2020-10-06. (Primary data from various sources; see OPSD source documentation.)

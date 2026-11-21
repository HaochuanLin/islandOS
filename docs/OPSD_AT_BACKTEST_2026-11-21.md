# First OPSD public historical backtest — Austria (AT)

**Run date:** 2026-11-21  
**Repository commit:** 7d86952f483a91056a68e6aec7e28a1396fe1c4c  
**Workflow:** [OPSD public energy forecast backtest](https://github.com/HaochuanLin/islandOS/actions/runs/44867978251)  
**Evidence artifact:** [Download report bundle](https://github.com/HaochuanLin/islandOS/actions/runs/44867978251/artifacts/14692297818)  
**Artifact SHA-256:** f910e83493dababb6402e1414cedbaee2104464b8e50583c0f5b7976edb3fa33  
**Artifact retention:** GitHub reported expiry on 2026-12-21.

## Evidence classification

This run successfully downloaded the official OPSD Time series package (version 2020-10-06) in a GitHub-hosted runner and completed the legacy and canonical forecast evaluations.

- Evidence class: public historical regional aggregate.
- Region: Austria (AT).
- Site telemetry: no.
- Synthetic values in the reported backtest: no.
- Customer savings, site accuracy, deployment accuracy, or operational reliability claimed: no.

Source: [OPSD Time series 2020-10-06](https://data.open-power-system-data.org/time_series/2020-10-06/). The CSV raw SHA-256 is 6a7f2bc571314cbf9c321cc03437691cd4be95c3a6f075e60ff99e8035c704c8; the selected normalized history SHA-256 is 56bfbc81fb97094a435cb0ba612f0fe70bcf1a369ef1a903977891f50432fcd5.

## Selected data window and coverage

The workflow scanned 50,401 CSV rows. It found 32,790 rows where all four requested signals were present, finite, and physically valid. The longest contiguous hourly interval containing all four signals had 8,734 observations:

[2015-03-29T04:00:00Z, 2016-03-27T02:00:00Z)

This is the longest qualifying interval found by the workflow, not the full OPSD package history. Of the scanned rows:

| Row category | Count |
|---|---:|
| All rows scanned | 50,401 |
| Complete rows across all four signals | 32,790 |
| Complete rows outside the selected contiguous interval | 24,056 |
| Incomplete or invalid rows | 17,611 |
| Selected contiguous observations | 8,734 |
| Total rows outside the selected interval | 41,667 |

No missing observations were imputed, interpolated, resampled, or silently bridged.

Selected source columns:

| Signal | OPSD column | Source unit | Canonical IslandOS unit |
|---|---|---|---|
| Load | AT_load_actual_entsoe_transparency | MW | kW |
| Solar | AT_solar_generation_actual | MW | kW |
| Wind | AT_wind_onshore_generation_actual | MW | kW |
| Price | AT_price_day_ahead | EUR/MWh | EUR/kWh |

The selected wind field is the onshore fallback column, not a claim of total Austrian wind generation. Unit conversion is explicit (MW × 1,000 to kW; EUR/MWh × 0.001 to EUR/kWh). It does not scale country-level values into a facility.

## Canonical 168-hour rolling-origin results

Candidate selection used only the pre-holdout training history. The 168-hour horizon used 50 complete rolling folds, scoring 8,400 forecast points per signal. The following table shows the candidate selected by aggregate MAE and its corresponding rolling-origin metrics.

| Signal | Selected candidate | MAE | RMSE | Bias (prediction − actual) | WAPE |
|---|---|---:|---:|---:|---:|
| Load (kW) | Seasonal Naive | 754,119.76 | 1,133,020.77 | +302,665.71 | 11.02% |
| Solar (kW) | Seasonal Naive | 21,022.14 | 43,143.76 | −538.57 | 21.92% |
| Wind onshore (kW) | Recent Mean | 484,274.24 | 625,082.71 | +44,045.48 | 85.42% |
| Day-ahead price (EUR/kWh) | Seasonal Naive | 0.0076094 | 0.0104469 | +0.0025606 | 25.04% |

The wind result is weak: its rolling WAPE is 85.42%, and the selected model's MAE is only modestly better than Persistence. It should not be treated as a reliable wind forecast for operational scheduling without further validation or improved features/models.

## Canonical final 168-hour holdout

The final holdout is the last 168 observations, [2016-03-20T02:00:00Z, 2016-03-27T01:00:00Z] inclusive. It was excluded from candidate selection, rolling-origin evaluation, and interval calibration. Every candidate was forecast from the same pre-holdout history and scored on the same holdout timestamps.

| Signal | Selected candidate | MAE | RMSE | Bias (prediction − actual) | WAPE |
|---|---|---:|---:|---:|---:|
| Load (kW) | Seasonal Naive | 916,982.14 | 1,079,269.43 | −736,005.95 | 12.36% |
| Solar (kW) | Seasonal Naive | 15,166.67 | 27,640.12 | −3,226.19 | 12.87% |
| Wind onshore (kW) | Recent Mean | 341,447.92 | 478,406.29 | −273,470.24 | 68.77% |
| Day-ahead price (EUR/kWh) | Seasonal Naive | 0.00444643 | 0.00519673 | −0.00073214 | 18.61% |

In this one-week holdout, the candidate selected using only pre-holdout rolling-origin data also had the lowest holdout MAE among eligible candidates for each of the four signals. This is a descriptive result from one region and one final block, not a model-promotion or deployment gate. Load and wind show material negative holdout bias; that risk must be considered before downstream optimization consumes these point forecasts.

## Horizon-dependent candidate selection

The best candidate by rolling-origin MAE varied by both signal and horizon:

| Signal | 1 hour | 6 hours | 24 hours | 168 hours |
|---|---|---|---|---|
| Load | Persistence | Seasonal Naive | Seasonal Naive | Seasonal Naive |
| Solar | Seasonal Naive | Seasonal Naive | Seasonal Naive | Seasonal Naive |
| Wind onshore | Persistence | Persistence | Persistence | Recent Mean |
| Day-ahead price | Persistence | Seasonal Naive | Seasonal Naive | Seasonal Naive |

This supports signal- and horizon-specific evaluation rather than assuming one forecasting model is best for every resource and lead time. It does not establish that the chosen models are suitable for a specific facility.

## Validation status and remaining gates

The workflow completed all steps successfully: official CSV download, contiguous-window selection, legacy and canonical evaluations, provenance/coverage assertions, evidence summary generation, and artifact upload.

The same commit also passed the repository's Python unit tests (1,150 passed, 2 skipped, 578 subtests passed, 16 warnings) and the other six CI workflows, including dependency audit, container smoke test, Windows gateway build, RO/integration tests, and the existing Nan'ao regression check.

This is the first verified real public-historical OPSD backtest in this Phase 2 branch. It does **not** complete Phase 2 quality gates. Remaining work:

1. Repeat the same protocol on at least one additional OPSD region with complete, documented signal coverage.
2. Add more than one untouched final test block spanning different seasons/operating regimes.
3. Investigate wind forecast error and load/wind holdout bias before defining forecast-risk handling for optimization.
4. Establish candidate qualification criteria across regions and seasons; do not promote a model based only on this one run.
5. Keep public regional aggregate data distinct from measured site telemetry and never infer customer savings from forecast MAE.

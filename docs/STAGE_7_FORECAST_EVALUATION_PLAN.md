# Stage 7 — forecast and optimization evidence

**Status:** evaluation primitives implemented; public-data and site-data validation remain pending.

## Forecast evaluation contract

- Score only forecasts with timestamp-aligned realized observations.
- Report MAE, RMSE, bias, WAPE, prediction interval coverage and mean interval width.
- Report per-lead-step MAE/RMSE/bias/coverage so a good one-step score cannot hide long-horizon degradation.
- Compare against an explicitly supplied, timestamp-aligned baseline. MAE skill is positive when the candidate beats the baseline; undefined when baseline MAE is zero.
- Missing actuals, malformed timestamps, non-finite values and incomplete baseline coverage fail closed.

## Required benchmark protocol

1. Preserve chronological order; never randomly split time-series observations.
2. Keep a final holdout outside model selection and hyperparameter tuning.
3. Report each signal independently with its unit, cadence, sample count and data provenance.
4. Compare against at least one declared naive/seasonal baseline.
5. Report results by forecast lead time and, where enough observations exist, by operating regime.
6. Keep forecast error separate from dispatch feasibility, service reliability and economic outcomes.
7. Record dataset version/hash, date range, timezone, missing-data policy, model/version and evaluation configuration.

## What is not claimed

The benchmark module does not fetch external datasets or assert any numerical accuracy. A reproducible public dataset replay and then a customer/site dataset replay are still required. Synthetic fixtures validate software behavior only.

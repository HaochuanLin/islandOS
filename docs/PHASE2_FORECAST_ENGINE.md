# Phase 2 — Multi-signal forecast engine

## Objective

Provide a reusable, auditable forecasting service for aligned hourly energy and resource signals. The engine is designed to forecast signals such as PV output, wind output, essential load, flexible demand, water demand, and electricity price. Each signal declares its unit and whether negative values are physically permitted.

This phase is a forecasting capability, not an end-to-end customer deployment. The current implementation is an experimental prototype and does not claim site-calibrated accuracy.

## Current implementation

`islandos_core/forecast_engine.py` exposes `forecast_signals(...)` and returns a `ForecastBundle` containing:

- Forecasts for every supplied signal, each with its own selected model and unit.
- Exact UTC target timestamps and point predictions.
- Lower and upper planning bounds based on the 90th percentile of absolute chronological holdout errors.
- A chronological holdout score (MAE, RMSE, signed bias) and separate baseline scores.
- A SHA-256 digest of the normalized timestamps, units, and input values.

### Candidate models

1. **Persistence:** repeat the latest observed value.
2. **24-hour seasonal naive:** repeat the most recent daily profile.
3. **Ridge autoregression:** a small regularized regression model using lagged values (1, 2, 3, 24, and 48 hours) and hour/day-of-week cyclical features.

The model is selected independently for each signal. Ridge is used only when its recursive chronological holdout MAE is strictly lower than the strongest baseline. Otherwise the strongest baseline remains selected. This prevents a more complicated model from being chosen merely because it is labelled AI. After selection, the ridge model is refit on the full history available at forecast time; holdout observations are never used to score the candidate before selection.

The holdout is the final contiguous 20% of the supplied history. The model is trained only on the earlier portion. Multi-step forecasts are evaluated recursively: predictions, not future actual observations, are fed back into later steps.

## Data contract

- At least 72 hourly observations per signal.
- Timestamps must be timezone-aware, strictly ordered, and contiguous at one-hour intervals. They are normalized to UTC.
- Each signal must have exactly one value per timestamp and an explicit non-empty unit.
- Values must be numeric and finite. Negative values are allowed unless the signal is declared non-negative.
- Forecast horizon is 1–168 hours.
- No missing-value imputation, clipping of source observations, or silent unit conversion is performed.
- Non-negative forecasts are clipped at zero; negative-price signals must be explicitly allowed by omitting them from `non_negative_signals`.

## Uncertainty and interpretation

The displayed bounds are a simple empirical planning band: forecast ± the 90th percentile of absolute errors from the chronological holdout. They are not a calibrated probabilistic prediction interval and do not guarantee coverage. Forecast errors may grow with horizon, especially under recursive autoregression; the current band does not model horizon-dependent uncertainty.

A model winning on one supplied history is not proof of future skill. Evaluation must use representative data, compare against baselines, inspect seasonal and stress periods, and repeat across multiple chronological windows. Synthetic data validates software behavior only.

## Deliberate exclusions

- No external weather, market, outage, or calendar covariates yet.
- No deep learning or large pretrained time-series model.
- No automatic model deployment or continuous online learning.
- No forecast-to-optimizer closed loop in this phase.
- No live telemetry ingestion, equipment command, or autonomous control.
- No claim of measured customer savings or site accuracy.

## Next engineering gates

1. Test the model against realistic public or customer-authorized time series with provenance.
2. Add expanding-window multi-fold evaluation and horizon-specific error analysis.
3. Add exogenous covariates only where timestamp alignment and availability-at-decision-time are proven.
4. Propagate forecast scenarios into the physical evaluator in the subsequent integration phase.
5. Promote a model only when it consistently beats transparent baselines on relevant held-out data and stress cases.

# Phase 2 — Multi-signal forecast engine

## Objective

Provide a reusable, auditable forecasting service for aligned hourly energy and resource signals. The engine is designed to forecast signals such as PV output, wind output, essential load, flexible demand, water demand, and electricity price. Each signal declares its unit and whether negative values are physically permitted.

This phase is a forecasting capability, not an end-to-end customer deployment. The current implementation is an experimental prototype and does not claim site-calibrated accuracy.

## Public historical data input

A strict local-file adapter for the Open Power System Data (OPSD) hourly package is available in [`docs/PHASE2_PUBLIC_DATA.md`](PHASE2_PUBLIC_DATA.md). It maps selected region columns for load, solar, wind, and day-ahead price into the engine's aligned UTC data contract, preserving source-column provenance and a SHA-256 digest. The OPSD package is historical (2015 to mid-2020), geographically aggregated, and is intended for reproducible engineering backtests—not live market forecasts or site-level claims. Water demand is not present in this source.

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

## Forecast-to-planning hand-off

A validated, policy-free hand-off is available in `islandos_core/forecast_contract.py`:

```python
from islandos_core.forecast_contract import build_forecast_planning_input

planning_input = build_forecast_planning_input(
    forecast_bundle,
    {"pv": "kW", "critical_load": "kW", "tariff": "USD/kWh"},
)
```

The caller supplies the exact signal allow-list and expected units. The adapter rejects missing signals, unit mismatches, non-finite values, invalid prediction bounds, malformed history digests, and signals whose forecast timestamps do not align exactly. Equivalent timezone-aware timestamps are normalized to UTC before comparison and hand-off. Returned signal mappings are read-only so a downstream component cannot accidentally mutate the forecast snapshot. It returns common target timestamps, point forecasts, lower/upper planning bounds, units, selected model IDs, and the source-history SHA-256 digest. Extra signals are ignored unless explicitly requested.

This is a data contract only: it does not choose equipment schedules, optimize costs, assume asset constraints, or issue commands. A downstream optimizer must still apply physical limits, operating constraints, tariff semantics, and reliability requirements explicitly.

## Uncertainty and interpretation

The displayed bounds are a simple empirical planning band: forecast ± the 90th percentile of absolute errors from the chronological holdout. They are not a calibrated probabilistic prediction interval and do not guarantee coverage. Forecast errors may grow with horizon, especially under recursive autoregression; the current band does not model horizon-dependent uncertainty.

A model winning on one supplied history is not proof of future skill. Evaluation must use representative data, compare against baselines, inspect seasonal and stress periods, and repeat across multiple chronological windows. Synthetic data validates software behavior only.

## Deliberate exclusions

- No external weather, market, outage, or calendar covariates yet.
- No deep learning or large pretrained time-series model.
- No automatic model deployment or continuous online learning.
- No dispatch optimizer, forecast-to-optimizer closed loop, or autonomous control in this phase; only the validated data hand-off is defined.
- No live telemetry ingestion, equipment command, or autonomous control.
- No claim of measured customer savings or site accuracy.

## Next engineering gates

1. Run the OPSD adapter and CLI on a complete, provenance-documented public historical interval; inspect data quality and rolling-origin scores.
2. Use `evaluate_signal_rolling(...)` to compare the actual built-in persistence, seasonal-naive, and ridge candidates at multiple horizons; review stability across folds before changing automatic promotion.
3. Add exogenous covariates only where timestamp alignment and availability-at-decision-time are proven.
4. Integrate the validated planning input with the physical evaluator in the subsequent integration phase, then compare forecast-driven decisions against a transparent baseline.
5. Promote a model only when it consistently beats transparent baselines on relevant held-out data and stress cases.


## Canonical site signal catalog

The semantic signal vocabulary is maintained in `islandos_core/forecast_signal_catalog.py`.
Use `forecast_site_signals(...)` when forecasting site data so known signals share
one domain, unit, and physical-sign contract across data onboarding and prediction.
This is the canonical new-work entry point: it routes each signal through the
pluggable `PredictionEngine` in `islandos_core/prediction_engine.py`, not a new
parallel model registry.

The catalog currently covers:
- Energy supply: PV, wind, grid import/export, and diesel generation.
- Energy demand: total site load and flexible load.
- Storage: battery charge, discharge, and state of charge.
- Prices: electricity tariff (including explicitly currency-labelled negative prices).
- Resource/fuel demand: hourly water demand and diesel fuel consumption.
- Environment: ambient temperature.

Example:

```python
from islandos_core.forecast_signal_catalog import forecast_site_signals

bundle = forecast_site_signals(
    timestamps,
    {
        "pv_power_kw": pv_kw,
        "load_kw": load_kw,
        "tariff_per_kwh": tariff,
        "water_demand_m3_per_hour": water_demand,
    },
    {
        "pv_power_kw": "kW",
        "load_kw": "kW",
        "tariff_per_kwh": "USD/kWh",
        "water_demand_m3_per_hour": "m3/h",
    },
    horizon=24,
)
```

Known signal IDs enforce their canonical unit and non-negative/negative-value
semantics before entering the common model-selection pipeline. Custom signals
remain supported when callers provide explicit units; their physical sign
semantics are not guessed. The catalog is a semantic validation layer, not a
claim that every signal has site-trained or externally validated model skill.


### Model evaluation and replacement

`forecast_site_signals` accepts an optional `PredictionEngine`. The default
engine registers the built-in seasonal-naive, recent-mean, and linear-trend
candidates, ranks them using rolling-origin replay, and selects the lowest-error
eligible candidate independently for each signal. A customer or integrator can
supply a separately configured engine with one or more registered candidates;
the selected model ID/version and input-history digest remain in each result.

```python
from islandos_core.forecast_signal_catalog import forecast_site_signals
from islandos_core.prediction_engine import PredictionEngine

engine = PredictionEngine(include_builtin_candidates=False)
engine.register(MyForecastCandidate())  # implements model_id, version, predict(...)
bundle = forecast_site_signals(timestamps, history, units, horizon=24, engine=engine)
selected = bundle.results["pv_power_kw"].model_id
```

Candidate registration is a software extension point, not automatic model
promotion to production. Candidate suitability still depends on representative
chronological backtests, data quality, and site-specific review.

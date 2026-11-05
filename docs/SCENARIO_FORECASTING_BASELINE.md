# Scenario forecasting baseline

The Microgrid screening page now has a forecast stage before physical simulation.

## Method

- Input window: 168 synthetic hourly observations (seven days).
- Forecast method: seasonal-naive repetition of the latest 24-hour profile.
- Forecast horizon: the selected 24–168 hourly steps.
- Signals: PV output, wind output, essential electric load, and water demand.
- The resulting forecast arrays, rather than a separately generated future truth series, are passed into the common microgrid physical model for all candidate schedules.

This method is intentionally transparent and dependency-free. It is a benchmark, not a trained machine-learning model, site-calibrated forecast, or evidence of forecast skill. Repeating yesterday's profile cannot anticipate weather fronts, outages, holidays, demand shocks, or equipment degradation.

## Evaluation

`islandos_core/scenario_forecasting.py` provides:
- `seasonal_naive_forecast`: non-negative hourly seasonal-naive forecast.
- `evaluate_forecast`: MAE, RMSE, and WAPE (undefined when all actual values are zero).
- `rolling_origin_evaluate`: chronological, non-overlapping rolling-origin evaluation.
- `forecast_microgrid_signals`: applies the baseline consistently to named microgrid signals.

Forecast evaluation must use a chronological holdout. Do not randomly shuffle time-series observations or fit preprocessing on future observations. A site model should be promoted only after it beats simple baselines on representative, held-out site data and relevant high-demand / low-renewable periods.

## Data and operational limits

The interactive page generates synthetic history. Its forecast and schedule comparison are therefore software demonstrations only, not site predictions, measured savings, or operating instructions. Real deployment requires timestamp-aligned and quality-checked site history, weather forecasts, tariff and equipment constraints, operator review, and independent validation. The page is a planning simulator, not a live controller.

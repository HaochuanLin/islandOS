# Forecast plugin benchmarking

IslandOS evaluates a forecast plugin with a rolling-origin, one-step-ahead holdout. At each test timestamp, the plugin receives only earlier observations. The generated JSON report includes the input file SHA-256, plugin ID/version, holdout window, sample count, and forecast rows.

## Run a benchmark

Use a trusted plugin module and a CSV with timezone-aware ISO-8601 `timestamp` values and non-negative `water_demand_m3` values. Rows must be continuous hourly observations.

```bash
python experiments/backtest_forecast_plugin.py data/processed/hourly.csv \
  --plugin your_package.forecast:YourForecastPlugin \
  --history-hours 168 \
  --test-fraction 0.2 \
  --output build/plugin-backtest/forecast_report.json
```

The plugin is imported and executed as local Python code. Only run plugins you trust.

## Read the metrics

- **MAE**: mean absolute error in m³/hour; lower is better.
- **RMSE**: root mean squared error in m³/hour; penalizes larger misses more heavily.
- **Bias**: mean prediction minus actual; positive means overforecast on average.
- **Underforecast rate**: fraction of test rows where prediction is below actual.
- **Persistence baseline**: predicts the last observed demand for the next hour.
- **Seasonal-naive 24-hour baseline**: predicts from the same hour on the previous day, only where that lag exists.
- **Skill vs baseline MAE**: `1 - plugin_MAE / baseline_MAE`. Positive means the plugin has lower MAE than the named baseline; negative means worse. If baseline MAE is zero, the score is null.

The seasonal comparison uses the exact same timestamps for the plugin and seasonal baseline; inspect `seasonal_comparable_plugin_metrics` when comparing their MAE. The seasonal baseline may have fewer samples than the full holdout. Never compare errors calculated on different windows as though they were directly equivalent.

## Evidence limits

A lower error on one holdout does not prove generalization, causality, physical validity, or suitability for operating a real plant. Compare against simple baselines across multiple time periods and sites, preserve data provenance, inspect forecast bias and underforecasting, and validate the complete forecast-to-dispatch workflow before using results for planning. The report does not train a model, perform online learning, or automatically promote a candidate.

# Water-demand forecast performance monitoring

This tool is the next step after generating out-of-sample water-demand forecasts:
once the matching actual demand readings arrive, it compares forecast errors over
time and flags a possible deterioration. It does **not** automatically retrain a
model or replace the current model.

## Input

Prepare a UTF-8 CSV with one row per hour and these columns:

| Column | Meaning |
|---|---|
| `timestamp` | ISO-8601 timestamp with a timezone offset |
| `actual_water_demand_m3` | Measured demand for that hour, in m³ |
| `forecast_water_demand_m3` | Forecast that was issued before the measured hour, in m³ |

The timestamps must be strictly ordered and continuous at hourly intervals.
Values must be finite and non-negative. The tool rejects missing hours and
invalid values instead of silently repairing the data.

## Run it

A clearly synthetic 72-hour example is included at `data/examples/synthetic_forecast_monitor_demo.csv`. It deliberately changes forecast error in the final day so you can see how a review alert works. It is **not measured data** and does not represent real forecast accuracy. Run it with:

```bash
python experiments/monitor_forecast_performance.py \
  data/examples/synthetic_forecast_monitor_demo.csv \
  --window-hours 24 \
  --output build/water-demand-forecast/monitor-demo.json
```

The expected result is `review_recommended` because the example's last-day error is deliberately larger than its first-day error. GitHub Actions runs this example as a smoke test and saves the JSON report as an artifact.

For your own data, run from the repository root:

```bash
python experiments/monitor_forecast_performance.py \
  path/to/actual-and-forecast.csv \
  --window-hours 24 \
  --mae-degradation-fraction 0.25 \
  --output build/water-demand-forecast/monitor.json
```

The default compares the first 24-hour window with the most recent 24-hour
window. It reports MAE, RMSE, signed bias, and underforecast rate for each window.
If recent MAE is more than 25% higher than baseline MAE, it returns
`review_recommended`. When the baseline MAE is zero, any nonzero recent MAE
triggers a review. The newest complete window is always included; if the input
length is not an exact multiple of the window size, that last window can overlap
the previous one.

## How to interpret the alert

A warning is a prompt to inspect meter quality, missing events, occupancy,
weather, plant changes, and forecast quality. It is **not** proof of statistical
drift. Before changing a model, rerun a chronological backtest and compare it
with persistence and seasonal baselines. Retraining should only be adopted after
the candidate model improves held-out performance and passes operational checks.

Forecasts must be genuinely out-of-sample and aligned with the actual demand
at the same timestamps. If forecasts were made using the future actual values,
the monitor's results are invalid. Synthetic data is useful for testing the
code path, not for proving real-site forecast skill.

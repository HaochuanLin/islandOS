# Water-demand forecasting baseline

This experiment adds a first, deliberately simple step toward data-driven
water-demand prediction. It does **not** assume water demand is normally
distributed and does not claim that the prototype is already learning online.

## Try the end-to-end example

A small, deterministic hourly dataset is included at
`data/examples/synthetic_water_demand_demo.csv`. **Every value in this file
is synthetic, not measured island or customer data.** It is only intended to
show the input format and let the full workflow run without private data.

Run from the repository root:

```bash
python experiments/water_demand_forecast.py \
  data/examples/synthetic_water_demand_demo.csv \
  --output build/water-demand-forecast/report.json
```

The JSON report contains holdout metrics, each held-out forecast, distribution
diagnostics, and prediction-interval coverage. The CI workflow runs this same
example and uploads the report as an artifact, so basic end-to-end operation
is checked on every relevant push and pull request.

## Input

Use a UTF-8 CSV with one row per hour:

| Column | Meaning |
|---|---|
| `timestamp` | ISO-8601 timestamp with a timezone offset |
| `water_demand_m3` | Freshwater demand during that hourly interval, in m³ |

Rows must be strictly ordered and continuous at one-hour intervals. Demand
must be finite and non-negative. The script rejects missing hours and invalid
values rather than silently filling or correcting them.

## Evaluate on public measured data

A real public benchmark is available: the SOWEKI water-demand series measured at rural German reservoir outflows. It is not island-specific, but it allows the forecasting pipeline to be checked against measurements rather than only synthetic examples. See [the dataset, license, preparation steps, and limitations](SOWEKI_WATER_DEMAND_DATA.md).

Prepare one downloaded SOWEKI series first, then run the same chronological forecast evaluation on the resulting hourly CSV. Keep the report clearly labeled as SOWEKI data; its accuracy is not evidence of accuracy for Nan'ao or another site.

## Evaluation

The script holds out the final chronological segment and compares:
- **Persistence:** next-hour demand equals the latest observation.
- **Seasonal naive:** next-hour demand equals the observation 24 hours earlier.
- **Bias-corrected seasonal naive:** subtract the mean forecast error measured
  on the training history from the 24-hour seasonal forecast. The correction
  is fitted before the test window and clipped at zero.

It reports MAE, RMSE, and bias on the same held-out hours. In addition, the
expanding-window rolling-origin backtest recalibrates the seasonal bias before
each test hour using only earlier observations and earlier forecast errors. Its
metrics are reported separately from the fixed-training-window comparison.
A leakage-guard test changes only later observations and verifies that an earlier
forecast remains unchanged. This checks the implementation's time boundary; it
does not guarantee that the statistical model is accurate. It also reports
descriptive Jarque–Bera diagnostics for the held-out demand values and the
training-history seasonal-forecast errors. The approximate p-value is a
diagnostic, not proof that a distribution is or is not Gaussian.

Gaussian-style 90% and 95% prediction intervals are centered on the bias-corrected
seasonal forecast and use the training-history residual spread. Their empirical
coverage is measured on held-out observations. The intervals are not guaranteed
to have nominal coverage. Because demand cannot be negative, the lower bound
and corrected point forecast are clipped at zero; empirical coverage remains
important.

## Compare a first machine-learning model

The optional [water-demand model comparison](WATER_DEMAND_ML_COMPARISON.md)
adds a small scikit-learn gradient-boosting model and compares it with previous-hour,
previous-day, and previous-week baselines on the same chronological holdout.
It is deliberately not deep learning. The model should only be considered better
if it improves out-of-sample results across multiple time windows and useful
operational metrics, not just one synthetic demo.

## Why not start with deep learning?

A neural network can be useful when there is enough high-quality historical
data and relevant predictors such as hour of day, day of week, holidays,
occupancy, weather, leaks, and water-system outages. Without those data, a
complex model can merely memorize synthetic patterns and look more intelligent
than it is. The persistence and seasonal-naive baselines provide a transparent
minimum bar that a later model must beat on chronological holdout periods.

## Next milestones

1. Collect timestamped measured demand and record units, missingness, meter
   quality, occupancy/tourism, and known outages.
2. Compare normal, log-normal, Gamma, and empirical residual distributions
   against out-of-sample calibration; select based on diagnostics, not habit.
3. Add hour/day/holiday/occupancy/weather predictors and evaluate with rolling
   chronological backtests.
4. Compare statistical models and machine-learning models against the simple
   baselines, including prediction-interval calibration.
5. Only then introduce scheduled retraining or online updates, with drift
   monitoring and a versioned model registry.

All example/synthetic data must be labeled as such. A successful software test
only verifies implementation behavior; it does not establish forecast accuracy
for a real island.

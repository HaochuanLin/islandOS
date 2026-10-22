# Water-demand forecasting baseline

This experiment adds a first, deliberately simple step toward data-driven
water-demand prediction. It does **not** assume water demand is normally
distributed and does not claim that the prototype is already learning online.

## Input

Use a UTF-8 CSV with one row per hour:

| Column | Meaning |
|---|---|
| `timestamp` | ISO-8601 timestamp with a timezone offset |
| `water_demand_m3` | Freshwater demand during that hourly interval, in m³ |

Rows must be strictly ordered and continuous at one-hour intervals. Demand
must be finite and non-negative. The script rejects missing hours and invalid
values rather than silently filling or correcting them.

Example:

```csv
timestamp,water_demand_m3
2025-01-01T00:00:00+00:00,28.4
2025-01-01T01:00:00+00:00,27.9
```

## Run

```bash
python experiments/water_demand_forecast.py path/to/hourly_water_demand.csv \
  --output build/water-demand-forecast/report.json
```

The script holds out the final chronological segment and compares:
- **Persistence:** next-hour demand equals the latest observation.
- **Seasonal naive:** next-hour demand equals the observation 24 hours earlier.

It reports MAE, RMSE, and bias on the same held-out hours. It also reports
descriptive Jarque–Bera diagnostics for the held-out demand values and the
training-history seasonal-forecast errors. The approximate p-value is a
diagnostic, not proof that a distribution is or is not Gaussian.

A Gaussian-style 90% and 95% prediction interval is constructed from the
historical seasonal-forecast error spread, then evaluated by actual holdout
coverage. The interval is not guaranteed to have its nominal coverage. Because
demand cannot be negative, the lower bound is clipped at zero; that makes
empirical coverage especially important.

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

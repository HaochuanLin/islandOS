# Water-demand uncertainty in dispatch planning

This experiment compares two planning assumptions on the same out-of-sample
hourly window:

1. **Point forecast:** the selected water-demand forecast.
2. **Upper-bound stress case:** a selected upper prediction bound, such as the
   90% upper bound from the statistical baseline.

Both runs keep the realized water demand unchanged for execution and outcome
scoring. Only the demand value supplied to planning changes. This helps reveal
whether a conservative planning assumption shifts the trade-off between water,
cold storage, and remaining renewable surplus.

## Run

First generate an out-of-sample demand report:

```bash
python experiments/water_demand_forecast.py \
  data/examples/synthetic_water_demand_demo.csv \
  --output build/water-demand-forecast/report.json
```

Prepare paired hourly power data whose `water_demand_m3` values match the
forecast report at the same timestamps. The CSV must contain `timestamp_utc`,
`actual_surplus_kw`, `forecast_surplus_kw`, `water_demand_m3`, and
`cooling_demand_kw_th`. Then run:

```bash
python experiments/evaluate_water_demand_uncertainty_dispatch.py \
  path/to/paired_power.csv \
  build/water-demand-forecast/report.json \
  --point-column seasonal_bias_corrected_forecast_m3 \
  --upper-column seasonal_bias_corrected_90pct_upper_m3 \
  --output build/forecast-dispatch/uncertainty-comparison.json
```

The adapter joins both columns by UTC timestamp and rejects missing matches or
mismatched actual demand. The report compares rolling-dispatch outcomes for the
point and upper-bound planning runs, including unmet water, unmet cooling,
remaining surplus, constraint-violation hours, and the illustrative score.

## Interpretation

- An upper prediction bound is a **stress-test input**, not necessarily a better
  point forecast. It may encourage more water production planning but can also
  displace cooling or use more available renewable energy.
- Inspect raw service outcomes as well as the aggregate score. The default
  score weights are illustrative and must not substitute for site priorities.
- The interval must be generated from a valid out-of-sample method and the same
  demand series. Do not pair an interval from one model or dataset with another
  model's point forecast.
- A successful test proves the software path works; it does not establish
  interval calibration, real-island benefit, plant safety, or controller
  readiness. Synthetic fixtures are not measured site evidence.
- This is a paired scenario comparison, not robust optimization and not a
  guarantee that the upper-bound plan is better.

This feature is useful even before local historical data is available: it
establishes a transparent place to evaluate uncertainty once suitable measured
data and calibrated prediction intervals exist.

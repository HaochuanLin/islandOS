# Forecast-driven RO simulation

## Purpose

The legacy RO/reservoir simulator historically used perfect foresight for its look-ahead start rule. That remains the default for backward compatibility, but it is optimistic. The simulator now accepts forecast arrays so the planning decision can be evaluated separately from realized physical operation.

## API

```python
result = simulate(
    wind_kw,
    pv_kw,
    load_kw,
    realized_water_demand_m3_per_hour,
    params,
    forecast_curtailment=forecast_surplus_kw,
    forecast_water_demand=forecast_water_demand_m3_per_hour,
)
```

- `forecast_curtailment` is the predicted renewable surplus available for RO planning at each hourly step.
- `forecast_water_demand` is the predicted water demand used by the reservoir-capacity feasibility check.
- Both forecasts must be one-dimensional, finite, non-negative, and the same length as the realized inputs.
- The model uses forecasts for look-ahead start decisions and storage-feasibility planning. Actual RO power use, backup consumption, water production, storage, spill, and deficit still use realized inputs.
- When omitted, each forecast defaults to the realized series, preserving historical behavior and making the perfect-foresight assumption explicit in the output.

The result includes `planning_curtailment`, `planning_water_demand`, and booleans indicating whether forecast arrays were explicitly supplied. The existing `curtail` output remains the realized curtailment used to calculate physical power use.

## Forecast-error behavior

A forecast can predict enough surplus to start RO while realized surplus later falls short. In backup mode, the shortfall is recorded in `ro_backup`. In no-backup mode, the safety fallback may emergency-stop the plant before the minimum run time is complete; `emergency_stop` records this and `check_min_run` reports the violated minimum-run invariant. This is an exposed simulation failure mode, not a safe real-plant control strategy.

The simulator does not train a forecast model. Use the optional public-data or site-specific forecast experiments to produce forecast arrays, then evaluate error, underforecast risk, water-service deficits, backup energy, and reservoir bounds together. Forecast skill on one public collection does not establish island-site transfer or field safety.


## Run a paired forecast-vs-oracle experiment

After joining a water-demand forecast report to the matching power series, evaluate how forecast errors affect RO/reservoir operation:

```bash
python experiments/evaluate_forecast_driven_ro_sim.py \
  build/forecast-dispatch/paired_with_water_forecast.csv \
  --output build/forecast-driven-ro/hourly.csv \
  --report build/forecast-driven-ro/report.json \
  --ro-power-kw 400 --specific-energy-kwh-m3 3.5 \
  --min-run-hours 2 --tank-capacity-m3 3000 \
  --tank-initial-m3 800 --tank-min-m3 200
```

The evaluator reports forecast MAE/bias, backup energy, water deficit/spill, RO run hours, emergency stops, and minimum-run validity. It compares the forecast-driven run with the legacy perfect-foresight run on the same realized series. Treat the latter only as an optimistic oracle, not as a realistic baseline or attainable savings estimate. The paired input must contain actual and forecast surplus plus actual and forecast water demand on continuous hourly timestamps.

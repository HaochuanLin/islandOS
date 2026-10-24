# Plug-in forecast model interface

## Product positioning

IslandOS is designed as a **plug-in energy/water decision and simulation platform**: data sources, forecast models, and device-protocol adapters should be replaceable at documented boundaries. The current repository has a working experiment-to-dispatch adapter for water-demand forecasts. It is not yet a universal plug-and-play controller: site-specific mapping, units, equipment constraints, data quality, and engineering approval remain required.

## Runtime plug-in contract

The dependency-free runtime interface is implemented in `islandos_core/forecasting.py`:

- `WaterObservation` enforces timezone-aware timestamps and finite, non-negative demand.
- `ForecastRequest` requires continuous hourly history and strictly future, continuous hourly targets.
- `WaterDemandForecastPlugin` defines the `model_id`, `version`, and `predict(history, target_timestamps)` contract.
- `ForecastModelRegistry` registers models, rejects duplicate IDs, checks output length and values, and returns predictions with an input-history SHA-256 digest.
- `tests/test_forecast_plugin_registry.py` exercises the contract, including malformed timestamps, gaps, negative values, NaN/Infinity and duplicate model IDs.

A new model can implement this small interface without importing PyTorch or changing the dispatch core. The registry does not decide which model is best, silently promote candidates, or connect predictions to a live controller.

## Forecast model adapter contract

A forecast experiment is a replaceable producer of a chronological JSON report. For dispatch integration, the report must have:

- `status: "models_compared"`
- `forecast_rows`: chronological rows with timezone-aware `timestamp`, `actual_water_demand_m3`, and one or more non-negative forecast columns.
- source CSV SHA-256, model/library version, training/test window, and explicit limitations.

The existing join adapter verifies UTC timestamp alignment and rejects missing/duplicate/gapped timestamps or actual-demand mismatches. It then emits the normalized `forecast_water_demand_m3` column consumed by the dispatch evaluator. A new model can therefore be added without rewriting the dispatch simulator.

## Optional LSTM experiment

The optional PyTorch LSTM consumes a prepared hourly CSV with `timestamp` and `water_demand_m3`, uses the previous 168 hours plus calendar-cycle features, and compares its one-step predictions with previous-hour/day/week baselines and the incumbent HistGradientBoosting model. Training duration is selected using a chronological validation tail with early stopping; scaling parameters exclude that validation tail, and the final model is refit using only pre-test history. The second expanding-window evaluation repeats the same leakage-aware procedure with its own scaler. Reports include input SHA-256, library versions, seed, selected epochs, validation metrics, train/test sizes, and holdout metrics.

Install and run:

```bash
python -m pip install -r requirements-deep-learning.txt
python experiments/compare_water_demand_deep_learning.py \
  data/processed/your_prepared_hourly.csv \
  --output build/deep-learning/lstm_comparison.json --epochs 12
```

The public-data workflow `deep-learning-water-demand.yml` runs the experiment against SOWEKI measured series, archives source and report artifacts, and supports a manual choice of series ID and epoch count. A green run proves the experiment executed and its report is valid; it does **not** prove the LSTM beats the baseline. The winner must be determined from the recorded metrics, not assumed.

## Safety and limitations

- This is a one-step-ahead research candidate, not online learning or an automatically deployed model.
- The LSTM is not silently substituted for the incumbent forecast.
- Do not send its output to a live controller without a candidate-review gate, site-specific backtest, uncertainty/risk checks, and human engineering approval.
- A model trained on one SOWEKI collection does not establish transfer to a different island or utility.
- PyTorch is an optional, separately installed dependency; the default app and standard CI environment do not require it.


## Model promotion policy

The multi-series workflow now emits an explicit machine-readable benchmark decision. The LSTM is only eligible for site-specific review if it beats the incumbent gradient-boosting model on at least 80% of evaluated series in the walk-forward window and achieves at least 5% mean MAE improvement. This is a conservative research gate, not a universal model-selection theorem; a passing result does not deploy the model. The public SOWEKI series are one collection, not independent island sites. Final promotion still requires the existing forecast-candidate review gate, representative local data, high-demand underforecast checks, and human approval.

The model registry is an executable integration boundary; the optional LSTM experiment and the registry are intentionally separate from automatic live dispatch. This allows third-party models to be plugged into a shared contract without confusing interface compatibility with demonstrated predictive quality.


## End-to-end third-party plugin workflow

Implement the documented plugin contract, then evaluate it without changing the simulator or the join adapter:

```bash
python experiments/backtest_forecast_plugin.py \
  data/processed/your_prepared_hourly.csv \
  --plugin your_package.forecast:MyForecastPlugin \
  --history-hours 168 --test-fraction 0.2 \
  --output build/plugin-backtest/forecast_report.json

python experiments/build_forecast_dispatch_input.py \
  data/processed/paired_power_dispatch.csv \
  build/plugin-backtest/forecast_report.json \
  --forecast-column plugin_forecast_m3 \
  --output build/plugin-backtest/dispatch_input.csv
```

The backtest uses a chronological test tail and gives the plugin only the prior `history-hours` observations for each one-step prediction. It records the source CSV SHA-256, plugin identity/version, test window, metrics, and limitations. Its report uses the existing `rolling_backtest_completed` contract accepted by the timestamp-checked dispatch join. The join preserves measured water demand separately from the forecast planning column.

**Security boundary:** `--plugin` imports and executes Python code in the current process. Only load trusted local packages. This harness proves integration compatibility, not forecast skill, plant safety, or field readiness.

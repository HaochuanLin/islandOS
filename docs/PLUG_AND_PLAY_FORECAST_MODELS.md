# Plug-in forecast model interface

## Product positioning

IslandOS is designed as a **plug-in energy/water decision and simulation platform**: data sources, forecast models, and device-protocol adapters should be replaceable at documented boundaries. The current repository has a working experiment-to-dispatch adapter for water-demand forecasts. It is not yet a universal plug-and-play controller: site-specific mapping, units, equipment constraints, data quality, and engineering approval remain required.

## Forecast model adapter contract

A forecast experiment is a replaceable producer of a chronological JSON report. For dispatch integration, the report must have:

- `status: "models_compared"`
- `forecast_rows`: chronological rows with timezone-aware `timestamp`, `actual_water_demand_m3`, and one or more non-negative forecast columns.
- source CSV SHA-256, model/library version, training/test window, and explicit limitations.

The existing join adapter verifies UTC timestamp alignment and rejects missing/duplicate/gapped timestamps or actual-demand mismatches. It then emits the normalized `forecast_water_demand_m3` column consumed by the dispatch evaluator. A new model can therefore be added without rewriting the dispatch simulator.

## Optional LSTM experiment

The optional PyTorch LSTM consumes a prepared hourly CSV with `timestamp` and `water_demand_m3`, uses the previous 168 hours plus calendar-cycle features, and compares its one-step predictions with previous-hour/day/week baselines. It records input SHA-256, library version, seed, train/test sizes, metrics, and a second chronological evaluation window.

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

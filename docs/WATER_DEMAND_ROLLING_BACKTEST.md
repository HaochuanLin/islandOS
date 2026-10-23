# Repeated chronological water-demand model backtest

A single train/test split can make a model look unusually good or bad because
one period may be easier than another. This experiment repeats the comparison
across multiple non-overlapping test windows. At each window, it retrains the
gradient-boosting model using only the earlier history and evaluates it beside
three simple baselines.

## Run it

Install the optional ML dependencies:

```bash
python -m pip install -r requirements-ml.txt
```

Then run:

```bash
python experiments/backtest_water_demand_models.py \
  path/to/hourly_water_demand.csv \
  --initial-train-fraction 0.65 \
  --test-window-hours 24 \
  --step-hours 24 \
  --output build/water-demand-forecast/rolling-backtest.json
```

Input must have the same timezone-aware, continuous hourly columns as the
[model comparison experiment](WATER_DEMAND_ML_COMPARISON.md). Each fold must
contain at least 24 test hours; test windows cannot overlap. The report includes
metrics for each fold and pooled metrics across every evaluated hour.

## What this improves

- **Time robustness:** reveals whether model ranking changes across different
  periods rather than trusting one holdout.
- **Fair comparison:** persistence, previous-day, previous-week and gradient
  boosting are evaluated on the same timestamps.
- **Leakage control:** each fold trains only on timestamps before its test
  window. Forecast features use only lagged observations.
- **Reproducibility:** model settings are fixed and the report records the
  cutoffs, window sizes, fold metrics and pooled metrics.

## Interpretation limits

Repeated evaluation is stronger evidence than one holdout, but it is not proof
of generalization to another island, climate, season, or water system. A
synthetic fixture is only a software smoke test. For a meaningful data-driven
claim, run the same procedure on measured data, keep dataset provenance clear,
and compare more than MAE: inspect RMSE, bias, peak-demand errors and the impact
on downstream dispatch. Public SOWEKI measurements are real but come from rural
German reservoir outflows, not island desalination production or Nan'ao.

This is offline expanding-window evaluation, not automatic online learning.
Model retraining should only be considered after there is sufficient measured
history and a monitored evaluation process.

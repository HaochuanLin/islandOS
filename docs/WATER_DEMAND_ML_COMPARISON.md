# Compare water-demand forecasting models

This optional experiment compares a small machine-learning model with simple
forecasting baselines on the **same chronological holdout**. It is a step
between the existing statistical baseline and any future deep-learning work.

## Run it

Install the optional machine-learning dependencies:

```bash
python -m pip install -r requirements-ml.txt
```

Prepare a measured hourly series using the [SOWEKI dataset guide](SOWEKI_WATER_DEMAND_DATA.md),
or use the clearly synthetic example to verify the software workflow:

```bash
python experiments/compare_water_demand_models.py \
  data/examples/synthetic_water_demand_demo.csv \
  --output build/water-demand-forecast/model-comparison.json
```

The report includes per-model MAE, RMSE and prediction bias, held-out hourly
predictions, and the model with the lowest MAE on this specific holdout. The
synthetic example verifies that the pipeline runs; it is not evidence of
real-world forecasting skill.

## Models compared

- **Persistence:** the previous hour's measured demand.
- **Previous-day seasonal baseline:** demand at the same hour one day earlier.
- **Previous-week seasonal baseline:** demand at the same hour one week earlier.
- **HistGradientBoostingRegressor:** a small scikit-learn model using previous
  hour/day/week demand, the previous 24-hour mean, and cyclical hour/day-of-week
  features.

The model is fitted only on the earlier chronological segment. Test evaluation
is rolling one hour ahead: once an hour's measured demand is available, it can
be used as a lag for the next forecast. This is not a multi-day-ahead forecast.
No rows are shuffled.

## How to interpret the result

Do not assume the machine-learning model wins. Keep a simple baseline if it
has lower or similarly good error, better stability, or clearer calibration.
Review MAE, RMSE and bias together, inspect high-demand periods, and repeat
the evaluation across multiple chronological windows and datasets before
choosing a model.

This experiment does **not** use a neural network, does not retrain online,
and does not include weather, occupancy, holidays, leakage or plant-operation
features. A model that predicts reservoir demand also does not predict
desalination production: production depends on plant capacity, energy
availability, storage and operating constraints.

The public SOWEKI measurements are from rural German reservoir outflows. They
are useful for testing the pipeline against real measurements, but they are
not island-specific, are not Nan'ao data, and do not establish transfer to an
island water system. Never present synthetic results as measured performance.

# Train and evaluate a Mafate household-load forecast

This optional experiment trains a small scikit-learn gradient-boosting model on
the **hourly normalized measurements** produced by
[the Mafate importer](MAFATE_MICROGRID_DATA.md). It compares the trained model
with persistence, previous-day and previous-week baselines on the same
chronological test timestamps.

## Install and run

The data archives must first be downloaded from the cited Zenodo record and
extracted, as described in the [import guide](MAFATE_MICROGRID_DATA.md).

```bash
python -m pip install -r requirements-ml.txt
python experiments/import_mafate_microgrid_data.py \
  --data-dir /path/to/extracted-mafate-files \
  --output-dir build/mafate
python experiments/train_mafate_load_model.py \
  build/mafate/microgrid_hourly.csv \
  --target house_1_load_kw \
  --output build/mafate/house1-forecast-report.json \
  --model-output build/mafate/house1-load-model.joblib
```

Choose `house_1_load_kw`, `house_2_load_kw`, or `house_3_load_kw` to train
a separate model for each household. The report includes model and baseline
metrics, train/test timestamps, eligible sample counts, and per-hour predictions.
The optional model artifact is saved separately from the report.

## How training works

- **Chronological split:** the first 70% of eligible time is used for training;
  the final 30% is held out for testing. The split can be changed with
  `--train-fraction` between 0.60 and 0.85.
- **Features:** previous-hour load, the load at the same hour yesterday, the
  load at the same hour last week, the previous 24-hour mean, and cyclical
  hour-of-day/day-of-week features.
- **Model:** `HistGradientBoostingRegressor`, trained only on the earlier
  segment, with fixed settings and a fixed random seed.
- **Fair comparison:** persistence, 24-hour seasonal naive, 168-hour seasonal
  naive and the trained model are evaluated on the exact same test timestamps.
- **Rolling one-step-ahead protocol:** for each test hour, earlier observed
  test-period loads may be used as lag features. This models repeatedly updating
  a one-hour-ahead forecast; it is not a 24-hour-ahead forecast.
- **No hidden gap filling:** missing target or lag observations exclude a sample.
  The script requires a continuous hourly time index and reports how many
  candidate test rows were excluded.

The report uses MAE, RMSE and prediction bias in kW. The machine-learning model
is not assumed to outperform simple baselines; judge it using the test metrics.
If a baseline wins, keep the baseline until the model improves.

## Limits

This is the first training path for real energy time series, not a production
forecasting service. It uses only lag and calendar features, does not use weather
forecasts, and does not perform multi-step uncertainty calibration or online
retraining. Results from three homes in one experimental microgrid do not
establish performance for other islands. The dataset has no freshwater-demand,
desalination-production or reservoir-inventory targets, so this model does not
train the water side of islandOS.

Training this small model locally is normally free; it uses CPU and does not
require a paid AI API or GPU. The optional dependency set is
`requirements-ml.txt`.

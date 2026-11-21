# House 1 load forecast on real Mafate data

Data: Demand_house_1_dataset.csv from the Mafate Roche Plate microgrid (Zenodo record 8186303, CC BY 4.0, Calogine et al. 2023). One year of one-minute readings averaged to hourly values, 1 May 2020 to 1 May 2021.

Method: train on the first 70% of the year in time order, then forecast each hour of the remaining 30% one hour ahead, using only earlier observations. Compared with three simple baselines.

| Forecast (test period 12 Jan to 1 May 2021, 2,534 hours) | MAE (kW) | RMSE (kW) |
|---|---|---|
| Same as previous hour (persistence) | 0.053 | 0.084 |
| Same hour yesterday | 0.061 | 0.099 |
| Same hour last week | 0.069 | 0.106 |
| Gradient-boosting model | 0.046 | 0.071 |

The model's error was 12% lower than the best baseline (MAE) and 15% lower on RMSE. The house used 0.14 kW on average in the test period, so the typical error is still about a third of the average load.

Limits: one small house at one research site, one-hour-ahead forecasts only, no weather inputs, and no water or desalination data in this dataset.

Reproduce:

    python experiments/import_mafate_microgrid_data.py --data-dir <folder with the CSV> --output-dir build/mafate --allow-missing
    python experiments/train_mafate_load_model.py build/mafate/microgrid_hourly.csv --target house_1_load_kw --output build/mafate/house1-forecast-report.json

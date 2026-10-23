# Public measured water-demand data: SOWEKI

## Dataset found

The [SOWEKI Water Demand Dataset on Zenodo](https://zenodo.org/records/19627517)
was published in April 2026 by researchers at the German Research Center for
Artificial Intelligence, the Eifel-Mosel water utility, and the University of
Trier. It provides 11 real measured water-demand series collected at reservoir
outflows serving small rural areas in Germany.

- **Time resolution:** 15 minutes
- **Coverage:** series-specific dates from 2024 through January 2026
- **Typical size:** approximately 47,000–70,000 records per series
- **Source columns:** `timestamp` and `value`; `value` is a demand flow rate in m³/h
- **License:** Creative Commons Attribution 4.0 International (CC BY 4.0)
- **Source:** https://zenodo.org/records/19627517
- **Citation:** Sehmer, F., Hoffmann, M., Kloos, N., & Bergmann, R. (2026).
  *SOWEKI Water Demand Dataset*. Zenodo. https://doi.org/10.5281/zenodo.19627517

This is a genuine public measurement dataset, so it is suitable for testing
forecasting methods on data that was not invented for the demo. It is **not**
Nan'ao Island data, not desalination-plant production data, and not a guarantee
that a model trained here will generalize to islands or other utilities.

## Download and prepare one series

The adapter can download the public source directly; you do not need to find or
upload a data file yourself. From the repository root, run:

```bash
python experiments/prepare_soweki_water_demand.py --download --dataset-id 1 \
  --output build/water-demand-forecast/soweki_hourly.csv \
  --report build/water-demand-forecast/soweki_preparation.json
```

Choose any dataset ID from 1 to 11. The raw download is saved under
`build/water-demand-forecast/raw/` and the prepared hourly series is saved
separately. Alternatively, download a CSV manually from the
[Zenodo dataset page](https://zenodo.org/records/19627517) and pass its path
instead of `--download`.

The adapter converts the 15-minute series into the hourly format accepted by
`experiments/water_demand_forecast.py`. Four quarter-hour flow-rate samples
are averaged per hour. Because the source values are in m³/h, that mean rate
has the same numerical value as the volume in m³ over a one-hour interval.

### Missing data and time boundaries

The source intentionally retains some real-world data-quality issues. The adapter sorts records by timezone-normalized timestamp, deduplicates only rows with the exact same timestamp and numeric value, and rejects conflicting values for one timestamp rather than silently averaging them. The preparation report records raw row count, duplicate rows removed, source-order anomalies, and up to ten examples of invalid numeric values. Rows with blank, non-numeric, non-finite, or negative demand are excluded; any hour missing one or more valid quarter-hour samples is excluded as a whole. Conflicting duplicate timestamps remain a hard error. The
adapter does **not** interpolate missing quarter-hours. It excludes incomplete
hourly bins, then exports only the longest continuous run of complete hours,
because the forecast baseline rejects gaps. The JSON report records how many
hours were excluded and the selected time range. If the longest run has fewer
than 48 hours, the command fails instead of fabricating data; the minimum can
be adjusted with `--min-hours`, but never below 43 hours. This lower bound
leaves enough training history for the baseline's chronological split and
seasonal-error calibration.

After preparation, evaluate the actual-data baseline:

```bash
python experiments/water_demand_forecast.py \
  build/water-demand-forecast/soweki_hourly.csv \
  --output build/water-demand-forecast/soweki_forecast_report.json
```

Compare the result with the synthetic demo, but keep the results separate and
label the SOWEKI source in any chart or presentation. Use chronological
holdouts; do not shuffle the time series randomly. Inspect the dataset's
documented quality notes before interpreting forecast errors.

## Why this is a useful first step

A public measured dataset lets us check that the pipeline can handle real
patterns, real missingness, and outliers. It does not replace local historical
data: occupancy, tourism, weather, leakage, storage levels, and operating
policies may differ. When site-specific data eventually becomes available, it
should be evaluated separately and should determine which model is adopted.

### Verified reproducible example run

The public-data workflow was run successfully on 2026-10-23 for SOWEKI series 1. The evidence artifact is attached to [GitHub Actions run 39952100393](https://github.com/HaochuanLin/islandOS/actions/runs/39952100393). The prepared contiguous segment contained 5,533 hourly rows, with 1,384 rows in the chronological holdout.

| Forecast baseline | Holdout MAE (m³/h) | Holdout RMSE (m³/h) | Bias, forecast − actual (m³/h) |
|---|---:|---:|---:|
| Persistence (previous hour) | 1.0513 | 1.3948 | +0.0020 |
| Seasonal naive (24 hours) | 0.9751 | 1.3721 | −0.0098 |
| Bias-corrected seasonal naive | 0.9751 | 1.3721 | −0.0090 |

The training-history 90th-percentile threshold was 9.5195 m³/h. Among 103 holdout hours at or above that threshold, the underforecast rate was approximately 83.5% for all three baselines. Peak-period MAE was 1.5956 m³/h for persistence and about 2.01 m³/h for the seasonal variants. Thus, the seasonal baseline improved overall MAE but performed worse on this peak-demand subset.

These are results for one measured rural-German series and one chronological split. They do not demonstrate transfer to islands, Nan'ao, other seasons, or operational water-supply adequacy. Review the attached JSON artifact for source-quality counts, interval coverage, and limitations before using the metrics.


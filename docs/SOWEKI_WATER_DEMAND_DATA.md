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
- **Source columns:** \`timestamp\` and \`value\`; \`value\` is a demand flow rate in m³/h
- **License:** Creative Commons Attribution 4.0 International (CC BY 4.0)
- **Source:** https://zenodo.org/records/19627517
- **Citation:** Sehmer, F., Hoffmann, M., Kloos, N., & Bergmann, R. (2026).
  *SOWEKI Water Demand Dataset*. Zenodo. https://doi.org/10.5281/zenodo.19627517

This is a genuine public measurement dataset, so it is suitable for testing
forecasting methods on data that was not invented for the demo. It is **not**
Nan'ao Island data, not desalination-plant production data, and not a guarantee
that a model trained here will generalize to islands or other utilities.

## Download and prepare one series

1. Open the [Zenodo dataset page](https://zenodo.org/records/19627517).
2. Download one of the files named \`soweki_wdd_1.csv\` through
   \`soweki_wdd_11.csv\`. Do not rename or edit its columns.
3. From the repository root, run:

\`\`\`bash
python experiments/prepare_soweki_water_demand.py path/to/soweki_wdd_1.csv \\
  --output build/water-demand-forecast/soweki_hourly.csv \\
  --report build/water-demand-forecast/soweki_preparation.json
\`\`\`

The adapter converts the 15-minute series into the hourly format accepted by
\`experiments/water_demand_forecast.py\`. Four quarter-hour flow-rate samples
are averaged per hour. Because the source values are in m³/h, that mean rate
has the same numerical value as the volume in m³ over a one-hour interval.

### Missing data and time boundaries

The source intentionally retains some real-world data-quality issues. The
adapter does **not** interpolate missing quarter-hours. It excludes incomplete
hourly bins, then exports only the longest continuous run of complete hours,
because the forecast baseline rejects gaps. The JSON report records how many
hours were excluded and the selected time range. If the longest run has fewer
than 48 hours, the command fails instead of fabricating data; the minimum can
be adjusted with \`--min-hours\`, but never below 36.

After preparation, evaluate the actual-data baseline:

\`\`\`bash
python experiments/water_demand_forecast.py \\
  build/water-demand-forecast/soweki_hourly.csv \\
  --output build/water-demand-forecast/soweki_forecast_report.json
\`\`\`

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

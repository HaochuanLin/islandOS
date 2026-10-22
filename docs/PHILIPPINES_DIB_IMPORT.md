# Importing the Philippines DIB workbook

The workbook `RETransition_DIB_Dataset_08SEP2023.xlsx` supplied for the islandOS
data-integration experiment contains 208 screened mini-grid records and tables
for monthly power demand, monthly solar resource, monthly wind speed, diesel
capacity/operating hours, and future scenario outputs.

The workbook itself is **not committed to this repository**. This avoids
redistributing a file before its original source, attribution requirements, and
licence have been verified. Keep the original workbook locally and pass its
path to the importer.

## Run it

Install the small Excel reader dependency if it is not already installed:

```bash
python -m pip install -r requirements.txt
python experiments/import_philippines_dib_workbook.py \
  /path/to/RETransition_DIB_Dataset_08SEP2023.xlsx \
  --output-dir build/philippines-dib
```

The command writes:

| Output | What it contains |
|---|---|
| `sites.csv` | Grid ID, name, coordinates and daily schedule |
| `monthly_power_demand.csv` | 2022 monthly maximum, minimum and average load in MW |
| `monthly_ghi.csv` | Monthly global-horizontal-irradiance values, preserving the workbook's unit label verbatim |
| `monthly_wind_speed.csv` | Monthly wind-speed values at 10 m elevation |
| `diesel_assets.csv` | Generator/rental unit labels, dependable capacity and accumulated operating hours |
| `manifest.json` | Row counts, missing-average count, source sheets, caveats and suggested use |

The importer validates required worksheets, grid IDs, numeric values, non-negative
loads/resources/capacities, monthly minimum/average/maximum ordering, and cross-sheet
grid alignment. Missing average-load cells are preserved as blank and counted in the manifest; the importer fails loudly instead of silently fabricating missing values.

## Important interpretation limits

- This is a **monthly, cross-island planning dataset**, not a timestamped hourly
  operating history. Monthly averages cannot be expanded into genuine hourly
  training samples.
- The workbook's GHI column says `kW/m2`; the importer preserves that exact label
  instead of guessing whether it means irradiance or daily irradiation. Confirm
  the original methodology before using it in a physical PV model.
- Wind speed is stated at 10 m. Turbine hub-height estimates require an explicit
  conversion assumption or better data.
- Scenario/projection sheets are deliberately excluded from the normalized
  observational tables so scenario outputs are not mistaken for measured facts.
- The importer does not verify the original workbook's provenance, measurement
  method, or licence. Add a proper source citation and licence note before
  redistributing the source workbook or derived data publicly.
- There are no timestamped freshwater demand, desalination production, or tank
  inventory series in the imported tables. This workbook can help calibrate the
  **energy/planning** side; it cannot train the water-demand model by itself.

## Recommended next step

Use this workbook to profile variation across island grids and test monthly
scenario assumptions. For forecasting and forecast-aware dispatch, acquire
hourly/sub-hourly metered load and generation data. For the water side, seek
timestamped water demand, RO production, tank level, salinity/temperature, and
plant energy consumption. Keep measured data, modelled resource values, and
scenario projections in separate fields with source metadata.

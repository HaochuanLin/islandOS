# Importing the Mafate measured microgrid dataset

islandOS now supports a public, real-world time-series dataset from the
Roche Plate experimental stand-alone microgrid in Mafate, Reunion Island. The
data paper describes in-situ measurements from three homes and a PV/battery
system over approximately one year, with meteorology sampled about every 20
seconds and power/household channels about every minute.

- Dataset: [Zenodo record 8186303](https://zenodo.org/records/8186303)
- DOI: [10.5281/zenodo.8186303](https://doi.org/10.5281/zenodo.8186303)
- Data paper: Calogine, D., Francou, J., Abbezzot, C., & Tovondahiniriko, F.
  (2023). *Data in experimental stand-alone microgrid: solar production,
  domestic loads, battery storage and meteorological series*. Data in Brief,
  51, 109643. [https://doi.org/10.1016/j.dib.2023.109643](https://doi.org/10.1016/j.dib.2023.109643)
- License: Creative Commons Attribution 4.0 International (CC BY 4.0).
  Attribute the authors and dataset when using or redistributing it.

## Get the source files

Download these five archives from the Zenodo record and extract them into one
folder. The archive names end in `.7z`; the files inside should be named:

- `Meteo_dataset.csv`
- `Solar_plant_dataset.csv`
- `Demand_house_1_dataset.csv`
- `Demand_house_2_dataset.csv`
- `Demand_house_3_dataset.csv`

The importer can search subfolders under the input directory, so each archive
may be extracted into its own folder. The raw archives and measurements are
not committed to this repository.

## Run the importer

From the repository root:

```bash
python experiments/import_mafate_microgrid_data.py \
  --data-dir /path/to/extracted-mafate-files \
  --output-dir build/mafate
```

The script uses only Python's standard library. It writes:

| Output | Purpose |
|---|---|
| `meteo_hourly.csv` | Hourly mean of weather observations |
| `solar_plant_hourly.csv` | Hourly mean of PV, inverter and battery measurements |
| `house_loads_hourly.csv` | Hourly mean per-house load and per-channel readings, converted from W to kW |
| `microgrid_hourly.csv` | Combined hourly features for forecast experiments |
| `manifest.json` | Citation, licence, source row counts, per-file SHA-256 hashes, hourly coverage and limitations |

## Data handling and limits

- The script computes the arithmetic mean of the readings that exist in each
  hour. It does **not** interpolate missing measurements or convert average
  power into an energy total.
- The manifest records a SHA-256 digest for each of the five raw source CSVs.
  These hashes let reviewers verify that later experiments use byte-identical
  source files; they do not prove measurement accuracy or completeness.
- Source channels `Input4`, `Input5`, and `Input1` are treated as the total
  load for houses 1, 2, and 3 respectively, following the dataset README. The
  other channels represent different appliances in each house; their meanings
  are not interchangeable.
- The source README does not specify a timezone. Output timestamps preserve the
  source's timezone status, and the manifest flags this uncertainty. Confirm the
  timezone before using these values for real-time scheduling.
- This is one experimental microgrid and three homes, not a representative
  sample of all islands. It is useful for time-series pipeline testing, demand
  forecasting experiments, PV/battery model checks and hourly backtests, but
  results must not be presented as universal island performance.
- This dataset contains no freshwater demand, desalination production, or tank
  inventory. Water-side model training still needs separate operational data.

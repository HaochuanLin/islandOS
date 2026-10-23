## Project maturity and delivery gates

See [Engineering maturity roadmap](ENGINEERING_MATURITY_ROADMAP.md) for the scored targets, evidence requirements, and release gates.

# Experiments and workflows

This page is a command reference for the research workflows in islandOS. Run commands from the repository root after installing the required dependencies. Use `python` below for your active Python environment.

**Evidence boundary:** synthetic fixtures are for software checks and reproducible comparisons. They do not establish forecast accuracy or performance for any real island. For each external dataset, preserve its source, units, license, time zone, and preprocessing notes.

## Local app

```bash
pip install -r requirements.txt
streamlit run app.py
```

The Streamlit app supports a synthetic demo or uploaded hourly CSV, parameter editing, fixed-strategy comparisons, hourly audits, report downloads, and an experimental NSGA-II search. It is a planning prototype, not a real-time controller.

The strategy-comparison CSV requires these columns:

- `timestamp`: timestamp string, strictly increasing
- `renewable_surplus_kw`: available renewable surplus power in kW
- `diesel_displacement_potential_kw`: assumed potential to displace diesel generation, in kW
- `grid_price_per_kwh`: assumed price per kWh
- `off_peak`: whether the row is in the configured off-peak period (`true/false` or `1/0`)
- `grid_available`: whether grid supply is available (`true/false` or `1/0`)
- `water_demand_m3`: water demand for the row, in m³
- `backup_available_kw`: optional assumed backup power limit, in kW; defaults to zero when omitted

Use consistent intervals and site-appropriate units. The current app parser checks required fields, finite non-negative numeric values, flags, and increasing timestamps; it does not infer missing measurements or verify that the supplied data represent the actual site's physics.

## Core simulation and dispatch

### Original 24-hour RO demo

```bash
python island_microgrid_ro_sim.py
```

Runs the original synthetic wind/PV/load example, simplified rule-based RO dispatch, and freshwater inventory model. The output plot is illustrative.

### Compare flexible-load policies

```bash
python experiments/compare_dispatch_policies.py
python experiments/generate_dispatch_report.py --output-dir build/dispatch-report
```

The report workflow writes a Markdown summary, charts, CSV/JSON outputs, and an hourly audit for the configured synthetic scenarios. It checks accounting and configured bounds, not plant safety or site-specific feasibility.

### Rolling-horizon dispatch prototype

```bash
python experiments/rolling_horizon_dispatch.py
python experiments/forecast_error_robustness.py
```

These experiments compare replanning with fixed-priority strategies and examine forecast-error sensitivity. They use simplified scenarios and are not an operational controller.

### Parameter and objective sensitivity

```bash
python experiments/parameter_sensitivity.py path/to/site_hourly.csv --output build/parameter-sensitivity.json
python experiments/weight_sensitivity_audit.py
```

The parameter experiment evaluates selected equipment assumptions; the weight audit re-scores the same outcomes under alternative illustrative objective weights.

## Optimization and site data

### Search policy candidates

```bash
python optimization/grid_search_optimizer.py
python optimization/nsga2_dispatch_optimizer.py --json
python experiments/benchmark_nsga2_vs_exhaustive.py --scenario steady_surplus --output build/pareto-benchmark.json
```

The grid search covers a small configured policy space. NSGA-II is an experimental multi-objective evolutionary search, not a trained AI model. The Pareto benchmark measures search coverage in the configured finite space; it does not validate the underlying simulator.

### Run the optimizer on an hourly CSV

Start from `data/templates/site_hourly_input_template.csv`, fill it with site data, and run:

```bash
python experiments/run_nsga2_from_csv.py path/to/site_hourly.csv \
  --source-type measured \
  --output-dir build/site-optimization
```

Supported source labels include `measured`, `public`, `synthetic`, and `forecast`. The runner validates the schema, units and time ordering but does not repair missing records. Its standard input schema is different from the app's strategy-comparison schema; use the template and the [parameter guide](PARAMETER_CONFIGURATION.md). Outputs include `nsga2_results.json` and `pareto_front.csv`.

The optional annualized lifecycle-cost objective requires a complete calendar-year hourly series and all required cost fields. It is a first-pass estimate and omits costs documented in the parameter guide; do not use it as a bankable project assessment.

## Forecasting experiments

### Water-demand baselines and prediction intervals

```bash
python experiments/water_demand_forecast.py data/examples/synthetic_water_demand_demo.csv \
  --output build/water-demand-forecast/report.json
```

Compares simple chronological baselines, reports MAE/RMSE/bias, descriptive distribution diagnostics, and empirical prediction-interval coverage. The bundled data is synthetic.

### Compare water-demand ML against naive baselines

```bash
python experiments/compare_water_demand_models.py data/examples/synthetic_water_demand_demo.csv \
  --output build/water-demand-forecast/model-comparison.json
python experiments/backtest_water_demand_models.py data/examples/synthetic_water_demand_demo.csv \
  --initial-train-fraction 0.65 --test-window-hours 24 --step-hours 24 \
  --output build/water-demand-forecast/rolling-backtest.json
```

The optional gradient-boosting model is compared with previous-hour/day/week baselines. Repeated chronological backtests help show whether performance is stable across periods. Synthetic scores validate the workflow only, not real demand predictability.

For a public measured water-demand example, see the [SOWEKI guide](SOWEKI_WATER_DEMAND_DATA.md). That dataset is not island-specific and cannot validate a model for another site.

### Connect water-demand forecasts to dispatch

After producing a chronological water-demand model report, join its out-of-sample
predictions to the matching timestamps in a paired power/dispatch CSV:

```bash
python experiments/build_forecast_dispatch_input.py path/to/paired_power.csv \
  build/water-demand-forecast/model-comparison.json \
  --forecast-column hist_gradient_boosting \
  --output build/forecast-dispatch/paired-with-water-forecast.csv

python experiments/evaluate_forecast_dispatch.py \
  build/forecast-dispatch/paired-with-water-forecast.csv \
  --output build/forecast-dispatch/results.json
```

The paired power CSV must contain `timestamp_utc`, `actual_surplus_kw`,
`forecast_surplus_kw`, `water_demand_m3`, and `cooling_demand_kw_th`. Its actual
water-demand values must match the model report at the same timestamps. The
adapter normalizes timestamps to UTC, rejects mismatches and missing joins, and
writes only the forecast report's held-out rows. The simulator uses the forecast
for planning and the actual demand for execution and outcome scoring.

For `backtest_water_demand_models.py` reports, add `--fold N` to select one
continuous test window. This avoids combining separated backtest windows into a
CSV that the hourly dispatch evaluator would correctly reject. The adapter
does not train or update a model; it connects existing predictions to the
simulation. Synthetic power traces validate the software path only.

### Forecast-to-dispatch evaluation

```bash
python experiments/generate_synthetic_dispatch_benchmark.py --check
python experiments/evaluate_forecast_dispatch.py data/examples/synthetic_dispatch_benchmark.csv \
  --output build/forecast-dispatch-benchmark/results.json
python experiments/evaluate_forecast_dispatch_windows.py path/to/paired_hourly.csv \
  --window-hours 168 --output build/forecast-dispatch-windows.json
python experiments/evaluate_forecast_dispatch_continuous.py path/to/paired_hourly.csv \
  --output build/forecast-dispatch-continuous.json
```

The synthetic benchmark compares forecast-driven dispatch with fixed policies and a hindsight reference. For site data, the paired CSV must align actual and forecast surplus with water and cooling demand. The windowed evaluator resets inventories between windows; the continuous evaluator carries state forward. See [forecast-to-dispatch evaluation](FORECAST_DISPATCH_EVALUATION.md) and the [continuous backtest guide](CONTINUOUS_FORECAST_DISPATCH_BACKTEST.md).

### Weather-data baseline

```bash
python data_sources/nasa_power_hourly.py \
  --latitude -35.2 --longitude -63.5 \
  --start 20200101 --end 20200107 \
  --output data/raw/nasa_power_hourly.csv
python data_sources/prepare_environmental_features.py data/raw/nasa_power_hourly.csv \
  --output data/processed/nasa_environmental_features.csv
python experiments/forecasting_baselines.py data/raw/nasa_power_hourly.csv \
  --output data/processed/forecast_baselines.csv
python experiments/train_weather_forecaster.py data/processed/forecast_baselines.csv \
  --output data/processed/trained_weather_forecast.csv
```

The coordinates and dates are examples only. This workflow predicts environmental parameters from NASA POWER; it does not create measured island load, PV generation, or wind generation. Check the downloaded metadata and the [NASA POWER API documentation](https://power.larc.nasa.gov/docs/services/api/temporal/hourly/).

## Data preparation and quality checks

```bash
python data_quality.py path/to/data.csv --source-type public
python experiments/prepare_soweki_water_demand.py --download --dataset-id 1 \
  --output build/water-demand-forecast/soweki_hourly.csv
```

The data-quality checker validates supported time-series fields and intervals. The SOWEKI adapter prepares a public measured water-demand series as an hourly CSV without silently interpolating missing data. See [SOWEKI data notes](SOWEKI_WATER_DEMAND_DATA.md).

Other source-specific guides:

- [Mafate measured microgrid data import](MAFATE_MICROGRID_DATA.md)
- [Mafate load forecasting](MAFATE_LOAD_FORECAST.md)
- [Philippines DIB workbook import](PHILIPPINES_DIB_IMPORT.md)
- [Equipment and economic parameter configuration](PARAMETER_CONFIGURATION.md)

## Automated checks and artifacts

Run the core unit/regression suite:

```bash
python -m unittest discover -s tests -v
```

GitHub Actions also runs configured smoke checks, benchmark reproducibility checks, and generates downloadable artifacts when the workflow succeeds. Artifact reports are retained temporarily by GitHub Actions; consult the latest [workflow runs](https://github.com/HaochuanLin/islandOS/actions/workflows/ro-tests.yml).

A passing test means the checked software behavior is reproducible under the test conditions. It does not prove forecast skill, engineering safety, economic viability, or performance in a field deployment.

## Read-only telemetry replay and advice prototype

This optional subsystem is separate from the Streamlit demo and is intended for recorded-data replay and local operator review. It is not a live control system.

Validate/normalize a recorded CSV or JSON Lines stream:

```bash
python islandos_gateway.py data/examples/telemetry_replay_demo.csv --format csv --mapping configs/device_mapping.example.json --output build/telemetry/validated.jsonl
```

Generate a recommendation-only report:

```bash
python islandos_advisor.py data/examples/telemetry_replay_demo.csv --format csv --mapping configs/device_mapping.example.json --output build/telemetry/advisor-report.json
```

Start the local HTTP review dashboard:

```bash
python islandos_gateway_server.py --host 127.0.0.1 --port 8765 --audit-file build/telemetry/http-ingest-audit.jsonl
```

The HTTP server rejects non-loopback bind addresses. Optional bearer-token authentication uses `ISLANDOS_GATEWAY_TOKEN`; it is disabled by default, so do not expose the development service to untrusted networks. No PLC/setpoint writes or actuator commands are implemented. See [the telemetry contract](TELEMETRY_INTEGRATION_CONTRACT.md) for canonical fields, units, freshness, mapping, and security boundaries.

All included replay data is synthetic. A passing software test proves the tested software behavior only; it does not certify sensors, vendor mappings, plant interlocks, forecast quality, or site safety.

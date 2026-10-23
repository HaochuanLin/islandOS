# islandOS — Island Energy & Water Planning

<p align="center">
  <strong>Explore how renewable-energy surplus can support useful island resources.</strong><br>
  A simulation-first research toolkit for flexible-load dispatch, water–energy planning, and forecast evaluation.
</p>

<p align="center">
  <a href="https://github.com/HaochuanLin/islandOS/actions/workflows/ro-tests.yml"><img src="https://github.com/HaochuanLin/islandOS/actions/workflows/ro-tests.yml/badge.svg?branch=main" alt="Regression tests"></a>
  <img src="https://img.shields.io/badge/status-research%20prototype-orange" alt="Research prototype">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT license">
</p>

**Current status:** islandOS is an early-stage prototype. It includes a local interactive web app, simplified energy–water simulations, policy comparisons, optimization experiments, data-quality checks, and forecasting research. Some workflows remain separate prototypes; real-island performance is not validated and no field deployment is claimed.

<p align="center">
  <img src="assets/demo_en.png" alt="Illustrative synthetic islandOS simulation output" width="850">
</p>
<p align="center"><em>Synthetic illustration only—not field measurements or evidence of real-world savings.</em></p>

## Start here

### 1. Run the interactive web app

The Streamlit app lets you compare energy–water strategies without editing Python code.

~~~bash
git clone https://github.com/HaochuanLin/islandOS.git
cd islandOS
python -m venv .venv

# Windows PowerShell
.venv\Scripts\Activate.ps1

# macOS / Linux (use this instead of the Windows command)
source .venv/bin/activate

pip install -r requirements.txt
streamlit run app.py
~~~

Open the local URL printed in your terminal. The app includes an overview, strategy simulator, and data guide. You can run the labelled synthetic demo or upload a site CSV, adjust simplified RO/tank assumptions, compare policies, inspect hourly results, run an experimental NSGA-II search, and download CSV outputs.

See the [Web App Guide](docs/WEB_APP.md) for feature descriptions, required columns, interpretation boundaries, and troubleshooting.

### 2. Run the original command-line demo

~~~bash
python island_microgrid_ro_sim.py
~~~

This runs the original 24-hour synthetic reverse-osmosis (RO) demonstration and writes an illustrative plot.

### 3. Run tests

~~~bash
python -m unittest discover -s tests -v
~~~

The GitHub Actions workflow also runs regression tests and reproducible synthetic forecast/dispatch checks. Passing tests show that software checks pass; they do not establish real-site accuracy or engineering safety. [View workflow runs](https://github.com/HaochuanLin/islandOS/actions/workflows/ro-tests.yml).

## What it can do today

| Area | Current capability | Boundary |
|---|---|---|
| Energy–water simulation | Simplified RO production, freshwater inventory, and flexible-load scenarios | Not a complete island-grid or plant-physics model |
| Strategy comparison | Transparent fixed policies; water, energy, cost and hourly audit outputs | Results depend on input quality and configured assumptions |
| Optimization | Grid search and experimental NSGA-II Pareto search | Model-based search, not an AI model trained on island operating data |
| Interactive web app | CSV upload, editable assumptions, charts/tables, downloads | Local planning prototype, not a live controller |
| Forecast experiments | Water-demand baselines, rolling backtests, a small ML comparison, and weather-parameter baselines | Not yet an integrated, validated forecast-to-control system |
| Data workflows | CSV quality checks, NASA POWER weather import, Philippines DIB workbook import, and Mafate time-series import | Data sources have different resolutions and coverage; they are not interchangeable |

## Recommended workflow

1. Start with the synthetic demo to understand the interface and model.
2. Review the input schema and equipment assumptions before uploading site data.
3. Keep measured, public, forecast, and synthetic data clearly separated.
4. Compare candidate policies against simple baselines and inspect hourly constraints—not only aggregate scores.
5. Treat results as exploratory until validated against local measurements and reviewed by qualified operators.

## Bring your own site data

For the command-line site optimizer, start with [the hourly CSV template](data/templates/site_hourly_input_template.csv) and [example equipment parameters](config/site_parameters.example.json).

~~~bash
python experiments/run_nsga2_from_csv.py path/to/site_hourly.csv \
  --source-type measured \
  --output-dir build/site-optimization
~~~

The runner checks required fields, timestamps, spacing, and non-negative finite values. It does not silently fill missing observations. The input series must provide the required hourly renewable generation, essential load, water demand, and cooling demand fields. See the [parameter guide](docs/PARAMETER_CONFIGURATION.md) before interpreting results or costs.

## Forecasting and evaluation

Forecasting work is experimental and deliberately evaluated against transparent baselines before more complex models are trusted. The repository includes water-demand forecast comparisons and rolling chronological backtests, a small gradient-boosting comparison, and separate weather-parameter experiments. These are not yet one continuously learning system.

- [Water-demand forecasting baseline](docs/WATER_DEMAND_FORECAST.md)
- [Water-demand ML comparison](docs/WATER_DEMAND_ML_COMPARISON.md)
- [Rolling water-demand backtest](docs/WATER_DEMAND_ROLLING_BACKTEST.md)
- [Forecast-to-dispatch evaluation](docs/FORECAST_DISPATCH_EVALUATION.md)
- [Continuous forecast/dispatch backtest](docs/CONTINUOUS_FORECAST_DISPATCH_BACKTEST.md)
- [Mafate measured-load forecast](docs/MAFATE_LOAD_FORECAST.md)

## Data sources and experiment guides

- NASA POWER weather-data import — environmental parameters, not a direct renewable-generation forecast; see the data-source workflow in the repository.
- [Philippines DIB workbook importer](docs/PHILIPPINES_DIB_IMPORT.md)
- [Mafate measured microgrid data](docs/MAFATE_MICROGRID_DATA.md)
- [SOWEKI public water-demand data](docs/SOWEKI_WATER_DEMAND_DATA.md)
- [End-to-end synthetic benchmark](docs/END_TO_END_BENCHMARK.md)
- [NSGA-II versus exhaustive Pareto benchmark](docs/PARETO_BENCHMARK.md)
- [Energy–water strategy comparison](docs/ENERGY_WATER_STRATEGY_COMPARISON.md)
- [AI/research architecture and boundaries](docs/AI_ARCHITECTURE.md)

## Implementation status and limitations

**Implemented or runnable:** synthetic demo, local Streamlit interface, simplified freshwater accounting, flexible-load policy comparisons, candidate optimization, input validation, forecast baselines, and reproducible tests.

**Experimental or incomplete:** site-specific calibration, integrated forecast-aware dispatch, complete island-grid physics, detailed RO/cooling equipment dynamics, full economic/emissions modelling, and operator-reviewed safety constraints.

**Not claimed:** deployed autonomous control, validated island-wide savings, proven emissions reductions, battery-life extension, or reliable performance at a specific island. Synthetic examples are software fixtures, not evidence of real-world performance.

## Repository map

| Path | Purpose |
|---|---|
| app.py | Interactive Streamlit planning app |
| island_microgrid_ro_sim.py | Original synthetic RO demo |
| flexible_loads.py, dispatch_engine.py | Flexible-load models and shared-budget dispatcher |
| experiments/ | Reproducible simulation, optimization, and forecast experiments |
| optimization/ | Grid-search and NSGA-II optimization |
| data_sources/, data_quality.py | Data import and validation |
| docs/ | Detailed workflows, schemas, assumptions, and limitations |
| tests/ | Unit and regression tests |

## Development principles

- Make assumptions, units, provenance, and uncertainty explicit.
- Protect essential services and surface constraint violations.
- Compare new models against transparent baselines on chronological holdouts.
- Never present synthetic results as measurements or prototypes as validated deployments.

## License

MIT — see [LICENSE](LICENSE).

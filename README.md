# islandOS — Energy–Water Planning Prototype

<p align="center">
  <strong>Explore how renewable-energy surplus could support essential island resources.</strong><br>
  Simulation tools for flexible-load dispatch, water–energy planning, forecasting experiments, and policy comparison.
</p>

<p align="center">
  <a href="https://github.com/HaochuanLin/islandOS/actions/workflows/ro-tests.yml"><img src="https://github.com/HaochuanLin/islandOS/actions/workflows/ro-tests.yml/badge.svg?branch=main" alt="Regression tests"></a>
  <img src="https://img.shields.io/badge/status-research%20prototype-orange" alt="Research prototype">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT license">
</p>

**islandOS is an early-stage research prototype, not a deployed island control system.** It helps users explore when flexible loads—such as reverse-osmosis (RO) desalination and cold storage—might use renewable surplus while tracking water service, energy use, and simplified equipment constraints.

<p align="center">
  <img src="assets/demo_en.png" alt="Illustrative output from the synthetic islandOS simulation demo" width="900">
</p>
<p align="center"><em>Illustrative synthetic simulation only—not field measurements or evidence of real-island performance.</em></p>

## What it can do today

- **Interactive strategy screening:** choose synthetic demo data or upload hourly site data; adjust key RO and water-tank assumptions; compare strategies; inspect hourly outcomes; export results.
- **Energy–water dispatch experiments:** compare priority-based flexible-load policies, run a rolling-horizon prototype, and upload paired hourly power/water/cooling data to compare dispatch policies with a per-hour audit.
- **Multi-objective policy search:** use grid search or an experimental NSGA-II optimizer to inspect trade-offs among unmet water/cooling demand and remaining renewable surplus.
- **Forecasting experiments:** evaluate water-demand baselines and optional machine-learning models with chronological holdouts and rolling backtests.
- **Data preparation:** validate time-series CSVs and import selected public weather, measured microgrid, and monthly planning datasets with provenance notes.
- **Reproducible checks:** run unit/regression tests and synthetic benchmark workflows through GitHub Actions.

These tools are **not yet one fully integrated, validated forecast-and-control pipeline**. The forecasting experiments do not automatically provide validated island solar/wind generation and demand forecasts to a live controller.

## Try the interactive app

From the repository root:

```bash
python -m venv .venv
# Windows PowerShell:
.venv\\Scripts\\Activate.ps1
# macOS / Linux:
source .venv/bin/activate

pip install -r requirements.txt
streamlit run app.py
```

The app opens in your browser on your own machine. It is a local Streamlit application; this repository alone does not mean a public hosted website is available.

For a judge-ready walkthrough, see the [competition demo runbook](docs/COMPETITION_DEMO_RUNBOOK.md). It includes a repeatable short demo path, what outputs to inspect, and what the prototype cannot claim.

In the app, you can:
1. Use the clearly labeled synthetic demo or upload an hourly CSV.
2. Set RO power, specific energy, water-tank capacity and initial inventory, minimum run time, and optional cost assumptions.
3. Compare fixed operating strategies and review summary metrics, water outcomes, and hourly audit rows.
4. Run the experimental NSGA-II search, inspect feasible candidates and trade-offs, and download reports.
5. Download a CSV template from the data guide.

**Uploaded data:** the strategy-screening app expects `timestamp`, `renewable_surplus_kw`, `diesel_displacement_potential_kw`, `grid_price_per_kwh`, `off_peak`, `grid_available`, and `water_demand_m3`. The optional `backup_available_kw` column describes an assumed available backup-power limit. See [the app's data guide](docs/ENERGY_WATER_STRATEGY_COMPARISON.md); values and units must be appropriate for your site. Missing values are not silently imputed.

## Device integration prototype (recommendation-only)

The **Telemetry gateway** page and `islandos_gateway.py` add a first vendor-neutral ingest boundary. The gateway accepts CSV/JSONL, optionally maps vendor-specific field names and scales, checks timestamp freshness and measurement quality, and exports an audit trail. It does **not** open a PLC connection or write setpoints.

```bash
# Validate the included synthetic sample deterministically
python islandos_gateway.py data/examples/telemetry_replay_demo.csv \
  --format csv --max-age-seconds 7200 --received-at 2026-10-23T07:00:00Z \
  --output build/telemetry/replay-audit.jsonl

# Map a vendor export after editing the example point map for that device
python islandos_gateway.py vendor-export.jsonl \
  --mapping config/device_map.example.json \
  --output build/telemetry/mapped-audit.jsonl

# Validate, compare policies, and produce a recommendation-only report
python islandos_advisor.py data/examples/telemetry_replay_demo.csv \
  --max-age-seconds 7200 --received-at 2026-10-23T07:00:00Z \
  --output build/telemetry/advisor-report.json
```

Windows x64 standalone `islandos-gateway.exe` and `islandos-advisor.exe` are built by the [Windows gateway workflow](.github/workflows/windows-gateway-build.yml). The workflow also assembles and executes a portable `islandos-demo-package.zip` containing both programs, example telemetry, a field-mapping template, a double-click launcher, and usage/safety notes; it validates the generated JSON report before uploading the `islandos-gateway-windows-x64` artifact. The executable is an offline telemetry validator/replay tool, not a hardware driver. Real deployment still requires a site-approved point map, protocol adapter, authentication/network configuration, PLC interlocks, and hardware-in-the-loop validation. See [hardware integration architecture](docs/HARDWARE_INTEGRATION_ARCHITECTURE.md).

## Local HTTP telemetry ingress (read-only)

The optional `islandos_gateway_server.py` service accepts canonical JSON samples at `POST http://127.0.0.1:8765/telemetry`, validates freshness and required measurements, appends accepted records to JSONL, and exposes `GET /health`, `GET /latest`, and `GET /advice`. It binds to loopback only; it has no Modbus/MQTT client and no actuator-write endpoint. A device on the computer needs a local protocol bridge that posts the canonical fields. Do not expose the HTTP service directly to a LAN or public network.

Example payload:
```json
{
  "timestamp_utc": "2026-10-23T07:00:00Z",
  "renewable_surplus_kw": 18.5,
  "water_demand_m3": 3.2,
  "cooling_demand_kw_th": 6.5,
  "quality_flag": "good"
}
```

Run locally with `python islandos_gateway_server.py`. The Windows portable package includes `islandos-gateway-server.exe` and `run-gateway-server.bat`. `GET /advice` requires at least two valid hourly-aligned rows and a fresh latest sample; it runs the shared policy evaluator and returns a recommendation-only JSON report. Pass `--mapping config/device_map.example.json` after adapting the source keys to the device export. The HTTP server remains an ingress adapter only; hardware control remains out of scope.

## Run the web model in Docker

With Docker installed, run `docker compose up --build` and open `http://127.0.0.1:8501`. The supplied Compose file binds to loopback only. Do not expose the app to a LAN or public network without adding authentication, network restrictions, and a site-approved security review. A separate CI workflow builds the image and probes Streamlit's health endpoint.

## Quick start: command-line demo

To run the original 24-hour synthetic RO demo instead of the app:

```bash
pip install -r requirements.txt
python island_microgrid_ro_sim.py
```

For a compact reference to the other experiments, see [Experiments and workflows](docs/EXPERIMENTS_AND_WORKFLOWS.md).

## Documentation

| Topic | Guide |
|---|---|
| Interactive app inputs and strategy assumptions | [Energy–water strategy comparison](docs/ENERGY_WATER_STRATEGY_COMPARISON.md) |
| Forecast evaluation connected to dispatch experiments | [Forecast-to-dispatch evaluation](docs/FORECAST_DISPATCH_EVALUATION.md) |
| Continuous, state-carrying dispatch backtests | [Continuous backtest guide](docs/CONTINUOUS_FORECAST_DISPATCH_BACKTEST.md) |
| Water-demand forecasting and interval checks | [Water-demand forecast baseline](docs/WATER_DEMAND_FORECAST.md) |
| Forecast performance monitoring after actuals arrive | [Forecast monitoring](docs/WATER_DEMAND_FORECAST_MONITORING.md) |
| Compare incumbent and candidate water forecasts before model changes | [Candidate review gate](docs/WATER_DEMAND_CANDIDATE_REVIEW.md) |
| Water-demand uncertainty in dispatch | [Water-demand uncertainty dispatch](docs/WATER_DEMAND_UNCERTAINTY_DISPATCH.md) |
| Compare water-demand machine learning with simple baselines | [Water-demand model comparison](docs/WATER_DEMAND_ML_COMPARISON.md) |
| Public measured water-demand dataset and preparation | [SOWEKI dataset guide](docs/SOWEKI_WATER_DEMAND_DATA.md) |
| Train and evaluate measured household-load forecasts | [Mafate load-forecast guide](docs/MAFATE_LOAD_FORECAST.md) |
| Import measured Mafate microgrid time series | [Mafate data guide](docs/MAFATE_MICROGRID_DATA.md) |
| Import the Philippines DIB workbook | [DIB import guide](docs/PHILIPPINES_DIB_IMPORT.md) |
| Equipment and economic assumptions | [Parameter configuration](docs/PARAMETER_CONFIGURATION.md) |
| Synthetic benchmark protocol | [End-to-end benchmark](docs/END_TO_END_BENCHMARK.md) |
| Optimizer comparison methodology | [Pareto benchmark](docs/PARETO_BENCHMARK.md) |
| More runnable commands | [Experiments and workflows](docs/EXPERIMENTS_AND_WORKFLOWS.md) |

## Current maturity

| Capability | Status |
|---|---|
| Synthetic RO demo and water-inventory accounting | Implemented with simplified physics |
| Interactive strategy comparison and hourly audit | Available as a local Streamlit prototype |
| Flexible-load dispatch and multi-objective optimization | Experimental; limited candidate space and simplified plant models |
| Public-data import and time-series quality checks | Implemented for selected data sources and formats |
| Water-demand forecasting | Baselines and optional ML comparison/backtesting; site accuracy not established |
| Weather-parameter forecasting | Experimental; not an island PV, wind, or electricity-demand forecast |
| Integrated forecast-aware island controller | Not implemented as a validated end-to-end system |
| Live equipment control, site safety validation, and field-proven savings | Not available |

## Important limitations

- Simulation and benchmark fixtures are synthetic unless a dataset is explicitly identified as measured or public.
- Public data from another site can test the data pipeline, but it does not establish accuracy for Nan'ao or any other island.
- The RO and cold-storage models simplify real equipment behavior; the full island electrical system, battery dispatch, network constraints, protection, and plant interlocks are not comprehensively modelled.
- Optimizer results are candidate trade-offs under declared assumptions, not guaranteed operating schedules or safety approvals.
- Cost estimates are preliminary and omit several project-specific financial and operational factors. No field-proven savings, emissions reductions, or resilience gains are claimed.

## Run tests

```bash
python -m unittest discover -s tests -v
```

GitHub Actions runs additional regression and reproducibility checks. A passing test verifies software behavior—not model accuracy, engineering feasibility, or real-world benefit.

## Development principles

1. Keep data provenance, units, and assumptions explicit.
2. Protect essential services and report constraint violations.
3. Compare complex models against transparent baselines on chronological holdouts.
4. Label synthetic, public, forecast, and measured data correctly.
5. Do not present experimental code as a deployed or validated AI system.

## License

MIT — see [LICENSE](LICENSE).


The advisor compares four policies and checks sensitivity across four declared objective-weight profiles. It recommends only among operational policies with zero reported constraint-violation hours; if none is feasible, it requests operator review and returns no recommendation. This remains decision support, not a control command.

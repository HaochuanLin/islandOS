# islandOS — AI Island Energy Brain

> **An AI-driven resource orchestration and simulation platform for isolated island microgrids.**

IslandOS explores how software intelligence can coordinate renewable generation, essential electricity demand, and flexible resource production on isolated islands. Its core idea is to turn otherwise-curtailed renewable electricity into useful local resources—starting with freshwater and potentially extending to cooling, fuel, public services, and deferrable computing.

**Current status: early-stage, simulation-only MVP.** The original demo simulates renewable curtailment, rule-based reverse-osmosis (RO) desalination dispatch, and freshwater reservoir dynamics using synthetic data. The development branch also contains experimental RO/cold-storage plug-ins and a shared-budget dispatcher. Forecasting, AI-driven planning, and multi-objective optimization are not yet implemented.

## Why IslandOS?

Isolated and remote communities may face expensive imported fuel, limited freshwater infrastructure, variable renewable generation, and challenging marine operating conditions. When wind and solar generation exceed immediate electricity demand, some renewable energy may be curtailed.

IslandOS investigates a software-first approach: predict when flexible energy may be available, then schedule compatible loads to produce useful resources without compromising essential electricity supply or equipment constraints.

The project aims to **reduce avoidable renewable curtailment and explore alternatives to relying exclusively on chemical batteries**. It does not assume that water, ice, hydrogen, or computing can replace batteries in every situation; each pathway must be evaluated against its own physical, economic, safety, and infrastructure constraints.

## The IslandOS concept

**IslandOS = Forecast + Plan + Orchestrate + Simulate + Evaluate**

1. **Forecast** renewable generation, essential demand, and resource needs over a rolling time horizon.
2. **Plan** feasible schedules for flexible loads while respecting essential-service priorities and equipment constraints.
3. **Orchestrate** when and how much electricity is allocated to each compatible load.
4. **Simulate** the resulting energy and resource flows.
5. **Evaluate** candidate schedules against transparent baselines and measurable metrics.

## The first MVP: water–energy co-simulation

The original Python prototype generates 24-hour synthetic wind, solar PV, base-load, and water-demand series; estimates potential surplus as max(0, wind + PV - base_load); dispatches a rule-based RO plant; enforces a simplified minimum continuous run duration; tracks freshwater production and reservoir inventory; and plots the results.

**Important physical distinction:** stored freshwater is used for water supply. It is not converted back into electricity. Producing water during surplus periods shifts electricity consumption in time; it does not make the reservoir an electrical battery.

## Pluggable flexible loads

| Module | Potential use | Status on development branch |
|---|---|---|
| RO desalination | Produce freshwater and build a water buffer | Experimental plug-in; legacy demo remains separate |
| Ice making / cold storage | Support fisheries, food preservation, and cooling demand | Simplified experimental plug-in |
| Green hydrogen | Produce hydrogen where equipment, safety, storage, and offtake are credible | Planned |
| Municipal services | Shift eligible wastewater or waste-handling loads | Planned |
| Deferrable computing | Run interruptible compute jobs during suitable surplus windows | Planned |

These are candidate extensions, not interchangeable loads. Each module needs explicit power limits, conversion efficiency, operating windows, equipment constraints, storage capacity, demand, and safety requirements.

## Shared-budget dispatcher (experimental)

The development branch adds dispatch_engine.py, a transparent priority-based dispatcher. It gives each load only the renewable surplus left by higher-priority loads, reports backup power separately, and checks this conservation identity:

~~~text
initial available surplus = renewable power allocated + remaining surplus
~~~

Example:

~~~python
from dispatch_engine import dispatch_flexible_loads
from flexible_loads import IceStorageLoad, ROWaterLoad, ROConfig

ro = ROWaterLoad(ROConfig(allow_backup_power=False))
ice = IceStorageLoad()

result = dispatch_flexible_loads(
    available_power_kw=[500, 350, 600],
    requests=[
        (ro, [10, 10, 10]),  # earlier entries have higher priority
        (ice, [0, 100, 100]),
    ],
)
print(result.remaining_power_kw)
print(result.loads.keys())
~~~

The order in requests is an explicit priority policy, not an optimized schedule. The dispatcher allocates flexible loads against renewable surplus only; it does not model a complete island electrical network, battery, or generator dispatch. RO look-ahead is derived from the supplied future series after higher-priority loads are scheduled, so this remains a perfect-foresight simulation rather than an operational forecast.

## AI and optimization roadmap

IslandOS is intended to become AI-enabled through measurable forecasting and decision-making—not by labelling a fixed rule as AI.

1. **Reliable simulation:** validate energy and water balances and equipment constraints.
2. **Forecasting baseline:** compare simple forecasts against held-out data and report errors.
3. **Rolling-horizon planning:** plan over a future window, execute the near-term decision, then re-plan.
4. **Multi-objective optimization:** evaluate NSGA-II or multi-objective simulated annealing for trade-offs among cost, reliability, curtailment, and any defensible battery degradation model.
5. **Scenario evaluation:** compare rule-based and optimized strategies across weather, demand, and forecast-error scenarios.

No algorithm is assumed to guarantee a global optimum or the complete true Pareto front. Every candidate schedule must be checked by the same simulator, and any final recommendation must come from the evaluated feasible set using an explicit decision rule.

## Evaluation metrics

| Metric | Purpose |
|---|---|
| Renewable curtailment (kWh) | Measure unused renewable energy |
| Essential load not served (kWh) | Check electricity-service reliability |
| Flexible-load energy (kWh) | Track electricity allocated to each module |
| Freshwater produced / unmet water demand (m³) | Measure water-service performance |
| Operating cost | Include only after defining cost inputs |
| Battery degradation proxy | Include only with a defensible model |
| Constraint violations | Verify equipment and service constraints |
| Forecast error | Test whether forecasts improve on a baseline |

Lower curtailment alone does not prove a better system if essential service, resource delivery, or equipment constraints worsen.

## Demo assumptions

The existing demo uses synthetic data and simplified assumptions. Results are illustrative model outputs, not measurements from a real island.

- RO rated power: 400 kW
- RO specific energy consumption: 3.5 kWh/m³
- Minimum continuous run duration: 2 hours
- Reservoir capacity: 3,000 m³
- Initial reservoir storage: 800 m³
- Simulation horizon: 24 hours

The project does not yet quantify lifecycle cost, emissions reductions, avoided battery replacement, or real-world resilience improvements.

## Quick start

~~~bash
git clone https://github.com/HaochuanLin/islandOS.git
cd islandOS
python -m venv .venv
# Windows:
.venv\\Scripts\\activate
# macOS / Linux:
source .venv/bin/activate
pip install -r requirements.txt
python island_microgrid_ro_sim.py
~~~

The script runs the original 24-hour synthetic demo and saves island_microgrid_ro.png.

Run all regression tests, including the plug-in and shared-budget tests:

~~~bash
python -m unittest discover -s tests -v
~~~

## Repository status

| Capability | Status |
|---|---|
| Synthetic hourly wind / PV / load inputs | Implemented |
| Rule-based RO dispatch in original demo | Implemented |
| Simplified reservoir water balance | Implemented |
| RO and cold-storage plug-in prototypes | Experimental |
| Shared renewable-surplus budget dispatcher | Experimental; priority-based |
| Regression tests and GitHub Actions workflow | Implemented for selected invariants |
| Real weather / terrain / load data adapters | Planned |
| Forecasting and rolling-horizon AI planning | Planned |
| Multi-objective Pareto search | Planned |
| Hydrogen, municipal, and compute modules | Planned |
| Field deployment and measured validation | Not available |

## Limitations and responsible claims

- The data generator is synthetic; no real island dataset or field deployment is included.
- The original RO start rule uses future values from the generated series. This is a perfect-foresight simplification, not a deployable forecast.
- The experimental dispatcher is sequential and priority-based; it does not optimize priorities or jointly optimize all load decisions.
- The plug-in RO model is not numerically identical to the legacy simulator and is not a validated plant model.
- The cold-storage model omits thermal leakage, temperature-dependent COP, compressor cycling, and site-specific refrigeration constraints.
- RO membrane flushing, fouling, variable-load behaviour, and ageing are not fully modelled.
- Reservoir dynamics omit site-specific factors including pumping energy, water quality, leakage, and evaporation.
- A complete grid, diesel-generator, and battery dispatch model is not implemented.
- Cost, emissions, battery-life extension, and social impact have not been quantified.

Impact statements describe project goals and hypotheses to test, not verified outcomes. Real deployment would require site-specific engineering, data validation, safety review, and operational oversight.

## Contributing and development

See docs/AI_ARCHITECTURE.md for module boundaries, the optimization workflow, and staged implementation. New features should include tests, explicit assumptions, and baseline comparisons.

## License

Released under the MIT License. See LICENSE for details.

## Latest engineering update: shared-budget dispatch

The development branch now includes dispatch_engine.py, which runs the experimental RO and cold-storage plug-ins in a caller-defined priority order. Each load sees only the residual renewable surplus after previous loads have been dispatched. The dispatcher verifies that allocated renewable power plus remaining surplus equals the initial available surplus, and it accounts for backup power separately.

Regression tests in tests/test_dispatch_engine.py cover priority effects, power-budget conservation, separate backup accounting, duplicate module names, and invalid inputs. This is not an optimizer or field validation.


## Latest engineering update: reproducible policy comparison

Run the synthetic baseline experiment from the repository root:

~~~bash
python experiments/compare_dispatch_policies.py
python experiments/compare_dispatch_policies.py --json
~~~

The experiment compares RO-only, cold-storage-only, RO-first, and cold-storage-first dispatch across three fixed synthetic surplus profiles. It reports flexible-load renewable energy, remaining surplus, backup energy, water production/shortage, cooling served/shortage, and modelled constraint-violation hours. Automated tests check aligned inputs, all policy/scenario combinations, non-negative metrics, and deterministic repeatability.

**Interpretation limit:** these profiles are illustrative, not measured island data. The experiment does not establish that either priority order is universally best, and it does not yet compare against a mathematically optimized schedule or a full grid/battery/generator model.


## Latest engineering update: connected grid-search optimizer

Run a small, reproducible search over eight candidates:

~~~bash
python optimization/grid_search_optimizer.py
python optimization/grid_search_optimizer.py --scenario steady_surplus --json
~~~

The search varies the order of RO and cold storage and four RO minimum-run durations (1–4 hours). Each candidate is evaluated by the same shared-budget simulator. The code filters infeasible candidates, constructs a non-dominated archive for water shortage, unmet cooling, and remaining renewable surplus, then selects its recommendation from that exact archive using disclosed normalized weights.

This is an **exhaustive grid search over a small policy space**, not machine learning, NSGA-II, or a global optimum over all hourly schedules. It is a first connected optimization baseline. The objectives and weights are illustrative; changing service priorities may change the recommendation. All current scenarios remain synthetic.


## Latest engineering update: physical-balance regression checks

The RO plug-in now refuses to initiate a new minimum-run cycle when fewer than the required run hours remain in the simulation horizon. Configuration validation also requires a finite RO start ratio in [0, 1] and finite positive rated power / specific energy. Regression tests check per-step freshwater inventory conservation, cold-storage inventory conservation, demand served plus unmet demand, storage bounds, and the late-horizon start edge case.

These checks strengthen internal consistency; they do not establish that the simplified models accurately represent a real desalination plant or industrial cold store.


## Forecast-error robustness experiment (synthetic)

Run the deterministic policy-selection sensitivity experiment:

~~~bash
python experiments/forecast_error_robustness.py
python experiments/forecast_error_robustness.py --json
~~~

It evaluates three synthetic surplus profiles under four relative forecast-error patterns: perfect, +20% overforecast, -20% underforecast, and alternating +/-20%. The optimizer selects a candidate using the perturbed profile; that candidate and a fixed-priority baseline are then evaluated against the original profile. A perfect-information result is included as a hindsight reference, not an achievable online policy.

**Important limitation:** the current dispatcher is reactive to the per-step available-power series. This experiment tests how forecast perturbations change policy selection; it does not simulate a fixed hourly schedule committed from a forecast, nor does it validate a trained forecasting model. All data are synthetic.


## Forecast-error robustness experiment (synthetic)

Run the deterministic policy-selection sensitivity experiment:

~~~bash
python experiments/forecast_error_robustness.py
python experiments/forecast_error_robustness.py --json
~~~

It evaluates three synthetic surplus profiles under four relative forecast-error patterns: perfect, +20% overforecast, -20% underforecast, and alternating +/-20%. The optimizer selects a candidate using the perturbed profile; that candidate and a fixed-priority baseline are then evaluated against the original profile. A perfect-information result is included as a hindsight reference, not an achievable online policy.

**Important limitation:** the current dispatcher is reactive to the per-step available-power series. This experiment tests how forecast perturbations change policy selection; it does not simulate a fixed hourly schedule committed from a forecast, nor does it validate a trained forecasting model. All data are synthetic.


## Rolling-horizon dispatch prototype

Run:

~~~bash
python experiments/rolling_horizon_dispatch.py
python experiments/rolling_horizon_dispatch.py --json
~~~

At each hour, the prototype scores the two load priority orders over a three-hour forecast window, executes only the first-hour decision against realized surplus, carries freshwater and cold-storage inventories forward, and replans. It compares this rolling policy with fixed priority orders and a perfect-information hindsight reference across synthetic forecast-error cases.

Limitations: synthetic profiles only; no trained forecasting model; RO minimum-run commitment is not modeled in this prototype; the perfect-information reference is not deployable. This is an experimental closed-loop control scaffold, not a site-ready controller.


The rolling-horizon experiment now prints a case-level normalized score comparison between the rolling policy and both fixed priority policies. Lower scores are better; negative `rolling_minus_best_fixed` means the rolling policy scored better than the best fixed policy in that specific synthetic case. The weights (water unmet 0.45, cooling unmet 0.45, remaining surplus 0.10) are illustrative, not validated stakeholder preferences. Do not generalize one case to all islands.


## Objective-weight sensitivity audit

Run `python experiments/weight_sensitivity_audit.py` or add `--json` for machine-readable output. The audit re-scores the same 12 synthetic scenario/error outcomes under five illustrative weight sets: balanced reliability, water priority, cooling priority, surplus priority, and equal objectives. It reports rolling-policy wins/ties/losses against the best of the two fixed priority policies, plus mean and range of score differences. This isolates sensitivity to scoring preferences; it does not validate the simulation physics or establish real stakeholder priorities.


## CSV time-series data quality gate

IslandOS now includes a strict CSV validator for hourly inputs. It expects these columns and units:

| Column | Unit |
|---|---|
| `timestamp` | ISO-8601 timestamp with timezone |
| `wind_kw` | kW |
| `pv_kw` | kW |
| `critical_load_kw` | kW |
| `water_demand_m3` | m³ per time step |
| `cooling_demand_kw_th` | kW thermal |

Run it before importing a dataset:

~~~bash
python data_quality.py path/to/data.csv --source-type public
python data_quality.py path/to/data.csv --source-type measured --json
~~~

The source label is required and must be one of `measured`, `public`, `synthetic`, or `forecast`. The validator checks required/duplicate headers, empty fields, numeric/finite/non-negative values, timezone-aware timestamps, duplicate or non-monotonic timestamps, and expected time-step spacing (60 minutes by default; configurable with `--interval-minutes`). It exits non-zero on invalid input and reports issues rather than silently cleaning data.

Important: column names do not guarantee unit correctness. Users must confirm units and provenance from the source documentation. The validator does not perform unit conversion, imputation, interpolation, capacity plausibility checks, or leakage analysis; passing validation is a structural quality check, not proof that data are authentic or suitable for operational decisions.


## Public environmental data: NASA POWER hourly importer

NASA POWER publishes hourly solar and meteorological time series through its official API. IslandOS includes a small importer for three environmental parameters: `ALLSKY_SFC_SW_DWN`, `T2M`, and `WS10M`. The importer requests UTC timestamps and writes both a CSV and a sidecar JSON containing the request, location, download time, response metadata, and limitations.

~~~bash
python data_sources/nasa_power_hourly.py \
  --latitude -35.2 --longitude -63.5 \
  --start 20200101 --end 20200107 \
  --output data/raw/nasa_power_hourly.csv
~~~

The coordinates and dates above are an example only; replace them with a study site and period. See the [NASA POWER hourly API documentation](https://power.larc.nasa.gov/docs/services/api/temporal/hourly/).

**Important boundary:** this import supplies environmental covariates, not measured wind/PV generation or island demand. It does not manufacture missing load/water/cooling data, convert units, or claim site-level accuracy. Check parameter units in the response metadata before conversion. The output uses a distinct schema and is not the canonical six-column operational dataset accepted by `data_quality.py`; additional validated load/resource data and an explicit alignment/feature-engineering step are required before simulation.

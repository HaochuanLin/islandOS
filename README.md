# islandOS — AI Island Energy Brain

> **An AI-driven resource orchestration and simulation platform for isolated island microgrids.**

IslandOS explores how software intelligence can coordinate renewable generation, essential electricity demand, and flexible resource production on isolated islands. Its core idea is to turn otherwise-curtailed renewable electricity into useful local resources—starting with freshwater and potentially extending to cooling, fuel, public services, and deferrable computing.

**Current status: early-stage, simulation-only MVP.** The implemented prototype simulates renewable curtailment, rule-based reverse-osmosis (RO) desalination dispatch, and freshwater reservoir dynamics using synthetic data. Forecasting, AI-driven planning, multi-objective optimization, and additional load modules are development goals—not capabilities claimed as already implemented.

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

The long-term vision is a configurable software “energy brain” that can adapt to different islands through data adapters, load modules, and site-specific constraints.

## 1 + N architecture

### The “1”: simulation and decision core

The planned core architecture contains:

- **Data layer:** renewable generation, base load, water demand, weather forecasts, and optional site metadata.
- **Forecasting layer:** baseline forecasts first, with machine-learning models evaluated only when data and validation support them.
- **Planning layer:** rule-based baselines and optimization algorithms that compare feasible schedules.
- **Simulation layer:** time-step energy balance, flexible-load operation, resource inventories, and constraint checks.
- **Evaluation layer:** cost, renewable curtailment, unmet essential demand, resource shortages, equipment cycling, and other explicitly modelled metrics.
- **Explanation layer:** show why a load was selected, which constraints were active, and how candidate schedules differ.

### The first MVP: water–energy co-simulation (implemented)

The current Python prototype:

- Generates 24-hour synthetic wind, solar PV, base-load, and water-demand time series.
- Estimates potential surplus as max(0, wind + PV - base_load).
- Dispatches an RO desalination plant as a flexible load using a rule-based heuristic.
- Models a minimum continuous RO run duration.
- Tracks freshwater production and a simplified upland-reservoir water balance.
- Plots renewable output, curtailment, RO operation, and reservoir level.

**Important physical distinction:** stored freshwater is used for water supply. It is not converted back into electricity. Producing water during surplus periods shifts electricity consumption in time; it does not make the reservoir an electrical battery.

### “N”: pluggable flexible-load modules (planned)

| Module | Potential use of flexible electricity | Status |
|---|---|---|
| RO desalination | Produce freshwater and build a water buffer | Implemented as a simplified simulation |
| Ice making / cold storage | Support fisheries, food preservation, and cooling demand | Planned |
| Green hydrogen | Convert electricity to hydrogen when technically and economically feasible | Planned |
| Municipal services | Shift eligible wastewater treatment or waste-handling loads | Planned |
| Deferrable computing | Run interruptible compute jobs during suitable surplus windows | Planned |

These are candidate extensions, not interchangeable loads. Each module must specify its power limits, conversion efficiency, operating windows, ramping or minimum-run constraints, storage capacity, demand or offtake, and safety requirements. Hydrogen production requires appropriate equipment, storage, safety controls, and a credible use case; it should not be enabled merely because electricity is available.

## AI and optimization roadmap

IslandOS is intended to become AI-enabled through measurable forecasting and decision-making—not by adding a chatbot or labelling a fixed rule as AI.

1. **Reliable simulation foundation:** validate energy and water balances; make equipment constraints explicit; test edge cases.
2. **Forecasting baseline:** compare simple persistence or statistical forecasts against held-out synthetic or real time-series data. Report forecast errors and disclose data limitations.
3. **Rolling-horizon planning:** plan over a future window, execute only the near-term decision, then re-plan when observations or forecasts update.
4. **Multi-objective optimization:** evaluate methods such as NSGA-II or multi-objective simulated annealing for trade-offs among operating cost, reliability, curtailment, and modelled battery degradation.
5. **Load plug-ins:** implement and test one additional module, preferably ice making/cold storage, before expanding to more complex pathways.
6. **Scenario evaluation:** compare the rule-based baseline and optimized strategies across multiple weather, demand, and forecast-error scenarios.

No optimization method is assumed to guarantee a globally optimal schedule or the complete true Pareto front. Candidate schedules must be checked against the same simulator and constraints. A final recommendation should be selected from the evaluated feasible candidate set, with its decision criteria made explicit.

## Evaluation: prove improvement against a baseline

The project should report metrics only when their definitions and model assumptions are explicit.

| Metric | What it helps evaluate |
|---|---|
| Renewable curtailment (kWh) | How much potential renewable energy remains unused |
| Essential load not served (kWh) | Whether essential electricity demand is unmet |
| Flexible-load energy (kWh) | How much electricity is allocated to each module |
| Freshwater produced / unmet water demand (m³) | Water-service performance |
| Operating cost | Economic performance, once cost inputs are defined |
| Battery degradation proxy | Storage impact, only if a defensible degradation model is implemented |
| Constraint violations | Whether equipment and service constraints are respected |
| Forecast error | Whether forecasts improve on an appropriate baseline |

A lower curtailment number alone does not prove a better system. A schedule must also preserve essential services, satisfy resource needs, obey equipment limits, and account for the cost and consequences of running each flexible load.

## Demo results and assumptions

The existing demo uses synthetic data and simplified assumptions. The figures are illustrative model outputs, not measurements from a real island and not evidence of field performance.

- RO rated power: 400 kW
- RO specific energy consumption: 3.5 kWh/m³
- Minimum continuous run duration: 2 hours
- Reservoir capacity: 3,000 m³
- Initial reservoir storage: 800 m³
- Simulation horizon: 24 hours

The current model does **not** yet quantify lifecycle cost, emissions reductions, battery replacement avoided, or real-world resilience improvements.

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

The script runs the 24-hour synthetic demo and saves island_microgrid_ro.png.

To use the existing simulator from Python:

~~~python
import island_microgrid_ro_sim as m

params = m.Params(allow_backup_power=False, min_run_hours=2)
wind, pv, load, water_demand = m.load_data(24)
result = m.simulate(wind, pv, load, water_demand, params)

runs, constraints_ok = m.check_min_run(
    result["ro_on"], params.min_run_hours
)
print("RO run segments:", runs)
print("Minimum-run constraint satisfied:", constraints_ok)
~~~

To use custom time series, pass equally sized arrays for wind, PV, base load (kW), and water demand (m³/h).

## Repository status

| Capability | Status |
|---|---|
| Synthetic hourly wind / PV / load inputs | Implemented |
| Rule-based RO dispatch | Implemented |
| Simplified reservoir water balance | Implemented |
| Constraint checking for RO minimum run | Basic check implemented; edge cases need further testing |
| Real weather / terrain / load data adapters | Planned |
| Forecasting model | Planned |
| Rolling-horizon AI planning | Planned |
| Multi-objective Pareto search | Planned |
| Ice, hydrogen, municipal, and compute modules | Planned |
| Field deployment and measured validation | Not available |

## Limitations and responsible claims

- The current data generator is synthetic; no real island dataset or field deployment is included.
- The RO start rule uses future values from the generated time series to evaluate its start window. This is a perfect-foresight simplification, not a deployable forecast.
- The current RO model is simplified and does not fully model membrane flushing, fouling, variable-load behaviour, or membrane ageing.
- Reservoir dynamics omit several site-specific factors, including pumping energy, water quality, leakage, and evaporation.
- The current prototype does not include a complete grid, diesel-generator, or battery dispatch model.
- Cost, emissions, battery-life extension, and social impact have not yet been quantified.
- Additional load modules, standardised APIs, and hosted services are not implemented.

Impact statements in this repository describe project goals and hypotheses to test, not verified outcomes. Real deployment would require site-specific engineering, data validation, safety review, and operational oversight.

## Contributing and development

See docs/AI_ARCHITECTURE.md for the proposed module boundaries, optimization workflow, and staged implementation plan. New features should include tests, explicit assumptions, and baseline comparisons.

## License

Released under the MIT License. See LICENSE for details.


## Latest engineering update: RO startup feasibility and regression tests

The development branch includes a correction to the **no-backup-power** RO startup rule. Previously, a start window could pass a mean-curtailment threshold even when one hour in the minimum-run window had less than the RO rated power; that could force an early stop and violate the minimum-run constraint. In no-backup mode, a start is now permitted only when every hour in the proposed minimum-run window has at least the rated power available as curtailment. Backup-enabled mode retains the mean-based startup heuristic because backup power can cover shortfalls.

Regression tests were added for:
- avoiding infeasible no-backup startup windows;
- respecting minimum-run segments in feasible no-backup cases;
- accounting for backup energy during forced-run shortfalls;
- refusing to start when the minimum run cannot fit within the simulation horizon;
- reservoir storage bounds and overflow accounting; and
- mismatched input-array lengths.

A GitHub Actions workflow runs the unit-test suite on pushes to `main` and `draft/**`, and on pull requests. The tests are committed, but results should be treated as **pending until the workflow has actually completed successfully**. This correction improves a specific dispatch edge case; it does not validate the full physical model or establish field performance.

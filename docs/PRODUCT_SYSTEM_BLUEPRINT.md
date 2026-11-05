# IslandOS Product and System Blueprint

**Product definition:** IslandOS is a predictive, multi-resource decision-support and optimization platform for energy-constrained regions and distributed infrastructure.

**Scope boundary:** the product is generic. Islands and RO desalination are useful early examples, not the product boundary. Target application families are (1) islands and remote communities, (2) industrial parks and facilities, (3) water infrastructure, and (4) microgrids and distributed energy systems.

**Evidence rule:** this document distinguishes implemented code, experimental modules, and planned integration. Synthetic and public datasets can validate software workflows and benchmark methods; they do not establish performance at a particular site.

## 1. The system IslandOS is intended to understand

A site may contain:

- Generation: PV, wind, grid import, diesel or other backup generation.
- Storage: batteries and, where modelled, thermal or other storage.
- Essential electricity demand: residential, public-service, industrial critical loads.
- Flexible electricity demand: RO desalination, pumping, refrigeration, thermal storage, deferrable industrial processes, and other qualified assets.
- Resource inventories: water tanks, thermal stores, production buffers, and process backlogs.
- External conditions: weather, tariffs, outages, resource demand, equipment availability, and operating constraints.

The engineering challenge is not to optimize one machine in isolation. It is to compare feasible operating plans across coupled energy and resource balances while protecting critical services.

## 2. Decision loop and current implementation map

| Decision-loop stage | Intended responsibility | Repository foundation | Current maturity / gap |
|---|---|---|---|
| 1. Data acquisition | CSV, APIs, normalized signals, sensors, PLC gateways, history | `islandos_core/signals.py`, `islandos_sensors/`, `data_quality.py`, `data_sources/`, gateway and telemetry modules | Schema validation and read-only telemetry prototypes exist. Protocol/site mapping and live production integration are not universal. |
| 2. State recognition and forecasting | Forecast PV, wind, essential demand, resource demand, availability, and uncertainty | `islandos_core/forecasting.py`, `experiments/forecasting_baselines.py`, water-demand backtests and weather experiments | Replaceable water-demand forecast contract and several experiments exist. A unified, site-calibrated multi-signal forecast service is not implemented. |
| 3. Physical system model | Couple generation, storage, loads, conversion equipment, inventories, and limits | `islandos_core/microgrid_model.py`, `flexible_loads.py`, `island_microgrid_ro_sim.py` | A new integrated deterministic PV/wind–battery–grid–diesel–RO–water accounting baseline is implemented. Network physics, detailed asset dynamics, and site calibration remain gaps. |
| 4. Multi-objective optimization | Generate, simulate, reject infeasible, compare, and rank candidate schedules | `islandos_core/schedule_evaluator.py`, `experiments/rolling_horizon_dispatch.py`, `optimization/`, `experiments/nsga2_dispatch_optimizer.py` | Three transparent rule-based flexible-load candidates are evaluated on common physics; deterministic stress-scenario replay reports worst-case service, cost, and emissions. Experimental optimizers are not yet connected as one auditable pipeline. |
| 5. Decision console | Show schedule, expected outcomes, risks, constraints, reasons, and operator approval | `app.py`, `islandos_core/decision.py`, `islandos_advisor.py` | Interactive simulation and simple read-only advice exist. A complete forecast → model → optimizer → explanation console remains planned. |
| 6. Feedback and continuous improvement | Compare forecast with actuals, audit operator choices, monitor drift, update approved models | `islandos_core/audit.py`, forecast monitoring and telemetry experiments | Provenance, reports, and offline monitoring experiments exist. No autonomous online learning or automatic production model promotion is claimed. |

## 3. Optimization objectives and safety hierarchy

IslandOS should not minimize electricity cost at the expense of critical services.

**Hard constraints first:**

- Essential electricity service and declared reserve requirements.
- Resource inventory bounds and minimum service reserves.
- Equipment rated power, energy, ramp, minimum run/stop, and availability limits where data exists.
- Battery SOC and charge/discharge power limits.
- Grid import/export limits and generator capacity.
- Valid, fresh, unit-consistent input signals; invalid or stale critical inputs fail closed.

**Then evaluate competing objectives:**

1. Economic cost: grid purchases, fuel, operating costs, and only defensible degradation costs.
2. Reliability: unserved critical electricity, unmet water or other resource demand, and reserve violations.
3. Sustainability: emissions and renewable curtailment, using declared emission factors and accounting boundaries.
4. Asset health: battery throughput/degradation and equipment cycling, only when a documented model exists.
5. Resource efficiency: delivered water, cooling, production, or other useful output per unit of energy and resource.

Hard constraints must not be converted into soft weighted penalties merely to make an optimizer return a result. If no feasible schedule exists, report infeasibility and the violated constraints.

## 4. Technical responsibility boundaries

| Technology | IslandOS responsibility | Guardrail |
|---|---|---|
| Physical equations / digital model | Enforce energy, power, storage, conversion, and inventory accounting | Never infer unknown physical parameters silently |
| Statistics and ML | Predict future generation, load, resource demand, and equipment availability | Compare with simple chronological baselines; avoid leakage |
| Monte Carlo / scenario analysis | Evaluate uncertainty, forecast errors, outages, and extreme cases | State distributions, seeds, and assumptions |
| LP / MILP / heuristic scheduling | Compute feasible schedules under explicit constraints | Evaluate every candidate with the same physical simulator |
| MPC | Re-plan as new observations arrive and execute only an approved near-term decision | Simulation and advisory first; operator confirmation required |
| NSGA-II | Explore non-dominated trade-offs among defensible objectives | Do not claim global optimality; filter infeasible schedules |
| LLM | Explain results, translate operator questions, summarize risks | Must not invent measurements, replace the physics model, or bypass constraints |

AI value is primarily the combination of prediction, physical modelling, uncertainty evaluation, and optimization. An LLM is an optional interaction and explanation layer.

## 5. First integrated model milestone now in the repository

`islandos_core/microgrid_model.py` introduces a deterministic system-level accounting model with this priority policy:

1. Renewable generation serves essential electricity demand.
2. Battery discharge, grid imports, and diesel generation cover the remaining essential demand in that order.
3. Scheduled RO load may consume only renewable power remaining after essential demand.
4. Remaining renewable power charges the battery.
5. Any remaining renewable power is reported as curtailed.
6. Water production, water service, unmet demand, and tank inventory are balanced per step.

This is deliberately a transparent baseline policy. It is not the future optimizer, forecast model, or a complete digital twin. The runnable paired synthetic benchmark is `tools/run_integrated_microgrid_demo.py`.

## 6. Evidence that should appear in future pitch materials

Use measured or reproducible quantities, not adjectives. Every metric should identify the scenario, data source, seed or time window, baseline, and model version.

| Evidence family | Required evidence |
|---|---|
| Physical correctness | Maximum absolute energy-balance residual; water-balance residual; SOC and tank-bound violations |
| Service reliability | Unserved essential kWh and hours; unmet resource demand; reserve violations |
| Energy performance | Renewable utilization, curtailment, grid import, diesel generation, battery charge/discharge |
| Economic performance | Grid/fuel cost under explicit tariffs and fuel assumptions; sensitivity range; no unsupported savings claims |
| Forecast performance | MAE/RMSE/bias against persistence and seasonal baselines on chronological holdouts |
| Optimization quality | Feasible-schedule rate, objective trade-offs, runtime, repeatability, and baseline comparison |
| Robustness | Paired seeds, forecast error, low renewable, demand spike, energy-price shock, grid outage, equipment derating, and invalid telemetry |
| Integration readiness | Adapter contract tests, signal freshness/unit checks, read-only shadow-mode logs, operator review and rollback evidence |

A benchmark is not a product proof if the chosen policy is compared against a weaker baseline, uses future actuals unavailable at decision time, or hides unmet service.

## 7. V1–V5 product roadmap and exit gates

### V1 — Unified physical system model

- Couple generation, storage, grid, backup, essential loads, flexible loads, and resource inventories.
- Add invariant tests and deterministic scenario exports.
- Exit when energy/resource balances and equipment limits are independently regression-tested.

### V2 — Prediction and uncertainty

- Add replaceable forecasts for PV, wind, essential electricity demand, and resource demand.
- Compare with persistence and seasonal baselines using chronological holdouts.
- Add uncertainty scenarios and forecast-error stress tests. The current schedule evaluator includes deterministic PV/wind reduction, demand increase, tariff/fuel-cost increase, and combined stress replay; scenario-level results can be exported from the screening UI.
- Exit when model identity, data provenance, forecast metrics, stress assumptions, and input/target alignment are auditable. Current stress multipliers are illustrative sensitivity assumptions, not calibrated forecast-error distributions.

### V3 — Multi-objective optimization

- Generate candidate schedules and evaluate every candidate using the same integrated simulator. A first rule-based candidate set and common-physics ranking are implemented; a connected mathematical optimizer remains future work.
- Enforce critical-service and equipment constraints as hard feasibility gates; report schedules that fail any tested stress case rather than presenting them as safe operating plans.
- Report Pareto trade-offs and a disclosed recommendation-selection rule.
- Exit when the optimizer beats or explains its baseline on paired cases without increasing hidden service violations.

### V4 — Plug-and-play data integration

- Standardize asset and signal schemas, units, timestamps, freshness, quality, and configuration.
- Add CSV and API adapters first; add Modbus/PLC read-only adapters only with documented device maps and tests.
- Keep write/control paths disabled by default.
- Exit when a new site can be configured from documented mappings and pass a complete offline validation workflow.

### V5 — Supervised deployment and feedback

- Begin with offline replay and read-only shadow mode.
- Compare forecasts and recommendations with operator actions and measured outcomes.
- Define site-specific acceptance, cybersecurity, safety review, operator approval, and rollback.
- Only consider controlled actuation after authorized engineering review and hardware-in-the-loop validation.

## 8. Explicit non-claims

IslandOS does not currently claim a universal plug-and-play controller, a validated all-signal forecast service, globally optimal dispatch, certified safety, autonomous learning, live PLC actuation, or field-proven savings. Those claims require evidence beyond repository code and synthetic simulations.

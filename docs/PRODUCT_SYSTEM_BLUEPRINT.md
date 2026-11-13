# IslandOS Product and System Blueprint

## Product definition

**IslandOS is an AI-assisted, simulation-first energy and resource coordination decision-support platform for energy-constrained regions and distributed infrastructure.**

**Product promise:** From Energy Data to Intelligent Decisions.

IslandOS organizes system data, estimates future conditions, evaluates feasible alternatives, and presents explainable recommendations for human review. Its primary analytical value comes from forecasting, physical/system modelling, uncertainty evaluation, and optimization. An LLM may assist natural-language interaction or explanation, but it does not replace data validation, physical models, or constraint enforcement.

## External product workflow

The user-facing product workflow is always:

| Step | Purpose | Typical outputs |
|---|---|---|
| **INPUT** | Organize energy supply, demand, assets, resource requirements, operating constraints, data quality, and provenance | Validated scenario, asset inventory, data-quality report, assumptions |
| **PREDICT** | Estimate relevant future supply, demand, prices, availability, and system state; quantify uncertainty where supported | Forecast series, baseline comparison, error metrics, uncertainty/scenario information |
| **OPTIMIZE** | Evaluate feasible operating and investment alternatives against technical, service, economic, and environmental objectives | Candidate plans, feasibility checks, trade-off comparisons, sensitivity results |
| **DECIDE** | Explain recommendations, trade-offs, risks, assumptions, and evidence for human review | Decision report, recommendation rationale, unresolved data needs, audit record |

The four steps describe the product experience, not the number of internal packages, services, or engineering layers. Internal architecture may contain data adapters, asset registries, physical models, forecasting services, optimization algorithms, audit services, and user interfaces.

## Scope boundary

The product is generic. Islands and reverse-osmosis (RO) desalination are early examples, not the product boundary. Potential application families include remote communities, distributed energy infrastructure, microgrids, essential water and pumping systems, and industrial or commercial facilities with flexible loads, storage, or resource constraints. These are intended application families, not claims that every sector is currently supported or validated. Each pilot must define one bounded decision problem and evidence boundary.

## Evidence and maturity rules

Use these labels consistently:

- **Implemented on main:** code is present on the default branch and its current behavior is covered by appropriate tests or reproducible evidence.
- **Experimental:** code or a workflow exists but is exploratory, incomplete, narrowly scoped, or not validated for general use.
- **Planned:** described as a target capability but not implemented as a usable workflow.
- **Long-term:** depends on site integration, operational approval, security, hardware, or commercial validation beyond the current prototype.

A feature in an open pull request is not implemented on main. A passing software test does not establish forecast accuracy, physical feasibility at a real site, safety, customer value, or savings. Synthetic and public datasets can test workflows and methods; they do not establish performance at a particular customer site.

## 1. System domain IslandOS is intended to represent

A configured site may contain:

- **Energy supply:** PV, wind, grid import/export, diesel or other backup generation.
- **Storage:** batteries and, where explicitly modelled, thermal or other storage.
- **Demand:** essential electricity loads and flexible electricity loads.
- **Flexible processes:** pumping, RO desalination, refrigeration, thermal storage, deferrable industrial processes, and other qualified assets.
- **Resource inventories:** water tanks, thermal stores, production buffers, and process backlogs.
- **External conditions:** weather, tariffs, outages, resource demand, equipment availability, and operating constraints.

The engineering problem is to evaluate coupled energy and resource balances while protecting declared critical services—not merely optimize one machine in isolation.

## 2. Internal technical architecture mapped to the four-step workflow

| Product workflow | Internal technical responsibilities | Repository foundation | Current maturity / gap |
|---|---|---|---|
| **INPUT** | Data ingestion, schema and unit normalization, provenance, data-quality checks, asset identity, configuration, system state | `islandos_core/onboarding.py`, `islandos_core/workspace_store.py`, `islandos_core/forecast_signal_catalog.py`, `islandos_sensors/`, gateway and telemetry modules | CSV/XLSX onboarding, local-first workspace, canonical signal vocabulary and read-only telemetry reference exist. Universal vendor mapping and production integration are not implemented. |
| **PREDICT** | Time-series baselines, forecasting contracts, model evaluation, forecast uncertainty and scenarios | `islandos_core/forecast_signal_catalog.py`, `islandos_core/prediction_engine.py`, `islandos_core/forecast_contract.py`, experiments | Canonical multi-domain orchestration and replaceable candidates with rolling-origin replay exist. Site-calibrated accuracy and calibrated uncertainty remain unproven. |
| **OPTIMIZE** | Physical/system simulation, asset constraints, scenario evaluation, candidate generation, feasibility filtering, multi-objective ranking | `islandos_core/microgrid_model.py`, `islandos_core/prediction_dispatch_adapter.py`, `optimization/`, rolling-horizon and NSGA-II experiments | Forecast-driven joint battery/diesel schedule search with deterministic stress cases and service-equivalence gating exists. Broader asset coverage and calibrated robust optimization remain incomplete. |
| **DECIDE** | Recommendation policy, trade-off explanation, economic comparison, operator review, report generation, audit and feedback | `pages/06_Forecast_Led_Joint_Resource_Optimizer.py`, `frontend/`, `islandos_service_api.py`, `islandos_core/decision.py`, `islandos_core/audit.py`, `islandos_core/shadow_evidence.py`, `islandos_core/safety_governance.py` | Forecast-led schedule comparison, model provenance, JSON audit, simplified customer economics, React customer-console and membership foundations, local tenant-scoped reference API, persistent read-only shadow evidence and fail-closed review-package gate exist. Full-stack production deployment, continuous site telemetry, site economics, independent safety acceptance and customer usability remain unvalidated. |

## 3. System-level constraints and objectives

IslandOS should not minimize energy cost at the expense of declared critical services.

**Hard constraints first:**

- Essential electricity service and declared reserve requirements.
- Resource inventory bounds and minimum service reserves.
- Equipment rated power, energy, ramp, minimum run/stop, and availability limits where data exists.
- Battery state-of-charge and charge/discharge power limits.
- Grid import/export limits and generator capacity.
- Valid, fresh, unit-consistent input signals; invalid or stale critical inputs must not silently become trusted measurements.

**Then evaluate competing objectives:**

1. Economic cost: grid purchases, fuel, operating costs, maintenance, replacements, and only defensible degradation costs.
2. Reliability: unserved critical electricity, unmet water or other resource demand, and reserve violations.
3. Sustainability: emissions and renewable curtailment, using declared emission factors and accounting boundaries.
4. Asset health: battery throughput/degradation and equipment cycling, only when a documented model exists.
5. Resource efficiency: delivered water, cooling, production, or other useful output per unit of energy and resource.

Hard constraints must not be converted into soft weighted penalties merely to make an optimizer return a result. If no feasible schedule exists, report infeasibility and violated constraints.

## 4. Technical responsibility boundaries

| Technology | IslandOS responsibility | Guardrail |
|---|---|---|
| Physical equations / system model | Enforce energy, power, storage, conversion, and inventory accounting | Never infer unknown physical parameters silently |
| Statistics and ML | Predict future generation, load, resource demand, prices, and equipment availability where data supports it | Compare with chronological baselines; avoid leakage; report limits |
| Scenario analysis | Evaluate uncertainty, forecast errors, outages, and extreme cases | State distributions, seeds, assumptions, and whether scenarios are calibrated |
| LP / MILP / heuristic scheduling | Compute and compare candidate schedules under explicit constraints | Evaluate every candidate with consistent physical models |
| MPC | Re-plan as new observations arrive; any execution requires explicit approval | Simulation/advisory first; operator confirmation and site safety review required |
| NSGA-II | Explore non-dominated trade-offs among defensible objectives | Do not claim global optimality; filter infeasible schedules |
| LLM | Explain results, translate operator questions, summarize risks | Must not invent measurements, replace physics, or bypass constraints |

## 5. Current integrated model baseline

`islandos_core/microgrid_model.py` introduces a deterministic system-level accounting model with a selected priority policy:

1. Renewable generation serves essential electricity demand.
2. Battery discharge, grid imports, and diesel generation cover remaining essential demand in the configured order.
3. Scheduled RO load may consume only renewable power remaining after essential demand.
4. Remaining renewable power charges the battery.
5. Any remaining renewable power is reported as curtailed.
6. Water production, water service, unmet demand, and tank inventory are balanced per step.

This is a transparent energy–water baseline. It is not a general-purpose digital twin, a universal multi-resource model, the future optimizer, or a validated site model. The runnable paired synthetic benchmark is `tools/run_integrated_microgrid_demo.py`.

## 6. Evidence required for product claims

Every displayed metric should identify the scenario, data source, time window, seed where applicable, baseline, assumptions, and model/software version.

| Evidence family | Required evidence |
|---|---|
| Physical correctness | Maximum absolute energy/resource-balance residual; SOC and inventory-bound violations |
| Service reliability | Unserved essential energy and hours; unmet resource demand; reserve violations |
| Energy performance | Renewable utilization, curtailment, grid import, backup generation, storage charge/discharge |
| Economic performance | Cost under explicit tariffs, fuel, CAPEX/OPEX and maintenance assumptions; sensitivity range; no unsupported savings claims |
| Forecast performance | MAE/RMSE/bias against persistence and seasonal baselines on chronological holdouts |
| Optimization quality | Feasible-schedule rate, objective trade-offs, runtime, repeatability, and baseline comparison |
| Robustness | Paired seeds, forecast error, low renewable, demand spike, price shock, grid outage, equipment derating, and invalid telemetry |
| Integration readiness | Adapter contract tests, signal freshness/unit checks, read-only shadow-mode logs, operator review and rollback evidence |

A benchmark is not product proof if it compares against a deliberately weak baseline, uses future actuals unavailable at decision time, or hides unmet service.

## 7. Product maturity roadmap

- **Foundation:** unify project/scenario data, asset identity, units, constraints, and provenance.
- **Prediction:** standardize forecast contracts and evaluation; connect uncertainty to scenario evaluation.
- **Optimization:** evaluate all candidates with common physics and explicit feasibility rules; disclose heuristic limits.
- **Decision economics:** compare baseline and alternatives with traceable CAPEX, OPEX, maintenance, replacement, and sensitivity assumptions.
- **Supervised pilot:** begin with offline replay and read-only review; require site approval before any operational integration.
- **Product interface:** guide users through INPUT → PREDICT → OPTIMIZE → DECIDE and generate reproducible decision reports.

See [Productization Roadmap](PRODUCTIZATION_ROADMAP.md) for phase exit gates and customer-discovery requirements, and [Engineering stages 1–10 closeout](ENGINEERING_STAGES_1_10_CLOSEOUT.md) for merged implementation slices and remaining field gates.

## 8. Explicit non-claims

IslandOS does not currently claim universal plug-and-play integration, a validated all-signal forecast service, globally optimal dispatch, certified safety, autonomous online learning, live PLC actuation, field-proven savings, or bankable ROI. Those claims require evidence beyond repository code and synthetic simulations.

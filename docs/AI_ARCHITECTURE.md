# IslandOS AI Architecture — Working Draft

**Status:** design proposal. This document describes the intended architecture; components marked planned are not yet implemented.

## 1. Design goal

Build a simulation-first decision-support system that allocates available renewable electricity among essential demand and flexible resource-producing loads. The system should explain its choices and demonstrate improvements against a transparent baseline under repeatable scenarios.

The core is not a single algorithm. It is the contract between:
1. input data and forecasts;
2. a physical simulation model;
3. flexible-load models;
4. a planner/optimizer;
5. constraint validation and metrics;
6. decision explanations and reports.

## 2. Decision loop

For each planning time step:

1. Read the current state: renewable output, essential demand, resource inventories, and each load's operating state.
2. Obtain forecasts for a finite horizon. Forecasts must be distinct from future observations used only for post-run evaluation.
3. Generate candidate schedules for flexible loads.
4. Reject or penalize infeasible schedules according to clearly defined hard constraints.
5. Evaluate feasible schedules with the same simulator and objective definitions.
6. Maintain a non-dominated candidate set when using a multi-objective method.
7. Choose an operational action from the feasible candidate set using an explicit policy; do not select a recommendation from a separate, disconnected optimization run.
8. Execute only the near-term action, observe the updated state, and re-plan.

This is a proposed rolling-horizon workflow, not a feature currently available in the public MVP.

## 3. Essential services and flexible loads

Essential electricity demand must be treated as a priority. Flexible loads may consume only the power left after essential demand and other modelled constraints are accounted for. If the model includes a backup generator or battery, its power and energy limits, efficiency, and costs must be explicit.

Each flexible-load plug-in should expose a common conceptual contract:

- **Identity:** stable module name and configuration.
- **State:** on/off status, remaining minimum-run time, inventory, and other relevant internal state.
- **Feasibility:** minimum/maximum power, allowed operating windows, ramp limits, minimum up/down time, and safety constraints.
- **Resource conversion:** electricity consumed and useful output produced per time step.
- **Inventory/demand:** storage capacity, initial inventory, demand, unmet demand, and overflow/spillage where applicable.
- **Economics:** operating cost and value assumptions, if known.
- **Validation:** checks that the proposed action and resulting state are physically and operationally feasible.

A module must not claim benefits outside the physical boundary of its model. Freshwater shifts electricity consumption in time; it does not directly regenerate electricity. Ice storage may provide cooling services, but is not a generic electrical battery. Hydrogen has conversion losses and requires safe storage and a credible demand pathway.

## 4. Candidate modules

| Module | State/inventory | Key constraints | Useful output |
|---|---|---|---|
| RO desalination | Reservoir volume, on/off state | Rated power, minimum run time, water capacity, flushing assumptions | Freshwater |
| Ice making / cold storage | Stored cold or ice inventory | Chiller power, production efficiency, storage capacity, cooling demand | Cooling / preserved goods |
| Hydrogen | Hydrogen inventory | Electrolyser power range, efficiency, ramping, storage and safety constraints | Hydrogen |
| Municipal services | Process backlog or treatment state | Service deadlines, minimum process requirements, environmental constraints | Public service |
| Deferrable computing | Pending work | Deadline, interruptibility, maximum power | Completed compute jobs |

Only the RO / reservoir module exists in the current MVP. All other rows are design candidates.

## 5. Forecasting: start with honest baselines

Potential approaches include:
- persistence or seasonal-naive baselines;
- simple statistical models;
- machine-learning time-series models when data quantity and quality justify them.

Evaluate forecasts on held-out periods using documented metrics such as MAE or RMSE. Avoid data leakage: a model must not use future actual values when generating a forecast. For synthetic experiments, disclose how the data was generated and test whether conclusions survive changes in the data-generation assumptions.

The first milestone is not “use the most complex AI model.” It is to demonstrate whether a forecast improves on a simple baseline and whether forecast errors change the scheduling outcome.

## 6. Optimization: compare before committing

### Candidate methods

- **Rule-based heuristic:** interpretable baseline and useful fallback.
- **NSGA-II:** a practical first candidate for generating approximate multi-objective trade-off sets.
- **Multi-objective simulated annealing (MOSA):** a valid alternative if its acceptance rule, archive management, and diversity strategy are explicitly implemented and tested.
- **Single-objective simulated annealing:** useful for a scalarized objective or repeated preference-specific runs, but it does not automatically produce a valid Pareto front.

The choice should be based on schedule representation, constraints, runtime, repeatability, and solution quality—not on which algorithm sounds more like AI.

### Objective definitions

Potential objectives, subject to data availability:
- minimize operating cost;
- minimize unserved essential electricity;
- minimize unmet water / cooling demand;
- minimize renewable curtailment;
- minimize a defensible battery degradation estimate;
- maximize the value of useful resources produced.

Not all need to be optimized simultaneously. Critical service requirements may be hard constraints rather than objectives. Cost, emission, and degradation terms should be included only when their assumptions are documented.

### Pareto workflow

1. Generate candidate schedules.
2. Run every candidate through the same simulation and constraint checks.
3. Exclude infeasible schedules or report violations explicitly.
4. Remove dominated feasible candidates.
5. Check the archive for duplicates and preserve useful diversity.
6. Report objective values and feasibility for every retained candidate.
7. Select any recommended schedule from this evaluated archive, using a disclosed decision rule.

An approximate Pareto archive is not proof of the complete true Pareto front or a globally optimal solution.

## 7. Evaluation protocol

Compare the rule-based baseline and each candidate optimizer on the same scenarios and data:

- multiple random seeds;
- low-, medium-, and high-renewable conditions;
- demand peaks and resource shortages;
- forecast error and forecast bias;
- load-module availability changes;
- equipment constraints and boundary cases.

Report at minimum:
- renewable curtailment;
- essential electricity not served;
- each flexible load's energy consumption and useful output;
- resource demand shortfall and inventory;
- operating cost, only if modelled;
- battery degradation proxy, only if modelled;
- number and type of constraint violations;
- runtime, random seeds, and configuration.

A lower curtailment figure is not enough if the schedule increases essential-load outages, misses water demand, or violates equipment limits.

## 8. Implementation stages

### Stage 0 — Stabilize the current MVP
- Add tests for energy and water balance.
- Fix and test minimum-run behaviour for RO, including no-backup cases.
- Make the perfect-foresight assumption visible in reports.
- Keep the existing command-line demo working.

### Stage 1 — Standardize simulation and metrics
- Separate synthetic data generation, simulation, plotting, and metrics.
- Define units and time-step conventions.
- Add scenario configuration and reproducible seeds.

### Stage 2 — Add load interface
- Encapsulate the current RO model as the first plug-in.
- Define a common action/state/result interface.
- Add a minimal toy flexible load in tests to verify the interface.

### Stage 3 — Add forecasts and rolling planning
- Implement a baseline forecast first.
- Separate forecast inputs from future actuals.
- Execute only the next decision, then re-plan.

### Stage 4 — Add multi-objective optimization
- Start with a rule baseline and NSGA-II prototype, or implement MOSA if there is a clear reason to prefer it.
- Centralize objective calculation and Pareto filtering.
- Ensure the final recommendation is chosen from the same validated candidate archive.

### Stage 5 — Add one additional load
- Prefer ice making / cold storage as the first extension if an understandable demand and storage model can be defined.
- Add hydrogen only after representing conversion losses, operating limits, storage, safety assumptions, and a credible use case.

### Stage 6 — Evaluate and communicate
- Run controlled scenario comparisons.
- Publish reproducible configurations and output summaries.
- Separate measured facts, simulation results, assumptions, and future goals in the README.

## 9. Non-goals for the first AI MVP

- Do not claim real-world cost savings without site-specific inputs and comparative evidence.
- Do not claim battery replacement or lifetime extension without a defined battery model and baseline.
- Do not claim an actual autonomous controller or hardware integration; the project is currently simulation-only.
- Do not add a language model just to satisfy an AI label if it does not improve forecasting, planning, explanation, or user decision-making.

## 10. Definition of a credible milestone

A milestone is ready to describe as implemented when:
- code exists in the repository;
- automated tests cover its core constraints and edge cases;
- the demo can be reproduced from documented commands;
- assumptions and units are documented;
- results are compared with a baseline;
- limitations are stated alongside claims.


## Implemented extension-point prototype (development branch)

`flexible_loads.py` now defines a runtime-checkable `FlexibleLoad` protocol and a shared `LoadSimulationResult` output contract. The first implementations are `ROWaterLoad` and `IceStorageLoad`.

The common result reports electrical demand, backup electricity, explicit runtime constraint violations, useful resource production, served/unmet demand, spill, active state, and inventory trajectory. Units of the resource inventory and demand depend on the module and are documented in each configuration/class: RO uses m³ of water; cold storage uses kWh of thermal energy.

This API is an **experimental parallel path**. The original 24-hour demo still uses `island_microgrid_ro_sim.py`; unifying the legacy engine with plug-ins is a later integration task. The initial cold-storage model is intentionally simple and must not be presented as a validated refrigeration design.

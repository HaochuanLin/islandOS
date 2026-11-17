# Optimization Engineering Build-out Plan

## Purpose

Turn the existing forecasting and resource-coordination experiments into a reproducible, constraint-aware optimization workflow without overstating maturity. This plan is an engineering sequence, not a claim that future stages are already implemented.

## Current baseline (verified in source)

The repository already contains:

- A canonical multi-signal forecasting catalog with per-signal model selection, chronological backtesting and forecast provenance.
- A forecast-to-dispatch adapter that maps PV, wind, electrical load and tariff forecasts into the shared physical energy model.
- A seeded evolutionary Pareto search over battery set-points, diesel commitment/output, optional aggregate flexible-load allocation and grid export.
- Repeated evaluation of the same candidate schedule against deterministic forecast-envelope and grid-outage stress scenarios.
- Hard constraints for selected unmet-load thresholds and terminal battery reserve, plus physical dispatch audits and battery-first / grid-first baseline comparisons.
- A water-service adapter that converts water-demand forecasts into RO electrical demand, and two RO scheduling heuristics (just-in-time and tariff-look-ahead).

Important current limitations:

- The evolutionary search is stochastic and does not guarantee a global optimum.
- The existing evolutionary joint optimizer still rejects diesel ramp-down and minimum up/down-time configurations; the new deterministic MILP path handles these constraints in its own bounded formulation.
- The MILP reference path supports one battery, one diesel unit, one grid connection and a single-bus balance. It rejects grid export, nonlinear diesel fuel curves, critical/flexible-load decomposition and unsupported network constraints.
- The MILP assumes the diesel unit is initially OFF, prohibits unserved load, and permits battery charging only from contemporaneous renewable surplus.
- Constant-rate diesel fuel inventory is modeled when configured; nonlinear fuel curves remain unsupported by the MILP reference solver.
- Water production policies are selected from separate heuristics before the energy schedule search; water and energy are not yet jointly optimized as one decision problem.
- Forecast stress envelopes are deterministic scenarios, not calibrated joint probability distributions.
- All optimization paths remain offline advisory workflows; none writes to equipment.

## Delivery stages and acceptance gates

### Stage 1 — Reproducible end-to-end optimization demonstration

**Status: in progress in PR #255.**

- Provide one command-line example using synthetic, clearly labelled input data.
- Connect canonical multi-signal forecasting to the existing forecast-to-resource optimizer.
- Include water-demand/RO coupling, deterministic stress scenarios, physical/service constraints, baseline comparisons and provenance.
- Emit machine-readable output and explicitly report that no device write is authorized and no global optimum is claimed.
- Add an automated test that executes the example end to end.

**Acceptance gate:** the example runs in CI; at least one candidate passes all configured constraints and the physical audit; outputs include the synthetic-data label, forecast/model provenance, baseline comparisons and advisory-only boundary.

### Stage 2 — Equipment-constraint completeness

**Status: first bounded implementation added in this PR; not yet complete across all optimizer paths.**

- Added an independent diesel schedule validator for availability, rated/minimum-stable output, ramp-up, ramp-down and completed minimum up/down runs.
- The MILP path encodes diesel commitment, minimum stable output, ramp limits, minimum up/down times, battery SOC and charge/discharge limits.
- Constant-rate fuel inventory and per-step deliveries are modeled when configured; nonlinear fuel curves are rejected explicitly.
- Added a grid-import set-point to the shared simulator so a mathematical schedule can be replayed without silently changing the optimizer's grid/diesel split.
- The existing evolutionary joint optimizer still rejects ramp-down/minimum-time configurations. Do not treat this stage as complete until that search path is either extended or clearly segregated from the constrained MILP path.
- Battery capacity fade and network constraints are not decision variables in this MILP formulation; battery throughput cost is represented.

**Acceptance gate:** every MILP candidate passes the shared physical replay audit and independent diesel validator; infeasible configurations fail closed. CI must pass the new boundary tests.

### Stage 3 — Deterministic optimization benchmark

**Status: first SciPy/HiGHS MILP reference solver added in this PR; benchmark coverage remains limited.**

- Added a deterministic mathematical-programming reference solver using the pinned SciPy MILP capability.
- The initial formulation covers a single-bus energy balance with one battery, one grid connection, one diesel unit and renewable curtailment.
- The solver reports its termination status and only reports an optimality proof for the declared MILP when HiGHS returns an optimal status.
- MILP schedules are replayed through the shared physical simulator using explicit battery, grid-import and diesel set-points.
- Battery-first and grid-first policies are evaluated on the same inputs. The evolutionary joint optimizer is also run as a comparator only when its current equipment-constraint scope is compatible; otherwise the output explains why it is not comparable.
- Added a small constrained test instance and infeasibility / constraint-validation tests. Broader benchmark grids, independent hand-solvable optimality fixtures, timeout behavior and runtime scaling remain future work.

**Acceptance gate:** deterministic solutions reproduce within numerical tolerance, pass the same physical audit, and have fair service-equivalent baseline comparisons. An optimality claim is limited to the exact MILP formulation and a solver optimal status; it is not a claim of global optimality for the real site or full IslandOS system.

### Stage 4 — Forecast uncertainty and robustness

- Validate forecast intervals chronologically and measure empirical coverage before treating bounds as uncertainty inputs.
- Distinguish central forecasts, marginal stress envelopes and genuinely joint scenarios.
- Add explicit scenario construction and optional probabilities only when supported by evidence.
- Compare nominal, worst-case and risk-aware objectives without conflating them.
- Report which uncertainty assumptions materially change the selected schedule.

**Acceptance gate:** every scenario has traceable provenance; scenario assumptions and probability status are explicit; recommendations remain auditable under the tested uncertainty set.

### Stage 5 — Joint water-energy-flexible-load optimization

- Replace preselected RO heuristics with decision variables for RO production, tank inventory and flexible-load timing.
- Enforce water balance, tank bounds, RO capacity, service reserve, equipment operating windows and water-demand satisfaction.
- Co-optimize water and energy costs while preserving critical-service priorities.
- Compare against just-in-time and tariff-look-ahead RO baselines under identical service assumptions.

**Acceptance gate:** the same schedule simultaneously passes electrical and water-service audits; any water shortfall is explicit; cost comparisons are made only at equivalent service.

### Stage 6 — Operator-facing workflow and shadow evaluation

- Expose optimization as a clearly labelled experimental/advisory workflow in the product interface.
- Show input provenance, selected objective weights, constraints, candidate schedules, baseline comparisons, infeasibility reasons and model limitations.
- Require human review and retain a reproducible decision record.
- Validate retrospectively on authorized site data before any read-only shadow trial; no actuation is in scope.

**Acceptance gate:** an operator can reproduce and explain a recommendation from a saved configuration; site performance claims require independent, site-specific evidence.

## Product and evidence rules

- Synthetic data must always be labelled synthetic.
- A candidate is not "feasible" unless both the declared service constraints and the physical audit pass.
- A lower modeled cost is not a customer saving; compare only equivalent service and label the result as an estimate.
- A stochastic heuristic is not a global optimizer.
- A module, experiment or branch is not part of the hosted product until integrated, tested and explicitly promoted.
- No optimization result authorizes live device control.

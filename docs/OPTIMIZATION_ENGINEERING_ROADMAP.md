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
- The evolutionary optimizer now accepts diesel ramp-down and minimum up/down-time configurations by repairing every candidate schedule (short runs extended or filled, set-points tapered before each stop). Schedules the shared simulator still rejects are kept as infeasible candidates. A diesel minimum stable output combined with a slow ramp-down can still leave no feasible stop.
- Water production policies are selected from separate heuristics before the energy schedule search; water and energy are not yet jointly optimized as one decision problem.
- Forecast stress envelopes are deterministic scenarios, not calibrated joint probability distributions.
- The optimizer is an offline advisory workflow; it does not write to equipment.

## Delivery stages and acceptance gates

### Stage 1 — Reproducible end-to-end optimization demonstration

**Status: implemented in the Stage 1 baseline. The last successful full CI run is on commit `cb6e572`; subsequent Stage 2–6 commits require a fresh full CI run before acceptance.**

- Provide one command-line example using synthetic, clearly labelled input data.
- Connect canonical multi-signal forecasting to the existing forecast-to-resource optimizer.
- Include water-demand/RO coupling, deterministic stress scenarios, physical/service constraints, baseline comparisons and provenance.
- Emit machine-readable output and explicitly report that no device write is authorized and no global optimum is claimed.
- Add an automated test that executes the example end to end.

**Acceptance gate:** the example runs in CI; at least one candidate passes all configured constraints and the physical audit; outputs include the synthetic-data label, forecast/model provenance, baseline comparisons and advisory-only boundary.

### Stage 2 — Equipment-constraint completeness

**Status: delivered in the deterministic MILP reference path and, through candidate repair, in the evolutionary optimizer (`repair_diesel` in `optimization/energy_system_optimizer.py`, regression tests in `tests/test_optimizer_extensions.py`). Initial fuel above tank capacity fails closed with a regression test.**

- Extend candidate generation so diesel schedules can satisfy configured ramp-up and ramp-down limits, minimum stable output, minimum up-time and minimum down-time.
- Include fuel inventory / delivery limits where configured.
- Preserve battery SOC, charge/discharge power, efficiency and degradation constraints.
- Reject unsupported or incomplete site configurations explicitly; never silently clip an infeasible request and label it feasible.
- Add boundary and adversarial tests for every equipment constraint.
- Current MILP scope includes diesel availability, stable output, ramp limits, commitment, minimum up/down time, constant-rate fuel inventory/deliveries, battery SOC and charge/discharge limits. Cycle-driven battery capacity fade is explicitly rejected until modeled.

**Acceptance gate:** every returned candidate passes the shared physical audit and an independent constraint validator; infeasible configurations fail closed with actionable diagnostics.

### Stage 3 — Deterministic optimization benchmark

**Status: bounded MILP reference solver, shared-physics replay, independent diesel validation, equivalent-service rule baselines and objective-to-replay cost reconciliation implemented. A multi-case head-to-head against the evolutionary search (`experiments/run_optimizer_benchmark.py`, results in `results/optimizer_benchmark/`) and a timeout regression test are now delivered. All benchmark inputs are synthetic.**

- Add a deterministic mathematical-programming reference solver using the already pinned SciPy MILP capability, subject to a formulation review.
- Start with a clearly bounded model (battery, grid, diesel and essential load); add binary commitment variables only where required.
- Keep the evolutionary optimizer as a comparison method, not silently replace it.
- Replay both methods through the same physical simulator and compare objective values, feasibility, runtime and repeatability on identical inputs.
- Add small instances with independently checkable optima and tests for solver timeout / infeasibility.
- Current implementation solves a bounded single-bus model with SciPy/HiGHS, reports solver status, optimality scope and solve time, then replays the result through the shared simulator and independent diesel validator. It now reconciles the MILP objective against replayed grid, diesel, fuel, battery, demand-charge, RO and curtailment tie-break components, failing closed on a material mismatch.

**Acceptance gate:** deterministic solutions reproduce within numerical tolerance, pass the same physical audit, and outperform or explain trade-offs against transparent baselines on declared benchmark cases. No general global-optimum claim beyond the exact mathematical model and solver status.

### Stage 4 — Forecast uncertainty and robustness

**Status: interval scoring plus a deterministic directional stress-scenario builder implemented in `islandos_core/forecast_uncertainty.py` and `islandos_core/forecast_stress_scenarios.py`. The stress cases are now passed through the joint MILP by `islandos_core/stress_dispatch.py` (`forecast_stress_study`), which reports how far each scenario moves the schedule and how a plan made on one scenario performs in the others (`experiments/run_stress_tests.py`, results in `results/stress_tests/`). The intervals used there are assumed bands on synthetic data; site calibration remains unproven.**

- Validate forecast intervals chronologically and measure empirical coverage before treating bounds as uncertainty inputs.
- Distinguish central forecasts, marginal stress envelopes and genuinely joint scenarios.
- Add explicit scenario construction and optional probabilities only when supported by evidence.
- Compare nominal, worst-case and risk-aware objectives without conflating them.
- Report which uncertainty assumptions materially change the selected schedule.

**Acceptance gate:** every scenario has traceable provenance; scenario assumptions and probability status are explicit; recommendations remain auditable under the tested uncertainty set.

### Stage 5 — Joint water-energy-flexible-load optimization

**Status: bounded joint water-energy MILP path implemented in `optimization/milp_dispatch_optimizer.py`, now including a terminal tank level, an RO minimum production rate and one aggregate flexible load with a fixed energy budget and availability window. RO electrical demand and the flexible load are replayed through the shared energy simulator. Multiple flexible loads and RO start costs remain open.**

- Replace preselected RO heuristics with decision variables for RO production, tank inventory and flexible-load timing.
- Enforce water balance, tank bounds, RO capacity, service reserve, equipment operating windows and water-demand satisfaction.
- Co-optimize water and energy costs while preserving critical-service priorities.
- Compare against just-in-time and tariff-look-ahead RO baselines under identical service assumptions.
- The MILP baseline comparison replays battery-first/grid-first energy policies with the just-in-time RO profile and, under `water_policy_baselines`, with the tariff-look-ahead RO policy. A rule baseline that cannot serve the demand is reported as infeasible instead of failing the solve.

**Acceptance gate:** the same schedule simultaneously passes electrical and water-service audits; any water shortfall is explicit; cost comparisons are made only at equivalent service.

### Stage 6 — Operator-facing workflow and shadow evaluation

**Status: operator decision-record primitive plus a runnable synthetic MILP-to-human-review example and regression test implemented in `islandos_core/operator_decision.py` and `examples/operator_decision_record_demo.py`. Existing read-only Shadow Mode and hash-chain evidence ledger remain separate components. UI integration and authorized-site retrospective evaluation are not yet delivered.**

- Expose optimization as a clearly labelled experimental/advisory workflow in the product interface.
- Show input provenance, selected objective weights, constraints, candidate schedules, baseline comparisons, infeasibility reasons and model limitations.
- Require human review and retain a reproducible decision record. A hash-addressed decision-record primitive now captures input references, data provenance, objective weights, operating constraints, schedule, outcomes, baseline comparisons and physical audit; approval remains pending and device writes are prohibited.
- Validate retrospectively on authorized site data before any read-only shadow trial; no actuation is in scope.

**Acceptance gate:** an operator can reproduce and explain a recommendation from a saved configuration; site performance claims require independent, site-specific evidence.

## Product and evidence rules

- Synthetic data must always be labelled synthetic.
- A candidate is not "feasible" unless both the declared service constraints and the physical audit pass.
- A lower modeled cost is not a customer saving; compare only equivalent service and label the result as an estimate.
- A stochastic heuristic is not a global optimizer.
- A module, experiment or branch is not part of the hosted product until integrated, tested and explicitly promoted.
- No optimization result authorizes live device control.


## Current implementation boundary after Stage 4–6 kickoff

- Stage 4 currently scores marginal interval coverage, width and under/over-coverage on aligned held-out observations, and builds central / renewable-low-demand-high / cost-high / combined deterministic stress cases from caller-supplied intervals. The cases carry no probabilities. `forecast_stress_study` re-plans the joint MILP on each case for schedule-sensitivity comparison and replays held plans across cases.
- Stage 5 currently jointly chooses hourly RO production, flexible-load timing and electrical dispatch in one bounded MILP, with water tank balance, reserve, terminal level, RO capacity and RO minimum constraints. Independent water replay is required. Water-shortage stress events (low-renewable week, demand spike) are tested in `water_shortage_stress_test`; a plan with no tank reserve can run short when demand is higher than forecast, so a reserve or rolling re-planning is needed before any field use.
- Stage 6 currently packages a MILP result into a synthetic human-review decision record, verifies its digest in an end-to-end example, and explicitly keeps approval pending with device writes and command generation disabled. Existing Shadow Mode comparison and SQLite hash-chain evidence are available, but the operator UI and site-specific retrospective evaluation are not complete.
- No stage authorizes equipment control. All recommendations remain offline and human-reviewed.

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
- The joint optimizer explicitly rejects diesel ramp-down and minimum up/down-time configurations because it does not yet generate commitment schedules satisfying those constraints.
- Water production policies are selected from separate heuristics before the energy schedule search; water and energy are not yet jointly optimized as one decision problem.
- Forecast stress envelopes are deterministic scenarios, not calibrated joint probability distributions.
- The optimizer is an offline advisory workflow; it does not write to equipment.

## Delivery stages and acceptance gates

### Stage 1 — Reproducible end-to-end optimization demonstration

**Status: implemented in PR #255; CI passing on the current PR revision.**

- Provide one command-line example using synthetic, clearly labelled input data.
- Connect canonical multi-signal forecasting to the existing forecast-to-resource optimizer.
- Include water-demand/RO coupling, deterministic stress scenarios, physical/service constraints, baseline comparisons and provenance.
- Emit machine-readable output and explicitly report that no device write is authorized and no global optimum is claimed.
- Add an automated test that executes the example end to end.

**Acceptance gate:** the example runs in CI; at least one candidate passes all configured constraints and the physical audit; outputs include the synthetic-data label, forecast/model provenance, baseline comparisons and advisory-only boundary.

### Stage 2 — Equipment-constraint completeness

**Status: implemented for the deterministic MILP reference path in PR #255; the evolutionary optimizer remains unchanged and continues to reject its unsupported diesel commitment constraints.**

- Extend candidate generation so diesel schedules can satisfy configured ramp-up and ramp-down limits, minimum stable output, minimum up-time and minimum down-time.
- Include fuel inventory / delivery limits where configured.
- Preserve battery SOC, charge/discharge power, efficiency and degradation constraints.
- Reject unsupported or incomplete site configurations explicitly; never silently clip an infeasible request and label it feasible.
- Add boundary and adversarial tests for every equipment constraint.
- Current MILP scope includes diesel availability, stable output, ramp limits, commitment, minimum up/down time, constant-rate fuel inventory/deliveries, battery SOC and charge/discharge limits. Cycle-driven battery capacity fade is explicitly rejected until modeled.

**Acceptance gate:** every returned candidate passes the shared physical audit and an independent constraint validator; infeasible configurations fail closed with actionable diagnostics.

### Stage 3 — Deterministic optimization benchmark

**Status: bounded MILP reference solver and shared-physics replay implemented in PR #255; broader evolutionary-method benchmarking and timeout/infeasibility coverage remain follow-up work.**

- Add a deterministic mathematical-programming reference solver using the already pinned SciPy MILP capability, subject to a formulation review.
- Start with a clearly bounded model (battery, grid, diesel and essential load); add binary commitment variables only where required.
- Keep the evolutionary optimizer as a comparison method, not silently replace it.
- Replay both methods through the same physical simulator and compare objective values, feasibility, runtime and repeatability on identical inputs.
- Add small instances with independently checkable optima and tests for solver timeout / infeasibility.
- Current implementation solves a bounded single-bus model with SciPy/HiGHS, reports solver status, optimality scope and solve time, then replays the result through the shared simulator and independent diesel validator.

**Acceptance gate:** deterministic solutions reproduce within numerical tolerance, pass the same physical audit, and outperform or explain trade-offs against transparent baselines on declared benchmark cases. No general global-optimum claim beyond the exact mathematical model and solver status.

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

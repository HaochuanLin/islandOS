# IslandOS AI Architecture — Working Draft

**Status:** working design plus experimental simulation components. Planned features are identified explicitly; no field deployment is claimed.

## 1. Design goal

Build a simulation-first decision-support system that allocates available renewable electricity among essential demand and flexible resource-producing loads. The system should explain its choices and demonstrate improvements against a transparent baseline under repeatable scenarios.

The core is the contract between input data and forecasts, a physical simulation model, flexible-load models, a planner/optimizer, constraint validation and metrics, and decision explanations.

## 2. Decision loop

For each planning time step:

1. Read current renewable output, essential demand, resource inventories, and load states.
2. Obtain forecasts for a finite horizon. Forecasts must be distinct from future observations used only for post-run evaluation.
3. Generate candidate schedules for flexible loads.
4. Reject or penalize infeasible schedules according to clearly defined hard constraints.
5. Evaluate feasible schedules with the same simulator and objective definitions.
6. Maintain a non-dominated candidate set when using a multi-objective method.
7. Choose an operational action from the feasible candidate set using an explicit policy; never select a recommendation from a disconnected optimization run.
8. Execute only the near-term action, observe the updated state, and re-plan.

This rolling-horizon workflow is proposed, not yet implemented.

## 3. Essential services and flexible loads

Essential electricity demand must be treated as a priority. Flexible loads may consume only the power left after essential demand and other modelled constraints are accounted for. If backup generation or a battery is included later, its power and energy limits, efficiency, and costs must be explicit.

Each plug-in should expose identity/configuration, operating state, feasibility constraints, resource conversion, inventory/demand, economics where known, and validation. A module must not claim benefits outside its physical model. Freshwater shifts electricity consumption in time; it does not regenerate electricity. Ice storage provides cooling service, not electricity.

## 4. Candidate modules

| Module | State/inventory | Key constraints | Useful output | Status |
|---|---|---|---|---|
| RO desalination | Reservoir volume, simplified run state | Rated power, minimum run time, reservoir bounds | Freshwater | Experimental plug-in; separate from legacy demo |
| Ice making / cold storage | Stored thermal energy | Chiller power, COP, storage capacity, cooling demand | Cooling | Simplified experimental plug-in |
| Hydrogen | Hydrogen inventory | Efficiency, operating limits, storage and safety | Hydrogen | Planned |
| Municipal services | Process backlog or treatment state | Service deadlines, environmental constraints | Public service | Planned |
| Deferrable computing | Pending work | Deadline, interruptibility, maximum power | Completed jobs | Planned |

## 5. Shared-budget dispatch engine (experimental implementation)

dispatch_engine.py introduces a sequential, priority-based dispatcher over a single renewable-surplus budget.

- The caller provides loads in priority order and one demand series per load.
- Each load receives only the residual power left by earlier-priority loads.
- For RO, the dispatcher constructs a forecast window from the residual time series. This preserves shared-budget accounting but still assumes perfect look-ahead over the supplied series.
- Renewable power draw is calculated as total load power minus explicitly reported backup power.
- The dispatcher checks that no load exceeds its residual renewable budget and verifies the conservation identity: initial surplus equals total renewable allocation plus remaining surplus.
- Backup is reported separately; this module does not model the dispatch of a diesel generator or battery.

This is a transparent baseline policy, not an optimizer. Priority order can materially change results and must be reported when comparing scenarios.

## 6. Forecasting: start with honest baselines

Candidate approaches include persistence or seasonal-naive baselines, simple statistical models, and machine-learning models when data quantity and quality justify them. Evaluate forecasts on held-out periods with documented metrics such as MAE or RMSE. Avoid data leakage: future actual values must not be used to generate a forecast. For synthetic experiments, disclose the data-generation process and test robustness to its assumptions.

## 7. Optimization: compare before committing

Candidate methods include an interpretable rule-based heuristic, NSGA-II, and multi-objective simulated annealing (MOSA) if its acceptance rule, archive management, and diversity strategy are implemented and tested. Algorithm choice should be based on schedule representation, constraints, runtime, repeatability, and solution quality—not branding.

Potential objectives include operating cost, unserved essential electricity, unmet water/cooling demand, renewable curtailment, defensible battery degradation, and value of useful resources. Critical services may be hard constraints. Cost, emissions, and degradation terms should be included only with documented assumptions.

A credible Pareto workflow generates candidates, simulates all candidates with the same model, filters infeasible and dominated candidates, checks duplicates and diversity, reports each candidate's objective values and feasibility, and selects any recommendation from that same evaluated archive using a disclosed decision rule. An approximate archive is not proof of the complete Pareto front or a global optimum.

## 8. Evaluation protocol

Compare baseline and optimized strategies on the same scenarios, including multiple random seeds, low/medium/high renewable conditions, demand peaks, resource shortages, forecast errors, module availability changes, and equipment boundary cases.

Report renewable curtailment, essential electricity not served, each load's electricity and useful output, resource shortages and inventories, cost only if modelled, degradation only if modelled, constraint violations, runtime, seed, and configuration. Lower curtailment alone is not sufficient if essential service or resource delivery worsens.

## 9. Implementation stages

1. **Simulation integrity:** test energy and water balance; expose equipment constraints; preserve the existing CLI demo.
2. **Load interface:** an experimental common contract exists in flexible_loads.py with two initial load plug-ins.
3. **Shared budget:** an experimental sequential dispatcher allocates residual renewable power and checks conservation; further cross-load and edge-case validation is required.
4. **Forecasting and rolling planning:** implement a baseline forecast, separate forecast inputs from future actuals, and re-plan after observations.
5. **Multi-objective optimization:** centralize objective calculation, constraint validation, Pareto filtering, and selection from the same candidate archive.
6. **Scenario evaluation:** compare controlled scenarios and publish reproducible configurations and output summaries.

## 10. Non-goals for the first AI MVP

- No real-world cost savings claims without site-specific comparative evidence.
- No battery replacement/lifetime-extension claims without a defined battery model and baseline.
- No claim of autonomous control or hardware integration; this is simulation-only.
- No language model added merely for an AI label if it does not improve forecasting, planning, explanation, or decisions.

## 11. Definition of a credible milestone

A milestone is ready to describe as implemented when code exists, automated tests cover its core constraints, commands reproduce results, units and assumptions are documented, results are compared against a baseline, and limitations accompany claims.


## 12. Connected optimization prototype

The experimental module `optimization/grid_search_optimizer.py` connects candidate generation, the shared-budget simulator, Pareto filtering, and recommendation selection in one pipeline.

- **Search space:** eight candidates formed by two load priority orders and four RO minimum-run durations.
- **Evaluation:** every candidate uses `dispatch_flexible_loads` and the same scenario input.
- **Objectives:** minimize unmet water demand, unmet cooling demand, and remaining surplus. This objective set is illustrative; lower remaining surplus is not inherently better if it comes at an unacceptable resource or operating cost.
- **Feasibility:** candidates with modelled constraint-violation hours are excluded from the archive.
- **Archive:** candidates are retained if no other feasible evaluated candidate is at least as good in all three objectives and strictly better in one.
- **Recommendation:** a disclosed weighted normalized score selects one candidate from the same archive; the selected ID is checked by tests to belong to that archive.
- **Limitations:** the search space is small and manually parameterized. This is grid search, not AI/ML or a guarantee of a globally optimal schedule. The scenario profiles are synthetic, and the weights encode a policy choice rather than an objective truth.


## 13. Physical accounting and horizon-boundary checks

The RO plug-in refuses to start a new minimum-run cycle if the simulation has fewer than the required run hours remaining. This prevents the model from initiating a cycle that it knowingly cannot complete inside the simulated horizon. A cycle that was already running before the horizon boundary is still a modelling edge case for future rolling-horizon work.

Automated tests now assert stepwise accounting identities:
- RO water inventory at the next step equals current inventory plus production minus spill and water delivered.
- Cold-storage inventory at the next step equals current thermal inventory plus cooling produced minus cooling served and spill.
- Served demand plus unmet demand equals the requested demand for each time step.
- Inventories remain within configured bounds.

These are accounting invariants, not field validation. They test whether the code conserves its modelled quantities, not whether the chosen process assumptions match a real installation.


## 14. Forecast-error policy-selection sensitivity

`experiments/forecast_error_robustness.py` tests 12 deterministic cases: three synthetic surplus scenarios crossed with four forecast-error profiles (perfect, +20%, -20%, and alternating +/-20%).

For each case, the grid-search optimizer selects a policy candidate from the perturbed forecast profile. That selected candidate and a fixed RO-first, two-hour minimum-run baseline are evaluated on the original synthetic profile. The optimizer run on the original profile is shown as a perfect-information hindsight reference, not a deployable policy.

This is a **policy-selection sensitivity test**, not a forecast-model evaluation. The dispatch engine receives the original per-step power when candidates are replayed, so it remains reactive rather than executing a locked schedule planned from the forecast. No learned forecasting model, real weather data, probabilistic calibration, or field data are included. A future version should introduce a rolling-horizon planner that commits actions before observing realized generation, then score forecast errors against that locked plan.

# IslandOS AI and Decision Architecture

**Status:** architecture reference for the current research prototype. Implementation maturity is stated per capability; this document does not claim a field-validated or production control system.

## 1. Product role

IslandOS is an AI-assisted, simulation-first decision-support platform for energy-constrained infrastructure. It combines data onboarding, forecasting, constrained resource coordination, scenario comparison, and human-reviewed decisions.

AI refers to statistical and machine-learning forecasting, uncertainty analysis, and algorithmic optimization. A language model may assist explanation or interaction, but must not replace validated data, physical accounting, constraint checks, or operator authority.

## 2. Canonical user-facing workflow

The only public product workflow is:

**INPUT → FORECAST → COORDINATE → COMPARE → DECIDE**

| Step | Responsibility | Evidence / output | Maturity boundary |
|---|---|---|---|
| INPUT | Ingest and validate data, units, asset records, constraints, provenance and site configuration | Validated inputs, data-quality findings, asset/configuration records | CSV/XLSX onboarding and local workspace foundations exist; arbitrary vendor plug-and-play is not established |
| FORECAST | Estimate future generation, demand, resource needs, prices or availability where suitable data exists | Forecast series, chronological backtests, baseline metrics, provenance and uncertainty information where supported | Canonical forecast catalog and candidate interfaces exist; candidate quality is dataset-specific; site-calibrated accuracy is unproven |
| COORDINATE | Generate candidate schedules and allocate supported resources under explicit technical and service constraints | Feasible/infeasible schedules, resource allocations and constraint diagnostics | Bounded dispatch and selected battery/diesel/flexible-load/RO paths exist; broad universal multi-resource optimization is not established |
| COMPARE | Replay baseline and candidate alternatives under common assumptions and compare cost, service, reliability and resource-use trade-offs | Like-for-like metrics, service-equivalence checks, stress-case and sensitivity outputs | Selected comparisons exist; comprehensive cross-asset scorecards and customer-validated economics remain incomplete |
| DECIDE | Present rationale, assumptions, risks and audit records for human review | Decision summary, provenance, downloadable audit and unresolved-data needs | Decision/audit foundations exist; output is advisory and does not authorize equipment operation |

`PREDICT` in older code or documents means the forecasting responsibility now named `FORECAST`. `OPTIMIZE` refers to algorithms used within `COORDINATE`; it is not a separate public workflow step.

## 3. Technical pipeline

1. **Input contracts:** parse source data, validate schema, timestamps, units, missingness and provenance. Reject or quarantine malformed, stale, duplicate or future-dated critical observations according to the relevant contract.
2. **Signal preparation:** map source columns to canonical signal identifiers and retain source identity, units, timezone, interval and transformation metadata.
3. **Forecast generation:** use transparent persistence/seasonal baselines first. Optional statistical or machine-learning candidates must share input/output contracts and chronological evaluation folds.
4. **Constraint-aware coordination:** translate forecast signals into supported model inputs; enforce hard service and equipment constraints; explicitly report infeasible requests.
5. **Common-model comparison:** evaluate baseline and candidate schedules with the same physical/accounting model, time horizon, tariff and service requirements.
6. **Decision evidence:** persist model identity, input provenance, assumptions, constraints, scenario identifiers and output metrics so a reviewer can reproduce the result.

A module existing in the repository does not prove it is connected end-to-end to the hosted application. A passing software test does not establish forecast skill, field feasibility, safety, customer value or savings.

## 4. Forecasting requirements

- Preserve chronological ordering; do not randomly shuffle time-series observations when doing forward-looking evaluation.
- Use rolling-origin or otherwise time-respecting holdouts appropriate to the data.
- Compare candidates with persistence or seasonal-naive baselines on identical folds.
- Report MAE, RMSE, bias and WAPE only where the denominator and interpretation are appropriate.
- Record target signal, units, horizon, cadence, timezone, training window, test window, model version and data provenance.
- Keep future actual observations unavailable to forecast generation; use them only for retrospective scoring.
- Label synthetic-data performance as synthetic; public data from another geography is not site validation.
- Treat uncertainty intervals as empirical or model-derived only to the extent the method supports; do not call them calibrated without calibration evidence.

## 5. Coordination and optimization requirements

- Essential services and explicitly declared reserves take precedence over flexible consumption.
- Enforce rated power, energy, storage state, availability, minimum run/stop, time windows and process service requirements when represented by the model.
- If a required constraint cannot be represented, disclose the omission rather than implying it is enforced.
- Reject or flag infeasible schedules; do not silently shed critical service to improve cost.
- Replay all compared schedules through the same physical/accounting model.
- Describe heuristic search as bounded candidate search, not a guaranteed global optimum.
- Include cost, emissions, degradation or lifecycle terms only when their inputs, units and accounting boundary are documented.
- Forecast uncertainty and robust optimization remain experimental unless an end-to-end tested path proves otherwise.

## 6. Current model boundaries

The deterministic integrated microgrid model provides a selected energy/water accounting baseline for supported PV, wind, battery, grid, backup, RO and water-inventory flows. It is not a universal digital twin and does not model every network, protection, transient, plant-safety or process-chemistry behavior.

The device-level flexibility planner supports selected task classes and constraints. Its outputs are planning demonstrations, not measured savings. Tariff forecasting and price-aware flexible-load LP are experimental baselines, not trained market-price services.

Rolling-horizon and alternative multi-objective algorithms are research workflows. Their presence must not be interpreted as live MPC or operational control.

## 7. Technology responsibility boundaries

| Technology | Role | Guardrail |
|---|---|---|
| Physical equations / system model | Account for energy, power, storage, conversion and resource inventory | Never silently infer unknown physical parameters |
| Statistics and ML | Forecast signals when data supports the target and horizon | Chronological baselines, leakage prevention, provenance and limitations |
| Scenario analysis | Explore forecast error, outages, low renewable supply, demand spikes and derating | State seeds, distributions and calibration status |
| LP / MILP / heuristics / NSGA-II | Generate candidate schedules and explore trade-offs | Feasibility checks; no unsupported global-optimum claims |
| Rolling-horizon / MPC concepts | Re-plan as observations change | Advisory/simulation first; no execution without separate approval and site safety review |
| LLM | Explain outputs and summarize risks | Must not invent measurements, bypass constraints or issue device commands |

## 8. Evidence required for claims

Every metric should identify scenario, source, time window, seed where applicable, baseline, assumptions, units and model/software version.

| Evidence family | Required evidence |
|---|---|
| Physical correctness | Energy/resource balance residuals; SOC and inventory-bound violations |
| Service reliability | Unserved essential energy/hours; unmet resource demand; reserve violations |
| Energy performance | Renewable utilization/curtailment, grid imports, backup generation, storage throughput |
| Economic performance | Explicit tariff, fuel, CAPEX/OPEX, maintenance, replacement and sensitivity assumptions |
| Forecast performance | MAE/RMSE/bias against chronological baselines on held-out periods |
| Coordination quality | Feasible-schedule rate, service equivalence, trade-offs, runtime and repeatability |
| Robustness | Paired seeds, forecast error, outages, demand spikes, price shocks, equipment derating and invalid telemetry |
| Integration readiness | Adapter contract tests, freshness/unit checks, read-only shadow logs, operator review and rollback evidence |

A benchmark is not product proof if it uses future actuals unavailable at decision time, compares against a deliberately weak baseline, or hides unmet service.

## 9. Maturity labels

- **IMPLEMENTED:** present on `main` and supported by appropriate tests or reproducible evidence for the stated scope.
- **EXPERIMENTAL:** code or workflow exists but remains exploratory, limited, incompletely integrated, or not validated for general use.
- **PLANNED:** target capability without a usable current workflow.
- **LONG-TERM:** depends on site integration, independent review, operational approval, security, hardware or commercial validation.

A pull request is not part of mainline implementation until merged. Software tests do not establish site accuracy, safety acceptance or commercial outcomes.

## 10. Explicit non-claims

IslandOS does not currently claim universal plug-and-play integration, validated all-signal forecasting at a customer site, globally optimal dispatch, certified safety, autonomous online learning, live PLC actuation, field-proven savings or bankable ROI. These require evidence beyond repository code and synthetic simulations.

See [Product System Blueprint](PRODUCT_SYSTEM_BLUEPRINT.md), [Repository Map](REPOSITORY_MAP.md), [Productization Roadmap](PRODUCTIZATION_ROADMAP.md), and [Engineering Stages 1–10 Closeout](ENGINEERING_STAGES_1_10_CLOSEOUT.md) for related architecture and delivery boundaries.

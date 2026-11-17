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

**Status: in progress in PR #255.**

- Provide one command-line example using synthetic, clearly labelled input data.
- Connect canonical multi-signal forecasting to the existing forecast-to-resource optimizer.
- Include water-demand/RO coupling, deterministic stress scenarios, physical/service constraints, baseline comparisons and provenance.
- Emit machine-readable output and explicitly report that no device write is authorized and no global optimum is claimed.
- Add an automated test that executes the example end to end.

**Acceptance gate:** the example runs in CI; at least one candidate passes all configured constraints and the physical audit; outputs include the synthetic-data label, forecast/model provenance, baseline comparisons and advisory-only boundary.

### Stage 2 — Equipment-constraint completeness

- Extend candidate generation so diesel schedules can satisfy configured ramp-up and ramp-down limits, minimum stable output, minimum up-time and minimum down-time.
- Include fuel inventory / delivery limits where configured.
- Preserve battery SOC, charge/discharge power, efficiency and degradation constraints.
- Reject unsupported or incomplete site configurations explicitly; never silently clip an infeasible request and label it feasible.
- Add boundary and adversarial tests for every equipment constraint.

**Acceptance gate:** every returned candidate passes the shared physical audit and an independent constraint validator; infeasible configurations fail closed with actionable diagnostics.

### Stage 3 — Deterministic optimization benchmark

- Add a deterministic mathematical-programming reference solver using the already pinned SciPy MILP capability, subject to a formulation review.
- Start with a clearly bounded model (battery, grid, diesel and essential load); add binary commitment variables only where required.
- Keep the evolutionary optimizer as a comparison method, not silently replace it.
- Replay both methods through the same physical simulator and compare objective values, feasibility, runtime and repeatability on identical inputs.
- Add small instances with independently checkable optima and tests for solver timeout / infeasibility.

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


---

# Current Status Register — Mainline Evidence and Parallel Commercial Track

This register supplements, and does not replace or renumber, Engineering Roadmap Stages 1–6 above. Status below is assessed against **main**, not against unmerged pull requests. PR branches are identified separately so experimental work is not represented as shipped capability.

## Two parallel delivery tracks

- **Engineering Track — Stages 1–6:** establish reliable data, validated forecasts, physically feasible resource coordination, uncertainty handling, joint optimization and an auditable operator workflow.
- **Customer Value & Commercial Evidence Track — Stages 7–12:** establish who has the problem, whether it matters economically, how the market and buying process work, what approvals are needed, how recommendations are explained, and how external validation can be performed.

Stage 7 can proceed immediately because interviews and hypothesis design do not require the optimizer to be complete. Stages 8 and 11 must consume stable, traceable outputs from the engineering track. Stage 12 depends on Stage 6's read-only workflow and on authorized external evidence. No commercial stage lowers an engineering acceptance gate.

## Engineering Track — Stage 1–6 status register

### Stage 1 — Reliable Data Foundation / reproducible end-to-end demonstration
- **Current status (main): PARTIAL.** Main contains canonical forecasting/data-onboarding components and forecast/dispatch adapters, but the new single-command forecast-to-joint-optimizer demonstration in PR #255 is not merged.
- **Implemented evidence on main:** canonical signal catalog and provenance-oriented onboarding; forecast/dispatch adapters; existing forecast dispatch demos and regression tests.
- **Remaining tasks:** land and review the reproducible end-to-end example; align forecast timestamps, units and horizons; ensure data-quality failures block optimization; verify machine-readable provenance and output schemas.
- **Dependencies:** canonical data contracts and forecast adapter.
- **Acceptance criteria:** clean CI executes the example; identical inputs reproduce outputs within stated tolerance; at least one candidate passes independent physical and service audits; synthetic provenance and advisory-only boundary are explicit.
- **Tests required:** valid/invalid input schema, missing and non-finite data, timestamp alignment, deterministic run signature, end-to-end example, physical audit and output schema.
- **Known limitations:** synthetic data does not validate site accuracy; main does not yet contain the PR #255 joint workflow.

### Stage 2 — Forecasting Validation / equipment-constraint completeness
- **Current status (main): PARTIAL.** Main has forecasting evaluation and physical equipment checks in existing simulation paths. The broader diesel commitment/fuel and battery constraint implementation described in PR #255 is not merged.
- **Implemented evidence on main:** chronological forecast evaluation and forecast quality tests; existing dispatch and battery/RO constraint tests.
- **Remaining tasks:** validate each forecast signal against suitable baselines and chronological holdouts; complete constraint coverage in the optimizer actually used by the workflow; reject unsupported equipment models explicitly.
- **Dependencies:** Stage 1 data contracts; declared asset specifications and independent audit.
- **Acceptance criteria:** forecast metrics are computed on held-out observations; every optimizer candidate passes independent equipment validation; unsupported configurations fail closed with actionable diagnostics.
- **Tests required:** leakage/chronology, interval coverage where applicable, boundary and adversarial equipment constraints, infeasible configurations, independent replay.
- **Known limitations:** model performance on synthetic fixtures is not field forecast accuracy; PR #255's bounded MILP work remains unmerged.

### Stage 3 — Constraint-aware Resource Coordination / deterministic benchmark
- **Current status (main): PARTIAL.** Main has a seeded evolutionary dispatch optimizer and transparent heuristic baselines. The deterministic SciPy/HiGHS MILP reference implementation is in unmerged PR #255.
- **Implemented evidence on main:** evolutionary candidate search, dispatch simulation, baseline comparison and feasibility/audit tests.
- **Remaining tasks:** review and land a bounded MILP reference solver; establish independently checkable small cases; compare evolutionary and MILP approaches on identical cases; report runtime, feasibility and objective reconciliation.
- **Dependencies:** Stages 1–2, stable physics and declared objective terms.
- **Acceptance criteria:** deterministic reference cases reproduce; solutions pass shared physical replay; solver status and optimality scope are explicit; no claim exceeds the mathematical formulation.
- **Tests required:** known-optimum fixtures, repeatability, infeasible and timeout behavior, objective-to-replay reconciliation, baseline parity and physical audit.
- **Known limitations:** heuristic search is not globally optimal; PR #255's MILP is not a mainline capability and its latest head has no current CI run.

### Stage 4 — Forecast Uncertainty
- **Current status (main): PARTIAL.** Main contains forecast interval / uncertainty-related evaluation components. PR #255 adds a deterministic stress-case builder, but it is not merged or connected to optimizer sensitivity evaluation.
- **Implemented evidence on main:** forecast validation and uncertainty/forecast evaluation tests.
- **Remaining tasks:** assess interval calibration on chronological held-out data; distinguish marginal bounds from joint scenarios; route supported scenarios through the optimizer and report schedule sensitivity.
- **Dependencies:** validated forecast outputs from Stage 2 and deterministic optimizer from Stage 3.
- **Acceptance criteria:** each tested scenario has provenance and explicit probability status; no unsupported joint probabilities; recommendations are auditable across the declared uncertainty set.
- **Tests required:** interval alignment/coverage, invalid bounds, scenario construction, missing probability handling, optimizer replay across scenarios.
- **Known limitations:** synthetic intervals do not establish calibrated site uncertainty; deterministic directional stress cases are not probability distributions.

### Stage 5 — Joint Multi-resource Optimisation
- **Current status (main): NOT COMPLETE.** Main has separate energy dispatch and RO/water scheduling or costing components. The joint RO-production, tank-inventory and electrical MILP path is in PR #255 and is not merged.
- **Implemented evidence on main:** water-service adapters, RO scheduling heuristics, energy dispatch and water/RO cost accounting.
- **Remaining tasks:** integrate a reviewed joint optimizer; include flexible-load timing; compare against just-in-time and tariff-look-ahead policies at equivalent service; independently audit both electrical and water balances.
- **Dependencies:** Stages 1–4 and validated physical/equipment constraints.
- **Acceptance criteria:** one schedule simultaneously passes electrical, water, tank and equipment audits; unmet service is explicit; cost comparisons use the same time horizon and equivalent service.
- **Tests required:** water balance, tank bounds, RO capacity, load balance, flexible-load service, boundary cases, infeasibility and equivalent-service comparisons.
- **Known limitations:** separate heuristics are not joint optimization; no joint optimizer in PR #255 should be counted as mainline until merged and validated.

### Stage 6 — Operator Workflow & Shadow Mode
- **Current status (main): PARTIAL.** Main contains operator-facing pages/adapters and read-only shadow/evidence components. The new MILP-to-human-review decision-record example in PR #255 is not merged.
- **Implemented evidence on main:** customer dashboard and decision/audit components; shadow-mode comparison/evidence tests; hosted Streamlit application and advisory-only messaging.
- **Remaining tasks:** connect a reproducible recommendation record to the complete forecast/optimizer workflow; expose provenance, constraints, alternatives, limitations and approval state; conduct authorized retrospective replay before any shadow evaluation.
- **Dependencies:** Stages 1–5; authorized site data and accountable operator approval for external evaluation.
- **Acceptance criteria:** an operator can reproduce a recommendation from saved inputs/configuration; all outputs are read-only; human approval is explicit; site claims require independent evidence.
- **Tests required:** record integrity, provenance, constraint traceability, human approval state, no-command/no-write boundary, shadow comparison and failure handling.
- **Known limitations:** UI components do not by themselves establish a complete operator workflow; no site-specific retrospective validation or live actuation is claimed.

## Customer Value & Commercial Evidence Track — Stage 7–12

### Stage 7 — Customer Discovery & Persona
- **Status:** IN PROGRESS — discovery plan, role-separated persona hypotheses, problem hypothesis register and interview guide added in this branch.
- **Evidence:** documentation only; zero interview records are evidenced; all problem hypotheses remain NOT VALIDATED.
- **Remaining tasks:** conduct consent-based interviews across user, technical evaluator and economic buyer roles; anonymize records; update hypotheses with supporting and contradictory evidence.
- **Dependencies:** none beyond honest product-boundary description; can run alongside Engineering Stages 1–6.
- **Acceptance criteria:** documented evidence-backed target segment, role and buying path; auditable interview records; unresolved questions and sample limits explicit.
- **Tests / checks:** documentation link and consistency checks; manual review of consent, anonymization and evidence classification.
- **Limitations:** no customer feedback, partner, pilot, purchase or willingness-to-pay evidence is claimed.

### Stage 8 — Synthetic Impact & Economic Evidence
- **Status:** NOT STARTED.
- **Evidence:** existing RO cost accounting and economic sensitivity utilities are present and must be inspected/reused; no Stage 8 customer-impact comparison is implemented.
- **Remaining tasks:** build one repeatable synthetic case using identical inputs and constraints for baseline and candidate; reuse existing objective/cost accounting; report only metrics supported by the selected simulator and its audits; separate gross modeled operating benefit from software, integration, maintenance and training assumptions.
- **Dependencies:** Stage 7's problem definition; stable and auditable outputs from Engineering Stages 1–5. Start only after the chosen dispatch path can compare equivalent service.
- **Acceptance criteria:** deterministic example; identical input horizon and asset limits; independent physical/service audit; explicit units, currency and cost period; all unknown costs remain unknown; no synthetic saving described as a real customer saving.
- **Tests required:** input validation, unit/horizon alignment, baseline equivalence, physical violations, zero/negative values, economic arithmetic, missing-cost behavior and repeatability.
- **Limitations:** synthetic results show model behavior only and cannot establish customer ROI.

### Stage 9 — Market Sizing & Market Entry
- **Status:** NOT STARTED.
- **Evidence:** no defensible TAM/SAM/SOM dataset is currently established by this stage.
- **Remaining tasks:** define facility segments and eligibility filters; distinguish problem scale, facilities, technically suitable facilities and reachable buyers; create a source/year/geography/assumption/confidence register.
- **Dependencies:** Stage 7 target-segment evidence; Stage 8 definition of the customer problem and measurable value mechanism.
- **Acceptance criteria:** every numeric estimate is reproducible and sourced; ranges and exclusions are explicit; absent data is shown as a gap, not replaced by invented market size.
- **Tests / checks:** arithmetic and source audit; independent recalculation of segment filters and totals.
- **Limitations:** no market number or market share is claimed without traceable evidence.

### Stage 10 — Regulatory, Funding & Partnership Readiness
- **Status:** NOT STARTED.
- **Evidence:** existing data governance, security and pilot-readiness documentation provides reusable inputs; no jurisdiction-specific approval or secured funding/partnership is claimed.
- **Remaining tasks:** map authorization, privacy/cybersecurity, electrical protection, metering, dispatch authority, engineering approval, liability and any future actuation approval for a selected jurisdiction; document exploratory funding and partner routes.
- **Dependencies:** Stage 7 segment/geography; Stage 6 advisory boundary; future site-specific technical design.
- **Acceptance criteria:** jurisdiction and responsible authority identified for each requirement; unknowns and professional review needs explicit; funding and partnerships labelled exploratory until evidenced.
- **Tests / checks:** checklist completeness and source/date review; legal and engineering review before any real pilot.
- **Limitations:** generic documentation is not legal advice, regulatory approval, funding award or partnership agreement.

### Stage 11 — Customer Decision Product
- **Status:** NOT STARTED.
- **Evidence:** existing dashboard, audit, provenance and decision-record components must be reused; PR #255's decision-record primitive is not mainline.
- **Remaining tasks:** produce a customer-readable report with recommendation, baseline and alternatives, supported cost/service metrics, constraints, uncertainty, rationale, approval and provenance; trace every result to inputs, model and constraints.
- **Dependencies:** Engineering Stages 1–6 for stable output contracts; Stage 8 for economic fields; Stage 7 for role-specific language.
- **Acceptance criteria:** report is reproducible and auditable; missing metrics are omitted or labelled unavailable; no recommendation bypasses human approval; no device command is generated.
- **Tests required:** schema, provenance linkage, missing/invalid metrics, constraint disclosure, report determinism, approval state and no-command boundary.
- **Limitations:** customer report is a decision-support artifact, not a guarantee of savings or safe operation.

### Stage 12 — External Validation & Pilot Readiness
- **Status:** NOT STARTED — external validation NOT VALIDATED.
- **Evidence:** existing pilot governance, data onboarding and read-only shadow components provide a starting point; no authorized site dataset or completed external evaluation is claimed here.
- **Remaining tasks:** consent-based interviews; authorized historical data; qualified engineering review; retrospective replay; read-only Shadow Mode; operator disagreement logging; value and willingness-to-pay research; explicit stop/go gates.
- **Dependencies:** Stage 6 read-only workflow; Stages 7–11; site-owner authorization and qualified local engineering/security review.
- **Acceptance criteria:** written authorization, data-quality report, independent technical review, predefined success/stop thresholds, operator sign-off and reproducible evaluation report. Any missing approval is a no-go.
- **Tests / checks:** replay reproducibility, data permission audit, disagreement log completeness, shadow safety boundary and pre-agreed stop/go review.
- **Limitations:** code-only work and synthetic data cannot complete this stage; no deployment or actuation is authorized.

## Dependency map

- Stage 7 may proceed immediately and in parallel with Engineering Stages 1–6.
- Stage 8 requires Stage 7's problem/value hypotheses and stable, equivalent-service outputs from Engineering Stages 1–5.
- Stage 9 uses Stage 7's segment definition and Stage 8's value mechanism; it must not invent market totals.
- Stage 10 can be prepared alongside Stages 7–9, but its final checklist must be scoped to an actual target geography and site.
- Stage 11 depends on stable engineering output/provenance contracts (Stages 1–6), customer language (Stage 7) and supported economics (Stage 8).
- Stage 12 depends on Stage 6's read-only workflow and evidence/authorization produced across Stages 7–11.

## Repository implementation policy

- New commercial work is developed on a separate branch and reviewed independently from pending engineering PRs.
- Do not duplicate existing cost accounting, decision audit, provenance or shadow-mode modules. Inspect and reuse them before adding code.
- Preserve requirements locks, automated tests, Docker and Streamlit behavior. Do not connect experimental modules to the hosted app without a separate integration review.
- Do not merge while required CI is failing, absent or associated with a different commit. Draft PRs remain Draft until explicitly reviewed.
- Synthetic, inferred, externally reported and independently verified evidence must remain distinguishable.

# IslandOS zero-resource product hardening — new stages 1–6

**Purpose:** Convert the existing research/software foundations into a coherent, independently inspectable engineering-grade prototype without assuming customer access, site data, funding, hardware, or external partners.

**Relationship to existing roadmaps:** This is a new release/hardening sequence. It does not renumber or replace the historical engineering stages 1–10, the earlier A–F workstream, or the customer/commercial stages 7–12. It consolidates their remaining product-level gaps into six outcome-oriented stages.

**Evidence rule:** A stage is complete only when its acceptance evidence exists on `main`, the relevant automated checks pass on the exact merged commit, and the stated limitations remain visible. Documentation or an open PR alone is not completion.

## Stage 1 — Reproducible product baseline and repository convergence

**Goal:** A new technical user can clone, install, configure, run, test, and inspect the same supported IslandOS workflow without developer intervention.

Work:
- Reconcile open implementation branches against current `main`; identify unique value, stale duplicates, conflicts, and exact-head CI.
- Keep one canonical runtime path and document which app, API, CLI, and frontend paths are actually supported.
- Provide a clean-environment quick start and a single documented verification command.
- Verify runtime/development dependency locks, health checks, deterministic examples, and failure diagnostics.
- Remove or clearly quarantine dead/duplicate entry points only after import/call-path checks.

Acceptance:
- Fresh environment setup succeeds from documented commands.
- Supported local workflow starts and health checks pass.
- Full test suite and all required build/smoke workflows pass on the exact main commit.
- A contributor can reproduce one end-to-end example from a clean checkout.
- Unsupported or experimental paths are labelled, not silently presented as production-ready.

Initial findings (2026-11-18):
- `main` is `1a5d91df00af5d37ae3d2e6a065dc7d876de47da`.
- Existing merged software foundations are recorded in `docs/ENGINEERING_STAGES_1_10_CLOSEOUT.md`; its reviewed baseline is older and must be refreshed before it is treated as a current CI ledger.
- Open PRs include #250 (public-data forecast evaluation), #253 (canonical runtime/safety boundaries), #254 (guided Streamlit workspace), #255 (forecast-to-optimizer/MILP work), and #262 (one-line MILP replay interface fix). Their scopes overlap in places and must be reconciled rather than mass-merged.
- Exact-head checks observed: #250 all six workflows passed; #254 all seven observed workflows passed; #253 Python unit tests failed while its other five observed workflows passed; #262 all six workflows passed. #255 had no associated PR-triggered workflow runs in the current query.
- No claim is made here that any of these open PRs has merged.

## Stage 2 — Trustworthy data and portable site projects

**Goal:** A site/scenario is represented consistently from raw input through forecast, simulation, optimization, and report.

Work:
- Define and enforce canonical timestamp, timezone, unit, signal identity, asset identity, and missing-data contracts.
- Preserve source-file identity and provenance; distinguish measured, public, synthetic, and user-entered assumptions.
- Add portable project export/import with schema versioning and integrity checks.
- Fail closed on stale, duplicate, malformed, physically impossible, or unit-inconsistent critical inputs.
- Provide explicit data-quality and configuration-readiness reports.

Acceptance:
- Round-trip export/import preserves scenario meaning and provenance.
- Invalid critical inputs block downstream planning with actionable errors.
- Tests cover timezone/DST, gaps, duplicates, unit conversion, schema migration, and corrupted packages.
- A reproducible sample project runs end-to-end.

## Stage 3 — Evidence-grade forecasting

**Goal:** Forecasting is evaluated as a measurable service, not merely a model output.

Work:
- Use appropriate public historical datasets where licensing and data quality permit.
- Compare persistence, seasonal-naive, recent-mean/trend, and selected ML candidates on identical chronological windows.
- Prevent leakage in model selection, scaling, feature construction, and uncertainty estimation.
- Report per-signal/per-horizon MAE, RMSE, bias, WAPE where defined, fold boundaries, sample counts, and source hashes.
- Distinguish empirical error bands from calibrated prediction intervals; test regime and seasonal sensitivity.

Acceptance:
- One-click public-data replay produces a machine-readable report with source attribution and digest.
- All candidates are scored on identical holdout timestamps without training on the holdout.
- Baseline comparisons and failure cases are visible.
- No site-specific accuracy claim is made from public datasets.

## Stage 4 — Physically defensible multi-resource optimization

**Goal:** Candidate schedules are feasible under declared models and are independently checked before comparison.

Work:
- Reconcile the MILP reference path with the shared physical simulator and independent validators.
- Add known-optimum small fixtures, infeasible/timeout cases, repeatability checks, and objective-to-replay reconciliation.
- Extend supported asset constraints explicitly; reject unsupported constraints rather than silently ignoring them.
- Progress from bounded battery/grid/diesel dispatch to jointly optimized flexible loads and water/tank states where formulation is supportable.
- Compare against transparent baselines under equivalent service; report infeasibility and constraint violations.

Acceptance:
- Every displayed candidate passes independent physical and service audits.
- Known-optimum fixtures match within declared numerical tolerance.
- Solver timeout, infeasibility, and unsupported configurations fail closed.
- Claims are bounded to the mathematical model and tested asset set; no universal/global-optimum claim.

## Stage 5 — Defensible economics and decision-grade comparison

**Goal:** A reviewer can understand whether an option is economically attractive, what assumptions drive it, and when the right answer is “do not invest”.

Work:
- Build transparent lifecycle cost inputs: energy, fuel, demand charges where applicable, O&M, replacement, degradation only where modelled, integration, software, training, and financing assumptions where available.
- Keep service-equivalence and physical-feasibility gates ahead of savings calculations.
- Provide NPV, cash flow, simple/discounted payback, break-even, and sensitivity with explicit missing-input handling.
- Generate a structured decision report covering baseline, alternatives, cost/service impacts, assumptions, uncertainty, constraints, provenance, and no-go reasons.
- Clearly separate synthetic scenario economics from customer-verified economics.

Acceptance:
- Same inputs and model versions reproduce the same report.
- Missing cost inputs are not silently treated as zero.
- Infeasible or service-inferior options cannot be presented as savings.
- Report includes explicit “not enough evidence” and negative-value outcomes.

## Stage 6 — Independent operator workflow and deployment-ready prototype

**Goal:** A technically capable person who did not build IslandOS can complete and explain a bounded offline workflow, then review read-only evidence without device control.

Work:
- Connect INPUT → FORECAST → OPTIMIZE → COMPARE → DECIDE through one documented supported path.
- Make the UI show data quality, model provenance, uncertainty status, constraints, alternatives, infeasibility, limitations, and human approval.
- Complete local full-stack setup for the supported UI/API path, including safe defaults and health checks.
- Provide a simulator/mock adapter and contract tests for read-only telemetry; never imply a real vendor integration without testing it.
- Keep device writes disabled; define external prerequisites for any future site shadow trial.

Acceptance:
- Independent user test can complete the bounded workflow using a sample project without developer help.
- Saved run can be reproduced and exported with a verifiable audit record.
- Local deployment is documented and security boundaries are tested.
- No real-device actuation, safety certification, customer deployment, or field validation is claimed without separate external evidence.

## Delivery order and dependencies

- Stage 1 is the gatekeeper: establish the true mainline and supported runtime before expanding scope.
- Stage 2 underpins Stages 3–6.
- Stage 3 and Stage 4 can proceed in parallel once data contracts are stable.
- Stage 5 consumes only audited outputs from Stages 3–4.
- Stage 6 integrates the supported path and exposes evidence; it does not bypass upstream gates.

## Non-negotiable boundaries

- No fabricated customer interviews, site measurements, savings, partner commitments, or purchase intent.
- Synthetic data is always labelled synthetic; public data is not customer-site validation.
- A green test suite is software evidence, not a safety certificate or proof of physical operation.
- All device-write paths remain disabled.
- “Plug-and-play” is not claimed until a named interface has been independently tested on a real target environment.

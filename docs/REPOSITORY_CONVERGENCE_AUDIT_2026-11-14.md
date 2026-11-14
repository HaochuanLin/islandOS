# Repository convergence audit — stages 4–5

**Audit date:** 2026-11-14  
**Repository:** `HaochuanLin/islandOS`  
**Mainline snapshot audited:** `29c26af48c93a37d2a721acfcced53e068575df5`  
**Scope:** open pull requests, retained branch references, application/module boundaries, and duplicate-looking implementations.

This is a repository inventory and risk assessment. It is not a claim that every historical branch has been merged, every module is production-ready, or all end-to-end workflows are integrated.

## Executive findings

1. The mainline is coherent enough to continue from; no reason was found to reset the repository or mass-merge historical branches.
2. Branch inventory returned **248 non-main branch references**. Of these, 217 match branch heads associated with merged pull requests, 2 match currently open pull requests, and 29 have no matching merged/open PR head in the retrieved PR history.
3. The 29 unmatched branches were compared with main. Four are strictly behind main with zero unique commits. The other 25 have divergent histories and require content-level review; ahead/behind counts alone do not prove that their code is missing from main because squash-merged PRs create new commit ancestry.
4. Open PR #250 is still a draft. Its six observed CI checks passed, but its public OPSD evaluation tests use synthetic fixtures; the real downloaded OPSD data run is still explicitly outstanding. Do not claim public-data forecast accuracy or site validation from this PR.
5. Open PR #202 is a dependency update whose branch is 68 commits behind main. Its proposed `requirements.txt` replaces the current `-r requirements-runtime.lock` contract with floating minimum versions while leaving the lock unchanged. Do not merge without reconciling the lock and rerunning dependency/CI checks.
6. The application has multiple overlapping forecast and energy-model paths. These are not safe to delete based on names alone. A staged canonicalization is required.

## Stage 4 — branch and pull-request reconciliation

### 4.1 Branch inventory

| Classification | Count | Interpretation |
|---|---:|---|
| Branch refs matching a merged PR head | 217 | PR work was merged; branch refs remain on GitHub |
| Branch refs matching an open PR head | 2 | #250 and #202 |
| Branch refs without a matching merged/open PR head | 29 | Requires additional disposition |
| **Total non-main branch refs** | **248** | Snapshot count |

The PR history contains many merged engineering increments, including Phases A–F, engineering stages 1–10, G–K, forecast hardening, provenance, telemetry, economics, and Nan'ao pilot work. Examples include PRs #238–#249 and the older feature/hardening PRs. A branch whose name still exists is not evidence that its work is absent from main.

### 4.2 Four confirmed no-unique-commit branches

The following branches compare as `ahead_by = 0` and are behind main. They have no unique commits relative to the audited mainline:

- `product/device-mapping-preflight`
- `economic-sensitivity-report-guide`
- `markdown-link-integrity-check`
- `test/forecast-backtest-dispatch-contract`

**Disposition:** archive/delete candidates after a final reference check. No branch deletion was performed during this audit.

### 4.3 Divergent branches requiring preservation or manual review

The following examples have commits beyond main. They must not be bulk-deleted or merged without reviewing their file-level content and tests.

| Branch | Ahead / behind main | Initial assessment |
|---|---:|---|
| `product-foundation-desktop-ready` | 403 / 80 | Large alternate product/desktop line; contains desktop app, additional energy-system optimizer, and substantial docs/tests. Preserve for dedicated review. |
| `stage-3-unified-forecast-engine` | 268 / 80 | Related large alternate line; overlaps the desktop/product-foundation line. Preserve; compare by file and behavior before any migration. |
| `fix/uncertainty-dispatch-ci-readme` | 173 / 607 | Large historical integration line with app, telemetry, and dispatch changes; highly stale, not safe to merge wholesale. |
| `nan-ao-scenario-pilot` | 121 / 648 | Historical Nan'ao line. Keep as archival history; do not restore its old product identity or outputs to main. |
| `nan-ao-economic-dispatch` | 100 / 648 | Historical Nan'ao variant; do not merge wholesale. |
| `feat/phase5-local-data-workspace-port` | 8 / 64 | Workspace implementation history; much of this domain is already represented in main. Verify exact file parity before archiving. |
| `phase3/prediction-engine` | 22 / 31 | Earlier prediction/workspace integration line; likely superseded in part by merged Stage 2/3 work, but verify exact behavior. |
| `feat/phase-c-prediction-engine` | 4 / 62 | Earlier engine implementation; compare against current prediction engine before archiving. |
| `feat/stage-f-shadow-readiness` | 14 / 48 | Shadow/service changes; later Stage 9/10 work is in main. Verify whether any unique test or doc remains. |
| `feat/stage-f-shadow-readiness-foundation` | 8 / 48 | Overlaps the previous shadow branch; compare as a family. |
| `ui-rolling-dispatch-current-main` | 6 / 573 | Old app/UI snapshot; very stale and likely conflicts with current Streamlit page structure. Preserve until its tests and unique behavior are inspected. |
| `feat/dispatch-invariant-stress-suite` | 6 / 200 | Stress-test and CI work; check whether its test cases are already represented in main. |
| `feat/rolling-lab-weight-controls` | 3 / 194 | Rolling-lab UI changes; old branch, inspect only if the current page lacks the intended controls. |
| `supervised-pilot-acceptance-plan` | 2 / 563 | Historical acceptance-plan documentation; compare with current safety/governance docs. |
| `product/site-config-bootstrap-integration` | 2 / 360 | Small test change on a very stale line; verify against current site-config tests. |

The remaining unmatched references are older Dependabot, README, provenance, maturity-roadmap, Stage A evidence, readiness, and Stage F branches. They should be classified by exact file/blob parity and current CI relevance, not by branch names.

### 4.4 Open pull requests

#### PR #250 — public-data forecast evaluation

- Branch: `feat/phase2-opsd-canonical-evaluation`
- 32 commits ahead and 5 behind the audited main snapshot; GitHub reports the merge as clean.
- Six observed checks passed: Python dependency audit, Windows gateway build, container smoke test, RO tests, Python unit tests, and Nan'ao validation.
- Adds persistence baseline, chronological fold-level MAE/RMSE/bias/WAPE reporting, OPSD-to-canonical unit conversion, and stricter dispatch forecast validation.
- **Still a draft.** Its test fixtures are synthetic. The documentation correctly states that running the CLI against a real downloaded OPSD CSV is still required before claiming a public-data backtest.
- **Disposition:** preserve as a draft until the real public-data run is reproducible and the author marks it ready. Do not describe its passing tests as proof of forecast skill.

#### PR #202 — dependency updates

- Branch: `dependabot/pip/python-dependencies-cce624fea8`
- One commit ahead and 68 behind main; changes two requirements files.
- The branch changes `requirements.txt` to minimum-version ranges, while current main uses `requirements.txt` as a one-line include of `requirements-runtime.lock`. The PR does not update the runtime lock.
- **Disposition:** do not merge as-is. Reconcile the lock-generation contract and verify all pins, then rerun dependency audit and CI.

## Stage 5 — application and module architecture audit

### 5.1 Current call-path map

| Surface | Observed implementation path | Boundary |
|---|---|---|
| Main Streamlit app, `app.py` | `experiments.compare_energy_water_strategies`, `experiments.nsga2_dispatch_optimizer`, `optimization.price_aware_load_optimizer`, selected `islandos_core` modules, RO costing/baseline helpers | A large legacy-compatible screening surface; not a single end-to-end five-step orchestration service |
| Customer decision dashboard, page 05 | `forecast_engine` → `forecast_optimizer_adapter` / `energy_system` → `energy_system_optimizer` and lifecycle economics | Forecast-led customer screening path; synthetic defaults, no field validation |
| Forecast-led joint optimizer, page 06 | `forecast_signal_catalog` / `prediction_engine` → `prediction_dispatch_adapter` → `energy_system` | Newer canonical signal-catalog path; bounded offline schedule search |
| Device flexibility planner, page 09 | `flexible_tasks` → `flexible_task_dispatch` → `energy_system` | Equipment-task scheduling demonstration |
| Rolling horizon lab, page 2 | `experiments.rolling_horizon_dispatch` | Separate research/simulation page |
| Local customer workspace, page 07 | Loopback-only reference service UI | Not hosted SaaS authentication |
| Site workspace, page 08 | `site_workspace`, `workspace_store`, asset readiness | Local-first workspace; public hosted demo is not a customer data room |

The repository therefore contains several working paths, not one fully integrated pipeline. The five-step product workflow is the external product model; it must not be read as proof that every step is already wired into one application journey.

### 5.2 Duplicate-looking modules and correct treatment

| Concern | Existing paths | Assessment and action |
|---|---|---|
| Forecasting | `forecast_engine.py` and `prediction_engine.py` + `forecast_service.py` / `forecast_signal_catalog.py` | Two forecast paths are used by different pages. They have different candidate/evaluation contracts. Select one canonical service boundary, then adapt the other behind it; do not delete either before parity tests. |
| Energy accounting | `microgrid_model.py` and `energy_system.py` | Both simulate energy/resource behavior but cover different scopes. Define explicit model responsibilities and common input/output contracts before consolidation. |
| Schedule evaluation | `schedule_evaluator.py` and `optimization/energy_system_optimizer.py` | Rule-based common-model screening versus a separate optimizer. They are not interchangeable; add shared feasibility and service-equivalence tests before choosing a default. |
| Flexible loads | Root `flexible_loads.py` + `dispatch_engine.py`; core `flexible_tasks.py` + `flexible_task_dispatch.py` | Legacy load plug-in simulation versus equipment-task scheduling. Page 09 uses the core task path. Keep root modules as compatibility/research code until all consumers are identified. |
| Configuration | Root `islandos_config.py`; core `configuration.py` | Different scopes: illustrative RO/ice simulation settings versus typed site configuration. Do not merge based on similar names. |
| Telemetry/signal validation | Root `islandos_io.py`; core `signals.py` and forecast contracts | Root module handles telemetry parsing and fail-closed authorization; core contracts handle normalized signal values. Document the hand-off instead of replacing one with the other. |
| RO simulation | Root `island_microgrid_ro_sim.py`; core `microgrid_model.py` | Historical/standalone RO simulator versus integrated energy-water accounting. Preserve both until the test and consumer map is complete. |

### 5.3 Mainline architecture issues found

1. `app.py` still described the public product as a four-step workflow. This audit updates its docstring to the canonical five-step wording while explicitly stating that the complete workflow is not yet integrated end-to-end.
2. The main Streamlit entrypoint imports both `experiments/`, `optimization/`, and `islandos_core/`. This is functional but blurs the boundary between product services and research implementations.
3. The dashboard page and joint-optimizer page use different forecast services. This is the highest-priority convergence point because it affects model identity, metrics, provenance, and downstream scheduling.
4. The repository contains both a legacy energy-water model and a broader multi-resource energy model. A common accounting contract is needed before further optimization features are added.
5. Root modules are not automatically obsolete. Some are stable CLI/service boundaries, while others are older simulation entrypoints. Convert confirmed legacy consumers to thin wrappers only after tests and import/call-site checks.

### 5.4 Recommended canonical layering

- **UI:** `app.py` and `pages/` should collect inputs, render outputs, and call application services; avoid duplicating model logic in pages.
- **Application services:** one explicit orchestration layer should implement INPUT → FORECAST → COORDINATE → COMPARE → DECIDE for supported site types.
- **Domain/core:** `islandos_core/` should own canonical data contracts, signal semantics, site/asset models, physical accounting, feasibility, provenance, and decision records.
- **Algorithms:** `optimization/` should contain replaceable solver implementations called through core contracts.
- **Research:** `experiments/` should remain reproducible evaluation and benchmark code, not silently become the production application service.
- **Compatibility/CLI:** root entrypoints should either remain clearly documented tools or become thin wrappers around canonical core/application modules.

### 5.5 Next implementation gates

1. Build a machine-readable import/call graph from the full repository and map each module to its tests and UI/CLI consumers.
2. Define one forecast service contract and migrate page 05/page 06 behind adapters; require identical chronological folds, baselines, units, provenance, and forecast timestamps.
3. Define the boundary between `microgrid_model` and `energy_system`; use shared invariant tests for energy balance, SOC, reserves, and unmet critical service.
4. Decide whether root flexible-load modules are retained as a legacy plug-in API or wrapped around the core device-task contract.
5. Extract the main app's orchestration into testable application services, leaving Streamlit pages thin.
6. Only then deprecate or delete modules, one at a time, with import checks, test coverage, and a rollback commit.

## Changes made by this audit branch

- Updates the `app.py` module docstring to use the canonical five-step vocabulary and accurately state the current integration boundary.
- Adds this audit report. No optimizer, forecast model, simulation, telemetry, deployment, or test logic is changed.
- No branch is deleted and no draft PR is force-promoted or merged.

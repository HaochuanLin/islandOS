# islandOS Maturity Assessment and Improvement Plan

Assessment date: 2026-10-24  
Repository: https://github.com/HaochuanLin/islandOS  
Scope: repository-visible evidence only. Scores are engineering estimates, not a certification or proof of field readiness.

## Scoring rules

Each category is scored from 0 to 10. A score above 7 requires repeatable automated evidence; a score above 8 requires documented validation against representative data or environments. No source-code-only review can establish safe field operation. Targets are release gates, not claims about current capability.

## Baseline scores and current estimates (evidence-based)

Current estimates are provisional engineering judgments, not independent certification. They are raised only when the cited automated or external-data evidence exists.

## Baseline scores and targets

| Category | Baseline | Current estimate after phase 6 | Target | Evidence needed to raise score |
|---|---:|---:|---:|---|
| Core simulation and dispatch | 5.5 | 5.5 | 8.5 | Explicit physical/unit invariants, edge-case tests, conservation checks, benchmarked scenarios and documented model limits |
| Automated testing and reproducibility | 6.0 | 7.6 | 9.0 | Required CI checks, pinned/reproducible environment, deterministic seeds, archived run metadata, coverage of critical paths |
| Documentation and evidence audit | 6.5 | 7.8 | 9.0 | Claim-to-evidence register, data provenance, assumptions, known limitations and machine-readable experiment manifests |
| Interactive demo and usability | 6.0 | 6.0 | 8.5 | Reproducible local setup, smoke tests, accessible errors, clear synthetic-vs-measured labeling and verified public access |
| Branch and release management | 5.5 | 5.5 | 8.5 | Protected release path, tagged versioning, changelog, CI-gated releases, rollback and artifact provenance |
| Public data / site data validation | 5.5 | 7.8 | 8.5 | Source licences, immutable source snapshots, schema/unit/timezone checks, missing/stale-data handling and reproducible backtests |
| Commercialization and deployment readiness | 3.5 | 4.0 | 7.5 | Deployment guide, secret handling, monitoring, backups, threat model, support boundaries and pilot acceptance criteria |
| Overall software engineering maturity | 5.5 | 6.5 | 8.5 | Consistent interfaces, lint/type checks, dependency/security policy, architecture documentation and maintained CI |
| Real-environment operation validation | 2.0 | 2.0 | 7.0 | Independent site data, hardware-in-the-loop or shadow-mode trials, operational logs, signed engineering review and documented rollback; never infer this from simulation alone |

The baseline values are provisional judgments based on visible repository structure and README statements. The current estimates reflect only documented changes and inspected source evidence, not a completed runtime test campaign. The README explicitly describes the system as a research prototype, notes that synthetic inputs are used, and states that it is not a deployed island control system. It also notes that hosted public access has not been verified and that forecasting is not yet an integrated validated forecast-and-control pipeline.

## Improvement sequence

The number of phases is a planning estimate; later phases depend on findings from earlier tests.

1. **Evidence and safety boundary (phase 1 complete):** establish honest scores, targets, non-claims, and a reviewable evidence register.
2. **CI and deterministic baseline:** inspect every workflow, make critical tests required where repository settings permit, test deterministic seeds and record environment/version metadata.
3. **Simulation correctness:** add or strengthen tests for energy/water balance, bounds, missing data, invalid units, time ordering and failure modes; do not change scientific equations without evidence.
4. **Forecast and public-data validation:** validate time splits, baselines, leakage prevention, source provenance, freshness and site-specific schema assumptions.
5. **Demo and usability:** test clean installation and app startup; label synthetic data clearly; report hosted reachability separately from account-level visibility settings.
6. **Release and deployment controls:** versioned releases, dependency/security checks, reproducible artifacts, backup/restore and rollback procedures.
7. **Real-site pilot evidence:** only after qualified site review; run read-only/shadow mode first, compare predictions with measurements, and require human approval for any control integration.

## Progress log

### Phase 1 — evidence baseline (2026-10-23)

- Added this assessment plan and score rubric to docs/MATURITY_ASSESSMENT.md.
- Inspected the repository README, main dispatch implementation, its regression tests, the site-readiness gate and the primary RO test workflow.
- Confirmed the dispatch code contains checks for demand balance, inventory conservation, load-name uniqueness, time-step validity and shared renewable-power budget conservation. Existing tests cover several of these contracts. This supports the existence of meaningful correctness checks, but does not prove the suite passes in the current environment.
- Documentation/evidence score moves from 6.5 to 6.8 because scores, proof requirements, scope limits and a progress ledger are now explicit and reviewable. No other score increases because no test run, deployed environment, external dataset validation or field trial has been executed in this phase.
- Commit introducing the plan: 064420c6dd05d93a6ae0a21f14758f37aaf861d7.
- Commit recording the rescore: see this file's latest commit history on GitHub.

### Phase 2 — CI evidence and guardrails (2026-10-23)

- The RO simulation test workflow passed on commit `533fa76083b7aae53954465b191405391ac73b82`: [workflow run](https://github.com/HaochuanLin/islandOS/actions/runs/39983177469).
- The passing run archived the machine-readable reproducibility environment manifest and experiment artifacts, including water-demand rolling backtest, forecast-to-dispatch, and Pareto benchmark outputs. This is reproducible evidence for the synthetic workflow, not proof of site validity.
- Added CI gates in `.github/workflows/ro-tests.yml` to run `python -m pip check` and `python -m compileall -q .` before generating the environment manifest. Commit: `ea0b52a54f57eb961ab642efb5385a43a5641331`. The full workflow passed on commit `cee91f450dd4ea6e0f9e1642dbd5ab3d4303d616`: [workflow run](https://github.com/HaochuanLin/islandOS/actions/runs/39984162136). This run validates the dependency and syntax gates in that commit; later changes still require their own completed run.
- Rescore: automated testing/reproducibility 6.0 → 6.4 and documentation/evidence audit 6.8 → 7.0, justified by a completed passing CI run and archived run manifest/artifacts. Scores remain below target because dependencies are not fully locked, branch protection is not verified, and external/site validation is absent.
- Reviewed existing tests: shared energy budget and inventory conservation, invalid input rejection, chronological holdout, rolling-origin leakage guard, and demand-distribution diagnostics already have tests. Avoided duplicating these; next work should focus on dependency reproducibility, forecast integration edge cases, and site-data validation.



### Phase 4 — measured-data ML comparison and reproduction guide (2026-10-24)

- Extended `experiments/compare_water_demand_models.py` to record the exact input CSV SHA-256 and scikit-learn version; added regression assertions for both fields. Commits: [model provenance](https://github.com/HaochuanLin/islandOS/commit/47b9c397b9a07bb68589e04a80b1e2c6186a8610), [regression test](https://github.com/HaochuanLin/islandOS/commit/fa3b19b652c86c36d8663053dcebf7591b1ea262).
- Added the ML comparison to the public-data workflow. It compares previous-hour, previous-day, previous-week, and HistGradientBoosting forecasts on the same chronological holdout, validates finite metrics and input-hash alignment, and archives the ML report with raw and prepared data: [workflow implementation](https://github.com/HaochuanLin/islandOS/commit/9ee52389177716771bf1d8d7dc0a48ffb73100b8).
- The public measured-data workflow passed with the ML comparison: [successful run](https://github.com/HaochuanLin/islandOS/actions/runs/39985631870). On SOWEKI series 1, the selected continuous segment contains 5,533 hourly rows (2025-02-05 through 2025-09-23). The chronological split used 3,705 ML training samples and 1,660 test samples. HistGradientBoosting MAE was 0.663 m³/hour versus 0.973 for the previous-week seasonal baseline (about 31.9% lower); RMSE was 0.905 versus 1.351 (about 33.0% lower). The model's reported library version was scikit-learn 1.9.1.
- This is one dataset and one holdout. It does not establish generalization to other seasons/sites, a deep-learning or online-learning capability, or improved dispatch economics. The model must remain a candidate, not an automatic controller.
- Added [the reproducibility guide](REPRODUCIBILITY.md) and linked it from the README. It documents local commands, data lineage, hash checks, artifact contents, and interpretation limits.
- Rescore from completed evidence: automated testing/reproducibility 6.8 → 7.1; documentation/evidence audit 7.4 → 7.8; public-data validation 6.4 → 7.1; commercialization/deployment readiness 3.5 → 4.0 due to repeatable container and Windows build checks; overall software engineering maturity 5.5 → 6.0. Core simulation, interactive demo, branch/release management, and real-environment operation remain unchanged because these changes do not close their specific gaps.
- The full RO regression workflow passed on the preceding source/doc revision [70b71751 run](https://github.com/HaochuanLin/islandOS/actions/runs/39984921956). The latest model-provenance and measured-ML workflow changes are separately covered by the passing public-data run above; the newest full CI run is tracked independently and must pass before claiming that exact HEAD is fully green.


### Phase 5 — all-series validation and aggregate evidence (2026-10-24)

- Expanded the public-data workflow from one default series to an 11-series matrix on relevant pushes, pull requests, and a weekly schedule; manual dispatch can still select one series. Short series explicitly skip only the ML comparison when there is insufficient training history, while retaining the baseline data audit.
- Added an aggregation job that downloads each series artifact, checks coverage of series IDs 1–11, and writes a machine-readable summary with per-series MAE/RMSE, mean/median MAE reduction, missing IDs, and interpretation limits.
- The full matrix and aggregation succeeded: [workflow run](https://github.com/HaochuanLin/islandOS/actions/runs/39986497014). The archived summary reports 11/11 series compared, 11/11 gradient-boosting results beating the previous-week seasonal baseline, mean MAE reduction 37.49%, and median reduction 35.24%.
- These 11 time series come from one SOWEKI collection, not 11 independent locations. This is stronger evidence than one synthetic example, but it is not island-specific data and does not prove transfer to desalination demand or improved dispatch.
- Reproducibility instructions now describe the matrix and aggregate artifact: [guide update](https://github.com/HaochuanLin/islandOS/commit/b1f23387c67d4f1810b36b474cdb691719373bac).
- Rescore: automated testing/reproducibility 7.1 → 7.4; public-data validation 7.1 → 7.5; overall software engineering maturity 6.0 → 6.2. Other scores remain unchanged because this phase did not add protected releases, site commissioning evidence, or a publicly accessible hosted demo.


### Phase 6 — expanding-window validation and final regression pass (2026-10-24)

- Added up to three expanding-window folds to `experiments/compare_water_demand_models.py`. Each fold retrains only on targets before that fold's test window and compares the gradient-boosting candidate against the same three naive baselines. Added regression checks for fold boundaries, coverage, and non-negative finite metrics.
- The public-data workflow validates the walk-forward report, aggregates per-series fold metrics, and reports both main-holdout and expanding-window reductions. The 11-series workflow passed: [run and aggregate artifact](https://github.com/HaochuanLin/islandOS/actions/runs/39987177812). All 11 series were compared; the model beat the previous-week baseline on all 11 in the main holdout and in expanding-window evaluation. Mean/median MAE reduction was 37.49%/35.24% on the main holdout and 38.59%/36.92% across the expanding-window evaluation.
- The full RO regression workflow passed on the exact code/workflow revision: [successful run](https://github.com/HaochuanLin/islandOS/actions/runs/39987177934). Dependency audit, Nan'ao scenario validation, container smoke test, and Windows gateway build also passed on that revision.
- The result remains one public source collection of reservoir-outflow series, not independent island sites. The model is gradient boosting, not deep learning or online learning; one-step forecasts assume the previous hour's observation is available. No score is awarded for field operation or transfer to desalination demand.
- Rescore: automated testing/reproducibility 7.4 → 7.6; public-data validation 7.5 → 7.8; overall software engineering maturity 6.2 → 6.5. The remaining gap to 8+ is now primarily dependency locking, broader independent datasets/seasons, release controls, and site-specific validation.

## Evidence ledger

For every future score change, record: category and old/new score; exact commit SHA and changed paths; command or workflow used; pass/fail result and link to the run or artifact; remaining limitations and why the score is justified.

A code change alone does not prove a score increase. A workflow definition alone does not prove that the workflow passed. A synthetic simulation does not count as field validation.

## Non-negotiable operational boundary

islandOS must remain advisory/research software unless and until a site-specific safety case, qualified engineering review, instrument validation, failure handling, and authorized commissioning process exist. Never use this repository as the sole basis for operating desalination equipment, power systems, or other physical infrastructure.

### Phase 2 — CI feedback policy (updated 2026-10-23)

- During rapid pushes, multiple obsolete runs were cancelled. The current policy uses `cancel-in-progress: true` for the main RO workflow so the newest commit receives feedback instead of spending runner time finishing superseded commits.
- This is a throughput choice, not a claim that every historical commit was tested. Only completed runs with explicit success conclusions count as evidence.
- The main RO suite passed on commit `cee91f450dd4ea6e0f9e1642dbd5ab3d4303d616`: [successful run](https://github.com/HaochuanLin/islandOS/actions/runs/39984162136).

### Phase 3 — measured-data provenance and automatic backtest (2026-10-24)

- Added SHA-256 fingerprints for the downloaded source CSV and the prepared hourly series to `experiments/prepare_soweki_water_demand.py`. The fingerprints travel with the preparation report.
- Added regression assertions that recompute both fingerprints from actual file bytes: [test change](https://github.com/HaochuanLin/islandOS/commit/8bb3da497830df83ac5ce485bf50ec85dd96c3d0).
- The public-data workflow independently recomputes both hashes and fails on mismatch; it also validates hash format. Workflow change: [hash validation](https://github.com/HaochuanLin/islandOS/commit/d2add31d71fd00192b8493b46bb5907e5214ff9c).
- The measured SOWEKI backtest completed successfully with the fingerprint checks: [successful public-data run](https://github.com/HaochuanLin/islandOS/actions/runs/39984584825). Its artifact is available for 90 days. This establishes one repeatable public-data study, not transfer to island or Nan'ao conditions.
- Enabled automatic execution on relevant pushes to `main`: [workflow trigger change](https://github.com/HaochuanLin/islandOS/commit/a8a9dba987ad015864b45be813df9663e7de6fc6).
- The workflow revision also archives the raw source CSV and prepared hourly CSV alongside reports. The exact revision passed: [successful public-data run](https://github.com/HaochuanLin/islandOS/actions/runs/39984656770); the artifact was verified to contain both CSVs and all reports.
- Rescore based on the completed public-data run: automated testing/reproducibility 6.4 → 6.8; documentation/evidence audit 7.0 → 7.4; public-data validation 5.5 → 6.4. Remaining gaps include fully pinned dependencies, multiple independent datasets/seasons, protected release settings, and site-specific validation.

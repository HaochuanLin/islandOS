# islandOS Maturity Assessment and Improvement Plan

Assessment date: 2026-10-23  
Repository: https://github.com/HaochuanLin/islandOS  
Scope: repository-visible evidence only. Scores are engineering estimates, not a certification or proof of field readiness.

## Scoring rules

Each category is scored from 0 to 10. A score above 7 requires repeatable automated evidence; a score above 8 requires documented validation against representative data or environments. No source-code-only review can establish safe field operation. Targets are release gates, not claims about current capability.

## Baseline scores and current estimates (evidence-based)

Current estimates are provisional engineering judgments, not independent certification. They are raised only when the cited automated or external-data evidence exists.

## Baseline scores and targets

| Category | Baseline | Current estimate after phase 3 | Target | Evidence needed to raise score |
|---|---:|---:|---:|---|
| Core simulation and dispatch | 5.5 | 5.5 | 8.5 | Explicit physical/unit invariants, edge-case tests, conservation checks, benchmarked scenarios and documented model limits |
| Automated testing and reproducibility | 6.0 | 6.8 | 9.0 | Required CI checks, pinned/reproducible environment, deterministic seeds, archived run metadata, coverage of critical paths |
| Documentation and evidence audit | 6.5 | 7.4 | 9.0 | Claim-to-evidence register, data provenance, assumptions, known limitations and machine-readable experiment manifests |
| Interactive demo and usability | 6.0 | 6.0 | 8.5 | Reproducible local setup, smoke tests, accessible errors, clear synthetic-vs-measured labeling and verified public access |
| Branch and release management | 5.5 | 5.5 | 8.5 | Protected release path, tagged versioning, changelog, CI-gated releases, rollback and artifact provenance |
| Public data / site data validation | 5.5 | 6.4 | 8.5 | Source licences, immutable source snapshots, schema/unit/timezone checks, missing/stale-data handling and reproducible backtests |
| Commercialization and deployment readiness | 3.5 | 3.5 | 7.5 | Deployment guide, secret handling, monitoring, backups, threat model, support boundaries and pilot acceptance criteria |
| Overall software engineering maturity | 5.5 | 5.5 | 8.5 | Consistent interfaces, lint/type checks, dependency/security policy, architecture documentation and maintained CI |
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
- The newest workflow revision additionally archives both raw source and prepared hourly CSV, not just reports: [artifact update](https://github.com/HaochuanLin/islandOS/commit/8b5cb230f83165cc3132e5e77999d5065a5b302e). That exact revision's run is still queued/in progress at this assessment and is not counted as passed yet.
- Rescore based on the completed public-data run: automated testing/reproducibility 6.4 → 6.8; documentation/evidence audit 7.0 → 7.4; public-data validation 5.5 → 6.4. Remaining gaps include fully pinned dependencies, multiple independent datasets/seasons, protected release settings, and site-specific validation.

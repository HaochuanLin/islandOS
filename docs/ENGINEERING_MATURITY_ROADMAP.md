# Engineering maturity roadmap

This roadmap turns the project's maturity scores into evidence-based release gates. Scores are engineering assessments, not measured scientific quantities. A score may rise only when the listed evidence exists in the repository or in a documented, reviewable test run.

## Baseline and target scorecard

Baseline scores are provisional engineering assessments, not measured scientific quantities. The initial 2026-10-23 audit found that CI's unittest discovery did not cover ordinary pytest-style test functions; the automated-testing baseline and overall score have therefore been revised downward pending a green run of the expanded suite. Target scores are goals, not claims that the targets have already been met.

| Area | Initial baseline | Current verified | Target | Evidence required for target |
|---|---:|---:|---:|---|
| Core simulation and dispatch | 87/100 | 92/100 | 93/100 | Explicit invariants for energy/water accounting; adversarial boundary tests; benchmark results that report raw service metrics and do not require the proposed strategy to win every fixture; documented model limits. |
| Automated tests and reproducibility | 76/100 | 96/100 | 97/100 | Required CI checks on main and pull requests; deterministic fixtures; integration tests for public commands and exported JSON/CSV schemas; useful failure artifacts; no silently skipped core checks. |
| Documentation and evidence audit | 85/100 | 90/100 | 95/100 | Every major feature links to runnable commands, input schema, provenance, assumptions, expected outputs, limitations, and CI evidence; product and pilot scopes remain distinct. |
| Interactive demo and usability | 80/100 | 85/100 | 92/100 | Hosted app health is checked separately from code CI; clean-environment startup is tested; upload validation and user-facing failures have regression tests; demo clearly labels synthetic data and export provenance. |
| Branch and release management | 55/100 | 74/100 | 90/100 | Reduce stale/diverged branches and PRs; each PR has a bounded scope, current base, passing required checks, and a reviewable diff; no mass merge of divergent product/pilot histories. |
| Public-data / site-data validation | 25/100 | 25/100 | 60/100 | A documented measured or reputable public dataset with license, provenance, units, missingness audit, chronological holdout, baseline comparison, and reproducible results. This target does not imply Nan'ao field validation. |
| Commercial / deployment readiness | 38/100 | 57/100 | 70/100 | Repeatable install/deploy, documented support/security boundaries, explicit cost model and sensitivity analysis, stakeholder-defined acceptance criteria, and a documented pilot plan. No safety-critical control claim. |
| Overall software-engineering maturity | 82/100 | 91/100 | 95/100 | The engineering targets above are met with CI evidence, a clean branch/release path, and no unresolved high-severity defects. |
| Real-world operational validation | 38/100 | 38/100 | 60/100 | Independently sourced site measurements and a reproducible retrospective study with documented limitations. Higher scores require an authorized, supervised pilot and site-specific safety review; they cannot be reached by code-only work. |

## Delivery order

### Gate 1 — Main-branch reliability

- Keep main as the generic IslandOS product; keep Nan'ao as a separate scenario.
- Run unit, regression, forecast-to-dispatch integration, optimizer feasibility, and output-schema checks on pull requests and pushes to main.
- Confirm every reported CI result belongs to the exact commit being assessed.
- Preserve deterministic seeds and committed synthetic fixtures unless a change is intentional and reviewed.

**Exit condition:** the current main commit has green required checks and a documented command to reproduce the core test suite locally.

### Gate 2 — End-to-end evidence

- Exercise the app upload → validation → strategy comparison → export path with valid and invalid CSVs.
- Verify generated JSON and CSV outputs are parseable and include provenance / assumptions.
- Keep forecast quality metrics separate from dispatch outcomes and distinguish forecasts from realized values.
- Test infeasible cases and ensure the UI reports no feasible candidate rather than presenting one as safe.

**Exit condition:** CI reproduces an end-to-end report and verifies schema, row alignment, constraints, and deterministic behavior where expected.

### Gate 3 — Branch and PR hygiene

- Audit every open PR against its actual base and head SHAs.
- Do not merge a branch with substantial unrelated history merely to collect useful files.
- Port changes as small, reviewed commits or use a new branch based on current main.
- Close or label superseded work only after confirming its unique changes are either ported or intentionally discarded.

**Exit condition:** every active PR has a clear purpose, a current base, a manageable diff, and passing checks.

### Gate 4 — Data-backed evaluation

- Select a measured/public dataset before tuning models; record source, license, units, temporal coverage, missingness, and known biases.
- Establish persistence and seasonal-naive baselines before comparing machine-learning candidates.
- Use chronological holdouts and rolling evaluation; report MAE/RMSE/bias, interval coverage where applicable, and high-demand-period errors.
- Run sensitivity analysis for forecast error, demand uncertainty, RO specific energy, power limits, and storage capacity.

**Exit condition:** a reproducible study is published with limitations and results, whether positive, neutral, or negative. Do not tune the acceptance criteria after seeing results.

### Gate 5 — Supervised pilot readiness

- Define site-specific requirements with the operator and qualified engineers.
- Validate sensors, units, timestamps, data freshness, fallback behavior, and cybersecurity boundaries.
- Keep recommendations read-only until independent safety, controls, and operational reviews authorize any next step.
- Compare recommendations with actual operations in shadow mode before considering any control integration.

**Exit condition:** documented site authorization, safety review, operator sign-off, and measured shadow-mode evidence. This gate cannot be satisfied by code-only work.

## Scoring rules

1. A passing software test proves the tested software behavior, not physical fidelity or site benefit.
2. Synthetic data can prove repeatability and catch regressions, but cannot raise real-world validation above the data-backed evidence available.
3. A hosted demo being reachable is separate from CI passing and separate from field validation.
4. Do not change model parameters, seeds, or scoring weights merely to improve a score.
5. Every score change should name the commit, test/run evidence, and acceptance criterion that changed.
6. If a target depends on access to site measurements, operator decisions, credentials, or physical equipment, mark it blocked and document the dependency instead of fabricating evidence.

## Progress log

### 2026-10-23 — CI coverage audit

- Updated `.github/workflows/ro-tests.yml` to install the dependencies declared in `requirements.txt` alongside the additional test dependencies, reducing drift between the documented project environment and CI.
- Changed the main regression step from `python -m unittest discover -s tests -v` to `python -m pytest -q`. Pytest discovers both pytest-style test functions and unittest-compatible tests; the previous command did not by itself discover ordinary pytest-style test functions. The workflow retains the targeted NSGA-II pytest invocation as a separate focused check.
- Added explicit schema/numeric-invariant checks for the fixed 168-hour forecast-to-dispatch benchmark report, including aligned persistence-baseline metrics and all four policy result groups.
- Added focused input-validation regression tests for missing columns, timezone-aware hourly ordering, duplicate/gapped timestamps, invalid/non-finite numeric values, and optional water-demand forecasts in [`tests/test_forecast_dispatch_input_validation.py`](../tests/test_forecast_dispatch_input_validation.py) ([commit](https://github.com/HaochuanLin/islandOS/commit/621e633a5cde41cbe3ea17ded0a3af3d96405081)).
- During test review, corrected the CSV fixture helper to allow deliberately malformed column sets to be written, so the missing-column test reaches the production parser instead of failing in test setup ([follow-up commit](https://github.com/HaochuanLin/islandOS/commit/a838e45e530cff6fc13dd0a88d6eff013c380be0)).
- Relevant commits: [dependency alignment](https://github.com/HaochuanLin/islandOS/commit/c2ed08688458e40c6690f1af66606cba20d897d7), [benchmark report assertions](https://github.com/HaochuanLin/islandOS/commit/6e1a2bcc7f8b19ce0af37a98e60cbbbbaa03f76f), [complete pytest suite](https://github.com/HaochuanLin/islandOS/commit/d084395a982265015f0d29d8c3a863b7fe36c8b9).

**Verification status:** these changes have been committed to `main`, but a green CI result for the resulting head commit has not yet been confirmed in this log. Do not increase the automated-testing score until the run completes successfully. If CI exposes failures, fix the causes and rerun rather than reverting to narrower test discovery merely to get a green result.

### 2026-10-23 — Full-suite validation and clean scenario port

- The complete `pytest` suite passed on the clean Nan'ao port's PR head, including the new forecast-dispatch input-validation tests. The previously separate NSGA-II optimizer check and the full synthetic forecast-to-dispatch integration workflow also passed.
- The dedicated Nan'ao scenario workflow passed: the script compiled, its unittest regression suite passed, the fixed-seed 1,000-run output generation completed, JSON/CSV invariants passed, and the artifact uploaded successfully.
- Evidence: [RO simulation tests, run 39946761604](https://github.com/HaochuanLin/islandOS/actions/runs/39946761604) and [Nan'ao scenario validation, run 39946761587](https://github.com/HaochuanLin/islandOS/actions/runs/39946761587). Both ran on PR head `b97bff87ec47430584f5b68eb968ec224e84abae`.
- Merged [PR #44](https://github.com/HaochuanLin/islandOS/pull/44) as [commit `a2cb50d`](https://github.com/HaochuanLin/islandOS/commit/a2cb50dbcb60bf8abf332785de617a7be1bbf778). The port is based on current `main` and avoids merging the entire divergent Nan'ao branch.
- Adjusted the **current verified** testing score from 76 to 90 and overall software-engineering score from 82 to 85. These are interim scores, not target completion. Branch management moves only from 55 to 62 because the old PR #2 still contains additional unreviewed changes and PR #43 remains divergent.
- The post-merge `main` push run is not confirmed by the currently available workflow-run view; the verified runs above are on the exact code tree tested before merge. Keep that distinction explicit until the post-merge checks are confirmed.

### 2026-10-23 — Read-only telemetry and deployment validation merged

- Merged [PR #45](https://github.com/HaochuanLin/islandOS/pull/45) as [commit `b4e6c57`](https://github.com/HaochuanLin/islandOS/commit/b4e6c5762ea5b85a16c99d9ee634e0b34525ce10). The clean port adds vendor-neutral telemetry validation/mapping, file replay, a recommendation-only advisor, loopback-only HTTP ingest/review, security-boundary docs, Windows launchers, and container/Windows packaging checks.
- All four workflows passed on the exact PR head `125352a63e7f6dc794df01b5e4057dfec37840bf`: [RO simulation tests](https://github.com/HaochuanLin/islandOS/actions/runs/39947930884), [Nan'ao scenario validation](https://github.com/HaochuanLin/islandOS/actions/runs/39947930850), [container web smoke test](https://github.com/HaochuanLin/islandOS/actions/runs/39947930888), and [Windows gateway build](https://github.com/HaochuanLin/islandOS/actions/runs/39947930925).
- The full pytest suite, telemetry integration tests, generated scenario output checks, Docker build/health check, Windows executable smoke tests, and packaged advisor report validation all completed successfully.
- Updated current verified scores to reflect these results: testing 94, documentation 89, demo/deployment usability 84, branch/release management 72, deployment readiness 55, core simulation 89, and overall software-engineering maturity 89. These are still below the respective targets.
- PR #43 remains open but is explicitly annotated: its remaining divergent UI/workflow changes must be reviewed separately. PR #2 also remains open because its unported dispatch/model changes have not been audited. Neither old PR is safe to merge wholesale.
- These are software and packaging validations only. All included telemetry samples are synthetic, the gateway is loopback-only and recommendation-only, and real-site validation remains unchanged.

### 2026-10-23 — README command and formatting audit

- Fixed the Nan'ao script's inline-code delimiter in the main README and changed the documented full-suite command to `python -m pytest -q`, matching the primary CI workflow's test discovery.
- Commit: [`74870e3`](https://github.com/HaochuanLin/islandOS/commit/74870e3df16450b02c6cec52f2cfab996534d355).
- The GitHub connector's current combined-status query returned no status entries for the previously inspected head, and its workflow-run view exposes only pull-request-triggered runs. This is insufficient to assert that the latest main push passed; verify the exact current main SHA in GitHub Actions before changing the testing or overall score.
- No maturity score is increased by this documentation-only commit. The unresolved divergent PRs and the data/field evidence gates remain open.

### 2026-10-23 — Site-readiness port validated and merged

- Merged [PR #46](https://github.com/HaochuanLin/islandOS/pull/46) as [`a83928e`](https://github.com/HaochuanLin/islandOS/commit/a83928e01719ff8685d8af08cefb27085dbd29e7). The merge commit records the tested PR head as `c286ea0c5ddb8d03a2583e200d11c0e1678d3566`.
- All four required workflows completed successfully on that exact PR head: [RO simulation tests, run 39950537044](https://github.com/HaochuanLin/islandOS/actions/runs/39950537044), [Nan'ao scenario validation, run 39950537200](https://github.com/HaochuanLin/islandOS/actions/runs/39950537200), [container web smoke test, run 39950537054](https://github.com/HaochuanLin/islandOS/actions/runs/39950537054), and [Windows telemetry gateway build, run 39950536985](https://github.com/HaochuanLin/islandOS/actions/runs/39950536985).
- The verified changes add strict sensor message validation, fail-closed site-input readiness, staff data-entry forms, an offline scenario wrapper, and explicit water-balance/storage/dispatch invariant tests. The forms do not upload data or control equipment; readiness is not field safety approval.
- Updated current engineering assessments modestly: core simulation 89→91, testing 94→95, documentation 89→90, demo/usability 84→85, branch management 72→74, deployment readiness 55→57, and overall software engineering 89→90. These remain below targets and are tied to the cited tested PR head; the connector still does not expose a confirmed post-merge push run for the exact main SHA.
- A separate follow-up, [PR #47](https://github.com/HaochuanLin/islandOS/pull/47), adds 100 deterministic randomized physical-invariant cases. Its CI status is not yet available through the current workflow view, so those cases are not included in the score update.
- The open legacy PRs #2 and #43 remain unaudited in their residual diffs; do not merge them wholesale. Public-data/site-data validation and real-world operational validation remain unchanged because no island-specific measured data or supervised pilot evidence was added.

### 2026-10-23 — Randomized physical-invariant stress tests merged

- Merged [PR #47](https://github.com/HaochuanLin/islandOS/pull/47) as [`92e4cd7`](https://github.com/HaochuanLin/islandOS/commit/92e4cd7ed5eec42d0442c8eb7b11ad2b3fb839af).
- Added 100 fixed-seed randomized scenarios covering water-volume conservation, reservoir lower/upper bounds, non-negative spill/deficit, renewable draw limits, and RO rated-power accounting with backup enabled and disabled.
- All four validation workflows passed on the exact PR head `f76b3f3c8a5f29b7ca6dbe00cb52f70d9712ad64`: [RO regression, run 39951249477](https://github.com/HaochuanLin/islandOS/actions/runs/39951249477), [Nan'ao scenario, run 39951249457](https://github.com/HaochuanLin/islandOS/actions/runs/39951249457), [container smoke test, run 39951249475](https://github.com/HaochuanLin/islandOS/actions/runs/39951249475), and [Windows packaging, run 39951249563](https://github.com/HaochuanLin/islandOS/actions/runs/39951249563).
- Updated current verified scores: core simulation 91→92, automated tests 95→96, overall software-engineering maturity 90→91. The randomized test increases software invariant coverage only; it does not establish model fidelity or site performance.
- The measured SOWEKI workflow in [PR #49](https://github.com/HaochuanLin/islandOS/pull/49) has produced a successful public-data run, but its changes remain unmerged and require final review of all required checks before the public-data score changes.


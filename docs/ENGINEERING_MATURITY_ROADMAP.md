# Engineering maturity roadmap

This roadmap turns the project's maturity scores into evidence-based release gates. Scores are engineering assessments, not measured scientific quantities. A score may rise only when the listed evidence exists in the repository or in a documented, reviewable test run.

## Baseline and target scorecard

Baseline scores are provisional engineering assessments, not measured scientific quantities. The initial 2026-10-23 audit found that CI's unittest discovery did not cover ordinary pytest-style test functions; the automated-testing baseline and overall score have therefore been revised downward pending a green run of the expanded suite. Target scores are goals, not claims that the targets have already been met.

| Area | Initial baseline | Current verified | Target | Evidence required for target |
|---|---:|---:|---:|---|
| Core simulation and dispatch | 87/100 | 93/100 | 93/100 | Explicit invariants for energy/water accounting; adversarial boundary tests; benchmark results that report raw service metrics and do not require the proposed strategy to win every fixture; documented model limits. |
| Automated tests and reproducibility | 76/100 | 97/100 | 97/100 | Required CI checks on main and pull requests; deterministic fixtures; integration tests for public commands and exported JSON/CSV schemas; useful failure artifacts; no silently skipped core checks. |
| Documentation and evidence audit | 85/100 | 95/100 | 95/100 | Every major feature links to runnable commands, input schema, provenance, assumptions, expected outputs, limitations, and CI evidence; product and pilot scopes remain distinct. |
| Interactive demo and usability | 80/100 | 91/100 | 92/100 | Hosted app health is checked separately from code CI; clean-environment startup is tested; upload validation and user-facing failures have regression tests; demo clearly labels synthetic data, input provenance, run signatures, and exported model/optimizer configuration. |
| Branch and release management | 55/100 | 89/100 | 90/100 | Reduce stale/diverged branches and PRs; each PR has a bounded scope, current base, passing required checks, and a reviewable diff; no mass merge of divergent product/pilot histories. |
| Public-data / site-data validation | 25/100 | 60/100 | 60/100 | A documented measured or reputable public dataset with license, provenance, units, missingness audit, chronological holdout, baseline comparison, and reproducible results. This target does not imply Nan'ao field validation. |
| Commercial / deployment readiness | 38/100 | 60/100 | 70/100 | Repeatable install/deploy, documented support/security boundaries, explicit cost model and sensitivity analysis, stakeholder-defined acceptance criteria, and a documented pilot plan. No safety-critical control claim. |
| Overall software-engineering maturity | 82/100 | 94/100 | 95/100 | The engineering targets above are met with CI evidence, a clean branch/release path, and no unresolved high-severity defects. |
| Real-world operational validation | 38/100 | 38/100 | 60/100 | Independently sourced site measurements and a reproducible retrospective study with documented limitations. Higher scores require an authorized, supervised pilot and site-specific safety review; they cannot be reached by code-only work. |

## Current work-in-progress evidence (2026-10-24)

The forecast-to-dispatch CLI, CSV artifact SHA-256 manifest, regression tests in `tests/test_forecast_dispatch_demo.py`, and a dedicated CI test step have been added. The test step covers synthetic end-to-end output, output-file hash integrity, non-destructive handling of existing output directories, user-supplied-data labeling, insufficient history, timezone assumptions, hourly alignment, and non-finite input rejection. Three additional regression cases now verify fail-closed handling of invalid dispatch parameters, a custom plug-in that returns a non-finite forecast, and a plug-in that raises an unexpected runtime exception.

**These additions are not yet counted as a passing gate:** the latest commit has no verified green CI status available to this audit. Keep Gate 1 open until the exact current main commit has green required checks and the test suite is reproducible from a clean checkout. The hosted Streamlit interface is considered accessible based on the owner's direct verification; an AI-facing redirect is not treated as evidence that users must log in.

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

### 2026-10-23 — Public measured-data study passed and merged

- Merged [PR #49](https://github.com/HaochuanLin/islandOS/pull/49) as [`498d1fc`](https://github.com/HaochuanLin/islandOS/commit/498d1fc232f2aa8793988a62b9e4be706b03f3fc).
- The public-data workflow passed on exact PR head `dfb5c630255541c71ea77cc340eebda78d85967c`: [workflow run 39952100393](https://github.com/HaochuanLin/islandOS/actions/runs/39952100393). The same head's full pytest suite passed in [run 39952100357](https://github.com/HaochuanLin/islandOS/actions/runs/39952100357); Nan'ao, container, and Windows checks also passed in runs 39952100336, 39952100431, and 39952100456.
- The run downloaded SOWEKI series 1 under CC BY 4.0, audited source quality, removed only exact duplicate timestamp/value rows, excluded invalid numeric rows and incomplete hours without interpolation, ran a chronological holdout, checked prediction-interval coverage, and uploaded a reproducible JSON artifact.
- Observed sample metrics: 5,533 hourly rows, 1,384 chronological test rows. Persistence MAE was 1.0513 m³/h; 24-hour seasonal-naive MAE was 0.9751 m³/h. On 103 high-demand test rows defined using the training-history 90th percentile (9.5195 m³/h), underforecast rate was about 83.5% for all three baseline variants; high-demand MAE was 1.5956 m³/h for persistence and about 2.01 m³/h for seasonal variants. This shows better overall MAE does **not** imply better peak-risk behavior.
- Public-data/site-data validation rises 25→60 because the roadmap's documented public-data study gate is now satisfied. Documentation rises 90→91, branch management 74→76, and overall engineering maturity 91→92. These changes do not imply island/Nan'ao data validation or field readiness; real-world operational validation remains 38/100.

### 2026-10-23 — Closed the superseded telemetry UI PR

- Closed [PR #43](https://github.com/HaochuanLin/islandOS/pull/43) after documenting the residual-diff audit. The bounded read-only telemetry subsystem and packaging were already integrated via PR #45; the remaining `app.py` snapshot was older than current main and bundled several unrelated UI changes.
- The rolling-horizon upload/comparison experience is being ported as a separate, current-base page in [PR #52](https://github.com/HaochuanLin/islandOS/pull/52). Gateway review remains separate until its auth and network boundary can be reviewed independently.
- Branch/release management rises 76→78 for removing one stale, highly diverged open PR without mass-merging its history. PR #2 remains open intentionally as a separate Nan'ao scenario review/evaluation record; it must not be merged wholesale.

### 2026-10-23 — Hosted app access restriction discovered

- The new hosted-health check on [PR #51](https://github.com/HaochuanLin/islandOS/pull/51) found that both the landing page and `/_stcore/health` return HTTP 303 to `share.streamlit.io/-/auth/app` for unauthenticated requests. Evidence: [health run 39953323636](https://github.com/HaochuanLin/islandOS/actions/runs/39953323636); the uploaded report labels the status `requires_authentication`.
- This means the README's advertised public demo is not currently verified as publicly accessible. The README now discloses the restriction. If public access is intended, the app visibility must be changed in Streamlit Cloud settings; GitHub code cannot change that account-level setting.
- Recalibrated the interactive-demo score 85→82 and deployment-readiness score 57→52; overall engineering maturity 92→91. This is a downward correction based on live evidence, not a code regression. Do not raise these scores until anonymous access and the landing page are verified.
- The health workflow is intentionally non-blocking on pull requests because hosting visibility is an external setting; scheduled/manual checks remain failing until the access restriction is fixed.

### 2026-10-23 — Interactive rolling-horizon lab merged

- Merged [PR #52](https://github.com/HaochuanLin/islandOS/pull/52) as [`0744396`](https://github.com/HaochuanLin/islandOS/commit/0744396401e8c994b56d1399340d9ecf83497976).
- Added `pages/2_Rolling_Horizon_Lab.py`, a separate Streamlit multipage UI using the existing rolling-horizon model. It accepts synthetic or validated paired hourly CSV input, compares four policies, separates chart units, shows constraint warnings, and exports policy/hourly audit CSVs.
- Added an AppTest that opens the page, runs the synthetic comparison, and verifies the four-policy summary. All four validation workflows passed on exact PR head `189de71593648b1462da1da64b66b069c5c1fcd6`: [RO suite run 39953128946](https://github.com/HaochuanLin/islandOS/actions/runs/39953128946), [Nan'ao run 39953128984](https://github.com/HaochuanLin/islandOS/actions/runs/39953128984), [container smoke run 39953128952](https://github.com/HaochuanLin/islandOS/actions/runs/39953128952), and [Windows packaging run 39953129169](https://github.com/HaochuanLin/islandOS/actions/runs/39953129169).
- Interactive demo/usability rises 82→84, branch/release management 78→80, and overall software-engineering maturity 91→92. The page is an offline research UI; the public hosted app remains access-restricted until Streamlit Cloud visibility is changed.

### 2026-10-23 — Hosted health monitoring merged, access remains blocked

- Merged [PR #51](https://github.com/HaochuanLin/islandOS/pull/51) as [`6a9541d`](https://github.com/HaochuanLin/islandOS/commit/6a9541d133e4e19bdbbb81854daa5324bbbd8051). The workflow independently checks the hosted landing page and Streamlit health endpoint and uploads a JSON report; it is scheduled/manual and non-blocking on pull requests when the external host is restricted.
- All four software workflows passed on PR head `37d4ee9445f227a292357b26fd9d3b64333fb909`: [RO suite run 39953323618](https://github.com/HaochuanLin/islandOS/actions/runs/39953323618), [Nan'ao run 39953323462](https://github.com/HaochuanLin/islandOS/actions/runs/39953323462), [container smoke run 39953323458](https://github.com/HaochuanLin/islandOS/actions/runs/39953323458), and [Windows packaging run 39953323559](https://github.com/HaochuanLin/islandOS/actions/runs/39953323559).
- The health report itself remains `requires_authentication`, not healthy: anonymous requests receive HTTP 303 to Streamlit Cloud sign-in. This merge adds monitoring; it does not fix visibility. Do not increase demo or deployment scores until the external app is publicly reachable.
- Branch/release management rises 80→82 for consolidating stale PRs, adding a focused health monitor, and documenting the remaining external deployment gate.

### 2026-10-23 — Minimum-run property added to randomized stress test

- Merged [PR #53](https://github.com/HaochuanLin/islandOS/pull/53) as [`57e4ee8`](https://github.com/HaochuanLin/islandOS/commit/57e4ee88c1c2f5e8bfc4d76e8acc4fb4199d4492).
- The seeded 100-scenario invariant test now also checks every RO run segment meets `min_run_hours`, and that the no-backup perfect-foresight path does not trigger its emergency-stop fallback on consistent input traces.
- All four workflows passed on exact PR head `dae5789e4474b87c2af055868909b81d422a46b6`: [RO suite run 39953581944](https://github.com/HaochuanLin/islandOS/actions/runs/39953581944), [Nan'ao run 39953581929](https://github.com/HaochuanLin/islandOS/actions/runs/39953581929), [container smoke run 39953581951](https://github.com/HaochuanLin/islandOS/actions/runs/39953581951), and [Windows packaging run 39953581995](https://github.com/HaochuanLin/islandOS/actions/runs/39953581995).
- Core simulation rises 92→93, meeting its current target under the documented software-invariant rubric. Overall software-engineering maturity rises 92→93. Testing remains 96 rather than 97 until the required checks on the exact post-merge main head can be verified; PR-head success alone does not satisfy that final evidence gate.

### 2026-10-23 — Economic sensitivity tool merged; pilot plan re-based cleanly

- Merged [PR #54](https://github.com/HaochuanLin/islandOS/pull/54) as [`6e37f5c`](https://github.com/HaochuanLin/islandOS/commit/6e37f5cd2694ad8964ac92d04d02b90972db0279). The new fixed-candidate sensitivity report validates the full-year input summary and lifecycle-cost objective, recomputes each baseline candidate's stored cost, retains source/optimizer provenance, and reports low/high economic perturbations with explicit interpretation limits.
- All four software workflows and the hosted-health workflow completed successfully on exact PR head `70c5a225e8ff20d3faef9bf8223f3bf0a1711bfd`: [RO tests, run 39954391687](https://github.com/HaochuanLin/islandOS/actions/runs/39954391687), [Nan'ao, run 39954391715](https://github.com/HaochuanLin/islandOS/actions/runs/39954391715), [container smoke, run 39954391639](https://github.com/HaochuanLin/islandOS/actions/runs/39954391639), [Windows packaging, run 39954391669](https://github.com/HaochuanLin/islandOS/actions/runs/39954391669), and [hosted-health monitor, run 39954391731](https://github.com/HaochuanLin/islandOS/actions/runs/39954391731). Hosted-health workflow success means the diagnostic ran; it does not mean the public app is anonymously accessible.
- Documentation/evidence rises 91→92, commercial/deployment readiness 52→54, and branch/release management 82→84. These are bounded improvements: the cost study re-prices only the existing Pareto set and does not rerun NSGA-II; required cost assumptions still need documented site-specific sources; no bankable financial assessment is claimed.
- Closed superseded [PR #55](https://github.com/HaochuanLin/islandOS/pull/55) after creating [PR #56](https://github.com/HaochuanLin/islandOS/pull/56) from the exact current main base `6e37f5cd2694ad8964ac92d04d02b90972db0279`. PR #56 contains only the supervised pilot acceptance plan and README link. Its CI is pending; do not count it as merged or raise field-validation scores.
- Main-head CI after the squash merge is not exposed by the connector's PR-only workflow-run query. The exact PR-head validation is green, but the post-merge main check must remain a separate evidence gate.

### 2026-10-23 — Supervised pilot plan merged; legacy Nan'ao PR closed after audit

- Merged [PR #56](https://github.com/HaochuanLin/islandOS/pull/56) as [`fe6d72e`](https://github.com/HaochuanLin/islandOS/commit/fe6d72ebc5621ab4520eb18d0e42b0a7eda21cab). The plan defines a site-data manifest, chronological validation, read-only shadow mode, provisional acceptance metrics, stop/no-go conditions, evidence retention, and required sign-offs. It is a planning template only; it does not authorize actuation or prove that a pilot occurred.
- All four software workflows and the hosted-health diagnostic passed on exact PR head `3843f11b4702764419793e64cfeb5c22da22b533`: [RO tests, run 39954920323](https://github.com/HaochuanLin/islandOS/actions/runs/39954920323), [Nan'ao, run 39954920299](https://github.com/HaochuanLin/islandOS/actions/runs/39954920299), [container smoke, run 39954920304](https://github.com/HaochuanLin/islandOS/actions/runs/39954920304), [Windows packaging, run 39954920319](https://github.com/HaochuanLin/islandOS/actions/runs/39954920319), and [hosted-health diagnostic, run 39954920314](https://github.com/HaochuanLin/islandOS/actions/runs/39954920314). The hosted diagnostic passing does not mean anonymous public access is enabled.
- Closed legacy [PR #2](https://github.com/HaochuanLin/islandOS/pull/2) after a residual-diff audit confirmed the Nan'ao scenario itself is already identical to main and the remaining model, forecast/dispatch, tests, and UI changes are old, substantially divergent snapshots. The branch documented the older mean-based RO start rule with backup disabled, while main has the stricter look-ahead full-rated-power rule. No divergent history was merged.
- Closed the superseded duplicate pilot-plan PR #55 and merged its fresh-base replacement PR #56. Branch/release management rises 84→86; documentation rises 92→93; commercial/deployment readiness rises 54→55 because the pilot acceptance plan is now documented, while actual stakeholder approval and site deployment remain absent.
- The real-world operational-validation score remains 38/100. A written plan, public dataset, synthetic tests, and CI are not a site pilot. The hosted demo also remains access-restricted pending an external Streamlit Cloud visibility change.
- The connector does not provide a confirmed post-merge push-workflow record for the new main SHA; the cited green checks belong to the exact PR head, so that distinction remains open.

### 2026-10-23 — Economic sensitivity CLI integration test merged

- Merged [PR #57](https://github.com/HaochuanLin/islandOS/pull/57) as [`46760b7`](https://github.com/HaochuanLin/islandOS/commit/46760b7d79343b89940b083c57b5dad6e5b3553e).
- Added an end-to-end subprocess test for `experiments/economic_sensitivity.py` that validates the public CLI, JSON summary, exported report, candidate/scenario counts, optimizer provenance, interpretation limits, and synthetic data provenance.
- The first CI attempt caught an assertion that expected wording different from the actual report. Corrected the test assertion rather than weakening the report's limitation language. The corrected exact PR head `a256948048a279c5cecf4a7fea3fd6f32958cc4e` passed all four workflows: [RO suite run 39955663791](https://github.com/HaochuanLin/islandOS/actions/runs/39955663791), [Nan'ao run 39955663778](https://github.com/HaochuanLin/islandOS/actions/runs/39955663778), [container smoke run 39955663837](https://github.com/HaochuanLin/islandOS/actions/runs/39955663837), and [Windows packaging run 39955663931](https://github.com/HaochuanLin/islandOS/actions/runs/39955663931). The complete pytest step reported 346 passed, 6 warnings, and 392 subtests passed.
- Branch/release management rises 86→88: the legacy divergent PR #2 and duplicate PR #55 are closed after audits, and PR #57 was a bounded, current-base change. The connector still does not expose a confirmed post-merge main push run, so automated-testing remains 96 rather than 97 until that exact-head gate is satisfied.

### 2026-10-23 — Economic sensitivity validation hardened

- Merged [PR #58](https://github.com/HaochuanLin/islandOS/pull/58) as [`ef3d96e`](https://github.com/HaochuanLin/islandOS/commit/ef3d96e97eeeb1757695faf2bd57b3c9136dceb2).
- The cost sensitivity tool now validates each economic assumption separately, rejects negative/non-finite energy and water totals even when a unit price is zero, and requires the source report's quality status, supported source label, parseable timestamps, and 60-minute interval metadata before analysis.
- The end-to-end CLI test exposed a direct-script import-path issue; the repository root is now added to `sys.path` explicitly. This was fixed and revalidated rather than bypassing the CLI test.
- All four workflows passed on exact PR head `2312691d9c8e40732273258132c130ad5377e41b`: [RO tests, run 39956585085](https://github.com/HaochuanLin/islandOS/actions/runs/39956585085), [Nan'ao, run 39956585068](https://github.com/HaochuanLin/islandOS/actions/runs/39956585068), [container smoke, run 39956585067](https://github.com/HaochuanLin/islandOS/actions/runs/39956585067), and [Windows packaging, run 39956585162](https://github.com/HaochuanLin/islandOS/actions/runs/39956585162).
- Branch/release management rises 88→89: there are no open PRs after this merge, and the stale legacy PRs were audited and closed rather than merged wholesale. Old remote branch refs remain; the current GitHub integration exposes no branch-deletion action, so the branch-management target is not marked complete.
- Automated testing remains 96/100, not 97, until a green check on the exact post-merge `main` head can be independently confirmed. The verified runs above are on the exact PR head.

### 2026-10-23 — Cost-sensitivity report semantics documented and zero-baseline edge case fixed

- Merged [PR #59](https://github.com/HaochuanLin/islandOS/pull/59) as [`a22d65c`](https://github.com/HaochuanLin/islandOS/commit/a22d65cc3f82c0007ae74aeb6847848a4b0f034e).
- The sensitivity report no longer labels a mathematically undefined percentage delta as 0% when baseline cost is zero. It emits null min/median/max values where no relative deltas can be defined and records `undefined_baseline_count`.
- Expanded [the economic sensitivity guide](ECONOMIC_SENSITIVITY.md) with a field-by-field JSON report guide, null semantics, and a reproducibility/provenance checklist.
- All four workflows passed on exact PR head `30205329c8b9c1a14a075493758cd16ea1fcd794`: [RO tests, run 39957066275](https://github.com/HaochuanLin/islandOS/actions/runs/39957066275), [Nan'ao, run 39957066256](https://github.com/HaochuanLin/islandOS/actions/runs/39957066256), [Windows packaging, run 39957066396](https://github.com/HaochuanLin/islandOS/actions/runs/39957066396), and [container smoke, run 39957066337](https://github.com/HaochuanLin/islandOS/actions/runs/39957066337).
- Documentation/evidence rises 93→94 because the output schema, edge-case semantics, and reproducibility expectations are now explicit and test-backed. Automated testing remains 96 until a post-merge check on the exact `main` head is independently confirmed; no field-validation score changes.

### 2026-10-23 — Rolling dispatch exports retain provenance

- Merged [PR #60](https://github.com/HaochuanLin/islandOS/pull/60) as [`79f0634`](https://github.com/HaochuanLin/islandOS/commit/79f06345c28cf3ae36ea47f13d1c654813276b03).
- Both policy-comparison and hourly-audit CSV exports now include source type, source label, and SHA-256 of the exact input bytes. Built-in demo data are explicitly synthetic; uploaded files are labelled unverified.
- The Streamlit AppTest asserts that both download controls are provenance-labelled. All four workflows passed on the exact PR head `7ee92cbf592c8af42eb9bac159e181e7deb0b0f3`: RO suite [run 39958060630](https://github.com/HaochuanLin/islandOS/actions/runs/39958060630), Nan'ao scenario [run 39958060582](https://github.com/HaochuanLin/islandOS/actions/runs/39958060582), container smoke [run 39958060658](https://github.com/HaochuanLin/islandOS/actions/runs/39958060658), Windows packaging [run 39958060592](https://github.com/HaochuanLin/islandOS/actions/runs/39958060592).
- Interactive demo/usability rises 84→85 based on tested provenance-preserving downloads. This does not establish hosted-app availability or site-data validity.

### 2026-10-23 — Visible input provenance and local deployment runbook

- Merged [PR #61](https://github.com/HaochuanLin/islandOS/pull/61) as [`37fa452`](https://github.com/HaochuanLin/islandOS/commit/37fa4527227c29dcafe36044826f5f352992f089). The rolling-horizon lab now displays the validated source type, exact UTC coverage, and SHA-256 of the input bytes. The UI explicitly says a hash establishes content identity, not data trust or measurement quality. AppTest covers the source label, coverage, and hash. All four workflows passed on exact PR head `e9c48a4e2927fdcd7799395ca1378688892b0fc3`: RO suite [run 39958886633](https://github.com/HaochuanLin/islandOS/actions/runs/39958886633), Nan'ao [run 39958886609](https://github.com/HaochuanLin/islandOS/actions/runs/39958886609), container smoke [run 39958886850](https://github.com/HaochuanLin/islandOS/actions/runs/39958886850), Windows packaging [run 39958886636](https://github.com/HaochuanLin/islandOS/actions/runs/39958886636).
- Merged [PR #62](https://github.com/HaochuanLin/islandOS/pull/62) as [`6d33b33`](https://github.com/HaochuanLin/islandOS/commit/6d33b332afd0388481bc0dab25f245eb83703261). Added a README-linked local deployment runbook with Docker Compose/Python instructions, health checks, logs, shutdown/rebuild, loopback-only exposure guidance, and explicit production-readiness gaps. All five workflows passed on exact PR head `156575d761a1b5efd15ea5d200e7b3588ebb6b91`: RO suite [run 39958814226](https://github.com/HaochuanLin/islandOS/actions/runs/39958814226), Nan'ao [run 39958814259](https://github.com/HaochuanLin/islandOS/actions/runs/39958814259), container smoke [run 39958814183](https://github.com/HaochuanLin/islandOS/actions/runs/39958814183), Windows packaging [run 39958814216](https://github.com/HaochuanLin/islandOS/actions/runs/39958814216), hosted app health [run 39958814263](https://github.com/HaochuanLin/islandOS/actions/runs/39958814263).
- Interactive demo/usability rises 85→86 for visible provenance and UTC coverage backed by AppTest and full CI. Commercial/deployment readiness rises 55→56 for a repeatable local deployment procedure and explicit security/operations boundary. This does not imply production controls are implemented; authentication, authorization, TLS, security operations, backups, support ownership, and a supervised site pilot remain unresolved.

### 2026-10-23 — Current main branch CI verified

- The post-merge main code and evidence updates at `9ce1101e78a1eaade559f9fb9b3140e8d7ebb17e` passed all four push-triggered workflows: RO/full pytest suite [run 39959344907](https://github.com/HaochuanLin/islandOS/actions/runs/39959344907), Nan'ao scenario [run 39959344854](https://github.com/HaochuanLin/islandOS/actions/runs/39959344854), container web smoke [run 39959344879](https://github.com/HaochuanLin/islandOS/actions/runs/39959344879), and Windows portable package [run 39959344947](https://github.com/HaochuanLin/islandOS/actions/runs/39959344947). Each run is completed with conclusion `success` on that exact SHA.
- Automated tests/reproducibility rises 96→97 because the full pytest and integration/report-generation workflow is now verified on main as well as PR heads. This verifies software behavior and repeatable synthetic workflows, not physical fidelity or site performance.



### 2026-10-23 — Primary-app provenance, stale-result invalidation, and container hardening

- Merged [PR #63](https://github.com/HaochuanLin/islandOS/pull/63) as `4d49d12`. Strategy-summary and timestep-audit CSVs now carry source type, source label, and the SHA-256 of the exact input bytes. The exact PR head `deb6ca7adec502776a8c03114819af36d3617e00` passed all five applicable workflows; the resulting main commit `4d49d12eefa718474787b9ed517e0fa9d293cddf` also passed all four push-triggered workflows (runs 39960737271, 39960737194, 39960737031, and 39960737020). Interactive demo/usability rises 86→87.
- Merged [PR #64](https://github.com/HaochuanLin/islandOS/pull/64) as `e96e974`. NSGA-II Pareto exports now retain the same provenance fields, and cached optimizer output is cleared if the current input hash changes. The exact PR head `383d20968c109f69c97e3dc1b87e148a6ed850b6` passed all five workflows (runs 39960980775, 39960980743, 39960980693, 39960980689, and 39960980687). Interactive demo/usability rises 87→88. A content hash identifies bytes; it does not establish source trust or measurement accuracy.
- Merged [PR #65](https://github.com/HaochuanLin/islandOS/pull/65) as `1505f81`. Added a README-linked primary app guide covering the app-specific CSV schema, output exports, provenance semantics, and the difference between the UI schema and the separate CLI experiment schema. All five workflows passed on exact PR head `306877792491550a49da3536010bd337c66855b4` (runs 39961467901, 39961467898, 39961467814, 39961467682, and 39961467645). Documentation/evidence rises 94→95.
- Merged [PR #66](https://github.com/HaochuanLin/islandOS/pull/66) as `68d749b`. The Docker web image now runs as UID 10001 rather than root, and the container smoke test asserts that the runtime UID is non-zero. The exact PR head `90738420046e5b0512c43fd7d5d231ca243c1c14` passed the four applicable workflows: RO tests (39961612562), Nan'ao scenario (39961612528), container smoke (39961612588), and Windows packaging (39961612522). The hosted-app health workflow was not triggered for this Docker-only change. Commercial/deployment readiness rises 56→57; authentication, authorization, TLS, security operations, and production certification remain absent.
- No increase is made to automated-testing, core-simulation, public-data, branch-management, or real-world-validation scores in this entry. After this score update was drafted, all four push-triggered workflows passed on the exact final merged main head `68d749bf306239cfda0ce766f60a7e428aa089c1`: RO/full pytest suite (run 39961969911), Nan'ao scenario (39961970416), container smoke (39961969810), and Windows package (39961970005). This closes the post-merge CI evidence gate for these changes; the PR-head checks remain separately recorded above.


### 2026-10-23 — Simulator outputs invalidate on configuration changes

- Merged [PR #68](https://github.com/HaochuanLin/islandOS/pull/68) as `eb5fdbe`. Strategy and optimizer results now carry a deterministic run signature that covers the exact input SHA-256, RO/tank assumptions, interval, backup-energy price, and optimizer budget/build/seed. If a user changes input bytes or settings, the app clears stale strategy outputs and cached NSGA-II schedules instead of leaving a plausible-looking report on screen.
- Added an AppTest that changes RO rated power after a successful strategy comparison and verifies the old results and download controls are removed. The optimizer stale-result regression remains in place.
- All five workflows passed on exact PR head `57e7f998a54677ba8f84d23a8efcab53a5182edb`: hosted-health diagnostic (39963144272), Windows package (39963144243), full RO/pytest suite (39963144172), Nan'ao scenario (39963143982), and container smoke (39963143773).
- Interactive demo/usability rises 88→89. This is a stale-result prevention improvement, not evidence of forecast accuracy, physical fidelity, or site readiness. Post-merge main-head CI for `eb5fdbece0a718c61927a2898d3bc92481534708` must be recorded separately when complete.


### 2026-10-23 — Reproducible primary-app exports

- Merged [PR #70](https://github.com/HaochuanLin/islandOS/pull/70) as `147cffc`. Strategy summary and timestep-audit CSVs now carry a deterministic run signature and explicit model settings (RO power, specific energy, tank capacity/inventory, minimum run time, interval, and optional backup-energy price). NSGA-II Pareto exports also carry optimizer population, generations, seed, and build identifier.
- The UI displays the strategy run signature, and [the primary app guide](PRIMARY_APP_GUIDE.md) documents the export schema and cautions that neither the input hash nor run signature proves data accuracy or trustworthiness.
- All five workflows passed on exact PR head `2f15d1056a01b6f637688fe06dd86431b3c38fb0`: full pytest suite (39964732123), Nan'ao scenario (39964732246), container smoke (39964732128), Windows package (39964732098), and hosted app health (39964732099).
- Interactive demo/usability rises 89→90. After the PR-head checks passed, all four push-triggered workflows also passed on exact post-merge main head `147cffc1af077d2cf146ec143c436d04106b5f4a`: full pytest (39965249365), Nan'ao scenario (39965249471), container smoke (39965249321), and Windows packaging (39965249326). This closes the post-merge CI evidence gate for this change; no real-world-validation score is changed.


### 2026-10-23 — Dataset provenance validation hardening

- Merged PR #89, adding a dependency-free provenance metadata contract and tests for source URL, timezone-aware timestamps, data-status labels, variable metadata, optional SHA-256 digests, and deterministic hashing ([merge commit](https://github.com/HaochuanLin/islandOS/commit/58756b1f0c8278bf98e816df9e949748b29754b4)).
- Hardened the validator to reject non-mapping top-level input, non-string data-status values, empty/malformed HTTPS URLs, and URL parser errors with the documented `DatasetProvenanceError` instead of leaking incidental implementation exceptions ([validator commit](https://github.com/HaochuanLin/islandOS/commit/b1fd1d864b8cebba16586c33bd66631f887802b2)).
- Added regression cases for malformed IPv6 URLs, empty HTTPS hosts, list-valued status, non-mapping metadata, and non-bytes hash input ([test commit](https://github.com/HaochuanLin/islandOS/commit/6bb1e978d4082d3913732ef178e6bab850049eb3)).
- Score impact: no maturity score is raised solely because code was committed. Wait for CI against the exact `main` SHA, then reassess data-validation and overall engineering evidence. This metadata contract does not establish dataset licensing, accuracy, site relevance, or field validity.


### 2026-10-23 — Reusable provenance audit command

- Added `experiments/validate_dataset_provenance.py`, a command-line interface that validates and normalizes a provenance JSON record and can bind it to a local artifact's exact SHA-256 bytes.
- The CLI rejects a declared digest that does not match the supplied file and exits non-zero for malformed JSON or invalid metadata; regression coverage is in `tests/test_validate_dataset_provenance_cli.py`.
- Added [Dataset provenance validation](DATASET_PROVENANCE.md) with the schema, commands, and limits. This makes the contract directly usable in offline workflows; it does not yet automatically attach metadata to every importer or prove source accuracy/licence compliance.
- Score impact remains pending until the full CI workflow completes successfully for the exact main commit. Do not increase real-world validation scores based on this software-only change.
- Added a subprocess integration test for the documented `python -m experiments.validate_dataset_provenance` entry point, switched the guide to that reproducible invocation, and linked the guide from the README. The subprocess test guards against a CLI that works only when imported by pytest.



## Plug-and-play maturity scorecard (no private site data available)

The user-facing goal is that a new operator can install IslandOS, launch a demo, configure a hypothetical site, and evaluate the full input-to-report workflow before receiving measurements. Scores below are provisional engineering judgments on a 0–10 scale, not scientific performance metrics. They must only rise when corresponding repository evidence and exact-SHA checks support the change.

| Capability | Baseline before no-data bootstrap | Target | Midpoint checkpoint | Evidence required at midpoint |
|---|---:|---:|---:|---|
| No-data first-run onboarding | 6.0 | 8.0 | 7.0 | One documented command creates a deterministic synthetic CSV accepted by the app parser; hosted and local quickstarts identify synthetic data honestly. |
| Site configuration portability | 5.5 | 8.0 | 6.75 | One documented configuration contract, field units/defaults, actionable validation errors, and a working example profile. |
| Input validation and provenance | 6.5 | 8.5 | 7.5 | Valid/invalid upload integration tests, deterministic input/run signatures, and visible source status in exported artifacts. |
| Replaceable forecasting / dispatch interfaces | 6.5 | 8.0 | 7.25 | A minimal example plugin runs through the documented interface and produces a report consumed by the evaluation/dispatch path. |
| Local installation and deployment portability | 6.5 | 8.0 | 7.25 | Clean-environment install, health check, documented shutdown, and reproducible smoke test. |
| Real-site operational evidence | 2.0 | 4.0 | 3.0 | Without site measurements, only testability and evidence collection can improve; no synthetic-only work can prove field accuracy or equipment safety. |
| **Overall plug-and-play readiness** | **6.0** | **8.0** | **7.0** | At least half the baseline-to-target gap closed in each software-controlled area, with green CI and no claim that synthetic inputs represent real sites. |

### Midpoint rule

For each software-controlled capability, the midpoint is `baseline + (target - baseline) / 2`. The overall score is not raised merely because documentation or code was added: require a runnable path and passing tests on the exact candidate commit. Real-site evidence is tracked separately because it cannot be manufactured from synthetic data. A system can be easy to install and useful for planning without being certified for live control.


### 2026-10-24 — Plug-and-play onboarding, provenance, and CI feedback hardening

- Merged bounded onboarding and audit changes in PRs [#108](https://github.com/HaochuanLin/islandOS/pull/108), [#109](https://github.com/HaochuanLin/islandOS/pull/109), [#110](https://github.com/HaochuanLin/islandOS/pull/110), [#111](https://github.com/HaochuanLin/islandOS/pull/111), [#112](https://github.com/HaochuanLin/islandOS/pull/112), [#113](https://github.com/HaochuanLin/islandOS/pull/113), [#114](https://github.com/HaochuanLin/islandOS/pull/114), [#115](https://github.com/HaochuanLin/islandOS/pull/115), and [#116](https://github.com/HaochuanLin/islandOS/pull/116). Main now includes a one-command synthetic site demo, synthetic-data manifests and verification, site CSV timestamp/interval preflight, site configuration bootstrap/validation/audit, an offline first-run doctor, dispatch-input snapshot hashing, environmental-feature provenance hashes, and forecast skill metrics against naive baselines.
- Hardened CI in [PR #117](https://github.com/HaochuanLin/islandOS/pull/117), [#118](https://github.com/HaochuanLin/islandOS/pull/118), [#119](https://github.com/HaochuanLin/islandOS/pull/119), and [#120](https://github.com/HaochuanLin/islandOS/pull/120): pip/BuildKit caching, parallel dependency audits, removal of duplicate NSGA-II test execution, fallback to local Docker build when remote BuildKit initialization fails, cancellation of superseded push runs, and separate concurrency groups for scheduled/manual verification.
- A transient Docker Hub HTTP 502 caused cached-builder initialization to fail on commit 938e5aa0d381454579a43e0ec51af45a9fdc44e3. The fallback was added and verified: cached image build, non-root assertion, and Streamlit health check passed on main commit e4b859644bb633bbb91634103872e023cddabeb3 (run [40070315600](https://github.com/HaochuanLin/islandOS/actions/runs/40070315600)).
- The full current tree is identical between main commit 315c2989038d18354570ad68a2fab13ee866d626 and tested PR head d97c6ee6ac07dfb52557ebafa22b53abf5b4c8b1 (tree SHA 219c3f43f9fbeb6958cac3be93952ee8239c91c2). All five workflows passed on that exact tree: full RO/pytest and benchmark suite [run 40070382655](https://github.com/HaochuanLin/islandOS/actions/runs/40070382655), Nan'ao scenario [run 40070382659](https://github.com/HaochuanLin/islandOS/actions/runs/40070382659), container smoke [run 40070382687](https://github.com/HaochuanLin/islandOS/actions/runs/40070382687), Windows packaging [run 40070382662](https://github.com/HaochuanLin/islandOS/actions/runs/40070382662), and dependency audit [run 40070382689](https://github.com/HaochuanLin/islandOS/actions/runs/40070382689).
- Updated evidence-based scores: interactive demo/usability 90→91, commercial/deployment readiness 57→60, and overall software-engineering maturity 93→94. Branch/release management remains 89 because main branch protection and required-status enforcement are still disabled. Public-data/site-data validation remains 60 because no island-specific measured data was added. Real-world operational validation remains 38/100: synthetic workflows, hashes, and external public datasets do not constitute an authorized site pilot.

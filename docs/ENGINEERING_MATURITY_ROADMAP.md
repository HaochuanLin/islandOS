# Engineering maturity roadmap

This roadmap turns the project's maturity scores into evidence-based release gates. Scores are engineering assessments, not measured scientific quantities. A score may rise only when the listed evidence exists in the repository or in a documented, reviewable test run.

## Baseline and target scorecard

Baseline scores are the assessment recorded on 2026-10-23. They are provisional and should be revised downward if an audit finds missing evidence. Target scores are goals, not claims that the targets have already been met.

| Area | Baseline | Target | Evidence required for target |
|---|---:|---:|---|
| Core simulation and dispatch | 87/100 | 93/100 | Explicit invariants for energy/water accounting; adversarial boundary tests; benchmark results that report raw service metrics and do not require the proposed strategy to win every fixture; documented model limits. |
| Automated tests and reproducibility | 88/100 | 97/100 | Required CI checks on main and pull requests; deterministic fixtures; integration tests for public commands and exported JSON/CSV schemas; useful failure artifacts; no silently skipped core checks. |
| Documentation and evidence audit | 85/100 | 95/100 | Every major feature links to runnable commands, input schema, provenance, assumptions, expected outputs, limitations, and CI evidence; product and pilot scopes remain distinct. |
| Interactive demo and usability | 80/100 | 92/100 | Hosted app health is checked separately from code CI; clean-environment startup is tested; upload validation and user-facing failures have regression tests; demo clearly labels synthetic data and export provenance. |
| Branch and release management | 55/100 | 90/100 | Reduce stale/diverged branches and PRs; each PR has a bounded scope, current base, passing required checks, and a reviewable diff; no mass merge of divergent product/pilot histories. |
| Public-data / site-data validation | 25/100 | 60/100 | A documented measured or reputable public dataset with license, provenance, units, missingness audit, chronological holdout, baseline comparison, and reproducible results. This target does not imply Nan'ao field validation. |
| Commercial / deployment readiness | 38/100 | 70/100 | Repeatable install/deploy, documented support/security boundaries, explicit cost model and sensitivity analysis, stakeholder-defined acceptance criteria, and a documented pilot plan. No safety-critical control claim. |
| Overall software-engineering maturity | 84/100 | 95/100 | The engineering targets above are met with CI evidence, a clean branch/release path, and no unresolved high-severity defects. |
| Real-world operational validation | 38/100 | 60/100 | Independently sourced site measurements and a reproducible retrospective study with documented limitations. Higher scores require an authorized, supervised pilot and site-specific safety review; they cannot be reached with synthetic tests alone. |

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

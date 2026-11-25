# IslandOS application integration report — 2026-11-25

Baseline: `main` at `e6a179a` (F-03 squash merge), after T1–T7 and F-02/F-03/F-04.  
Scope: the Streamlit application (`app.py`, `islandos_ui/workspace.py`, customer pages 05/06/09), the
application-facing view models, and the local React reference viewer. No forecast, optimization,
simulation or economic formula was changed in this pass.

## 1. Short status

The application still runs real chains, not mock screens:

- **05 Customer Decision Dashboard:** hourly history → forecast → bounded policy comparison →
  stress/paired replay → service-equivalent economics → optional customer-entered investment screen →
  operator record and JSON.
- **06 Joint Resource Optimizer:** hourly history → manifest → forecast → joint resource search →
  recommended schedule → optional equal-day annual projection → JSON audit.
- **09 Device Flexibility Planner:** real but deliberately isolated device demo with fixed synthetic
  site inputs.
- The Data onboarding section can inspect a CSV/XLSX and store a CSV in the session-only handoff;
  05 and 06 both read it.

## 2. What changed since 2026-11-24

### 2.1 T1–T7

- **T1:** one shared input-fingerprint helper for the two customer pages.
- **T2:** 05 prints its assumptions and the recommended dispatch in the page, not only in JSON.
- **T3:** 06 shows forecast points and intervals on the page.
- **T4:** 09 gets a two-layer, readable error boundary instead of a single setup `ValueError`.
- **T5:** Workspace Microgrid copy is aligned; candidate CSV carries a scenario input fingerprint.
- **T6:** the React console labels itself a local reference surface and links the three planning paths.
- **T7:** the shared input fingerprint is wired into 05/06.

### 2.2 F-02/F-03/F-04

- **F-02:** 05/06 caught only `ValueError, KeyError, TypeError`; both now use
  `(ValueError, KeyError, TypeError, ArithmeticError, IndexError)`, print a "no partial output"
  caption, and stop the page.
- **F-03:** 05 shows `Local request SHA-256` and states it is not a cross-page run identity; 06
  renames `Canonical run` to `Canonical page run` and states it is not a handoff id for 05.
- **F-04:** the React viewer no longer silently hides a missing annual block; it shows
  `Not included in this report` with page-specific copy for 05, 06 and 09.

### 2.3 Cross-page input identity

`build_input_fingerprint` covers `history_sha256`, `site_digest`, `units`, `hour_count` and `currency`.
`page_settings_sha256` is stored separately because the two pages expose different knobs. Matching
fingerprints mean "same shared input", not "same run": 05 and 06 still mint different `run_id`s and
manifests over the same CSV. The UI now says so; it does not merge the runs.

## 3. Verification actually run

Python, full suite on `main` at `e6a179a` with Git on `PATH`:

```text
1594 passed, 4 skipped, 589 subtests passed, 155 warnings in 173.68s
```

Focused evidence:

- F-02: `pytest tests/test_page_error_boundaries.py tests/test_ui_smoke_all_pages.py -q` → 20 passed.
- F-03: `pytest tests/test_page_identity_labels.py tests/test_ui_smoke_all_pages.py -q` → 20 passed.
- F-04: `npm test` → 14 passed; `npm run build` → passed.

Environment note: the first full run, without Git on `PATH`, reported the same 1592 passed plus two
Git-dependent deployment/build-stamp failures. Both pass when `D:\Program Files\Git\cmd` is on `PATH`;
that is the run reported above, matching the repository's documented Windows setup.

## 4. What remains incomplete

These are real product/backend gaps, not hidden by the UI pass:

- **No single cross-page run identity (G1).** 05 and 06 still produce different `run_id`s and manifests
  over the same history. F-03 labels the difference; it does not create a shared run.
- **Annual replay is still absent (G2).** `replay_run_request` returns `annual: None` for 05, 06 and 09.
  The 06 annual projection remains a page checkbox plus an equal-days assumption.
- **Forecast points are not formally exportable (G5).** 06 displays points and intervals; there is no
  committed forecast-point CSV contract or download.
- **Simulation is not a first-class stage (G6).** It is embedded inside the optimizers; there is no
  common simulation result envelope.
- **Economic definitions remain incompatible (G8).** 05 customer-entered annual investment, 06 equal-day
  annual operating projection, 09 24-hour energy charge and workspace per-m³ indicators use different
  service boundaries and periods. Matching history does not make their cost figures comparable.
- **09 remains isolated.** It has fixed synthetic inputs, no forecast, no optimizer and no historical
  chain. Its error path is now readable, but the data path is still a demo.
- **The React console has no server-side session/auth (B-04).** It remains a local reference surface,
  not the public demo's primary path.
- **No real-site validation is claimed.** All results remain modeled/simulated.

## 5. What other module owners need to provide

These items need agreement with the named owners before the next integration step:

- **Jayni (backend interfaces):** a stable run envelope for forecast/optimization/economics results; a
  decision on whether annual/investment evidence is replayed by `POST /run`; the React session/auth
  contract or an explicit no-go.
- **Ilaha (forecast):** the forecast-point export schema and provenance fields, including units,
  `model_id`/`model_version`, interval method and `history_sha256`.
- **Sonika (simulation/device):** the simulation result envelope and the decision on whether 09 should
  consume a real history chain.
- **Liyue (economics):** the service-boundary/period/CAPEX/OPEX contract that decides whether any two
  cost figures are comparable.

The application should consume those contracts rather than inventing a second vocabulary.

## 6. Recommended next steps

1. Run CI and a browser pass on the merged deployment: Data onboarding → 06 → 05 with the same CSV, then
   a different CSV, then optional 09. Confirm the match/mismatch copy and shared-upload button.
2. Decide J-01 (run identity), J-02/M-04 (09 positioning and history chain), J-03/M-02 (economic
   comparison) and J-04 (simulation stage) before writing more integration code.
3. Add forecast-point export and a first-class simulation view only after Ilaha/Sonika/Jayni confirm the
   data contracts.
4. Treat a single cross-page run identity as a larger orchestration change, not a UI polish item.

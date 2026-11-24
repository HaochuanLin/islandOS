# IslandOS application integration report — 2026-11-24

Scope: the existing Streamlit application (`app.py`, `islandos_ui/workspace.py`, customer pages 05/06/09)
and the session handoff already implemented in `islandos_core/session_dataset.py`. This pass did not
change forecasting, optimization, simulation or economic calculations, and did not rebuild the React
console.

## 1. Short assessment

The application already contains real chains, not just mock screens:

- **05 Customer Decision Dashboard** goes from hourly history → forecast → a bounded two-policy comparison
  → stress/paired replay → service-equivalent economics → optional customer-entered investment screen
  → operator record and JSON.
- **06 Joint Resource Optimizer** goes from hourly history → manifest → forecast → joint resource search
  → recommended schedule → optional equal-day annual projection → JSON audit.
- **09 Device Flexibility Planner** is a real but deliberately isolated device demo with fixed synthetic
  site inputs.
- The Data onboarding section can inspect a CSV/XLSX and store a CSV in the existing session-only handoff;
  05 and 06 can both read it.

The biggest integration problems were not missing calculators. They were handoff and interpretation
problems:

1. **05 and 06 could be compared without warning when their inputs differed.** Each page printed a
   history hash, but neither page compared it with the other view's last input.
2. **A page-specific upload was a dead end.** The session handoff existed, but only Data onboarding
   offered to write it; uploading directly on 05 or 06 left the file on that page.
3. **The overview ordered 09 before 05's economics**, making the isolated device demo look like the
   second stage of the 05/06 history chain.
4. **The cost numbers have different boundaries.** Matching input does not make 05's investment screen
   and 06's operating projection interchangeable.

## 2. What was implemented

### 2.1 Cross-page input identity note

New `islandos_ui/customer_workflow.py` records, per customer page, the last history SHA-256 and provenance
seen in the browser session. On the next visit it compares the two snapshots:

- matching hash → a note that the input matches, followed by an explicit warning that the pages are
  still separate runs with different optimization and cost boundaries;
- different hash → a warning that the outputs are **not like-for-like** and the reader must use the same
  CSV or restore the same demo assumptions;
- no prior visit → a neutral prompt to open the other view.

This is presentation state only. It creates no shared `run_id`, merges no results and changes no model
calculation.

### 2.2 Page-local upload → existing session handoff

When a CSV is parsed successfully on 05 or 06, the page now offers **“Share this CSV with the other
customer view”**. The button calls the existing `store_session_dataset(...)`, so the other view can read
the same bytes through the existing `SESSION_DATASET_KEY`. The handoff remains browser-session-only, keeps
the existing SHA-256 verification and the 25 MiB limit, and does not add a second persistence mechanism.

### 2.3 Journey order and copy

The Workspace overview now reads:

1. Forecast and coordinate → 06
2. Compare policies and economics → 05
3. Optional device check → 09 (fixed synthetic inputs, explicitly not a continuation)

It also tells new users to start with Data onboarding when they have their own CSV, and that a direct
upload on either customer page can be shared with the other view.

### 2.4 Documentation

- `APP_INTEGRATION.md` now names `customer_workflow.py`, the new session-state key and the fact that
  matching input does not merge the two runs.
- `docs/FRONTEND_TEST_REPORT.md` header now labels the original T7 branch/PR as historical and points
  current integration status to this report.
- This report is the short assessment, implementation record and remaining-work list.

## 3. Verification actually run

Command:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  .venv/bin/python -m pytest -q
```

Result on the integration branch in the cloud VM:

**1545 passed, 4 skipped, 589 subtests passed, 69 warnings in 143.26s.**

Focused checks also passed:

- `tests/test_customer_workflow.py` — 9 passed. Covers match/mismatch state, page wiring, journey order,
  the match/mismatch UI copy, and a button-click flow that stores the CSV in the existing session key.
- Page smoke/navigation subset — 37 passed before the two UI tests were added; the full run above includes
  the current versions.

Environment caveat: the VM runs Python 3.12 and Streamlit 1.66.1, while the repository lock is documented
for Python 3.11 CI. The full suite passed here, but CI still needs to run on the repository's pinned
environment. No browser-flow claim is made from this run; page rendering was verified with Streamlit
`AppTest`.

## 4. What remains incomplete

These are real product/backend gaps, not hidden by the UI pass:

- **No single cross-page run identity (G1).** 05 and 06 still produce different `run_id`s and manifests
  over the same history. The UI now says so; it does not make them one run.
- **Annual replay is still absent (G2).** `replay_run_request` returns `annual: None`; the annual projection
  remains a page/06 checkbox outcome. Replayable annual evidence needs a core/transport contract.
- **Forecast points are not exportable (G5).** 05/06 show model quality/charts but do not export the exact
  forecast point series used by the optimizer.
- **Simulation is not a first-class stage (G6).** It is embedded inside the optimizers; there is no common
  simulation result envelope to compare “same input, same simulation, different optimizer.”
- **Economic definitions remain incompatible (G8).** 05 customer-entered annual investment, 06 equal-day
  annual operating projection, 09 24-hour energy charge and microgrid per-m³ indicators use different
  service boundaries and periods. Matching history does not make their cost figures comparable.
- **09 remains isolated (G7/G9).** It has fixed synthetic inputs, no forecast, no optimizer and only a
  `ValueError` setup/schedule error path.
- **The React console is unchanged.** It remains a reference surface, not the public demo's primary path.
- **No real-site validation is claimed.** All results remain modeled/simulated.

## 5. What other module owners need to provide

These items need agreement with the named owners before the next integration step:

- **Jayni (backend interfaces):** a stable run envelope for forecast/optimization/economics results, and
  a decision on whether annual/investment evidence is replayed by `POST /run`.
- **Ilaha, Sonika and Liyue (module owners):** confirm the forecast-point, simulation-result and economic-
  boundary contracts their modules can supply, including series/units, model/provenance, and period/service
  definitions. The application should consume those contracts rather than inventing a second vocabulary.

## 6. Recommended next steps

1. Run CI and a browser pass on the merged deployment: Data onboarding → 06 → 05 with same CSV, then a
   different CSV, then optional 09. Confirm the match/mismatch copy and shared-upload button.
2. Decide the economic boundary contract before adding any cross-page cost comparison or combined
   economics dashboard.
3. Add forecast-point export and a first-class simulation view only after Ilaha/Sonika/Jayni confirm the
   data contracts.
4. Treat a single cross-page run identity as a larger orchestration change, not a UI polish item.

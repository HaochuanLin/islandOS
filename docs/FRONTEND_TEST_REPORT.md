# Frontend closeout test report (T7)

Date: 2026-11-24
Branch: `release/frontend-t7`
Base: `origin/main` at `d4a6139`
Pull request: **#333** (open, not merged by T7)
Work: T1–T6 integrated; T7 documentation, one device-page presentation fix, one regression test,
and the closeout verification.

This report covers what was **actually run** on this branch. It does not claim a browser flow that
was not exercised, and it does not turn a synthetic result into a measured site result.

## 1. Branch contents

| Commit | Scope |
|---|---|
| `506a891` | T1 frontend completion audit |
| `9d96f23` | T2 upload rejection recovery and sidebar tooltip fix |
| `288a639` | T5 device-page units, plainer input headings, less internal subtitle |
| `9e68584` | T4 module integration audit |
| `a2c1414` | T6 frontend README: name the 8766 local API and proxy |
| T7 commit | Device-page task-charge vs replay-cost distinction; port documentation; test report; judge walkthrough; T1 status table |

No model, forecast, water, optimisation or economic assumption was changed. The application remains
read-only: no device control, no dispatch, no RBAC or multi-tenancy.

## 2. Results

### Full Python suite — passed

Command:

```text
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
python -m pytest -q
```

Result: **1522 passed, 4 skipped, 589 subtests passed, 69 warnings in 158.26s**.

The single-threaded BLAS variables are part of the command, not an after-the-fact excuse. The first
full run with default threading failed 13 tests, all in subprocess-heavy tests, with:

```text
OpenBLAS error: Memory allocation still failed after 10 retries, giving up.
```

Those 13 were re-run as a subset with the same single-thread settings and **16 passed in 5.87s**.
They are environment memory failures on this laptop, not frontend or contract failures. The green
1522-test result above is the one to cite, with the command that produced it.

### Targeted T7 tests — passed

```text
python -m pytest -q tests/test_device_planner_presentation.py \
  tests/test_ui_smoke_all_pages.py tests/test_page_headers.py \
  tests/test_demo_csv_schema.py tests/test_upload_guard.py
```

Result: **39 passed, 16 warnings in 14.53s**.

### React build, tests and CI — passed

```text
cd frontend
npm ci
npm test
npm run build
```

Result: `npm ci` installed 69 packages from the committed lockfile; `npm test` ran **6 Node tests**
(contract-viewer v3 guard and telemetry 404/401/500 behaviour); `npm run build` reported **36 modules
transformed** and produced both HTML entries and their assets in `frontend/dist/`.

The first lockfile was generated on Windows and omitted `@rollup/rollup-linux-x64-gnu`, so `npm ci`
passed but `vite build` failed on the Linux runner. The lockfile was regenerated with Linux, Windows
and macOS optional dependencies; `npm ci`, `npm test` and `npm run build` then passed locally, and
GitHub check-runs on head `0fd4a06` reported **12/12 success**.

This proves compilation, bundling and the two pure-module behaviours. It does not prove browser
usability, authentication, API behaviour, accessibility or deployment.

### Live Streamlit walkthrough — three customer pages verified

Local run: `http://127.0.0.1:8611`, browser viewport 1280×960, 2026-11-24.

- **Decision dashboard** rendered the Decision snapshot: Battery First, 17.93 USD, 0.00 kWh unmet,
  18.37 USD modeled difference; service equivalence and dispatch audit both passed.
- **Joint resource optimizer** rendered the canonical run/manifest/evidence digests, status
  "ready for human review", "device write not authorized", a four-scenario physical audit and the
  withheld annual basis.
- **Device flexibility planner** rendered after the T7 fix:
  - 72 kWh critical energy protected
  - 17 kWh flexible task energy
  - 13.77 USD scheduled task energy charge
  - 6.0 kW peak task demand
  - 103.2 kWh grid import
  - 15.44 USD replayed system energy cost
  - 0.00 kWh critical unmet
  - 0.00 kWh flexible load shed
- **Download** from the device page produced
  `islandos_device_flexibility_report.json` (7,429 bytes); the file has
  `application_views.request` and `.result`, both `schema_version: 3`.

The first live dashboard load showed a transient `MemoryError` in Altair while the full Python suite
was running concurrently. After stopping the suite and reloading, the page rendered normally. That is
a laptop memory-pressure event, not a page defect. Do not run the full suite and the live demo at the
same time on this machine.

### What was not run

- A signed-in React console flow against a running API (login, site create/select, telemetry,
  notifications, member management).
- The contract viewer in a browser with a downloaded page 05/06 report.
- Live page 07 or 08 (local-only; not in the judged public menu).
- Accessibility, visual regression, load or penetration tests.
- A browser-level upload of the rejected template; the recovery path is covered by
  `tests/test_demo_csv_schema.py` and `tests/test_upload_guard.py`.

No claim above depends on those unrun flows.

## 3. T7 defect fix

The T1 audit found two money figures on page 09 with no explanation and an empty subheading.
T5 added USD. T7 finished the fix:

- renamed `Scheduled energy charge` to `Scheduled task energy charge`;
- renamed `Energy cost` to `Replayed system energy cost`;
- merged the empty `Shared energy-system replay` heading with the comparison heading;
- added one caption: task-only charge versus whole-site replay including existing load and shared
  dispatch, "deliberately different and not expected to match";
- added `tests/test_device_planner_presentation.py` to pin the labels and the explanation.

The values did not change: 13.77 USD and 15.44 USD are still the model's own outputs.

## 4. Closeout follow-up

The remaining frontend findings were fixed on the same branch:

| ID | Item | Result | Evidence |
|---|---|---|---|
| F-01 | One local flag exposed the other local page | Fixed | Per-page predicates in `islandos_ui/navigation.py`; `app.py` registers 07 only with the API URL and 08 only with the workspace flag; 7 navigation tests pass. |
| F-04 | Viewer did not check `schema_version` | Fixed | `readViews()` rejects a request or result that is not v3; six Node tests cover v2, unversioned and v3 payloads. |
| F-05 | Telemetry 401/500 looked like "no data" | Fixed | `ApiError` carries the HTTP status; only 404 becomes `null`, other failures reach the error banner; Node tests cover 404, 401 and 500. |
| F-06 | Frontend CI was build-only | Fixed | `package-lock.json` committed; CI uses `npm ci` and runs `npm test`; viewer and telemetry tests are part of that command. |
| F-07 | 52 deprecated `use_container_width` calls | Fixed | All 52 now use `width="stretch"`; page smoke, header and navigation tests pass with no `use_container_width` warning. |
| F-08 | Site workspace create button stayed disabled after consent | Fixed | Found during the live page-08 check; `tests/test_local_workspace_creation.py` drives consent/no-consent creation. |
| G2 | `POST /run` promised annual evidence but returned `None` | Fixed as a documentation boundary | `transport.py` now states annual evidence is not replayed. |
| G3 | 05 investment inputs were discarded on replay | Fixed for the eight v3 request fields | `replay_run_request` returns an `investment` block from the existing evaluator; `tests/test_application_transport.py` checks equality. Replacement year, replacement cost and residual value remain page-only. |
| G1 | No single replayable end-to-end chain | Deferred by Phase 1 boundary | A new cross-page pipeline would change the model composition; not claimed as integrated. |
| G4 | 05 and 06 use different synthetic inputs | Deferred by Phase 1 boundary | Unifying them changes recorded demo numbers; the difference is documented. |

`F-02` (port mismatch) and `F-03` (device-page labels and heading) remain fixed from T7.

## 5. Follow-up verification

```text
python -m pytest -q tests/test_navigation_contract.py
-> 7 passed in 0.12s

python -m pytest -q tests/test_ui_smoke_all_pages.py \
  tests/test_page_headers.py tests/test_navigation_contract.py
-> 30 passed, 16 warnings in 13.63s

python -m pytest -q tests/test_application_transport.py \
  tests/test_contract_json_schema.py
-> 19 passed in 5.01s

python -m pytest -q tests/test_local_workspace_creation.py
-> 2 passed in 2.19s

cd frontend && npm test
-> 6 passed

cd frontend && npm run build
-> 36 modules transformed; both HTML entries built
```

The 16 warnings in the page run are Pandas 4 `reset_index(inplace=True)` deprecations from Streamlit's
chart helper. The former `use_container_width` warning is not present.

### Live local-only pages

Three local Streamlit instances were opened with different environment variables:

- only `ISLANDOS_API_BASE_URL=http://127.0.0.1:8766`: the menu showed **Customer workspace (local)**
  and not **Site workspace (local)**;
- only `ISLANDOS_ENABLE_LOCAL_WORKSPACE=1`: the menu showed **Site workspace (local)** and not
  **Customer workspace (local)**;
- both variables: page 08 opened, a temporary project was created through the real form, and the
  page then showed the active project, site configuration, equipment register, exports and
  `Local workspace audit chain: valid · 2 events`.

The live 08 check is what exposed F-08: the old form disabled its submit button on a checkbox value
that could not change until the form was submitted. The fixed form permits the click and refuses
the submit when consent is absent.

Page 07 opened its real sign-in form against the loopback API; no credential was entered, so the
signed-in tenant view is not claimed as exercised.

## 6. Acceptance statement

For the judged public Streamlit path, the branch is ready for the walkthrough in
`docs/JUDGE_WALKTHROUGH.md`: three customer pages render, the device-page cost distinction is
explicit, the report download has the v3 contract fields, the full Python suite passes with the
documented single-thread command, and the React bundle builds. The local 07/08 pages now appear only
under their own prerequisites.

G1 (one cross-page pipeline) and G4 (one shared 05/06 synthetic input) are **not fixed**; they are
Phase 1 limits recorded in `docs/MODULE_INTEGRATION_AUDIT.md`. The branch does **not** claim
production readiness, measured savings, site permission, a completed shadow trial, RBAC or device
control. The PR is not merged by this task.

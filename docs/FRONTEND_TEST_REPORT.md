# Frontend closeout test report (T7)

Date: 2026-11-24
Branch: `release/frontend-t7`
Base: `origin/main` at `d4a6139`
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

Result: **1518 passed, 4 skipped, 589 subtests passed, 69 warnings in 167.02s**.

The single-threaded BLAS variables are part of the command, not an after-the-fact excuse. The first
full run with default threading failed 13 tests, all in subprocess-heavy tests, with:

```text
OpenBLAS error: Memory allocation still failed after 10 retries, giving up.
```

Those 13 were re-run as a subset with the same single-thread settings and **16 passed in 5.87s**.
They are environment memory failures on this laptop, not frontend or contract failures. The green
1518-test result above is the one to cite, with the command that produced it.

### Targeted T7 tests — passed

```text
python -m pytest -q tests/test_device_planner_presentation.py \
  tests/test_ui_smoke_all_pages.py tests/test_page_headers.py \
  tests/test_demo_csv_schema.py tests/test_upload_guard.py
```

Result: **39 passed, 16 warnings in 14.53s**.

### React build — passed

```text
cd frontend
npm run build
```

Result: TypeScript and Vite build succeeded; **35 modules transformed**; both HTML entries and their
assets were produced in `frontend/dist/`.

This proves compilation and bundling. It does not prove browser usability, authentication, API
behaviour, accessibility or deployment. There is still no `package-lock.json`, and CI uses
`npm install --no-package-lock`; that remains an open P2 (T1 F-06).

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

## 4. Known open items after T7

These are documented, not silently fixed:

| ID | Item | Why it remains open |
|---|---|---|
| F-01 | One local flag exposes the other local page | Local-only menu; judged public menu is unaffected. Needs a per-page predicate and two tests. |
| F-04 | Viewer does not check `schema_version` | Requires a product decision: add a gate or narrow `APP_INTEGRATION.md` to match the presence-only viewer. |
| F-05 | React telemetry errors become "no data" | Console is not the judged demo; needs an API-layer distinction between 404 and failure. |
| F-06 | CI build-only; no lockfile | Would be a separate T6 follow-up; no lockfile was added. |
| F-07 | 52 deprecated `use_container_width` calls | Separate UI migration; current Streamlit still renders. |
| G1–G4 | Module integration high gaps | Contract/model/product decisions recorded in `docs/MODULE_INTEGRATION_AUDIT.md`; out of T7. |

`F-02` (port mismatch) is fixed in documentation: root README and page 07 now name `8766`, the
service default. `F-03` (device-page labels and heading) is fixed in this branch. The T1 audit keeps
its baseline findings and now carries a T7 status table so the two states are not confused.

## 5. Acceptance statement

For the judged public Streamlit path, the branch is ready for the walkthrough in
`docs/JUDGE_WALKTHROUGH.md`: three customer pages render, the device-page cost distinction is
explicit, the report download has the v3 contract fields, the full Python suite passes with the
documented single-thread command, and the React bundle builds.

The branch does **not** claim production readiness, measured savings, site permission, a completed
shadow trial, RBAC or device control. The PR is not merged by this task.

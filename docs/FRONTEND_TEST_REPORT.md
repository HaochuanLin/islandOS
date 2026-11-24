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

- **Decision dashboard** rendered the Decision snapshot: Battery First, 24.52 USD after the shared-history
  change, 0.00 kWh unmet, 10.55 USD modeled difference; service equivalence and dispatch audit both passed.
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
| G4 | 05 and 06 use different synthetic inputs | Fixed at the input layer | 05 starts from 06's `build_synthetic_site_history` via `build_customer_site_history`; at 1.0/1.0 both pages print the same `Shared history SHA-256`. 05's pinned cost is 24.52 USD; 06's 7,709.55 USD/year is unchanged. |

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

Page 07 opened its real sign-in form against the loopback API. In the signed-in acceptance run it
reached the owner view; before this run the signed-in tenant view had not been exercised.

### Signed-in browser acceptance

Run with a disposable local SQLite database, a temporary owner tenant and one site + notification
created through the API. The database and server were removed afterwards.

- **Page 07 (Streamlit, 1280×960):** the exact Email/Password fields were filled and the primary
  form submitted. The page then showed `Signed in · role: owner`, the tenant line, the
  `Organization members` table with the owner, and the `Notification inbox` tab contained
  **Inverter derate** with severity `warning`, the supplied message and `Mark as read`.
- **React console (Vite dev server, 1440×960):** the same owner signed in; the console showed
  `OPERATIONS CONSOLE`, **North microgrid** in the site list, `REGISTERED SITES 1`,
  `UNREAD NOTIFICATIONS 1`, the owner member row, the **Inverter derate** activity item, and
  `LATEST TELEMETRY — No validated record` / `No telemetry received`. The API indicator was
  `online` and no error banner appeared.
- Not covered: invitation acceptance, role mutation, telemetry ingestion, MFA/SSO, production TLS and
  multi-user isolation. Sign-out and server-side revocation in the browser were the gap this run left
  open; the 2026-11-24 pass below closes it. The React console remains a local reference surface, not
  the judged public demo.

### Sign-out and server-side revocation

A second pass on 2026-11-24 used the same method: disposable local SQLite database, temporary owner
tenant, one site and one unread **Inverter derate** notification created through the API, page 07 at
1280×960, services and database removed afterwards.

- **The first attempt failed.** The `Sign out` click returned `404 not found`; the page then showed
  "Signed out locally, but server-side revocation could not be confirmed", and the browser session row
  was still in the database afterwards, so the token stayed valid. Cause: the logout route was
  registered on `do_GET` only, while page 07 signs out with `POST /api/v1/auth/logout`.
  `frontend/src/api.ts` had been relying on its GET default, so the two clients disagreed about the verb.
- **Fix.** The route now answers `POST /api/v1/auth/logout`; `GET` on the same path no longer mutates
  session state (it returns `404`). `frontend/src/api.ts` sends the POST explicitly, and
  `tests/test_service_api_logout_route.py` covers both verbs (POST revokes and the token then fails
  with `401`; GET leaves the session usable).
- **Page 07 after the fix.** `Mark as read` on **Inverter derate** removed the button and left the card
  in place; the API reported `read_at = 2026-11-24T12:17:10Z` and `unread_only=true` returned 0 items.
  The `Sign out` click then produced `Signed out. The current server-side session was revoked.` above
  the restored Email/Password form, and the sidebar role/tenant lines disappeared.
- **Server side.** Before the click the session table held the browser token and one API token; after
  it exactly the browser row was gone, an `auth.logout` audit event was written for that session id,
  and the other session stayed valid — revocation is per-session, not per-user.
- **Token revocation at API level.** `GET /api/v1/members` → `200`, `POST /api/v1/auth/logout` →
  `{"revoked": true}`, reuse of the same bearer → `401` "session is invalid or expired".
- **React console (Vite dev server, 1440×960).** Its `/api` proxy was pointed at a private API
  instance on port 8770 because the repo's 8766 was in use by another service. The same owner signed
  in, `UNREAD NOTIFICATIONS` showed 1, `Mark as read` on **Inverter derate** took it to 0, and
  `Sign out ↗` returned the console to the Email/Password screen with no error banner. The session
  table again lost exactly the console session (an `auth.logout` event names it) while the API token's
  session stayed valid, so the POST route serves both clients.
- **Checks on this branch.** `python -m pytest -q` with the single-thread BLAS settings →
  `1530 passed, 4 skipped, 589 subtests passed`; `npm run build` in `frontend/` → build completed.

Screenshots from the patched Streamlit run (`docs/evidence/page-07-signout/`): `01-signed-out.png`
(prerequisite form), `02-signed-in.png` (owner view with member table), `03-inbox-before-read.png`,
`04-after-mark-read.png`, `05-after-sign-out.png`; `00-pre-fix-signout-failed.png` records the failed
`404` attempt before the fix. The React console pass is in `docs/evidence/react-console-signout/`:
`01-signed-in.png`, `02-after-mark-read.png`, `03-after-sign-out.png`.

## 6. Acceptance statement

For the judged public Streamlit path, the branch is ready for the walkthrough in
`docs/JUDGE_WALKTHROUGH.md`: three customer pages render, the device-page cost distinction is
explicit, the report download has the v3 contract fields, the full Python suite passes with the
documented single-thread command, and the React bundle builds. The local 07/08 pages now appear only
under their own prerequisites.

G1 (one cross-page pipeline) is **not fixed**; it is a Phase 1 limit recorded in
`docs/MODULE_INTEGRATION_AUDIT.md`, and the walkthrough states that 05/06/09 are three separate
page-level demonstrations. G4 is fixed at the input layer: 05/06 share the canonical synthetic
history and hash. The branch does **not** claim production readiness, measured savings, site
permission, a completed shadow trial, RBAC or device control. The PR is not merged by this task.

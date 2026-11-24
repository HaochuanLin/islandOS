# Frontend and application completion audit (T1)

Status: **audit only; no application code changed.**

- Repository: `D:\code\islandOS`
- Branch: `audit/frontend-baseline` (created from `origin/main` at `d4a6139`)
- Audit date: 2026-11-24
- Scope: Streamlit entry points and pages, React console and contract viewer, local reference API,
  application-view contracts, regression coverage.
- Out of scope: model mathematics, energy/water/forecast assumptions, new backend features,
  RBAC/multi-tenancy, device control, React API expansion, production deployment, PR creation.

This audit separates three things that are easy to conflate: **implemented behaviour**, **documented
intent**, and **verified test evidence**. A statement below is marked "confirmed" only when it was
reproduced from the current checkout by source inspection and, where applicable, by a render, build
or test. Where a path was inspected but not executed, the document says so.

## 1. Executive summary

The judged Streamlit demo passes its render and contract checks. All public page routes open under
Streamlit's `AppTest` without exceptions, the contract tests are green, and the React application
builds. There is no confirmed P0 defect for the public demo path in the checks performed. A live
browser walkthrough of the demo and a signed-in React console flow are still pending; this audit
does not claim them.

The remaining problems are concentrated in **local-only setup and presentation**, not in the core
screening path:

1. The local-only menu has one gate for two pages that need different prerequisites. Setting one
   prerequisite exposes the other page as a dead end.
2. Three different loopback API ports are published in user-facing text (`8000`, `8765`, `8766`);
   the service default is `8766`.
3. The device page shows two different cost figures (`13.77` and `15.44`) without currency labels or
   an explanation of why they differ, and leaves an empty subheading immediately above the comparison.
4. The contract viewer does not reject an old report version, although `APP_INTEGRATION.md` says it
   does. The code matches `frontend/README.md`'s "no validation of its own" description, so the
   documentation and the viewer disagree.

The React console is a local reference surface, not the competition demo. Its remaining issues are
P2: telemetry errors are silently converted to "no data", and CI proves only that the bundle compiles.

## T7 closeout status (2026-11-24)

This table is the current state after T2–T7 and the follow-up fixes on the same branch. Section 4
below remains the T1 baseline and is not rewritten to hide what was found.

| ID | Finding | Current status | Evidence |
|---|---|---|---|
| F-01 | One local flag exposes the other local page | **Fixed** | `app.py` registers 07 under `local_customer_workspace_enabled()` and 08 under `local_site_workspace_enabled()`; `tests/test_navigation_contract.py` covers both flags. |
| F-02 | API port inconsistent (`8000`/`8765`/`8766`) | **Fixed** | Root `README.md` and page 07 now name `8766`; service default is `8766`. |
| F-03 | Device page cost labels and empty heading | **Fixed** | T5 added USD; T7 renamed the two metrics, merged the empty heading, added the reconciliation caption and a source-level test. |
| F-04 | Viewer does not check `schema_version` | **Fixed** | `frontend/src/applicationViewsPayload.ts` rejects a request or result whose `schema_version` is not `3`; the Node test covers v2, unversioned and v3. |
| F-05 | React telemetry errors become "no data" | **Fixed** | `ApiError` carries the HTTP status; `latestTelemetry` returns `null` only for 404, and 401/500 reach the error banner. Node tests cover both paths. |
| F-06 | Frontend CI is build-only; no lockfile | **Fixed** | `frontend/package-lock.json` is committed; CI uses `npm ci` and runs `npm test` before `npm run build`; the Node behaviour test covers viewer and telemetry contracts. |
| F-07 | 52 deprecated `use_container_width` calls | **Fixed** | All 52 call sites now use `width="stretch"`; page smoke, header and navigation tests pass, and the deprecation warning is gone. |
| F-08 | Site workspace create button stayed disabled after consent | **Fixed** | Found during the live 08 check: a form widget cannot enable a button disabled on its own value. The button is now clickable and consent is enforced on submit; `tests/test_local_workspace_creation.py` drives both paths. |
| G1 | No single replayable end-to-end chain | **Deferred by Phase 1 boundary** | Fixing it requires a new cross-page pipeline and changes the model composition. That conflicts with the no-model-change/read-only boundary; the three page chains remain explicitly separate. |
| G2 | Replay contract promises annual but returns `None` | **Fixed as documentation boundary** | `islandos_core/transport.py` no longer promises annual replay; the response still returns `annual: None`, which is now the stated contract rather than an omission. |
| G3 | 05 investment inputs discarded on replay | **Fixed for the eight request fields** | `replay_run_request` now calls the existing evaluator and returns `investment`; `tests/test_application_transport.py` checks it equals the page evaluator. Replacement-year, replacement-cost and residual-value remain page-only because they are not in the v3 request. |
| G4 | 05 and 06 build different synthetic inputs | **Deferred by Phase 1 boundary** | Unifying them changes recorded demo numbers, which would invalidate the walkthrough and the cited figures. The difference is documented, not hidden. |

**Conclusion after the follow-up:** the judged public Streamlit path is ready for a walkthrough. The
frontend findings F-01 and F-04–F-07 are fixed. G2 is corrected as a contract boundary, G3 is fixed
for the request fields, and G1/G4 remain explicit Phase 1 limits rather than being presented as fixed.

## 2. Surface inventory

| Surface | Entry point / file | Authentication | Default data | Audit result |
|---|---|---|---|---|
| Streamlit shell | `app.py` | None | n/a | One `st.navigation` menu; public pages are registered; local pages are gated. Renders. |
| Decision workspace | `islandos_ui/workspace.py` | None | Synthetic demo + optional upload | Eight sections reachable through the in-page radio. Renders with no exception. Detailed model review not performed. |
| Customer decision dashboard | `pages/05_Customer_Decision_Dashboard.py` | None | Synthetic history and investment assumptions | Renders; downloads report and operator record; contract view present. |
| Joint resource optimizer | `pages/06_Forecast_Led_Joint_Resource_Optimizer.py` | None | `build_synthetic_site_history` | Renders; canonical run/manifest/evidence present; annual projection withheld until declared. |
| Device flexibility planner | `pages/09_Device_Flexibility_Planner.py` | None | Inline synthetic tasks | Renders; CSV and report downloads; presentation issues below. |
| Rolling horizon lab | `pages/2_Rolling_Horizon_Lab.py` | None | Synthetic rolling-horizon experiment | Registered as experimental; smoke test passes. |
| Local customer workspace | `pages/07_Local_Customer_Workspace.py` | Loopback API bearer token | Local SQLite service | Gated by its own `ISLANDOS_API_BASE_URL` predicate; not offered when only the site-workspace flag is set. |
| Local site workspace | `pages/08_Site_Workspace.py` | None | Local SQLite workspace | Gated by its own `ISLANDOS_ENABLE_LOCAL_WORKSPACE=1` predicate; not offered when only the API URL is set. |
| React console | `frontend/index.html`, `frontend/src/App.tsx` | Bearer token in component memory | Local API `/api/v1` | Builds; local reference only; telemetry 401/500 is surfaced, 404 remains "no data". |
| Contract viewer | `frontend/application-views.html`, `frontend/src/ApplicationViews.tsx` | None | Downloaded report + `GET /contracts` | Builds; requires request and result `schema_version: 3`. |
| Local reference API | `islandos_service_api.py` | Login/session token | SQLite | Loopback-only; tests pass; no device writes. |
| Application transport | `islandos_core/transport.py` | None | Loopback | Serves viewer, contracts, health and `POST /run`; tests pass. |

## 3. What is actually implemented

**Streamlit demo path**

- One navigation menu. `app.py` owns `st.set_page_config` and `st.navigation`; the eight workspace
  sections live under the default `Workspace` page.
- Three judged customer views: decision dashboard (05), forecast-led joint optimizer (06), device
  flexibility planner (09), plus the experimental rolling-horizon lab.
- Session-only uploads: uploaded CSV/XLSX is held in session state, hashed, and can be cleared;
  a tampered session dataset is discarded rather than crashing the page.
- Canonical run identity on 06: run id, manifest SHA-256 and evidence SHA-256 are shown and exported.
- Downloads on 05/06/09 include `application_views` blocks. The viewer reads those blocks; it does
  not recompute them.
- The default demo is synthetic and labelled as such on the pages and in the runbook.

**Local-only path**

- `pages/07` requires an explicit loopback `ISLANDOS_API_BASE_URL`; it rejects non-loopback URLs.
- `pages/08` requires `ISLANDOS_ENABLE_LOCAL_WORKSPACE=1`; without it the page warns and stops.
- The reference API implements health, login/logout, tenant sites, latest telemetry, notifications,
  members, invitations and role changes. Tests pass.
- The React console implements sign-in, site list/create, latest telemetry, notifications,
  member management and sign-out. It keeps the bearer token in memory only.

**Not implemented, and should not be claimed**

- Production authentication, SSO/MFA, RBAC, multi-tenancy, audit retention, TLS or a hosted service.
- Device control, dispatch approval, setpoint writes or autonomous operation.
- Optimization-run, dispatch-plan approval, historical analytics or full asset-management API
  endpoints for the React console.
- Browser E2E tests, accessibility tests or visual regression tests for either React surface.
- Site-validated forecast accuracy, measured savings or a production digital twin.

## 4. Confirmed defects and gaps

### F-01 — one local flag exposes the other local page as a dead end (P1)

**Where**

- `app.py:29-33`: `local_ui_enabled()` returns true if **either** `ISLANDOS_ENABLE_LOCAL_WORKSPACE=1`
  **or** `ISLANDOS_API_BASE_URL` is set.
- `app.py:103-117`: the same `if` registers **both** `pages/07` and `pages/08`.
- `pages/07_Local_Customer_Workspace.py:29-43`: page 07 requires `ISLANDOS_API_BASE_URL`.
- `pages/08_Site_Workspace.py:38-41`: page 08 requires `ISLANDOS_ENABLE_LOCAL_WORKSPACE=1`.

**Reproduction path (source inspection)**

1. Start with only `ISLANDOS_API_BASE_URL=http://127.0.0.1:8766`.
2. The menu contains both "Customer workspace (local)" and "Site workspace (local)".
3. Open "Site workspace (local)": it warns that the local workspace is disabled and stops.

The converse is also true: with only `ISLANDOS_ENABLE_LOCAL_WORKSPACE=1`, page 07 is registered and
warns that the API URL is not configured.

**Expected** — each local page appears only when its own prerequisite is present.

**Why it matters** — this is exactly the "public demo shows dead ends" failure the navigation
consolidation was meant to remove, moved into the local deployment. It is P1 rather than P0 because
the judged public menu has neither variable set.

**Suggested fix (T5, not this audit)** — split the predicate into
`local_site_workspace_enabled()` and `local_customer_workspace_enabled()`, and register each page in
its own list. Add two tests: API URL only registers 07 and not 08; workspace flag only registers 08
and not 07.

### F-02 — loopback API port is inconsistent across user-facing setup text (P1)

**Where**

- `islandos_service_api.py:668`: the service default is `--port 8766`.
- `README.md:114`: `ISLANDOS_API_BASE_URL=http://127.0.0.1:8000`.
- `pages/07_Local_Customer_Workspace.py:32`: warning suggests `http://127.0.0.1:8765`.
- `docs/STAGE_6_CUSTOMER_FRONTEND.md:17,20`: documents `8766` and the Vite proxy to `8766`.
- `frontend/vite.config.ts:12`: proxy target is `http://127.0.0.1:8766`.

**Reproduction path (source inspection)** — follow `README.md` line 114 with the default API command
from the same README (`python -m islandos_service_api`); the API listens on `8766`, while Streamlit
is pointed at `8000`. The local customer workspace cannot reach it. Following page 07's warning with
`8765` fails the same way.

**Why it matters** — a local reviewer following the primary README hits a connection failure before
seeing the page. It is P1 for local setup, P2 for the judged public demo.

**Suggested fix** — make `8766` the single documented port, or state `--port` explicitly in every
command that also sets `ISLANDOS_API_BASE_URL`. Update page 07's warning and the README snippet
together; do not change the service default in this audit.

### F-03 — device page shows two unexplained cost figures and an empty subheading (P1)

**Where**

- `pages/09_Device_Flexibility_Planner.py:103`: metric `"Scheduled energy charge"` renders
  `13.77` with no currency.
- `pages/09_Device_Flexibility_Planner.py:126`: table column `"Energy charge"` also has no currency.
- `pages/09_Device_Flexibility_Planner.py:145`: subheading `"Shared energy-system replay"`.
- `pages/09_Device_Flexibility_Planner.py:153`: the next subheading `"Like-for-like operating
  comparison"` follows immediately; no element is rendered under the first heading.
- `pages/09_Device_Flexibility_Planner.py:173`: metric `"Energy cost"` renders `15.44` with no
  currency. The page sets `currency="USD"` at line 214.

**Verified by render** — `AppTest` on page 09 reports no exception, and exposes:

```text
SUBHEADERS: ['Per-device schedule', 'Hourly demand and remaining task capacity',
             'Shared energy-system replay', 'Like-for-like operating comparison']
METRICS: [('Critical energy protected', '72 kWh'), ('Flexible task energy', '17 kWh'),
          ('Scheduled energy charge', '13.77'), ('Peak task demand', '6.0 kW'),
          ('Grid import', '103.2 kWh'), ('Energy cost', '15.44'),
          ('Critical unmet', '0.00 kWh'), ('Flexible load shed', '0.00 kWh')]
```

The two figures are not the same quantity: `13.77` is the sum of scheduled task energy charges
(`DeviceSchedulingResult.total_energy_cost`), while `15.44` is the whole-system replay cost from the
shared PV/wind/battery/grid/diesel accounting. A reader sees the larger number below the smaller one
with no explanation.

**Why it matters** — a judge can reasonably ask "which cost is the result?" and "why do they differ?"
This is a presentation/trust defect, not a model defect.

**Suggested fix** — label the top metric `"Scheduled task energy charge (USD)"`, label the lower
`"Replayed system energy cost (USD)"`, add currency to the table header, and either remove the empty
`"Shared energy-system replay"` heading or put the replay explanation under it. Add one caption:
the first is task-only, the second includes the site's pre-existing load and the shared system
dispatch. Do not change the model or either number.

### F-04 — viewer version behaviour contradicts the integration document (P1)

**Where**

- `frontend/src/ApplicationViews.tsx:32-48`: `readViews()` checks that the payload is an object,
  that an `application_views` block exists, and that `request` and `result` are present. It never
  reads or compares `schema_version`.
- `APP_INTEGRATION.md:408-411`: says a v2 report "opened in the viewer ... is refused with a version
  error" because `schema_version` is a `const` in the JSON Schema.
- `frontend/README.md:92-94`: says the viewer has "no validation of its own"; it only checks that
  `request` and `result` exist. This matches the code.

**Reproduction status** — confirmed by source inspection, not by a running browser. A payload with
`application_views.request` and `.result` but `schema_version: 2` has no rejection path in
`readViews()`: no version error is raised. The viewer will render whatever fields are present and
may show blanks or mislabelled fields.

**Why it matters** — either the document overstates the viewer, or the viewer is missing a promised
guard. Both are bad for a reviewer who downloads an old report and expects a refusal.

**Suggested fix (choose one, in T5/T6)** — (a) add a `schema_version === CONTRACT_VERSION` check in
`readViews()` and a test that a v2 block is rejected; or (b) narrow `APP_INTEGRATION.md` to say the
viewer checks presence only and the JSON Schema is the validating artifact. Do not leave both claims
standing. If (a), also check the request and result versions, not only the outer block.

### F-05 — React telemetry failure is displayed as "no telemetry" (P2)

**Where**

- `frontend/src/App.tsx:37-39`: the `catch` around `api.latestTelemetry()` has two branches that
  both call `setTelemetry(null)`; the `err` value is unused.
- `frontend/src/api.ts:19`: any non-2xx response throws an `Error`.

**Source inspection** — with a valid session, a 401/500 for
`/api/v1/sites/<id>/telemetry/latest` takes the same `catch` branch as the documented "no telemetry"
404. The screen shows the normal empty state "No telemetry received" rather than an error. Only the
site/notification refresh is surfaced through `error`. This path was not exercised in a browser.

**Why it matters** — an operator cannot distinguish "no data yet" from "the read failed". It is not
P1 for the competition because the React console is not the judged demo.

**Suggested fix** — catch only the documented `no telemetry` 404 and set a null state; surface other
errors through `setError`. Alternatively, have `api.latestTelemetry()` return `null` for the 404 and
throw for everything else.

### F-06 — frontend CI proves compilation only; no lockfile or behaviour test (P2)

**Where**

- `.github/workflows/customer-frontend.yml:28-29`: `npm install --no-package-lock` then
  `npm run build`.
- No `frontend/package-lock.json` is present in the checkout.
- `docs/STAGE_6_CUSTOMER_FRONTEND.md:35`: explicitly says the workflow validates compilation and
  bundling, not browser usability or security.

**Consequence** — a build can pass while login, site selection, telemetry refresh, notification
mark-read or member management is broken. Dependency resolution is also not pinned.

**Suggested fix (T6, not this audit)** — commit a lockfile and use `npm ci`; add at least a small
component/state test or a documented manual checklist with screenshots. Do not add a new framework
just to satisfy this audit.

### F-07 — deprecated `use_container_width` remains in 52 places (P2)

**Where** — 7 Streamlit files, 52 occurrences:

```text
islandos_ui/workspace.py (34), pages/05 (6), pages/09 (2), pages/06 (3),
pages/2_Rolling_Horizon_Lab.py (4), pages/07 (1), pages/08 (2)
```

**Evidence** — page 09's `AppTest` run prints: "Please replace `use_container_width` with `width`.
... will be removed after 2025-12-31." The current Streamlit version still renders, so this is not a
current failure.

**Suggested fix** — a separate UI-only migration to `width="stretch"`. Do not mix it with model or
report changes; verify each page after the change.

## 5. Findings checked and not confirmed

- **Page 05 demo clock lacks a date.** False. `pages/05_Customer_Decision_Dashboard.py:119-122`
  states the frozen date and hour, and the history caption at `:196-199` prints the full window.
  The short `"Demo clock pin 14:00 UTC"` suffix is redundant, not missing.
- **Page 09 uses different history signal IDs from 05/06.** The IDs differ, but the contract accepts
  a signal map with units; this is not by itself a contract violation. No failure was reproduced.
  Re-check only if a future strict signal catalog is added.
- **Page 05 annual binding moves with the wall clock.** Covered by
  `tests/test_app_identity_and_recovery.py`; two renders produced identical binding digests.
- **Public menu contains local dead pages.** False in the default environment; both local pages are
  behind the gate. The defect is the gate's granularity (F-01), not public exposure.

## 6. Priority list

### P0 — blocks the judged public demo or produces a false claim

None confirmed in the checks performed. All public menu pages render under `AppTest`; the contract
suite and the 175-test frontend subset pass; the React bundle builds. A live browser walkthrough and
a signed-in React console flow remain unverified, so this is not a statement that every interaction
has been exercised.

### P1 — judge-visible trust or local setup failure

1. F-01 local page gating: one flag exposes the other page as a dead end.
2. F-02 API port mismatch (`8000` / `8765` / `8766`).
3. F-03 device page cost labels, two unexplained figures, empty subheading.
4. F-04 viewer version claim versus actual behaviour.

### P2 — quality, verification and maintenance

5. F-05 React telemetry errors silently become "no data".
6. F-06 no frontend behaviour test or lockfile; CI is build-only.
7. F-07 deprecated `use_container_width` in 52 places.

## 7. Authoritative source for the default demo and reports

When a judge asks "where did this number come from?", the answer should point to the page and the
downloaded artifact, not to a slide.

| Page | Default input source | Default anchor | Primary artifact |
|---|---|---|---|
| 05 Decision dashboard | Synthetic history generated inline from the frozen demo clock; optional uploaded CSV/XLSX replaces it | `2026-11-22 14:00 UTC`, 168 hourly rows | `islandos_customer_decision_report.json`; also `islandos_operator_decision_record.json` |
| 06 Joint optimizer | `build_synthetic_site_history(demo_anchor, ...)`; optional uploaded CSV/XLSX replaces it | `2026-11-22 14:00 UTC` | `islandos_joint_resource_schedule.json` |
| 09 Device planner | Inline task list: clinic-critical, ice-maker, water-pump; constant tariff and PV/wind profiles | `2026-01-01 00:00 UTC`, 24 hours | `islandos_device_flexibility_demo.csv`; `islandos_device_flexibility_report.json` |

Rules for reading those artifacts:

- The report's `application_views` block is what the viewer renders. The viewer does not recompute
  anything.
- `05` downloads carry `application_views.request` and `.result`; `annual` is absent, which the viewer
  treats as null.
- `06` carries `annual` only after the reader declares the equal-days assumption; otherwise the page
  withholds it and the exported value is null.
- `09` carries `annual: null` by design; there is no annual projection for the device page.
- The displayed costs are modelled values from declared assumptions. They are not measured site
  results, a customer bill or a savings claim.

## 8. Verification actually run

All commands below were run from `D:\code\islandOS` on the audit branch. `git` was prepended to
`PATH` (`D:\Program Files\Git\cmd`) for the test runs.

### Python frontend/contract/workflow subset — 175 passed

```text
python -m pytest -q \
  tests/test_app_view_models.py tests/test_run_orchestration.py \
  tests/test_demo_clock.py tests/test_session_dataset.py tests/test_upload_guard.py \
  tests/test_customer_dashboard_adapter.py tests/test_decision_record_panel.py \
  tests/test_operator_decision_record_demo.py tests/test_device_flexible_tasks.py \
  tests/test_ui_smoke_all_pages.py tests/test_streamlit_overview.py \
  tests/test_app_identity_and_recovery.py tests/test_app_integration_doc.py \
  tests/test_application_transport.py tests/test_contract_json_schema.py \
  tests/test_contract_typescript.py tests/test_contract_versioning.py \
  tests/test_navigation_contract.py tests/test_page_headers.py \
  tests/test_main_app_provenance.py tests/test_islandos_service_api.py \
  tests/test_stage_e_members_notifications.py tests/test_stage_f_canonical_workflow.py \
  tests/test_app_workflow.py
```

Result: `175 passed, 56 warnings in 36.53s`. Warnings are Streamlit/Pandas deprecations, including
the `use_container_width` warning recorded as F-07.

### Earlier targeted subset — 87 passed

The same UI/contract/navigation set without the API/workflow tests: `87 passed, 36 warnings in
44.07s`.

### Build-info test with git on PATH — 26 passed

`python -m pytest -q tests/test_build_info.py` → `26 passed, 15 subtests passed in 4.31s`.

Without `D:\Program Files\Git\cmd` on `PATH`, the same test fails with
`'none' not found in 'build unknown (git-not-runnable)'`. That is an environment limitation of this
shell, not a product defect; the rerun with git available passes. Do not report the failure as a
frontend regression.

### Page 09 render inspection

`AppTest.from_file("pages/09_Device_Flexibility_Planner.py")` → no exceptions; the subheading and
metric lists are quoted under F-03. This is the runtime evidence for the empty heading and the two
unlabelled cost figures.

### React build — passed

```text
cd frontend
npm run build
```

Result: TypeScript and Vite build succeeded; 35 modules transformed; two HTML entries and their
assets were produced in `frontend/dist/`. This proves compilation and bundling only, not browser
usability, authentication, API behaviour or deployment.

### Full suite — partial, not counted as a pass

A full `python -m pytest -q` run was started twice. The first run stopped at the build-info
environment failure described above. The second run, with git on `PATH`, reached 27% with no
failures visible before it was stopped for time. **No full-suite pass is claimed.** The 175-test
subset above is the evidence for the frontend/application surfaces in this audit.

### What was not run

- A live browser walkthrough of the Streamlit demo (public menu, uploads, downloads).
- A signed-in React console flow against a running API, including telemetry, notifications and
  member management.
- The contract viewer opened in a browser with real page 05/06/09 downloads.
- The full Python suite to completion.
- Any penetration, accessibility, visual-regression or load test.

Those remain T2/T5/T6 work. No claim in this audit depends on them.

## 9. Recommended order after this audit

1. **T2** — fix F-01 and F-02 (local menu and port), because both are setup failures that can waste a
   reviewer's time.
2. **T3/T4** — fix F-03 (device-page labels and empty heading) and F-04 (viewer version behaviour or
   documentation), then add the corresponding tests.
3. **T5/T6** — do not expand React. Fix F-05, add the lockfile and at least one behaviour check, and
   migrate F-07 in an isolated UI-only change.
4. Re-run the 175-test subset and `npm run build` after each fix; report exactly which command was
   run and which pages were opened.

## 10. Audit boundary

This document does not modify application code, models, assumptions, competition results or data.
It does not open a PR. The only file written is this audit document. The candidate defects above are
confirmed at the level stated; none is presented as a measured site result or a production
authorization.

# Changelog

Notable project changes are recorded here. This is a research prototype; versioned releases are verification bundles, not site-operation approvals.

## Unreleased
- **Customer UI follow-ups from the public release audit.**
  Historical RO baseline now warns readers not to upload confidential or personally identifiable
  data to the public hosted demo. The Page 06 prediction table uses a narrower mobile-only type
  and cell-padding scale so `RMSE` stays inside the 390 px card without an inner horizontal
  scroll. Flexible-load now defaults its display-only currency label to `USD` instead of the
  literal `currency`; prices, calculations, units and exported values are unchanged.
- **Page 06 and replay now share the same canonical manifest builder.**
  The earlier replay change made repeated API replays deterministic, but page 06 still built its
  manifest through a separate path. That meant a page run and a replay of its request were not
  guaranteed to share a `run_id` or manifest digest. Both paths now call
  `build_joint_optimizer_manifest(request)`; the manifest timestamp comes from the last timestamp
  in the request's history window. A regression test checks the run ID, manifest SHA-256 and
  timestamp, and a page-wiring test guards the shared call. Pages 05 and 09 remain separate runs.


- **J-01 P1b technical run identity now maps directly onto immutable run records.**
  `derive_run_id()` derives a page-scoped `run-<05|06>-<sha16>` identity from the
  input group, site configuration, page settings/inputs, forecast and run settings,
  model-selection policy, catalogue version, optimizer and algorithm versions.
  The new `run_record_identity_fields()` maps it to `run_id`, `page`,
  `run_request_sha256`, and `input_group_id` for `record_run_record()`.
  `run_request_sha256` is the same technical identity digest, not a second hash and
  not the full request digest. Manually corrupted identities are rejected.
  Tests cover Page 05/06 vectors, technical-input sensitivity, investment/Page 09
  boundaries, exact replay, and `run_result_conflict` after mapping.
  Page 05/06 persistence and the v4 API contract remain separate integration work.

- **Local workspaces can now retain immutable run results with explicit consent.**
  Workspace schema 1.0 migrates to 1.1 and creates a separate `run_records` table
  keyed by `(project_id, run_id)`. Records retain request/result digests, request
  metadata, result JSON, optional canonical manifest and input fingerprints. Result
  storage requires explicit consent; retaining the full request/history arrays
  requires a separate opt-in. Metadata-only records can be viewed but are not
  replayable. Read APIs verify stored hashes and SQLite triggers reject ordinary
  updates/deletes. Project packages now carry run results; full requests are
  excluded by default and require a separate export/import opt-in.
  Records now also carry `run_request_sha256`, `input_group_id`, and
  `identity_schema_version` (0 legacy, 1 technical identity), with an index on
  `(project_id, input_group_id, created_at)`. Identical replay returns the stored
  record with `idempotent_replay=true` and adds no audit event; page, technical
  request, input group, result, or retention mismatches raise `RunRecordConflict`
  with 409 semantics. Failed runs are audit-only `run_failed` events,
  import/export accepts both 1.0 and 1.1 run records, and concurrent inserts are
  resolved by re-reading after `IntegrityError`.
  `tests/test_workspace_store.py`, `tests/test_workspace_backup_restore.py` and
  `tests/test_site_workspace.py` cover migration, consent, integrity, backup,
  idempotency, conflicts and project portability.


- **Sign out in the local customer workspace now revokes the session.**
  Page 07 and `frontend/src/api.ts` sign out with `POST /api/v1/auth/logout`, but the route was
  registered on `do_GET` only: the browser got `404 not found`, the page said "server-side revocation
  could not be confirmed", and the bearer stayed valid until expiry. The route now answers `POST`;
  `GET` on that path is a plain `404` and deletes nothing. `tests/test_service_api_logout_route.py`
  covers both verbs (POST revokes, then reuse returns `401`; GET leaves the session usable). Browser
  evidence for `Mark as read`, `Sign out` and token revocation is in
  `docs/FRONTEND_TEST_REPORT.md`, "Sign-out and server-side revocation".

- **05 and 06 now share one synthetic input at the same demo clock.**
  05 used its own inline 168-hour PV/wind/load/tariff loop, so the same nominal site produced a
  different history and hash on each page. 05 now calls
  `build_customer_site_history`, which starts from 06's `build_synthetic_site_history` at 40 kW PV /
  20 kW wind and then applies 05's `demand_scale` and `tariff_scale`. At `1.0/1.0` the timestamps and
  four signal arrays are identical, both pages print the same `Shared history SHA-256`, and 05's pinned
  24-hour cost is `24.52 USD` instead of `17.93`. 06's `7,709.55 USD/year` and `186,150 kWh` are
  unchanged. The checksum quantises each signal to six decimals before hashing, so the printed hash is
  stable across Python and libm runtimes without changing the arrays the models use.
  `tests/test_demo_site_history.py` covers the wrapper, hash and quantisation;
  `tests/test_demo_clock.py` compares the two pages' captions.

- **A broken session dataset no longer replaces page 05 or 06 with a stack trace.**
  `get_session_dataset` fails closed when the record fails its SHA-256 check, but both pages called it
  outside a handler, so a stale or tampered record took the whole surface down. `read_session_dataset`
  now returns `(record, reason)`, clears the bad record, and the pages tell the reader to upload again;
  the next run starts from a known state. `tests/test_session_dataset.py` covers the core helper and
  `tests/test_app_identity_and_recovery.py` opens both pages with a deliberately broken record.

- **05's annual-economics binding no longer changes identity on every rerun.**
  The manifest behind the binding stamped `datetime.now()`, and the digest includes that timestamp:
  two renders of the same inputs produced different manifest and binding SHA-256 values even though the
  run id stayed the same. The page now uses the window the run describes — the demo anchor for synthetic
  data, the last history hour for an upload — the same rule 06 already follows.

- **Build-stamp writes no longer share one `.tmp` file.**
  Two writers truncated and renamed the same temporary, and on Windows a concurrent `os.replace` can fail
  outright; the stamp is now written to a private temporary and the rename is serialised and retried.
  `tests/test_build_info.py` writes eight stamps from eight threads and checks the surviving file is one
  complete document with no temporary left behind.

- **The deployment check waits for the download button instead of racing its caption.**
  Streamlit renders the sidebar's `build …` line before the button beside it. `capture_stamp_download` read
  once, so a read landing in that gap found no button and the stamp fell back to the seven-character caption
  — observed on `3e1a990`, where the button appeared three seconds later. `find_stamp_button` now polls for
  up to ten seconds; on a real timeout the report says how long it waited, and the rendered-line fallback is
  unchanged. `tests/test_check_deployment.py` covers a late mount, a never-mounted button, and the timeout
  wording.

- **The default demo clock is frozen at 2026-11-22 14:00 UTC, so a default page reports one number.**
  Pages 05 and 06 used to pass `now.date()` and `now.hour` into the synthetic window; because the PV/wind
  ripple is keyed to the row index, the same code reported anywhere between `4,548.68` and `8,631.34`
  depending on when it was opened, with the `186,150 kWh` annual energy unchanged. The defaults now come
  from `islandos_core/demo_clock_defaults.py` — a new module on purpose: a running Streamlit process keeps
  imported modules in `sys.modules`, so editing `demo_site_history.py` would not take effect until a
  restart, while a new module is imported fresh. Both controls stay adjustable; moving either one
  reproduces another window. Uploaded CSVs are untouched: they carry their own timestamps and the demo
  clock is ignored on that branch. Before the shared-history change, the default screen read
  `7,709.55` on 06 and `17.93 USD` on 05 at any hour; `tests/test_demo_clock.py` asserts the widget
  defaults, the current pinned numbers and the shared hash. `APP_INTEGRATION.md` §6 records the new default and why the constant
  lives in its own module.

- **The hosted app now hands its stamp over as a download, so the commit is proved from bytes rather than a
  seven-character caption.** The two entries below established that Community Cloud never serves
  `/app/static/build_info.json`, and settled for reading `build 46d145a (git)` off the sidebar. That is a
  narrower claim than it looks: seven characters cannot be a full commit, and the line is the app's caption,
  not its document. `app.py` now offers **Download build stamp (JSON)** in the sidebar, built from
  `build_info.serialise_stamp()` — the same function that writes the file, so the bytes cannot drift. The
  check reads the static file first, then clicks that button inside the same headless session that warms the
  app, and validates the downloaded document with the same rules as the file; `stamp.source` records
  `static` or `download`, and an unreadable download is reported as a download failure, never promoted to a
  stamp. The sidebar line remains the last resort, so the previous entry's behaviour is preserved rather
  than replaced. Verified end to end on a local server in both configurations: with static serving off, the
  three pages return the shell, the download captures 260 B naming `46d145a60c…`, `commit.assertion` is
  `match`, `stamp.source` is `download`, `verdict = ok`, exit 0; with it on, `stamp.source` is `static` and
  the verdict is still `ok`. Tests: 1496 passed, 4 skipped (full suite), including
  `test_the_file_and_the_download_are_the_same_bytes`, an AppTest assertion that the sidebar renders the
  button, and five cases covering download-proved, download-mismatch, download-missing-then-line,
  unreadable-download and static-preferred. `APP_INTEGRATION.md` §7.1–§7.5 updated; §7.4 still says the
  static file and the download are never compared byte for byte.

- **"Which commit is the hosted app running?" is now a claim with evidence, not a blank.** `APP_INTEGRATION.md`
  said the deployed commit could not be shown from outside. Half of that was measured rather than assumed: on
  2026-11-23 every route on `islandos.streamlit.app` — a page, `/_stcore/health`, an invented path — answered
  `200` with one identical 9,782-byte Streamlit front-end shell, and the HTML carries no page title, button
  label or `schema_version` string at all, because Streamlit draws the page in the browser. Scraping the page
  therefore proves nothing, and an HTTP status cannot tell a live page from a missing one. The app now
  publishes a build stamp where the bytes *are* app-specific: `islandos_core/build_info.py` reads the
  deployment's own checkout (`git rev-parse HEAD`), `app.py` writes `static/build_info.json` at start-up and
  captions the sidebar `build <sha> (<resolved_from>)`, and `.streamlit/config.toml` enables
  `[server] enableStaticServing` so that the file would be served at `/app/static/build_info.json` on a host
  that enables the route. The commit is never a
  constant in the repository: a committed SHA would assert a fact nobody verified, and a CI-written stamp
  cannot contain the SHA of the commit that adds it, so it would only ever describe its parent.
  `tests/test_build_info.py` fails if a literal 40-hex value ever appears in the module. A deployment with no
  git metadata says `unknown` with the reason instead of inventing a value; `ISLANDOS_BUILD_COMMIT` is
  accepted for container builds but reported as `environment`, and is never compared to a branch.
  `scripts/check_deployment.py` turns this into one repeatable assertion: the three page routes must return
  the app shell, a headless session must render the page, the sidebar line must name the commit the stamp
  publishes, and `--expect-commit` must match it. A stamp that disagrees with itself — a short form that
  does not match its full commit, a sidebar line carrying the right sha with the wrong source tag — is
  refused rather than treated as a partial match. Exit codes 0–5 separate "passed", "page broken", "stamp
  missing", "commit drift", "self-declared commit" and "render did not confirm". `--warm` exists because a
  Streamlit script only runs when a session connects: a fresh container has no stamp file until someone opens
  the app, and an HTTP-only probe would call that deployment broken. `hosted-app-health.yml` runs the script
  (installing `playwright==1.65.2` and Chromium for the warm-up) six-hourly with the commit assertion, and on
  push and pull request without it, because a run seconds after a merge would report drift that has not
  happened yet. `tests/test_check_deployment.py` covers every classification against a local server; the one
  test that talks to the public app is skipped unless `ISLANDOS_LIVE_DEPLOYMENT=1`. Rendering has to be read
  in the right frame as well: Community Cloud serves a wrapper whose own body is ~72 characters of chrome
  around `<iframe src="…/~/+/">`, and the app's DOM exists only inside that frame — a 180-second wait for the
  container in the page itself timed out against a deployment that was rendering fine, so the warm-up
  searches every frame and records `frame_url`. Run against the deployment as it stands, the check reports
  `stamp_unavailable` (exit 2), because the running container predated the change; the follow-up below
  records what a reboot then showed. What this still does not
  prove is listed in `APP_INTEGRATION.md` §7.4 — that the process executes the commit it reports, that
  dependencies equal the lock, Streamlit Cloud's own provenance, that the stamp cannot be made to lie, and
  anything else the rendered page shows. A reboot was done, and it showed the file is not served at all
  (next entry).

- **The commit proof no longer depends on a route Community Cloud does not serve.** The stamp was built on
  the assumption that `[server] enableStaticServing` would make `/app/static/build_info.json` readable from
  outside. After a reboot onto `46d145a` the path still answered with the same front-end shell, so there was
  never a served file to read, and a check that insisted on one could only report a missing stamp. The check
  now takes the commit from whichever source names it: the stamp when the host serves it (all 40 characters),
  otherwise the sidebar's `build <sha> (git)` line read in a headless browser — seven characters, compared
  as a prefix of `--expect-commit` and reported with `commit.basis: rendered`. The assertions themselves are
  unchanged: three page routes, a render with no exception, a build line that names a commit (and agrees
  with a served stamp), and the commit matching `--expect-commit`; drift is still exit 3, an unattributed
  sha is still refused rather than assumed. Two exit codes moved: exit 2 now means "nothing asked, nothing
  named" (an HTTP-only run against Cloud), while "expected a commit and found none" stays exit 4. What does
  not change is what this proves: the seven-character line is the deployment's own claim exactly as the
  file was, so §7.4's "cannot be made to lie" limit stands, and that the process executes the code it names
  remains unproved.

- **The contract now has a written migration rule, and a gate that fails when it is skipped.**
  `CONTRACT_VERSION` was `3` with three committed artifacts and no statement of when to bump or what
  must move with it, so the next field change could land in one file. `APP_INTEGRATION.md` gains §4.7
  "Contract versioning": a table of what counts as a bump (add / remove / rename / retype a field, a
  unit or definition change, a per-page key change, a new page) and what does not (captions, comments,
  tests, formatting); the order to change things in (`CONTRACT_VERSION` → field tuples → builders →
  generated artifacts → `contracts.ts` and the viewer → tests → this document and this file); a
  copy-paste checklist; and the rule that old version files stay. The number now has one source:
  `SCHEMA_PATH` was the last literal `app_view_models.v3.json` and is now derived from
  `CONTRACT_VERSION`, the JSON Schema's `$id` is its own file name rather than a second spelling of
  it, and the generated `frontend/src/contracts.ts` header states the version it was rendered from.
  `tests/test_contract_versioning.py` fails unless the long table's `contract_version`,
  the JSON Schema's `$id` and its per-object `schema_version` consts, and the TypeScript header all
  name `CONTRACT_VERSION`; it is also parametrised over each single-artifact edit, so the "only changed
  one place" case is proven to fail rather than assumed, and it fails on any file under
  `docs/contracts` naming a version above the constant, so a rolled-back bump cannot leave a v4
  artifact behind. Verified two ways: raising `CONTRACT_VERSION`
  to `4` alone failed on the missing regenerated files, and copying the v3 artifacts under v4 names
  failed naming all three stale versions; both passed again after reverting. Repeating the first case
  on the pull request, where only `CONTRACT_VERSION` moved, turned the `Python unit tests` gate red
  (#1334) and the revert restored it (#1335), so the failure is the test's, not a local accident.
  No runtime, schema or page change.

- **The two recorded 06 annual costs are now checked-in, reproducible evidence.** `scripts/trace_annual_energy_cost.py`
  replays page 06's default path at an explicit anchor and reuses `islandos_core.demo_site_history` rather
  than keeping a second copy of the synthetic formulas. `results/annual-cost-trace/` holds the 14:00Z run
  (`7,709.553484 USD/year`), the 02:00Z run (`5,332.569196`), and the 24-hour sweep (`4,548.683071` to
  `8,631.338277`), plus a README that states what the evidence does and does not show. `186,150 kWh`,
  `0.00` equipment cost and `0 h` diesel run time hold in all 26 runs; the annual gap is the daily grid
  import (`138.387` vs `93.688 kWh`) at the same `3.91` tariff sum, not a tariff change.
  `tests/test_trace_annual_energy_cost.py` pins the 14:00Z and 02:00Z figures. No page formula, contract
  field, or `schema_version` changed.

- **06's run identity is derived from the window it describes, not from the wall clock.** The page minted
  a fresh `run_id` with `uuid4()` and stamped `created_at_utc` with `datetime.now(timezone.utc)` on every
  render, so two downloads of the same pinned window carried different `run_id`, `manifest_sha256`,
  `summary_sha256` and `projection_sha256` even though the request and every figure were identical — a
  reader could not tell whether the two files were the same record. `run_id` now comes from
  `deterministic_run_id("run", …)` over the dataset digest, site-configuration digest, window end, currency,
  search settings and availability, and `created_at_utc` is the window the run speaks for (the demo anchor
  for synthetic data, the last history hour for an uploaded CSV). Same pin, same file: two renders now
  agree field for field, and moving the pin from 14 to 02 changes the id as it should.
  `tests/test_demo_clock.py::test_a_pinned_window_downloads_as_the_same_record_twice` captures the real
  download bytes through `st.download_button` and compares both fields across two renders and across two
  pins. The recorded figures are untouched: pin 14 still gives `7,709.55 USD/year`, pin 02 `5,332.57`,
  `186,150 kWh` in both. No contract field was added and `schema_version` stays at `3`.

- **A demo clock makes the two recorded demo figures reproducible without freezing them.** Pages 05 and
  06 built their synthetic 168-hour history from `datetime.now(timezone.utc)`, and the PV/wind ripple
  is keyed to the row index: one hour later the 24-hour day sits on a different part of the ripple and
  the projected cost moves while the load total does not. Both pages now have a sidebar `Demo date (UTC)`
  and `Demo clock (UTC hour)`, defaulting to today and the current hour, so the default stays live while
  a reader can type back a recorded window. 06's annual caption names the 24-hour window it projects and
  the history caption names the pin; 05's history caption names the pin. The pinned timestamps still
  enter the request as `history.timestamps_utc`; no contract field was added and `schema_version` stayed
  at `3`. Pinning 06 at 14 gives `7,709.55 USD/year` and at 02 gives `5,332.57` with `186,150 kWh`
  unchanged. Pinning 05 at `2026-11-22 14:00Z` reproduces the recorded `17.93 USD`; the same hour on
  `2026-11-23` gives `19.91` because 05's load carries a `1.2 * (day < 5)` weekday term, so its window
  depends on the date as well as the hour — `17.931016` recurs on the dates whose weekday mix matches
  (11-15, 11-22, 11-29 in a 2026-11-09…30 scan). `tests/test_demo_clock.py` pins both pages at those
  windows, and `tests/test_demo_site_history.py` pins the anchor helper, including its date argument and
  its refusal of naive timestamps. `APP_INTEGRATION.md` gains a "Demo clock" section and its deployed-app
  sentence no longer implies the 05/06 demo figures are independent of when the page is opened.

- **The viewer is now a local tool, and the question is closed rather than deferred.** After the landing
  route (`GET /`), the open item was whether `frontend/application-views.html` is a local tool or a third
  console page. It is a local tool: it reads a downloaded report and `GET /contracts` on loopback, holds
  no session, has no `/api` proxy, and writes nothing. Option B — folding it into the console — is
  recorded as rejected, because it would add session plumbing and an auth-shaped error path to a page that
  never uses identity, and a route implies a hosted service this is not. The single entry is a read-only
  footer link in the console (`Contract viewer (read only) ↗`); sign-in is unchanged. `frontend/README.md`
  now states how to open it (one build + one transport command, or the footer link), what it shows, and
  what it does not: **the viewer does not compute and does not write**. The same pass made the 09 branch
  of the page honest — a `device_flexibility_planner` download renders its device schedule summary
  (critical/flexible energy, peak task demand, charge, earliest-feasible reference) instead of reading
  05/06-only fields, and `frontend/src/ApplicationViews.tsx` was expanded from one minified line into
  readable JSX without changing what any number means.
- **The viewer now has a landing route: one command, one origin.** `frontend/application-views.html` could
  only be opened from the Vite dev server or from disk, and from disk its `/contracts` fetch was a
  cross-origin request — the reason `GET /contracts` still carries `Access-Control-Allow-Origin: *`.
  `python -m islandos_core.transport` now serves `GET /` (the built `frontend/dist/application-views.html`)
  and `GET /assets/<file>` from `frontend/dist/assets` only, resolving each path and refusing anything
  outside the build output. With the viewer same-origin, its schema read needs no allowance at all. Without
  a build, `GET /` returns `404` with `hint: run npm run build in frontend/ first` instead of an empty page.
  `tests/test_application_transport.py` serves a temporary build, checks the HTML and JS content types, checks
  that `assets/../secret.txt` and a missing build both 404, and the real `dist/` from `npm run build` was
  fetched through the route (`/` 200, `assets/application-views-*.js` 200). No new endpoint beyond these two
  reads, no writes, no change to `/contracts` or `/run`.

- **The synthetic window behind 06's annual figure is now a parameter, not the wall clock.** The page
  built its default 168-hour history inside its body from `datetime.now(timezone.utc)`, with PV and wind
  ripple keyed to the row index; the same code at 14:00 UTC projected `7,709.55 USD/year` and at 02:00 UTC
  `5,332.57`, while `186,150 kWh` stayed unchanged. `islandos_core/demo_site_history.py` now holds the
  same numbers verbatim and takes `anchor_utc` as an argument; the page still passes "now", so no visible
  value moves (AppTest at the same hour: `186,150 kWh / 5,281.63 / 0.00 / 0 h` before and after).
  `tests/test_demo_site_history.py` pins the properties: the same anchor reproduces the same window, every
  24-hour block carries `510 kWh` of load, anchors 02 and 14 differ in PV but not in daily load or the
  24-point tariff total, and the builder never reads a clock. This makes the input declarable; it does not
  add a UI control to pin it.

- **The contract now has a standard JSON Schema, not only a description of one.** `docs/contracts/app_view_models.v3.json`
  said what each field carries, but nothing a stock validator could enforce; "a JSON Schema file" had been
  on the not-implemented list since the contract was introduced. `python -m islandos_core.contract_schemas
  --json-schema` now renders `docs/contracts/app_view_models.v3.schema.json` (draft 2020-12) from the same
  field constants: every object is closed, every declared key is required, `schema_version` is pinned to
  `3`, and the per-page shapes are `if`/`then` on `page` — 06 carries the dashboard's three settings keys
  and no `page_inputs`, 09 carries `page_inputs` with its `DeviceTask` array. `jsonschema` was already
  pinned in `requirements-ci.lock`, so `tests/test_contract_json_schema.py` validates a real built request
  and its replay result for 05, 06 and 09, and checks that a stray site key, a 09 request without
  `page_inputs`, a 05 request carrying one, a 06 request missing `availability` and a summary missing
  `summary_sha256` are all rejected. The long-form file is unchanged and still the human-readable one;
  nothing at runtime consults the schema.

- **A replayed request now reproduces the same run, not a look-alike.** `replay_run_request` rebuilt the
  06 manifest with `uuid.uuid4()` and `datetime.now()`, so replaying one saved request twice produced two
  different `run_id`s and two different manifest digests over identical numbers — a citation into "that
  run" pointed nowhere. Replay now passes `deterministic_run_id("run", {"request": request})` and a
  fixed `REPLAY_CREATED_AT_UTC` into `_manifest_from_request`, which took optional `run_id` /
  `created_at_utc` arguments for exactly this. `tests/test_application_transport.py` replays the same
  request twice and asserts the summaries are equal, that the ids match, and that changing one run setting
  changes the id. The pages keep their own uuid + wall-clock manifest, so nothing on screen changes: a
  replay id identifies the request, not the session that produced it.

- **The TypeScript side now compiles against the contract instead of a copy of it.** `frontend/ApplicationViews.tsx`
  declared its own `Field`/`Contract`/`Schema` shapes, so a renamed or retyped field would have compiled
  cleanly and failed only at runtime. `python -m islandos_core.contract_schemas --typescript` now renders
  `frontend/src/contracts.ts` from the same `contract_schema()` dict that produces
  `docs/contracts/app_view_models.v3.json` — one interface per block (`RunRequest`, its `site`, `history`
  and `page_inputs`, `DeviceTask`, `RunResultSummary`, `AnnualProjection` with `basis`, the 09
  `DeviceFlexibilitySummary`, plus `ContractField`/`ContractBody`/`ContractSchema`), each property annotated
  with its `type · unit · owner`. The viewer imports those types, `tsc -b && vite build` passes unchanged
  against them, and `tests/test_contract_typescript.py` fails unless the committed file equals
  `typescript_source()` byte for byte. No UI behaviour, value, unit or algorithm change.

- **The read-only transport now states its own limits.** `POST /run` requires `Content-Type: application/json` (`415` otherwise), refuses a declared body above 1 MB before reading it (`413`), and only `GET /contracts` answers an `OPTIONS` preflight; `OPTIONS /run` and `PUT`/`DELETE`/`PATCH` get `405`. The cross-origin allowance is unchanged and still limited to the schema read: `/run` never carries `Access-Control-Allow-Origin`. No endpoint, payload or replay path changed.

- **The device flexibility planner now publishes the same kind of request the other two pages do.** 09 had no `application_views` because its inputs are not sliders: three `DeviceTask` objects and a 24-hour residual power budget. Rather than widening `page_settings` — which means "numeric knobs" and is read by every consumer — the contract gains a `page_inputs` block (`CONTRACT_VERSION = 3`), `null` on 05 and 06 and carrying `task_power_budget_kw` plus the validated task list on 09. `run_orchestration.run_device_planner` holds the page's own order (schedule → tariff-aware replay → earliest-feasible reference), `replay_run_request` covers 09, and `build_device_flexibility_summary` copies the schedule's critical/flexible energy, charge and peak plus the two replays' grid import, cost, unmet and shed. The page's metrics are unchanged (72 kWh / 17 kWh / 13.77 / 6.0 kW / 103.2 kWh / 15.44 / 0.00 / 0.00), each of those numbers is now asserted in `tests/test_app_view_models.py`, and the transport replay of a real 09 request returns the same values. `docs/contracts/app_view_models.v3.json` is generated from the field constants. No algorithm, objective, default, tariff or annualisation change.

- **A React page now reads the contracts instead of re-deriving them.** The console in `frontend/` had no surface for the application view models, so "the contracts are shared" was a Python-only claim. `frontend/application-views.html` (built as a second Vite entry, `ApplicationViews.tsx`) loads a report downloaded from page 05 or 06, reads its `application_views` block, renders the request (page, hour count, site digest, provenance, request hash), the result summary (policy label, 24-hour cost, unmet load, service equivalence, withheld-claim flag, run id) and, when present, the annual projection's four figures with their declared day count. It can also fetch `GET /contracts` from the local transport and render every field's type, unit, nullability and owner. It performs no forecast, no optimisation, no economics and no writes; the existing console and its login flow are untouched. TypeScript compiles against the JSON the Python side emits, and the customer-frontend workflow builds both entries.

- **A run request can now be replayed outside Streamlit, and the contract says so in machine-readable form.**
  The view model's `history` had no time axis, so a saved request could only be described, not replayed; `run_request` is now `CONTRACT_VERSION = 2` with `history.timestamps_utc` (same length as every series, refused otherwise), and both pages pass their timestamps. `islandos_core/run_orchestration.replay_run_request` rebuilds the site, history, units, page settings and run settings from the request alone, runs the page's own sequence, and returns the result summary (05) or the joint optimizer summary with its canonical run id and decision status (06). `islandos_core/contract_schemas` exports every field's name, type, unit, nullability and owner (site / page / run / contract / data / display / gate / provenance / assumption) to `docs/contracts/app_view_models.v2.json`, checked against the builders' own constants. A read-only transport (`python -m islandos_core.transport`, stdlib only) serves `GET /contracts` and `POST /run` on `127.0.0.1`, refuses malformed or unsupported requests with `400`, and is deliberately outside the Streamlit deployment: no authentication, no persistence, no writes. No algorithm, objective, default or UI change.

- **The pages no longer own the order of their own run.** T4 gave a run a shape; the sequence — forecast → coordination inputs → objective weights → optimize → service-equivalent economics → stress → paired impact, and manifest → dispatch search for the joint optimizer — still sat in the page bodies, so any second front end would have had to reproduce it argument by argument. `islandos_core/run_orchestration.py` now holds `run_customer_dashboard` and `run_joint_optimizer`: same entry points, same keyword arguments, same derived weights (`cost = cost_priority`, `reliability = 1 - cost_priority`), and it returns every intermediate the pages still render. Pages 05 and 06 call it and keep only their widgets. `tests/test_run_orchestration.py` runs each sequence twice — once through the layer, once inline exactly as the page used to spell it — and compares config, history digest, weights, recommended policy, service-equivalence flags, stress policies, paired benefit, run id, manifest/evidence digests, decision status and dispatch summary; a subprocess assertion proves the module imports without Streamlit. No algorithm, objective, constraint, default, unit or layout changed.

- **The three view-model contracts are now published in the pages' own downloads, and pinned.** A contract that only lives in a local variable is not something another client can read, and one whose field names can drift is not a contract. Both pages now write `application_views` into their downloadable JSON (`request` + `result` on 05; `request` + `result` + `annual` on 06, `annual` being `null` until the equal-days assumption is declared), so the file a reader saves carries the same validated shapes the screen rendered. `islandos_core/app_view_models.py` declares `REQUEST_FIELDS`, `RUN_REQUEST_SITE_FIELDS`, `HISTORY_FIELDS`, `RESULT_SUMMARY_FIELDS`, `ANNUAL_PROJECTION_FIELDS` and `ANNUAL_BASIS_FIELDS` once, each builder asserts it emitted exactly those keys, and `tests/test_app_view_models.py` fails on any drift plus on a page that stops publishing the views it renders. No value, unit, algorithm or layout changed.

- **The pages now describe a run in a shape another front end can read.** 05 and 06 held their request, their results and their annual projection as ad-hoc dictionaries inside the page body, so a React/TypeScript front end would have had to re-derive all three. `islandos_core/app_view_models.py` (Streamlit-free, no `st.session_state`, no calculation) adds three versioned contracts: `build_run_request` (the site — all ten `SiteAssumptions` fields plus their digest — the history with units and provenance, the page-specific settings and the run-specific settings, each page's key set validated instead of merged), `build_run_result_summary` (recommended policy and its modelled 24-hour cost/unmet load with the service-equivalence gate on 05; run id, manifest/evidence digests, decision status and physical-audit verdict on 06, where `scenarios_audited` stays the adapter's list of scenario names), and `build_annual_projection` (the six figures plus basis, per-figure definitions and scope, refused outright when `verify_annual_operating_basis` rejects the record). The dashboard summary still carries no run id, so 05 and 06 over one CSV remain visibly two runs. Pages 05 and 06 read their metrics and annual figures from these views; no default, unit, algorithm, objective, constraint or layout changed, and `tests/test_app_view_models.py` (13 cases) proves the module imports no Streamlit in a subprocess, refuses missing/invalid fields instead of defaulting them, and keeps the synthetic provenance label. `APP_INTEGRATION.md` §4 documents the three contracts field by field, with site-level / page-specific / run-specific ownership, and states what is still Streamlit-only and what is still not implemented. No transport, no TypeScript package, no JSON Schema file.

- **One place now decides what "the site" means.** Pages 05, 06 and 09 each assembled their own `EnergySystemConfig` from their own sidebar values, so two pages describing the same site could hold different assumptions with nothing to notice. `islandos_core/site_inputs.py` is now the single construction point: `SiteAssumptions` carries exactly the ten site-level fields (PV kW, wind kW, grid import limit, battery capacity/power/initial/min/max SOC, diesel rating and variable cost), refuses to default any of them, rejects negative/NaN/bool/string inputs and impossible SOC bounds, and `to_energy_system_config()` is the only function that builds a config. The dashboard and the joint optimizer now pass `DEFAULT_SITE` (40 kW PV / 20 kW wind / 100 kW grid / 80 kWh 20 kW battery / SOC 0.60–0.10–0.95, plus diesel 30 kW at 0.32 in the optimizer), the planner passes `DEVICE_PLANNER_DEMO_SITE` (12 / 4.5 / 20 / 12 kWh 4 kW / diesel 5 kW at 0.35) — a different, deliberately smaller demo site, declared rather than merged into the big one. Page-specific settings (objective weights, load/tariff scalars, search population/generations/seed, device tasks and prices) and run-specific settings (investment life, discount rate, escalation, availability flags) stayed on their pages; no default value, unit or type moved, which `tests/test_site_inputs.py` (51 cases) pins field by field, including a comparison of the new construction against the exact literal config each page built before the refactor. `APP_INTEGRATION.md` §5 closes the "site assumptions assembled three times" break.


- **Wrote down how the界面 layer calls the core, and narrowed one now-false sentence.** `APP_INTEGRATION.md` adds the application/integration contract: a layer map (pages → Streamlit surfaces → one Streamlit-free helper → core), a page-by-page inventory of which core entry point each surface calls with which inputs, the page-file/route table, the single payload that crosses pages (`islandos_session_site_dataset`), the page-private session keys, and a boundary section for a future React/TypeScript front end that states plainly that no transport exists. It also records the fact most easily misread: 05 and 06 over the same CSV are **two runs** (`run-dashboard-…` minted by `deterministic_run_id` vs the planning run's id from `run_forecast_dispatch`), so two different `manifest_sha256` values are expected rather than a disagreement. In the same change, the 05-page annualisation line stops claiming "a simulated day is never multiplied into a year" — false since page 06 gained its declared-assumption projection — and now says "this screen never turns a simulated day into the bills it screens", pointing at §6.5 for the separate object. New `tests/test_app_integration_doc.py` fails if a named entry point disappears, if the shared session key changes, if the "two runs" statement is dropped, if a page is left out of the inventory, or if the document starts promising a transport that does not exist.

- **The joint optimizer page can now project its own simulated day onto a year — and says what that is.** The dashboard's investment screen takes customer-entered annual bills; the joint optimizer produced only a 24-hour run, so a reader had no annual figure at all and any "× 365" would have been a silent guess. `islandos_core/annual_operating_basis.py` adds `annualise_run_summary`, which scales eight run figures by a **declared** `days_equivalent_per_year` (integer 1–366) and derives diesel run hours by counting dispatch rows with positive `diesel_generation_kw`; the record carries `equal_day_assumption`, `simulated_hours`, `hours_equivalent_per_year`, `derived_from_run: true`, `site_validated: false`, `measured: false`, `bill: false`, the six figure definitions, and a `summary_source`. Page 06 grows an "Annual operating basis" section behind a checkbox plus a day-count slider, so nothing is annualised unless the reader states the assumption; it projects the recommended schedule's **own nominal dispatch summary** — the same run behind the hourly setpoint rows — and says in the caption that annualising the base day does not annualise the worst-case scenario. `annual_equipment_operating_cost` (fuel, battery throughput, diesel start/stop) is labelled a breakdown of `annual_energy_cost`, never an addition. `verify_annual_operating_basis` fails closed on a digest mismatch, a claimed bill, a claimed site validation, a missing `summary_source`, or an out-of-range day count. `INTEGRATION.md` §6.5 is replaced by the projection contract plus a six-figure definitions table that also states CAPEX is an investment assumption and never a projection of a run; gap 6 is closed down to "the projection is never used to fill or check the customer's bills". New `tests/test_annual_operating_basis.py` (18 cases) covers the scaling, the assumption being the only thing that moves a figure, the breakdown-not-addition rule, committed-hours-only, refused assumptions, tamper detection, the page's render order, and that the page projects the dispatch it already drew; `tests/test_integration_doc.py` now guards the conditional contract instead of the old absence.

- **Wrote down what each annual figure means and who may supply it.** "Annual energy cost" can mean the utility bill, the run's day cost multiplied by 365, or a market-average tariff, and the screen silently assumed one of them. `INTEGRATION.md` §6.4 is now a data dictionary for all eleven inputs — unit, range as `evaluate_investment_economics` actually validates it, what it means on this screen, the legitimate supplier, and what it must never be (the run's day cost annualised, the energy saving double-counted inside O&M, a hand-set `service_equivalent`). §6.5 and gap 6 record the remaining hole: nothing converts the run's 24-hour cost into an annual bill, and that bridge needs an annualisation contract (which hours, which tariff year, which service scope) before any number crosses from the day to the year. Adds three checks to `tests/test_integration_doc.py`, which now fails if the dictionary drops an input, its validated range, the "must never be" column, or the unbridged gap.

- **A first-time visitor now sees a complete investment screen instead of an empty one.** Prefilling was the missing half of the last change: after the withheld gate, the dashboard opened on advice to type bills into blank fields, so a stranger had to understand the product before it showed anything. The investment assumptions now default to a demonstration set (baseline bill 120,000 / proposed 84,000 / incremental O&M 6,000 / CAPEX 180,000 → NPV ≈ +21,302, payback ≈ 6.0 years, screen positive at the page's 10-year, 8% defaults), labelled in three places — the banner opens with "Illustrative screening results … synthetic demonstration figures, not a customer quote … or a site-validated return", the facts line names them as synthetic, and the binding records `annual_basis.source: synthetic_demonstration_figures`. Any edited value returns to `customer_entered_annual_bills`, and zeroing the bill and CAPEX still reaches the withheld branch, so the blank and real-project paths survive. Adds four cases to `tests/test_annual_economics_panel.py`; states the rule in `INTEGRATION.md` §6.2.

- **An unfilled customer dashboard no longer reports a verdict.** The sidebar's two annual bills and the CAPEX field default to zero, and the page screened those placeholders anyway: a first-time reader saw "Net present value 0 USD", "Payback not achieved" and "Screen result: Negative" — a conclusion about numbers nobody entered. The investment section now asks `annual_inputs_supplied(baseline_annual_bill, proposed_annual_bill, upfront_capex)` first; when the baseline bill and the CAPEX quote are missing it states that the screen is withheld, records `status: withheld_inputs_not_entered` with the inputs exactly as entered, and binds nothing to a run (the run citation, metrics and cashflow table appear together once real figures exist). A zero *proposed* bill stays valid, since an off-grid site can legitimately claim one. Adds seven cases to `tests/test_annual_economics_panel.py`; states the rule in `INTEGRATION.md` §6.2.

- **Customer dashboard: the annual figures now cite a run instead of floating free.** `pages/05_Customer_Decision_Dashboard.py` builds a canonical run manifest from the same dataset and site configuration the screen was computed on (deterministic `run_id` through `canonical_run.deterministic_run_id`), binds `evaluate_investment_economics` to it with `bind_annual_economics_to_run`, verifies the binding, and renders the basis — "bills entered by the customer, not derived from this run", plus the withheld line — above the first investment metric. A binding that does not verify stops the page instead of falling back to bare numbers. The citation also travels in the downloadable decision report as `investment_economics_binding`. New `islandos_ui/annual_economics_panel.py` holds that reading order in one place, and `tests/test_annual_economics_panel.py` fails if the basis ever slips below the first metric on the page.

- Froze the public URL of every menu page. Streamlit derives a page's slug from its file name, so the navigation consolidation silently killed the older `/06_Forecast_…`-style links — a reader got "Page not found / Running the app's main page" — and any future file rename would have moved a working link again. `st.Page` now declares `url_path` for all six pages through `islandos_ui/navigation.page_url_path`, and the value is exactly the slug the hosted app already serves, so nothing changes today while later renames can no longer break a bookmark. A contract test fails if a registered page stops declaring its slug.

- Gave the annual investment figures a way to say what they are. `evaluate_investment_economics` takes customer-entered annual bills, so nothing tied them to the run whose equipment and service they describe, and a reader could only assume. `bind_annual_economics_to_run(economics, manifest, …)` now emits a citation record carrying `run_id`, `site_ref`, `manifest_sha256`, `dataset_sha256`, the evaluation, and an `annual_basis` block with `derived_from_run: false` (a simulated day is never annualised into a year); `verify_investment_economics_binding` fails a record whose digest does not match, that claims a device write or command, that marks the bills as derived, or that hides a blocked result. Adds four cases to `tests/test_investment_economics.py`; closes gap 3 in `INTEGRATION.md`.

- Made two silent assumptions in the forecast handoff explicit. `generic_prediction_handoff.target_timestamps_utc` used to be copied from the PV forecast, i.e. the handoff assumed every signal shared that clock and would have crashed on an unmapped signal key; it now reads the clock from the validated dispatch bundle, which already refuses a signal whose target timestamps differ. The water extension also used to overwrite `essential_load` in place with no way to tell what the number contained; `water_service` now states `essential_load_includes_ro_power: true` and keeps the pre-RO series (`site_only_essential_load_kw`) with its digest (`site_only_electrical_load_history_sha256`), so a consumer subtracts exactly instead of guessing. Adapter results are unchanged for every existing key. Adds one case to `tests/test_prediction_dispatch_optimizer.py` and one to `tests/test_stage_d_water_coordination.py`; closes gaps 4 and 5 in `INTEGRATION.md`.

- Put the operator decision record on screen before any number. The joint-schedule page used to jump straight from the run caption to a "Selected policy" metric, so a schedule that failed its physical audit looked exactly like one that passed. `islandos_ui/decision_record_panel.py` now renders the gate first: a success/error banner for the record status, one sentence stating that the audit is a simulator replay rather than site validation or a safety certification, and a line carrying `human review = required`, `device write = not authorized` and the first eight characters of `record_sha256`. A run without a record is rejected instead of rendered. The record is also included in the downloadable audit JSON. Adds `tests/test_decision_record_panel.py`, which also fails if the gate ever slips below the first metric on the page.

- Folded the operator decision record into the canonical run. A "canonical planning run" used to return `recommendation`, `robust_customer_economics` and `decision_scope`, but not the auditable record, and the joint optimizer emitted no `physical_audit` for the record builder to gate on — so the caller had to compose the decision stage itself, and nothing proved it matched the run's evidence. The shape follows OpenLineage (run as envelope, facets attached to it): `forecast_optimizer_adapter` now derives a run-level `physical_audit` from the recommended schedule's per-scenario `audit_passed` flags (a replay of the same evidence, explicitly scoped as a simulator audit rather than site validation or a safety certification), and `run_forecast_dispatch` assembles the record from the manifest (`site_ref`, `created_at_utc`, provenance, the `manifest_sha256`/forecast `bundle_sha256`/`dataset_sha256` input refs) plus the recommendation's own objective weights, then verifies it and raises if it does not verify. The record stays read-only (`device_write_authorized: false`, `command_generated: false`, `human_review_required: true`, `operator_approval: pending`). Adds a case to `tests/test_planning_workflow.py`; closes gap 2 in `INTEGRATION.md`.

- Made `run_forecast_dispatch` enforce the forecast layer's hourly clock rule before any model runs. It previously accepted three timestamps and left the ≥72 contiguous tz-aware check to the forecast stage, so a five-row history failed one call later with a less specific message. The rule now lives in one public function (`forecast_signal_catalog.validate_hourly_timestamps`) called by both layers, and the composition layer reports `forecast history clock is invalid: …`. Adds three failure cases and a message check to `tests/test_planning_workflow.py`; closes gap 1 in `INTEGRATION.md`.

- Added `INTEGRATION.md`, the field-level contract between prediction, optimization, economics and decision: the run manifest's required fields, forecast inputs and outputs (units, contiguous hourly UTC timestamps, band semantics), the exact optimizer result keys the later stages consume, the two separate economics contracts (service-gated operating comparison and annual investment metrics), the operator decision record's fields and audit gates, and the digest chain that links them. It also records five gaps the code still has — a weaker timestamp check in the composition layer than in the forecast layer, no decision record inside the canonical run, unbound annual economics, the water load folded into `essential_load`, and the PV-timestamp assumption in the handoff. Add `tests/test_integration_doc.py` so the document cannot silently drift away from the entry points it names.

- Made the forecast lab demonstrable without a file. It previously required an uploaded CSV, so a first-time visitor saw an empty page; it now defaults to a built-in 168-hour synthetic history (`islandos_core/demo_datasets.py`) rendered under an explicit "Demo Data" banner, with the demo's provenance fixed to `synthetic` and the uploaded-CSV path unchanged. Fixing this surfaced two importer defects: a `_kwh` header suffix raised an unhandled `KeyError` (unknown suffixes now fall through to the unit-mismatch check instead of crashing), and `essential_load_kw` was not recognised as a load column, which left the demo marked `needs_review` with an unrecognized-column warning. Adds `tests/test_forecast_lab_demo.py`.

- Made rejected uploads explain themselves. Every CSV upload path (customer site history, rolling-horizon scenario, price-aware scenario, historical tariff prices) now reports a rejection through one shared panel in `islandos_ui/upload_guard.py`: what happened ("rejected - nothing was processed"), what the parser objected to, and how to fix the file (missing columns, timestamp format, unit suffixes, negative values, too few rows). Previously each handler printed the raw exception, which told users the parser failed but not what to change. Validation itself is unchanged, and every handler still stops instead of continuing on partial data. Adds `tests/test_upload_guard.py`.

- Added a four-line header to every entry page (`islandos_ui/page_header.py`, rendered at the top of the workspace and the four `pages/` views): what the page answers, where its data comes from, what a reader may conclude, and what it cannot tell them. Each header is three to five sentences and states the synthetic-or-uploaded status of its inputs. Adds `tests/test_page_headers.py`, which fails if an entry page renders no header, omits one of the four lines, or leaves placeholder text.

- Consolidated the Streamlit navigation into one menu. `app.py` is now a shell that owns `st.set_page_config` and a single `st.navigation` menu (Decision workspace / Customer views / Experimental / Local deployment only); the eight analysis sections moved unchanged into `islandos_ui/workspace.py` and keep their in-page sub-navigation. Previously Streamlit's automatic `pages/` list and the app's own sidebar radio rendered as two competing menus with 14 destinations, and page labels were file names. The local-only customer and site workspaces are registered only when `ISLANDOS_ENABLE_LOCAL_WORKSPACE=1` or `ISLANDOS_API_BASE_URL` is set, so the hosted demo no longer offers two dead ends. Adds `tests/test_navigation_contract.py` (one menu, every page file registered, local pages gated, workspace is the default) and extends the UI smoke tests to drive the real entrypoint.
- Fixed a SQLite handle leak in the Stage E reference service. `IslandOSStore` opened connections with `with self.connect() as db:`, but a `sqlite3.Connection` used as a context manager only commits or rolls back — it never closes. Every statement therefore kept the database file open until garbage collection, which is invisible on POSIX (open files can be unlinked) and fatal on Windows: `TemporaryDirectory.cleanup()` raised `WinError 32`, 10 tests failed, and a long-running local service accumulated open handles. All call sites now go through `session()`, which commits and closes; the Stage E tests that write directly to the store database close their raw connections explicitly. Local Windows `pytest` is now green (1150 passed, 2 skipped).
- Added `tests/test_ui_smoke_all_pages.py`, which renders each of the eight `app.py` sections plus the customer-facing pages and fails on any Streamlit exception; previously only two surfaces had render coverage.
- Simulation and optimization work package (all results synthetic): the joint MILP gains a terminal tank level, an RO minimum production rate, one aggregate flexible load, a tariff-look-ahead rule baseline, grid-before-diesel ordering and an exact "curtail only when the battery cannot take more" rule so that every solution replays through the shared simulator. The evolutionary search now accepts diesel ramp-down and minimum up/down times through candidate repair and has an optional warm start. Added `islandos_core/stress_dispatch.py` (forecast stress scenarios and water-shortage events connected to the optimizer), a forecast-based RO rule and RO minimum run time in the impact scenario, and three experiment runners (`run_optimizer_impact.py`, `run_optimizer_benchmark.py`, `run_stress_tests.py`) with results under `results/`. See `docs/SIMULATION_OPTIMIZATION_RESULTS.md`.

- Added an integrated deterministic microgrid energy–water model covering PV, wind, essential demand, battery SOC, grid imports, diesel backup, renewable-only scheduled RO consumption, curtailment, water production, tank inventory, and explicit unmet-service metrics. Added regression tests for energy/water conservation and operating limits.
- Added a seeded synthetic benchmark CLI that compares no-RO and renewable-only RO policies on paired inputs and exports provenance-labelled JSON and hourly CSV evidence.
- Added a generic product/system blueprint mapping the four-step INPUT/PREDICT/OPTIMIZE/DECIDE workflow to current modules, distinguishing implemented foundations from planned integration, and defining evidence-based V1–V5 exit gates.
- Refocused the README on IslandOS as a generic predictive multi-resource decision platform; Nan’ao is described only as an experimental pilot scenario.
- Merged the first implementation slice of engineering stages 1–10: core/data/prediction/optimization/economics foundations, React customer console, tenant membership workflows, local deployment CLI, persistent read-only Shadow Mode evidence ledger, and fail-closed safety review gate. See `docs/ENGINEERING_STAGES_1_10_CLOSEOUT.md` for PR links, current main CI evidence and explicit remaining product/site gates.

- Added a dependency-free forecast plug-in contract with strict hourly timestamp and numeric-value validation.
- Added a rolling-origin backtest harness for trusted third-party forecast plugins and a dispatch-compatible JSON report.
- Added an optional PyTorch LSTM experiment and multi-series comparison against gradient boosting and seasonal baselines.
- Added pinned Docker runtime dependencies and release-candidate verification with test, dependency-audit, container-smoke, checksum, and provenance-manifest steps.
- Kept live plant control, automatic model promotion, and site-readiness certification out of scope.

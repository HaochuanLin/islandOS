# APP_INTEGRATION: how IslandOS's界面层 calls the core

This document is the application-and-integration contract: which module each page calls, what it hands
over, what it gets back, which state crosses between pages, and where the line sits between
"framework-agnostic application layer" and "Streamlit-only rendering". It describes the code as it stands
today. Anything not yet true is listed in [§5](#5-known-breaks) instead of being promised.

Scope: offline planning only. No page in this repository writes to a device, and no page holds a
long-lived server-side store. The public demo runs entirely inside one browser session.

---

## 1. Layer map

| Layer | Modules | Depends on Streamlit? |
|---|---|---|
| Pages (composition) | `app.py`, `pages/*.py` | Yes |
| Streamlit surfaces | `islandos_ui/workspace.py`, `annual_economics_panel.py`, `decision_record_panel.py`, `page_header.py`, `upload_guard.py`, `customer_workflow.py` | Yes |
| Streamlit-free UI helper | `islandos_ui/navigation.py` (`page_url_path`) | No |
| Application-facing view models | `islandos_core/app_view_models.py` | No |
| Run orchestration | `islandos_core/run_orchestration.py` | No |
| Application/core | `islandos_core/*`, `optimization/*`, `experiments/*` | No |

Site assumptions have exactly one construction point: `islandos_core/site_inputs.py`.
`SiteAssumptions` holds the ten fields that describe a site's physical conditions, refuses to
default any of them, and `to_energy_system_config()` is the only function allowed to assemble an
`EnergySystemConfig`. Pages collect inputs and call it; they no longer build configs themselves.
`DEFAULT_SITE` is the dashboard/joint-optimizer site; `DEVICE_PLANNER_DEMO_SITE` is the planner's
deliberately smaller demo site — a different site, declared rather than merged.

The rule this table encodes: **a page may render, but it may not compute**. Every number a page shows has
to arrive from a function in the bottom row. `islandos_ui/navigation.py` is the only file under
`islandos_ui` that is already usable by a non-Streamlit front end.

---

## 2. Page → core call inventory

| Page | Entry point it calls | Inputs it builds | What it gets back |
|---|---|---|---|
| `/` workspace (`app.py` → `islandos_ui/workspace.py`) | `islandos_core.app_workflow.run_uploaded_strategy_comparison` | uploaded CSV bytes + `experiments.compare_energy_water_strategies.Config` | `(steps, detail, summary)` policies table |
| Decision dashboard (05) | `forecast_engine.forecast_signals` → `forecast_optimizer_adapter.build_coordination_inputs` → `optimization.energy_system_optimizer.optimize_energy_system` → `build_service_equivalent_economics` → `evaluate_forecast_stress_scenarios` → `impact_assessment.assess_energy_policy_impact` | site `EnergySystemConfig`, `Weights`, hourly history, tariff/currency label | forecast bundle, optimizer result, service-equivalent economics, stress rows, paired impact |
| Decision dashboard (05), investment section | `investment_economics.evaluate_investment_economics` → `bind_annual_economics_to_run` | entered annual bills, O&M, CAPEX, life, discount rate, escalations | `InvestmentEconomics` + binding record with `run-dashboard` id |
| Decision dashboard (05), operator record | `operator_decision.build_operator_decision_record` | optimizer result, site ref, recommendation id, weights, constraints | `offline_operator_decision_record` |
| Joint resource optimizer (06) | `planning_workflow.run_forecast_dispatch` | `create_run_manifest` manifest, tz-aware history, units, config, grid/diesel availability | forecast bundle, optimizer result, `decision_record`, `evidence_sha256` |
| Joint resource optimizer (06), annual section | `annual_operating_basis.annualise_run_summary` → `verify_annual_operating_basis` | `recommendation["dispatch"]["summary"]`, dispatch rows, declared day count | `annual_operating_basis_projection` |
| Device flexibility planner (09) | `flexible_tasks.schedule_device_tasks` → `flexible_task_dispatch.attach_device_task_schedule` → `energy_system.dispatch_energy_system` | `DeviceTask` list, 24-hour price series, task power budget, energy inputs | device schedule, integrated inputs, replay dispatch |
| Rolling horizon lab (2) | `experiments.rolling_horizon_dispatch` | uploaded/derived history, rolling window settings | replayed result cached for the current signature |
| Site workspace (08) | `site_workspace.*`, `workspace_store.*`, `assets.evaluate_asset_readiness` | local workspace directory, `AssetRecord` | readiness report |

Every function named above is importable without Streamlit; `tests/test_app_integration_doc.py` fails if
one of them disappears from the repository. Every page that describes a site also goes through
`islandos_core/site_inputs.py::SiteAssumptions.to_energy_system_config` before any core calculation, so
the site half of each call's inputs has one origin.

### 2.1 Page files and their routes

| File | Route | Section in this document |
|---|---|---|
| `islandos_ui/workspace.py` (registered by `app.py` as the default page) | `/` | §2 row 1 |
| `pages/05_Customer_Decision_Dashboard.py` | `/Customer_Decision_Dashboard` | §2 rows 2–4 |
| `pages/06_Forecast_Led_Joint_Resource_Optimizer.py` | `/Forecast_Led_Joint_Resource_Optimizer` | §2 rows 5–6 |
| `pages/09_Device_Flexibility_Planner.py` | `/Device_Flexibility_Planner` | §2 row 7 |
| `pages/2_Rolling_Horizon_Lab.py` | `/Rolling_Horizon_Lab` | §2 row 8 |
| `pages/07_Local_Customer_Workspace.py` | local deployment only | §3 (sign-in state) |
| `pages/08_Site_Workspace.py` | `/Site_Workspace` (local deployment only) | §2 row 9 |

Slugs are declared through `islandos_ui/navigation.page_url_path`, not derived from file names, so a
rename keeps the link alive. `pages/07` and `pages/08` are registered only when the local deployment is
configured (`ISLANDOS_API_BASE_URL` or `ISLANDOS_ENABLE_LOCAL_WORKSPACE=1`).

---

## 3. State that crosses pages

Exactly one payload is shared today:

- `islandos_core.session_dataset.SESSION_DATASET_KEY` = `"islandos_session_site_dataset"`. Stores the
  uploaded CSV bytes plus `sha256`, `source_type`, `file_name` and `session_only: true`. It lives in
  `st.session_state` and dies with the browser session. 05 and 06 both read it through
  `get_session_dataset(...)` and both clear it through `clear_session_dataset(...)` after consuming it.

Everything else is page-private:

| Key | Writer | Meaning |
|---|---|---|
| `islandos_result` | `islandos_ui.workspace` | last strategy comparison of the workspace page |
| `islandos_customer_history_context` | `islandos_ui.customer_workflow` | last history SHA-256 and provenance seen on each customer page; used only to warn that 05 and 06 are not like-for-like, never as a run result |
| `islandos_optimizer_result` | `islandos_ui.workspace` | last optimizer result of the workspace page |
| `rolling_lab_signature` / `rolling_lab_results` | `pages/2_Rolling_Horizon_Lab.py` | cache keyed by the current input signature |
| `islandos_access_token` / `islandos_role` / `islandos_tenant_id` | `pages/07_Local_Customer_Workspace.py` | local deployment sign-in state |
| widget keys (`annual_projection_joint_optimizer`, `annual_days_joint_optimizer`, …) | the page that renders them | per-widget UI state |

**Two pages do not share a run.** 05 mints `run-dashboard-…` through
`canonical_run.deterministic_run_id("run-dashboard", payload)` over its own dataset/config/policy digests;
06 gets its run id from `create_run_manifest` and `run_forecast_dispatch`. The same CSV therefore yields
two different `run_id`s and two different `manifest_sha256` values on the two pages, by design: they are
two separate offline runs over the same history, not one run shown twice. A reader who sees both must not
conclude that the pages disagree — they were never the same run.

The customer pages now record a presentation-only snapshot of each view's last history SHA-256 and
provenance in `islandos_customer_history_context`. On the next visit, `islandos_ui.customer_workflow`
compares the two snapshots and warns when they differ. It does not merge results, create a shared
run id, or claim that matching input makes the two pages' cost figures interchangeable. The same
helper also offers a page-local CSV the existing `store_session_dataset` handoff, so an upload on
05 or 06 can be reused by the other view without returning to Data onboarding.

---

## 4. The application-facing view models

`islandos_core/app_view_models.py` is the boundary a second front end reads instead of re-deriving
what a page already knows. It imports no Streamlit, touches no `st.session_state`, calls no page
function, and holds no global state; it neither calculates nor optimises — it reads objects the core
already produced, validates them, and returns plain JSON-able dictionaries with stated units,
nullability and provenance. `tests/test_app_view_models.py` proves the imports are Streamlit-free in a
subprocess (`'streamlit' not in sys.modules`) and pins every field below.

Four contracts, `CONTRACT_VERSION = 3`:

| Builder | Answers | Refuses |
|---|---|---|
| `build_run_request(page=…, site=…, timestamps=…, history=…, units=…, page_settings=…, page_inputs=…, run_settings=…, provenance=…, source_sha256=…)` | what this page asked the core to run | an unknown page, a page/run setting key outside that page's declared set, structured inputs on a page that has none, a signal without a unit, series of unequal length, non-numeric or empty series |
| `build_run_result_summary(page=…, result=…, economics=…, planning_run=…, currency=…)` | what the run produced, limited to what the pages display | a dashboard summary without service-equivalent economics or without `grid_first` / the recommended policy in `candidates`; an optimizer summary without a planning run, `run_id`, `manifest_sha256` or `evidence_sha256` |
| `build_device_flexibility_summary(result=…, metrics=…, reference_metrics=…, currency=…)` | 09's schedule and its two replays | a schedule dict without `schedules` / `critical_power_kw` / `total_power_kw`, or metrics missing the five copied figures |
| `build_annual_projection(record, currency=…)` | the declared-assumption annual projection | a record that `verify_annual_operating_basis` rejects (digest mismatch, claimed bill, claimed site validation, missing `summary_source`), or one missing `figures` / `basis` |

`to_json(view)` serialises any of them with `sort_keys=True, allow_nan=False`.

### 4.1 `run_request`

| Field | Type | Unit | Required | Nullable | Source | Ownership |
|---|---|---|---|---|---|---|
| `schema_version` | int | – | yes | no | `CONTRACT_VERSION` | contract |
| `request_type` | str | – | yes | no | constant `islandos_run_request` | contract |
| `page` | str, `customer_dashboard` \| `joint_resource_optimizer` \| `device_flexibility_planner` | – | yes | no | page | page discriminator |
| `site` | dict | kW, kWh, currency/kWh, SOC as fraction | yes | no | `SiteAssumptions.describe()` + `digest()` | **site-level** (single source: `site_inputs`) |
| `history.signals` | dict[str, list[float]] | kW per canonical signal | yes | no | the page's forecast input | data, not assumption |
| `history.units` | dict[str, str] | unit string per signal | yes | no | page | data |
| `history.hour_count` | int | hours | yes | no | derived from the series | data |
| `history.provenance` | str | – | yes | no | page (`Uploaded CSV` / `Demonstration data`) | data provenance |
| `history.source_sha256` | str, hex | – | yes | yes (`null` when nothing was uploaded) | page | data provenance |
| `page_settings` | dict | per page | yes (`{}` allowed) | no | page | **page-specific** |
| `page_inputs` | dict \| null | `task_power_budget_kw` (kW per hour) + `tasks` (objects) | yes / `null` on 05 and 06 | yes | page | **page-specific, structured** |
| `run_settings` | dict | per page | yes | no | page | **run-specific** |
| `request_sha256` | str, hex | – | yes | no | SHA-256 of the payload above | contract |

The site block carries all ten `SiteAssumptions` fields — `pv_rated_kw`, `wind_rated_kw`,
`grid_import_limit_kw`, `battery_capacity_kwh`, `battery_power_kw`, `battery_initial_soc`,
`battery_min_soc`, `battery_max_soc`, `diesel_rated_kw`, `diesel_variable_cost_per_kwh` — plus `digest`,
so a reader who only has the request still knows exactly which site it describes.

Page-specific and run-specific blocks, per page:

| Page | `page_settings` | `run_settings` |
|---|---|---|
| `customer_dashboard` (05) | `demand_scale`, `tariff_scale`, `cost_priority` (float, dimensionless) | `currency` (str); `investment` = `baseline_annual_energy_cost`, `proposed_annual_energy_cost`, `annual_incremental_om_cost`, `upfront_capex` (currency/year, currency, currency/year, currency), `project_life_years` (years, int), `discount_rate`, `annual_energy_saving_escalation_rate`, `annual_om_escalation_rate` (fraction/year) |
| `joint_resource_optimizer` (06) | none (empty mapping, refused if it carries anything) | `currency` (str); `optimizer_settings` = `population_size`, `generations`, `seed` (int); `availability` = `grid_all_hours`, `diesel_all_hours` (bool) |
| `device_flexibility_planner` (09) | none (its inputs are tasks, not knobs) | `currency` (str) |

09 is the one page whose inputs are objects rather than numbers: three `DeviceTask` records (class, rated
power, required energy, operating window, critical profile) and a 24-hour residual power budget. Those live
in `page_inputs` — `task_power_budget_kw` plus `tasks[{task_id, name, load_class, rated_power_kw,
required_energy_kwh, earliest_start_step, latest_finish_step, min_power_kw, minimum_run_steps,
interruptible, priority, availability, critical_power_profile_kw}]` — while `page_settings` keeps meaning
"numeric knobs" and stays empty. `page_inputs` is `null`, not `{}`, on 05 and 06, and a page that has no
structured inputs refuses one rather than dropping it.

### 4.2 `run_result_summary`

| Field | Type | Unit | Required | Nullable | Source | Ownership |
|---|---|---|---|---|---|---|
| `schema_version`, `record_type`, `page` | int, str, str | – | yes | no | contract | contract |
| `recommended_policy` | str \| null | – | yes | yes (06 only) | `result["recommendation"]["policy"]` | run |
| `recommended_policy_label` | str | – | yes | no | policy with underscores replaced; `Optimizer Recommendation` on 06 when no policy is named | display |
| `estimated_24h_energy_cost` | float \| null | currency/24 h | yes | yes (06) | selected candidate's `summary["estimated_energy_cost"]` | run (05 only) |
| `unmet_load_kwh` | float \| null | kWh/24 h | yes | yes (06) | selected candidate's `summary["unmet_load_kwh"]` | run (05 only) |
| `grid_first_estimated_24h_energy_cost` | float \| null | currency/24 h | yes | yes (06) | `grid_first` candidate's summary | run (05 only) |
| `service_equivalent` | bool \| null | – | yes | yes (06) | `economics["service_equivalent"]` / `result["robust_customer_economics"]` | run |
| `cost_comparison_valid` | bool \| null | – | yes | yes (06) | same | run |
| `cost_reduction_vs_grid_first` | float \| null | currency/24 h | yes | yes | `estimated_cost_reduction` | run |
| `savings_claim_withheld` | bool | – | yes | no | `not (service_equivalent and cost_comparison_valid)` (05) / `not cost_comparison_valid` (06) | gate |
| `candidate_policies` | list[str] | – | yes | no (empty on 06) | `result["candidates"]` | run (05 only) |
| `run_id`, `manifest_sha256`, `evidence_sha256` | str \| null | – | yes | yes (null on 05) | `planning_run` | run (06 only) |
| `decision_record_status` | str \| null | – | yes | yes | `planning_run["decision_record"]["status"]` | run (06 only) |
| `physical_audit_passed` | bool \| null | – | yes | yes | `decision_record["physical_audit"]["passed"]` | run (06 only) |
| `scenarios_audited` | list[str] \| null | – | yes | yes | `physical_audit["scenarios_audited"]` (scenario **names**, sorted by the adapter) | run (06 only) |
| `currency` | str \| null | – | yes | yes | page | display |
| `summary_sha256` | str, hex | – | yes | no | SHA-256 of the payload | contract |

The dashboard variant carries no run id at all, on purpose: the optimization run it displays is not the
run its investment screen later cites. The optimizer variant carries that run's digests, so the two
pages' summaries can never be mistaken for one run (§3).

### 4.3 `annual_projection`

| Field | Type | Unit | Required | Nullable | Source | Ownership |
|---|---|---|---|---|---|---|
| `schema_version`, `record_type` | int, str | – | yes | no | contract | contract |
| `run_id`, `manifest_sha256` | str, str | – | yes | no | the annualisation record | run |
| `data_provenance`, `summary_source` | str, str | – | yes | no | the record (`summary_source` names which dispatch summary was annualised) | provenance |
| `currency` | str \| null | – | yes | yes | page | display |
| `basis.days_equivalent_per_year`, `basis.hours_equivalent_per_year` | int, int | days, hours | yes | no | the record's declared assumption | **run-specific** assumption |
| `basis.equal_day_assumption` | str | – | yes | no | the record's sentence | assumption |
| `basis.derived_from_run`, `site_validated`, `measured`, `bill` | bool | – | yes | no | the record (`false` except `derived_from_run`) | provenance |
| `figures` | dict[str, float] | kWh, currency, hours | yes | no | `INTEGRATION.md` §6.5 six figures | run |
| `components_inside_annual_energy_cost` | dict[str, float] | currency | yes (may be empty) | no | the record's breakdown | run |
| `definitions` | dict[str, {unit, meaning}] | – | yes | no | the record's six definitions | contract |
| `scope` | str | – | yes | no | the record's scope sentence | contract |
| `projection_sha256` | str, hex | – | yes | no | the record's `annualisation_sha256` | contract |

### 4.4 How each page uses them, and what a React client would consume

Page 05 builds its request once, right after `site_assumptions.to_energy_system_config()` and before the
optimizer call, then reads `recommended_policy_label`, `estimated_24h_energy_cost`, `unmet_load_kwh`,
`grid_first_estimated_24h_energy_cost` and `savings_claim_withheld` from the summary instead of indexing
candidate dictionaries inline. Page 06 builds its request after the availability flags, reads
`recommended_policy_label` from the summary, and reads the annual figures, basis and digests from the
projection (which verifies the record before returning it).

Page 09 builds its request from the same task objects it schedules, hands it to
`run_device_planner` (schedule → tariff-aware replay → earliest-feasible reference), and renders
`build_device_flexibility_summary`, which copies — never recomputes — the schedule's critical energy,
flexible energy, charge and peak, plus the two replays' grid import, cost, critical unmet and shed.

A non-Streamlit client would keep its own site inputs, render the same widgets, call `build_run_request`,
hand the resulting document to `islandos_core/run_orchestration.py` (`run_customer_dashboard` /
`run_joint_optimizer`), and render `build_run_result_summary` / `build_annual_projection` — the same
validation, the same field names, the same units, and the same call order, without re-implementing any
of it. What it would still have to supply itself is listed in §4.5.

### 4.5 Still Streamlit-only, and still not implemented

Still Streamlit-only today: page layout and widget wiring, `st.session_state` keys (§3), the caption
wording, `AppTest`-based page tests, and every `islandos_ui/*` surface except `navigation.page_url_path`.

The view models are built **in-process**, read by the page for its metrics, and also written into the
page's downloadable JSON under `application_views` — `{request, result}` on 05, `{request, result,
annual}` on 06, where `annual` is `null` unless the reader declares the equal-days assumption, and
`{request, result, annual: null}` on 09.

A read-only transport now exists for non-Streamlit clients, but **No HTTP surface is deployed**: it is
`python -m islandos_core.transport`, binds `127.0.0.1` only, has no authentication and no persistence,
and is not part of the Streamlit deployment. It serves `GET /contracts` (the schema generated by
`islandos_core.contract_schemas`, committed at `docs/contracts/app_view_models.v3.json`) and `POST /run`
(replays one `run_request` through `run_orchestration.replay_run_request` and returns its summary — 05,
06 or 09, depending on the page discriminator). An
unsupported or malformed request gets `400` with a readable reason, never a silent default. `POST /run`
also requires `Content-Type: application/json` (`415` otherwise), refuses a declared body over 1 MB before
reading it (`413`), and only `GET /contracts` answers an `OPTIONS` preflight — `OPTIONS /run` and
unsupported methods get `405`. `GET /contracts`
alone carries `Access-Control-Allow-Origin: *`, because the schema is a committed public file and a
static viewer served from another local port must be able to read it; `POST /run` stays same-origin so a
page the user happens to have open cannot drive a replay on their machine.

The field list has a second consumer besides the JSON file: `python -m
islandos_core.contract_schemas --typescript` renders `frontend/src/contracts.ts` from the same
`contract_schema()` dict (`ContractField`, `ContractSchema`, `RunRequest`, `RunResultSummary`,
`AnnualProjection`, `DeviceTask`, …; each property keeps its `type · unit · owner` comment). The file is
committed because the browser build needs it, and `tests/test_contract_typescript.py` fails unless the
committed file equals `typescript_source()` byte for byte, so a renamed field cannot reach the viewer
unnoticed. It is not a published npm package.

The viewer has a landing route instead of a second server: `python -m islandos_core.transport` also serves
`GET /` (the built `frontend/dist/application-views.html`) and `GET /assets/<file>` (only files under
`frontend/dist/assets`, traversal refused), so one command gives a browser page that reads `/contracts`
same-origin. Without a build it answers `404` with `hint: run npm run build in frontend/ first` rather than
pretending to serve a page.

Replay identity: page 06 and `replay_run_request` now use the same
`build_joint_optimizer_manifest(request)` builder. It derives the `run_id` from the dataset digest,
site-configuration digest, end of the history window, currency, optimizer settings and availability.
The manifest timestamp is the last timestamp in that same request window, not the wall clock. Therefore
the page and replay produce the same canonical `run_id` and `manifest_sha256` for the same validated
request. Pages 05 and 09 remain separate workflows with their own identity boundaries; matching input
does not merge their runs.

Three generated artifacts describe the same fields for different readers:

| File | Reader | Command |
|---|---|---|
| `docs/contracts/app_view_models.v3.json` | human / any client needing unit + nullability + owner | `python -m islandos_core.contract_schemas` |
| `docs/contracts/app_view_models.v3.schema.json` | a standard validator (draft 2020-12) | `python -m islandos_core.contract_schemas --json-schema` |
| `frontend/src/contracts.ts` | the viewer's TypeScript build | `python -m islandos_core.contract_schemas --typescript` |

The JSON Schema closes every object (`additionalProperties: false`), requires every declared key, pins
`schema_version` to `3` so a v2 report fails rather than being half-read, and encodes the per-page shapes
with `if`/`then` on `page`: 06 must carry the dashboard's three settings keys and no `page_inputs`; 09 must
carry `page_inputs` with its `DeviceTask` array. `tests/test_contract_json_schema.py` validates a real
built request and its replay result for 05, 06 and 09 through `jsonschema` (already present in
`requirements-ci.lock`), and asserts that the closed objects reject an extra site key, a 09 request without
`page_inputs`, a 05 request carrying one, a 06 request missing `availability`, and a summary missing its
`summary_sha256`. The annual projection is pinned field by field at the same level but has no builder-derived
document in the unit test — the downloaded 06 report is the artifact that carries it.

Still not implemented: authentication, a hosted/public endpoint, a published TypeScript package, a JSON
Schema validator dependency, a server-side run store, and any persistence of a request beyond the caller's
own process.

One React surface does consume the contracts without recomputing them: `frontend/application-views.html`
(second Vite entry) loads a downloaded report's `application_views` block, renders request, result and
annual summary, and can display `GET /contracts` field by field. Its prop and payload types come from
`frontend/src/contracts.ts`, so the viewer compiles against the contract instead of a hand-written copy of
it. It is a viewer, not a second implementation: it formats numbers the Python side already decided.

Where that surface lives is settled: **it is a local tool, not a third console route.** It has no session,
no `/api` proxy and no writes; the console carries one read-only footer link to it and nothing else about
the sign-in flow changed. `frontend/README.md` is the entry point for how to open it, what it shows and
what it does not (including that a 09 download renders the device schedule and no annual projection).
Folding it into the console would buy an identity the page has no use for and a route that implies a
hosted service, so that option is recorded as rejected rather than merely deferred.


### 4.6 `device_flexibility_summary`

| Field | Type | Unit | Source |
|---|---|---|---|
| `schema_version`, `record_type`, `page` | int, str, str | – | contract |
| `run_id` | null | – | 09 has no canonical run id; identity is `summary_sha256` |
| `method` | str | – | `DeviceSchedulingResult.method` |
| `critical_energy_kwh` | float | kWh/24 h | sum of `critical_power_kw` |
| `flexible_task_energy_kwh` | float | kWh/24 h | sum of non-critical schedule `energy_kwh` |
| `scheduled_energy_charge` | float | currency/24 h | `total_energy_cost` |
| `peak_task_demand_kw` | float | kW | max of `total_power_kw` |
| `grid_import_kwh`, `estimated_energy_cost`, `critical_unmet_load_kwh`, `flexible_load_shed_kwh` | float | kWh / currency / kWh / kWh | tariff-aware replay `summary` |
| `reference_grid_import_kwh`, `reference_estimated_energy_cost` | float | kWh, currency | earliest-feasible reference `summary` |
| `currency` | str \| null | – | page |
| `summary_sha256` | str, hex | – | SHA-256 of the payload |

The 09 demo's own numbers (72 kWh protected, 17 kWh flexible, 13.77 charge, 6.0 kW peak, 103.2 kWh grid
import, 15.44 cost, 0.00 unmet, 0.00 shed) are asserted in `tests/test_app_view_models.py` and replayed
through the transport, so a regression in either path fails a test rather than moving a number silently.

### 4.7 Contract versioning

`CONTRACT_VERSION` in `islandos_core/app_view_models.py` is the only place the number is written.
Everything else derives from it: the long table's `contract_version`, the JSON Schema's `$id` and the
`schema_version` `const` in every object, the header comment of `frontend/src/contracts.ts`, and the file
names under `docs/contracts/`. `tests/test_contract_versioning.py` fails unless the three committed
artifacts and the module agree, and fails if an artifact is still on an old file name.

One number covers the whole `app_view_models` data model, not one per contract: the four shapes travel
together in one `application_views` block, so a client holding a report needs a single answer to "which
shapes am I reading". The version is a monotonic integer — `1`, `2`, `3` — never reused, never a
prerelease. It is not semver, and deliberately so: every object is closed (`additionalProperties: false`)
and every declared key is required, so there is no compatible "add an optional field" move. Under
SchemaVer's terms, an addition to a closed object is a MODEL-level change — it prevents interaction with
data written under the previous version — so one integer is the whole vocabulary this contract needs.

#### When to bump

| Change | Bump? | Why |
|---|---|---|
| Add a field to any object | **yes** | closed objects: a v3 reader rejects the key, a v4 reader requires it |
| Remove or rename a field | **yes** | the old key disappears; both versions treated it as required |
| Change a field's type, nullability or required-ness | **yes** | the `const`, the TypeScript property and the validator all change |
| Change a unit or a definition while the type stays (`kW` → `kWh`, 24 h → a year) | **yes** | the shape is identical but the numbers no longer mean the same thing |
| Change a per-page key set (`page_settings`, `run_settings`, `page_inputs`) or add a page | **yes** | the `if`/`then` branches and the `page` discriminator are contract surface |
| Change a caption, docstring, comment, test or generator formatting | no | nothing a client reads changes |

The test that a bump is earned: compare the emitted document both ways. If a v3 report no longer
validates against the v4 schema, and a v4 report does not validate against v3, the change is a contract
change. If both directions pass, it was documentation, not contract — leave the number alone.

#### What must move together

In this order. Each step reads the one above, so doing them out of order is how a "one-place PR" happens.

1. `CONTRACT_VERSION` in `islandos_core/app_view_models.py`, then the field tuples the builders assert
   against (`REQUEST_FIELDS`, `RESULT_SUMMARY_FIELDS`, `*_FIELDS`, `PAGE_SETTING_KEYS`,
   `RUN_SETTING_KEYS`).
2. The builders in the same module — `build_run_request`, `build_run_result_summary`,
   `build_device_flexibility_summary`, `build_annual_projection`. A field the schema declares but the
   builder never emits fails `tests/test_app_view_models.py`, not the schema test.
3. `islandos_core/run_orchestration.py` and `islandos_core/transport.py`, only if the changed field
   crosses them.
4. The three generated artifacts (§4.5), one command each — never hand-edited.
5. The front end that imports them: `frontend/src/contracts.ts` is regenerated; a new nullable field has
   to be handled in `frontend/src/ApplicationViews.tsx` before `npm run build` passes.
6. The tests that pin the surface: `tests/test_app_view_models.py` (page values),
   `tests/test_contract_json_schema.py` (a built request and its replay validate),
   `tests/test_application_transport.py` (`GET /contracts`, `POST /run`), and
   `tests/test_contract_versioning.py` (the three artifacts and the version).
7. This document and `CHANGELOG.md`: the §4.1–§4.6 field tables, the artifact table in §4.5, and one
   Unreleased bullet saying what changed and that an older report is now refused.

#### Checklist

Every pull request that touches the contract copies this list into its description and ticks it. The
gate is `python -m pytest -q`, which `.github/workflows/python-unit-tests.yml` already runs on every
pull request, so no new workflow is needed.

- [ ] Decide the bump: one row of the table above, with the "which report stops validating" answer
      written down.
- [ ] `CONTRACT_VERSION = N + 1`; no live path still names `v{N}` (`docs/contracts/` keeps the old files,
      nothing else should).
- [ ] Field tuples and builders updated; `python -m pytest tests/test_app_view_models.py -q` green.
- [ ] `python -m islandos_core.contract_schemas` → `docs/contracts/app_view_models.v{N+1}.json`.
- [ ] `python -m islandos_core.contract_schemas --json-schema` → `app_view_models.v{N+1}.schema.json`.
- [ ] `python -m islandos_core.contract_schemas --typescript` → `frontend/src/contracts.ts`.
- [ ] `python -m pytest tests/test_contract_versioning.py tests/test_contract_json_schema.py
      tests/test_contract_typescript.py tests/test_application_transport.py -q` green.
- [ ] `cd frontend && npm run build` — the viewer compiles against the regenerated types.
- [ ] §4.1–§4.6 tables, the §4.5 artifact table and this section's file names updated; `CHANGELOG.md`
      bullet added.
- [ ] The previous version's files left in place, not rewritten or deleted.
- [ ] If the bump is rolled back, the files it wrote are deleted with it: the gate fails on any
      file naming a version above `CONTRACT_VERSION`, so a reverted bump cannot leave a v4 artifact
      behind.

#### Old versions

Old files stay. `docs/contracts/app_view_models.v2.json` is still the only description of the reports
already downloaded under v2; a bump to v4 adds `v4.json` and `v4.schema.json` and leaves both v3 files
untouched. Nothing regenerates a previous version, and no test compares it to the current module — that
is the point: a frozen file describes a frozen shape. A v2 report opened in the viewer is refused
with a version error instead of being read halfway: the viewer checks that both `request.schema_version`
and `result.schema_version` equal `3`, and the JSON Schema pins the same constant for validators and
`POST /run`. Keeping the old files costs a few kilobytes; deleting them loses the only
written answer to "what did that cited report contain".

---

## 5. Known breaks

1. ~~**Site assumptions are assembled three times.**~~ Closed: `islandos_core/site_inputs.py` is now
   the single construction point. `SiteAssumptions` carries only site-level fields (PV, wind, grid
   limit, battery capacity/power/SOC bounds, diesel rating and variable cost); page-specific
   settings (objective weights, the dashboard's load and tariff scalars, the optimizer's search
   population/generations/seed, the planner's tasks and price vector) and run-specific settings
   (investment life, discount rate, escalation, availability flags) stay on their pages. Every
   default value, unit and type is pinned by `tests/test_site_inputs.py`. The device planner keeps
   a *different* site on purpose (`DEVICE_PLANNER_DEMO_SITE`: 12 kW PV, 4.5 kW wind, 20 kW grid,
   12 kWh / 4 kW battery, 5 kW diesel) instead of inheriting the 40/20/100 site.
2. **Run identity is not shared across pages.** See §3. No page can currently say "this is the same run
   the dashboard used", because no run id is handed off.
3. ~~**Data preparation lives inside Streamlit function bodies.**~~ Closed by two steps: config
   construction lives in `site_inputs` (T3), the request/result/annual shapes in `app_view_models`
   (T4), and the *call order* in `run_orchestration` (T8). Pages 05, 06 and 09 now collect inputs,
   build their request, call one orchestration function, and render. What remains page-side is
   widget wiring and the presentation of values that already exist.
4. ~~**No transport for a non-Streamlit front end.**~~ Closed: `islandos_core/transport.py` serves
   `GET /` (the built viewer), `GET /contracts`, `GET /health` and `POST /run` over loopback, and
   `replay_run_request` covers all three pages. Still open is what §4.5 lists: authentication, a hosted
   endpoint, a published npm package, and a run store. The contract now also ships a draft 2020-12 JSON
   Schema and generated TypeScript types, but neither is distributed.

Maintenance rules: a new page adds a row to §2; a new cross-page key is registered in §3; a new
Streamlit-free entry point is added to the bottom row of §1. `tests/test_app_integration_doc.py` guards
these three.

---

## 6. The demo clock: why two runs disagree, and how to get a number back

Pages 05 and 06 both open on a synthetic 168-hour history. Until this change that history was anchored to
`datetime.now(timezone.utc)`, and the PV/wind ripple is keyed to the row index, so opening the page one
hour later moves the 24-hour day across the ripple. The load total stays the same; the projected cost
does not. That is why the same 06 page was recorded at `7,709.55 USD/year` and later at `5,332.57` with
no formula change.

Both pages now carry a **Demo clock** in the sidebar, and its default position is frozen:

- `Demo date (UTC)` defaults to **2026-11-22** and `Demo clock (UTC hour)` to **14** — the window the
  recorded `7,709.55` was measured at. Both controls stay adjustable, so another hour is one move away.
  The constants live in `islandos_core/demo_clock_defaults.py` (a new module, so a running Streamlit
  process imports it fresh rather than keeping a cached copy of an edited one).
- Because the default no longer follows the wall clock, the default screen reports one number at any
  time of day: `7,709.55` on 06 and `24.52 USD` on 05. The previous behaviour — the same code reporting a
  different figure depending on the hour it was opened — is what the range `4,548.68–8,631.34` recorded.
- The controls only touch the synthetic default. An uploaded CSV supplies its own timestamps, and the
  clock is ignored.
- 06's annual caption names the 24-hour window the projection belongs to, and the history caption names
  the pin. 05's history caption names the pin too.
- The pinned window enters the run request as `history.timestamps_utc`, so a downloaded report carries
  the timestamps a replay needs. No contract field was added and the schema version did not move.

**06 is a function of the hour.** Its generator has no weekday term, so pinning `14` gives
`7,709.55` and pinning `2` gives `5,332.57` on any date, with `186,150 kWh` unchanged. Pin the date only
to make the printed window stable.

**05 now starts from 06's canonical window.** The base series is
`islandos_core.demo_site_history.build_synthetic_site_history` at the nominal site (40 kW PV, 20 kW
wind); page 05 then applies its two customer controls, `demand_scale` to load and `tariff_scale` to
price. At `1.0/1.0` the timestamps and the four signal arrays are identical to 06's default, and both
pages print the same `Shared history SHA-256`. The checksum quantises each signal to six decimals
before hashing, so it is stable across Python and libm runtimes; the model still receives the unrounded
arrays. Pinning `2026-11-22 14:00Z` gives `24.52 USD`
(`7,709.55 USD/year` on 06 is unchanged). A different date still moves the renewable phase because the
PV/wind ripple is keyed to the row index; the date no longer changes a weekday load term, because 05 no
longer has one. `tests/test_demo_clock.py` asserts the pinned cost and the shared hash; the unit
identity is in `tests/test_demo_site_history.py`.

What this proves: a recorded demo number can be reproduced from the controls, and the difference between
two recorded runs is a difference of input window, not of formula. What it does not prove: that the demo
figure is a property of the site. It is still synthetic, still unvalidated; the default is now fixed so it
no longer drifts with the wall clock, but the number remains a property of the synthetic window, not of a
real site.

---

## 7. What "deployed" can and cannot prove

The deployed artifact is the Streamlit Community Cloud app that builds from `main`:

- `https://islandos.streamlit.app/Customer_Decision_Dashboard`
- `https://islandos.streamlit.app/Forecast_Led_Joint_Resource_Optimizer`
- `https://islandos.streamlit.app/Device_Flexibility_Planner`

"Which commit is it running?" used to be unanswerable: the page exposed no build stamp, and no deploy hook
wrote one. The reason is measured (§7.1), not assumed. What answers it now is a stamp the app writes from
its own checkout (§7.2), read by one script that turns it into a repeatable assertion (§7.3); §7.4 lists
what that still cannot show.

### 7.1 What the front end exposes — measured 2026-11-23

| Request | Response |
|---|---|
| `/`, `/Customer_Decision_Dashboard`, `/Forecast_Led_Joint_Resource_Optimizer`, `/Device_Flexibility_Planner` | `200`, `text/html`, one identical 9,782-byte Streamlit shell |
| `/_stcore/health` | the same shell, not `ok` |
| a path that does not exist | the same shell, `200` |
| any of the above without a session cookie | `303` to `share.streamlit.io/-/auth/app`, then the shell once the cookie jar is kept |
| `/` loaded in a headless browser | the page's own body is ~72 characters of chrome around `<iframe src="…/~/+/">`; the sidebar, the pages and every `data-testid` exist only inside that frame |

Consequences, which bound what any check may claim:

- an HTTP status proves nothing: a missing page and a live page answer the same `200`;
- no page title, button label or `schema_version` string is present in the HTML, because Streamlit renders
  the page in the browser — "scrape the visible marker" cannot be done without a headless browser;
- even with a browser, the app is not in the document that was served: a check that waits for the app
  container in the outer page times out against a perfectly healthy deployment (measured 2026-11-23:
  a 180-second timeout on `[data-testid="stAppViewContainer"]` while the page rendered normally inside
  the iframe);
- the three page routes differ only in their URL; the server returns the same bytes for each.

Separately, a report downloaded from a page states `schema_version: 3` and carries `application_views`; that
ties the *file* to the contract (`docs/contracts/app_view_models.v3.schema.json` validates it) and says
nothing about which code produced it.

The build stamp was meant to be served from `./static`: `/app/static/<name>`, with
`[server] enableStaticServing = true` in `.streamlit/config.toml`. Measured on 2026-11-23, after the app had
been rebooted onto `46d145a`, `/app/static/build_info.json` still answered with the same 9,782-byte shell,
while the sidebar inside the iframe said `build 46d145a (git)`. On Community Cloud that route is therefore
not available: no app-specific bytes are served from a file a session wrote. The file remains useful for a
self-hosted run, or for a host that does serve `./static`.

The stamp is still reachable on Cloud as a download: the sidebar offers **Download build stamp (JSON)**, and
the bytes come from the running app, not from static serving. A browser click is needed, so the same headless
session that warms the app also reads it. A local server reproduces both worlds: with
`--server.enableStaticServing false` the path returns exactly the hosted shell; with `true` it returns
`200 application/json`.

### 7.2 The build stamp

At start-up `app.py` calls `islandos_core.build_info.build_stamp()`, writes the result to
`static/build_info.json` (best-effort: a read-only deployment still renders the page), captions the
sidebar with `build <short sha> (<resolved_from>)`, and offers the same bytes as a sidebar button,
**Download build stamp (JSON)**. One function, `build_info.serialise_stamp()`, produces both the file and
the download, so the two cannot drift apart. The file is written whether or not the host serves it;
§7.1 records where it is, and is not, readable.

| Field | Meaning |
|---|---|
| `schema_version` | `1`; a consumer refuses anything else |
| `source_commit`, `source_commit_short` | the deployment's `git rev-parse HEAD`, or `null` |
| `resolved_from` | `git` (read from the checkout), `environment` (`ISLANDOS_BUILD_COMMIT`), `none` |
| `unresolved_reason` | why no commit was found: `not-a-git-checkout`, `git-not-runnable`, `unexpected-rev-parse-output` |
| `working_tree_dirty` | tracked files differ from that commit; untracked files are ignored, so the stamp's own write does not mark every deployment dirty |
| `captured_at_utc` | when the stamp was read |

The commit is read from the deployment, never from a constant in this repository: a committed SHA would
assert a fact nobody verified. A CI-written stamp is also unusable as an answer, because a commit cannot
contain its own SHA — the file would describe the parent of the commit that adds it, and every merge would
produce a second commit whose own identity is again unrecorded. `tests/test_build_info.py` fails if
`build_info.py` ever contains a literal 40-hex value.

`ISLANDOS_BUILD_COMMIT` is accepted for a deployment without git metadata (a container build) and is
reported as `environment`; it is a declaration, not a measurement, so §7.3 never compares it to a branch.

### 7.3 The check

```
python scripts/check_deployment.py --base-url https://islandos.streamlit.app \
    --warm --expect-commit "$(git rev-parse HEAD)"
```

It probes the three page routes, opens the app once in a headless browser, reads the stamp and the sidebar's
build line, and writes a JSON report with `--report`. The commit is taken from whichever source names one,
strongest first: the stamp served at `/app/static/build_info.json` (40 characters); failing that, the
sidebar's download of the same document (40 characters); failing that, the rendered `build` line (seven
characters, compared as a prefix of `--expect-commit`). `stamp.source` says `static` or `download`, and
`commit.basis` says `stamp` or `rendered`. The download button is looked for for up to ten seconds, at a
quarter-second interval, before it is called absent: `Locator.count()` answers on the spot and never waits,
while the sidebar draws its caption before the button beneath it, so one look can report a missing button
that is merely late. A run that finds `download.state=not-found` therefore spent those seconds looking;
`not-found` means absent, not slow. Exit codes:

| Code | Meaning |
|---|---|
| 0 | three pages return the app shell, the app renders, the deployment names its commit, and (when expected) it matches |
| 1 | a page route did not return the Streamlit shell |
| 2 | nothing was named and nothing was asked: an HTTP-only run that neither expected a commit nor found a stamp |
| 3 | the named commit differs from `--expect-commit`, or `--expect-commit` is not a full SHA |
| 4 | a commit was expected but the deployment names none that can be compared: no source named one, or the only one is self-declared |
| 5 | the rendered app did not name a commit: it raised, showed no build line, or the line was unattributed or disagreed with a served stamp |

`--warm` is not a convenience. A Streamlit script runs only when a browser session connects, so an
HTTP-only probe sees nothing of the running process on Community Cloud — measured: the stamp path answers
with the shell (§7.1) — and on a container that has just restarted, a self-hosted stamp file does not exist
yet either. The warm-up runs one session, which is what can click the download and read the build line;
both are cross-checked against the static file when one is served. That session also asserts that the page
renders without an exception. The workflow installs `playwright==1.65.2` and Chromium for this step,
pinned in the workflow rather than in `requirements-ci.lock` because the unit-test job needs no browser.

The warm-up searches every frame of the page for the app container, because a self-hosted server renders
the app in the page itself while Community Cloud renders it in the wrapper iframe (§7.1). The report
records `frame_url`, so the evidence names the frame whose sidebar was read.

Before comparing anything the check validates the document itself: schema version, a 40-hex
`source_commit`, `resolved_from` in `{git, environment, none}`, a `source_commit_short` that agrees with the
full commit, `working_tree_dirty` as a boolean or `null`, and a capture timestamp. A stamp that disagrees
with itself is treated as unreadable rather than as a partial match, and the sidebar line must carry the
same source tag as the stamp — `build 1a2b3c4 (environment)` does not confirm a `git` stamp even though
the sha matches. With no stamp served, the line itself must attribute the sha to `git`; a bare
`build 1a2b3c4` is reported as unattributed instead of being assumed.

The report separates `claims` (each with `proved` and its evidence) from `not_proved`.
`.github/workflows/hosted-app-health.yml` runs it six-hourly and on manual dispatch with `--expect-commit`
set to the checked-out `main`; on push and pull request it runs without the commit assertion and without
failing the build, because a run seconds after a merge would race Streamlit Cloud's own file update and
report drift that has not happened yet.

### 7.4 What is still not proved

- that the process executes the code of the commit it reports, beyond the checkout `git` is read from;
- that Community Cloud serves the static stamp at all: `/app/static/build_info.json` answered with the
  front-end shell after a reboot on 2026-11-23, so on Cloud the stamp comes from the sidebar download
  instead, and the two routes are never compared byte for byte;
- that the installed dependencies equal `requirements-runtime.lock`;
- Streamlit Community Cloud's own build identity, provenance or CDN behaviour;
- that the stamp or the caption cannot be made to lie — a code change could report a constant, and no
  external check detects that; only review and `tests/test_build_info.py` stand against it;
- everything the rendered page shows beyond the build line: only the elements the check reads are inspected.

### 7.5 Rebuild timing, and the failure this catches

Streamlit Community Cloud updates app files from the repository almost in real time, redeploys fully when
dependencies change, and needs a reboot when `.streamlit/config.toml` changes. A deployment can therefore
lag `main` for minutes after a merge — expected, not a defect. What the six-hourly run catches is a
deployment that is *stuck*: a sidebar that still names an older commit, or one that stops naming a commit
at all.

The download button, not the static file, is what carries the stamp on Cloud: it is rendered by `app.py`
and handed to the browser by the running process, so no static serving is involved. Because a Streamlit
script runs only when a session connects, nothing exists until someone opens the page — which is why the
check warms the app rather than trusting an HTTP read; and because Community Cloud does not serve
`./static` (§7.1), a reboot does not change that. A drift verdict therefore means "the running code is not
the commit on `main`", and exit 5 means "the running code did not say which commit it is" — the two
failures worth paging for.

---

Maintenance rules: a new page adds a row to §2; a new cross-page key is registered in §3; a new
Streamlit-free entry point is added to the bottom row of §1; a new externally observable fact is added to
§7 and to `scripts/check_deployment.py`, or §7 says it is not observable.
`tests/test_app_integration_doc.py` guards these three.

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
| Streamlit surfaces | `islandos_ui/workspace.py`, `annual_economics_panel.py`, `decision_record_panel.py`, `page_header.py`, `upload_guard.py` | Yes |
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

---

## 4. The application-facing view models

`islandos_core/app_view_models.py` is the boundary a second front end reads instead of re-deriving
what a page already knows. It imports no Streamlit, touches no `st.session_state`, calls no page
function, and holds no global state; it neither calculates nor optimises — it reads objects the core
already produced, validates them, and returns plain JSON-able dictionaries with stated units,
nullability and provenance. `tests/test_app_view_models.py` proves the imports are Streamlit-free in a
subprocess (`'streamlit' not in sys.modules`) and pins every field below.

Three contracts, `CONTRACT_VERSION = 1`:

| Builder | Answers | Refuses |
|---|---|---|
| `build_run_request(page=…, site=…, history=…, units=…, page_settings=…, run_settings=…, provenance=…, source_sha256=…)` | what this page asked the core to run | an unknown page, a page/run setting key outside that page's declared set, a signal without a unit, series of unequal length, non-numeric or empty series |
| `build_run_result_summary(page=…, result=…, economics=…, planning_run=…, currency=…)` | what the run produced, limited to what the pages display | a dashboard summary without service-equivalent economics or without `grid_first` / the recommended policy in `candidates`; an optimizer summary without a planning run, `run_id`, `manifest_sha256` or `evidence_sha256` |
| `build_annual_projection(record, currency=…)` | the declared-assumption annual projection | a record that `verify_annual_operating_basis` rejects (digest mismatch, claimed bill, claimed site validation, missing `summary_source`), or one missing `figures` / `basis` |

`to_json(view)` serialises any of them with `sort_keys=True, allow_nan=False`.

### 4.1 `run_request`

| Field | Type | Unit | Required | Nullable | Source | Ownership |
|---|---|---|---|---|---|---|
| `schema_version` | int | – | yes | no | `CONTRACT_VERSION` | contract |
| `request_type` | str | – | yes | no | constant `islandos_run_request` | contract |
| `page` | str, `customer_dashboard` \| `joint_resource_optimizer` | – | yes | no | page | page discriminator |
| `site` | dict | kW, kWh, currency/kWh, SOC as fraction | yes | no | `SiteAssumptions.describe()` + `digest()` | **site-level** (single source: `site_inputs`) |
| `history.signals` | dict[str, list[float]] | kW per canonical signal | yes | no | the page's forecast input | data, not assumption |
| `history.units` | dict[str, str] | unit string per signal | yes | no | page | data |
| `history.hour_count` | int | hours | yes | no | derived from the series | data |
| `history.provenance` | str | – | yes | no | page (`Uploaded CSV` / `Demonstration data`) | data provenance |
| `history.source_sha256` | str, hex | – | yes | yes (`null` when nothing was uploaded) | page | data provenance |
| `page_settings` | dict | per page | yes (`{}` allowed) | no | page | **page-specific** |
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
annual}` on 06, where `annual` is `null` unless the reader declares the equal-days assumption.

A read-only transport now exists for non-Streamlit clients, but **No HTTP surface is deployed**: it is
`python -m islandos_core.transport`, binds `127.0.0.1` only, has no authentication and no persistence,
and is not part of the Streamlit deployment. It serves `GET /contracts` (the schema generated by
`islandos_core.contract_schemas`, committed at `docs/contracts/app_view_models.v2.json`) and `POST /run`
(replays one `run_request` through `run_orchestration.replay_run_request` and returns its summary). An
unsupported or malformed request gets `400` with a readable reason, never a silent default.

Still not implemented: authentication, a hosted/public endpoint, a TypeScript package, a JSON Schema
validator dependency, a server-side run store, and any persistence of a request beyond the caller's own
process.


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
   (T4), and the *call order* in `run_orchestration` (T8). Pages 05 and 06 now collect inputs,
   build their request, call one orchestration function, and render. What remains page-side is
   widget wiring and the presentation of values that already exist.
4. **No transport for a non-Streamlit front end.** §4.5.

Maintenance rules: a new page adds a row to §2; a new cross-page key is registered in §3; a new
Streamlit-free entry point is added to the bottom row of §1. `tests/test_app_integration_doc.py` guards
these three.

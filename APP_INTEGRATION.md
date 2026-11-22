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
| Application/core | `islandos_core/*`, `optimization/*`, `experiments/*` | No |

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
one of them disappears from the repository.

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

## 4. What a React/TypeScript front end would need (not implemented)

The bottom row of §1 is already the application layer: pure Python, no Streamlit, no UI state. A
non-Streamlit front end would need a transport (HTTP/JSON) around those entry points, and three JSON
shapes that do not exist yet:

- `run_request`: manifest payload + history + units + site config + availability flags (today: keyword
  arguments to `run_forecast_dispatch`).
- `run_result_summary`: run id, `manifest_sha256`, `evidence_sha256`, decision-record status, recommended
  policy, service-equivalence verdict (today: Python dicts inside the page).
- `annual_projection`: the six figures of `INTEGRATION.md` §6.5 with their declared basis (today: a record
  produced by `annualise_run_summary`; its keys already match, but nothing serialises it to a documented
  wire format).

This section states a boundary, not a delivered API. No HTTP surface, no TypeScript package, and no
JSON schema file exist in this repository.

---

## 5. Known breaks

1. **Site assumptions are assembled three times.** 05 (`pages/05…`, ~line 199), 06 (~line 119) and 09
   (~lines 110 and 134) each call `EnergySystemConfig(...)` from their own sidebar widgets, with
   different field sets. Two pages describing "the site" can hold different assumptions, and nothing
   detects it. Planned: one constructor shared by all three (T3 in the integration prompt).
2. **Run identity is not shared across pages.** See §3. No page can currently say "this is the same run
   the dashboard used", because no run id is handed off.
3. **Data preparation lives inside Streamlit function bodies.** 05 and 06 build configs, manifests and
   optimizer calls inline, so nothing except Streamlit can reuse that path. Planned: a Streamlit-free
   view-model layer (T4).
4. **No transport for a non-Streamlit front end.** §4.

Maintenance rules: a new page adds a row to §2; a new cross-page key is registered in §3; a new
Streamlit-free entry point is added to the bottom row of §1. `tests/test_app_integration_doc.py` guards
these three.

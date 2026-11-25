# B-01 Project Binding Audit

- Status: **read-only implementation audit; no runtime changes**.
- Baseline: `main` at the time of review, 2026-11-25.
- Purpose: establish how Page 05/06 can obtain a real local Workspace `project_id` before any run-record persistence is wired.
- Related work: J-01 in PR #362; run-record storage proposal in PR #359.
- Scope: project identity and consent boundary only. This document does not approve or implement the complete run-identity contract.

## 1. Finding

Page 05 and Page 06 currently create canonical manifests with fixed descriptive identifiers:

- Page 05: `streamlit-customer-decision-dashboard`.
- Page 06: `streamlit-joint-resource-workspace`.

These values are passed as `project_id` to `create_run_manifest`, but they are not created in the local Workspace `projects` table. They are not database-backed customer project IDs.

The local Workspace is a separate, opt-in surface:

- Page 08 is disabled unless `ISLANDOS_ENABLE_LOCAL_WORKSPACE=1`.
- Its database path is `ISLANDOS_WORKSPACE_DB`, defaulting to `.islandos/workspace.sqlite3`.
- It initialises the workspace and creates projects only after explicit consent.
- New project IDs are generated as `site-<12 hex>`.
- Existing projects are selected from `list_projects(db_path)` in the Page 08 UI.

Page 05 and Page 06 do not currently import or call the Workspace project-selection, project-creation, or run-record persistence functions. No shared active-project context is visible in either page's current entry path.

**Consequence:** a manifest's fixed `streamlit-*` project label cannot be passed to `record_run_record` as though it were a real local project. The run-record writer checks that the project exists in the `projects` table and rejects unknown project IDs.

## 2. Evidence in the current code

| Evidence | Current implementation | Implication |
|---|---|---|
| Page 08 opt-in | `pages/08_Site_Workspace.py:38-46` | Workspace is not automatically available in every deployment. |
| Workspace DB | `pages/08_Site_Workspace.py:43` | Local database path is configurable and distinct from the Streamlit run manifest. |
| Project creation | `pages/08_Site_Workspace.py:69-73` | IDs are generated for explicit user-created projects after consent. |
| Project selection | `pages/08_Site_Workspace.py:83-87` | Page 08 selects a real project from the local DB. |
| Page 06 manifest | `pages/06_Forecast_Led_Joint_Resource_Optimizer.py:286-287` | Fixed manifest label is not proof of a registered Workspace project. |
| Page 05 manifest | `pages/05_Customer_Decision_Dashboard.py:651-652` | Same issue exists on Page 05. |
| Run-record guard | `islandos_core/workspace_store.py:603-604` on the #359 implementation | The writer requires the supplied project ID to exist. |

The public hosted Streamlit demo and the opt-in local Workspace must not be conflated. The existing architecture documentation says the hosted demo is not connected to the local Workspace store. This audit does not propose enabling customer-data persistence on the public hosted demo.

## 3. Recommended B-01 contract

### 3.1 Separate manifest label from persistence project identity

Keep the existing manifest `project_id` field unchanged for the current manifest schema until a separately reviewed manifest migration exists. Do not reinterpret the fixed `streamlit-*` values as local database IDs.

For persistence, use an explicit context value:

- `registered`: a user-selected `project_id` read from the active local Workspace database.
- `unregistered`: no Workspace project has been selected or the Workspace is disabled.

Do not create a project implicitly when a user opens Page 05 or Page 06. Project creation remains an explicit Page 08 workflow with its existing metadata-consent step.

### 3.2 Persistence gate

A run may be written to `run_records` only when all of the following are true:

1. Local Workspace is enabled and its configured database can be initialised.
2. The user explicitly selected a project that exists in that database.
3. The user explicitly consents to storing the run result.
4. Full request/history retention is separately consented to; otherwise save metadata-only.
5. The run identity and run-record API contract have been approved and implemented.

If any condition is absent, keep the run in the current in-memory/downloadable workflow and mark it as not persisted. Do not fabricate a project ID or silently create a project.

### 3.3 Project context lifecycle

The active project must be resolved from the local Workspace at the point of persistence, not cached indefinitely as a global or inferred identifier.

The selected project context should carry only:

- `project_id`
- display name (for UI only)
- Workspace database identity/path (internal context; never included in public run identity)
- source of selection (explicit user selection)

The project display name, local file path, owner username, and workspace database path must not enter `input_group_id` or `run_id`.

### 3.4 Failure and compatibility behaviour

- Workspace disabled: no persistence; existing calculation remains available.
- No project selected: no persistence; show an explicit “not saved to a project” state.
- Project missing/deleted between selection and write: fail closed; do not fall back to a fixed manifest label.
- Consent absent: do not call the persistence API.
- Existing historical manifest IDs and run IDs remain unchanged.
- A registered project ID is a persistence partition, not part of the shared input-group identity.

## 4. Minimal implementation sequence after contract approval

1. **Shared context reader:** add a small UI-agnostic helper that reads the configured Workspace DB and returns the list of valid project IDs. It must not create projects.
2. **Page selection:** expose an optional active-project selector on 05/06 only when local Workspace is enabled. Do not make it a prerequisite for running simulations.
3. **Consent boundary:** present separate explicit choices for saving the result and retaining the full request/history. Default both to off.
4. **Persistence adapter:** after J-01 and #359 contracts are agreed, translate the selected project context plus the page's canonical run identity into the run-record API.
5. **History view:** show only records belonging to the selected project; do not infer cross-project membership from matching input groups.
6. **Tests:** cover Workspace disabled, no project, valid project, invalid/stale project, consent off, metadata-only consent, full-retention consent, and no accidental project creation.

## 5. Explicit non-goals

This B-01 slice does not:

- merge the local Console API database with the Streamlit Workspace database;
- make the hosted Streamlit demo a customer data room;
- introduce cloud storage, multi-tenant SaaS, remote access, or a public API;
- change the canonical manifest v1 schema;
- alter Page 05/06 calculations or annual economics;
- implement J-01 `derive_input_group_id` / `derive_run_id` before owner sign-off;
- modify PR #359 or any other contributor's branch;
- automatically create a project or retain customer data.

## 6. Decisions still required

| Decision | Recommendation | Owner |
|---|---|---|
| Should 05/06 persistence be local-Workspace-only in this phase? | Yes; hosted demo remains non-persistent. | Product owner |
| Should project selection be optional for running the calculation? | Yes; only persistence requires a registered project. | Product owner |
| Should a run with no selected project be stored under a synthetic `unregistered` database project? | No; do not create a fake project. Keep it unpersisted. | Product owner / #359 owner |
| Should the current manifest's fixed `streamlit-*` labels be migrated? | No change in this phase; preserve manifest v1 and legacy records. | J-01 owner |
| Should the Console API's tenant/site identity be bridged to Workspace project identity now? | No; separate system and separate scope. | Product owner |

## 7. Verification performed

Read-only source inspection of:

- `pages/08_Site_Workspace.py`
- `pages/05_Customer_Decision_Dashboard.py`
- `pages/06_Forecast_Led_Joint_Resource_Optimizer.py`
- `islandos_core/workspace_store.py`
- `islandos_core/site_workspace.py`
- `islandos_core/run_orchestration.py`

No application code, database, page behaviour, authentication, calculations, or other contributor branch was changed. No runtime tests are claimed because this PR adds an architecture audit only.

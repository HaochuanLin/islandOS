# IslandOS Backend Architecture Audit

- **Date:** 2026-11-25
- **Repository:** `HaochuanLin/islandOS`
- **Baseline:** `main` at `17d0ec7757600ac22250bcdc6146a48793d0c0b8`
- **Mode:** read-only architecture audit; no application code or model calculations changed
- **Purpose:** establish the actual backend/data-integration baseline before implementing the remaining Backend & Data Engineering work.

## 1. Executive finding

IslandOS does not need a new backend built from scratch. It already has substantial foundations for run contracts, deterministic manifests, local project storage, data provenance, forecast hand-off, a local reference API, and a separate tenant/telemetry service.

The main gap is **composition and persistence**: these foundations are separate, and the actual planning runs are not yet recorded and retrievable through one persistent run-record interface. The current HTTP planning transport is deliberately stateless. The persistent workspace store records project/import metadata, assets, audit events and immutable metadata manifests, but it is not yet the run-history store used by `replay_run_request`.

The product must continue to distinguish separate page workflows. A shared input fingerprint is not a shared run, and matching history does not make economic outputs interchangeable.

## 2. Current architecture inventory

| Layer | Existing implementation | Current boundary |
|---|---|---|
| Request/result contracts | `islandos_core/app_view_models.py`, contract version 3; `contract_schemas.py` generates JSON Schema and TypeScript types | Stable page-specific request and summary shapes; not a full persisted run envelope |
| Page orchestration | `run_orchestration.py`: `run_customer_dashboard`, `run_joint_optimizer`, `run_device_planner`, `replay_run_request` | Three separate compositions; no single 05/06/09 pipeline |
| Canonical planning manifest | `canonical_run.py`: deterministic run ID, dataset/site/forecast/optimizer provenance and SHA-256 verification | Used by the joint optimizer and replay path; generated in memory |
| Local project persistence | `workspace_store.py`: projects, import metadata, asset versions, immutable metadata manifests, audit chain, backup/restore | Local-first, single-user prototype; not connected to planning replay |
| Extended site workspace | `site_workspace.py`: site-profile versions, optional original CSV/XLSX retention, project package export/import | Raw source retention is separate, opt-in and local-only (20 MiB limit) |
| Session data hand-off | `session_dataset.py` | 05/06 can share uploaded CSV bytes in the current Streamlit session (25 MiB limit); not durable storage |
| Planning HTTP transport | `islandos_core/transport.py` | Loopback-only, read-only/stateless contract viewer and replay endpoint; no auth, persistence or deployed hosted endpoint |
| Tenant and telemetry API | `islandos_service_api.py` | Separate loopback local reference service with its own SQLite store for tenants, users, sessions, sites, telemetry, invitations and notifications; no planning-run API |
| React console | `frontend/src/api.ts`, `App.tsx` | Uses the tenant/telemetry API; planning runs remain in the Streamlit demo |
| Forecast hand-off | `forecast_service.py`, `forecast_contract.py`, `prediction_dispatch_adapter.py`, `forecast_optimizer_adapter.py` | Useful adapters and validation exist, but the application has more than one forecast path |
| Simulation | `dispatch_energy_system`, `simulation_adapter.py` and page-specific replay paths | Shared physical dispatch is reused, but there is no common first-class simulation result envelope |

## 3. Run identity: three different concepts must not be conflated

| Surface | Current identity behaviour | Audit conclusion |
|---|---|---|
| Page 05 — Customer Decision Dashboard | The application-view result summary intentionally has no `run_id`. Its separate investment-economics binding creates a deterministic `run-dashboard` identity and canonical manifest from the investment screen's own inputs. | Do not attach that investment citation to the optimizer result as if they were one run. |
| Page 06 — Joint Resource Optimizer | Creates a canonical manifest and a deterministic planning `run_id`; the planning workflow also produces forecast/evidence digests and a decision record. | This is the strongest existing canonical run path. |
| Page 09 — Device Flexibility Planner | Its result summary has no canonical `run_id`; `summary_sha256` identifies the summary. It uses fixed demonstration inputs and remains an isolated device-planner workflow. | Do not imply it is the next stage of the 05/06 history chain. |
| `POST /run` replay | The joint-optimizer replay derives a deterministic ID from the request and pins replay time. 05 and 09 return their page-specific summaries; they do not become the 06 run. | A replay identity identifies the replay request, not an original browser session. |

### Additional B1 finding: page 06 and replay do not share the same run-ID derivation

The page 06 code derives its run ID from a specific payload: dataset digest, site-configuration digest, window-end timestamp, currency, optimizer settings and availability (`pages/06_Forecast_Led_Joint_Resource_Optimizer.py`, around the run-manifest construction).

The replay path instead calls `deterministic_run_id("run", {"request": request})` and pins `created_at_utc` to `REPLAY_CREATED_AT_UTC` (`islandos_core/run_orchestration.py::replay_run_request`). These are different identity inputs, and the replay manifest timestamp also differs from the page's window-based timestamp. Therefore page execution and replay are deterministic independently, but the code does not currently establish that they represent the same canonical run or manifest.

The current replay test proves only that replaying the same request twice produces the same replay ID and summary. It does not compare a page-generated run ID/manifest with the replay-generated ID/manifest. The helper docstring in `_manifest_from_request` also says the page mints a fresh UUID and wall-clock timestamp, which no longer matches page 06's current deterministic, window-based implementation.

**B1 acceptance requirement:** define one shared run-identity builder and use it from both page 06 and replay, or explicitly model page execution and replay as different run records linked by the same request fingerprint. Add a regression test that compares the chosen identity semantics across both paths. Do not claim identity equivalence until this test passes.

The merged `#348` change adds `build_input_fingerprint` and `compare_input_fingerprints` in `islandos_ui/customer_workflow.py`. It separates shared-input fields from page-specific settings. The helper is not yet wired into the 05/06 pages on the audited `main`; it must be treated as an input-comparison tool, not a run merger.

## 4. Persistence: what is and is not stored

### Existing capabilities

- `workspace_store.py` stores project metadata and imported-file metadata, including the original byte hash, source classification, row/signal counts and quality status.
- Its `run_manifests` table stores an immutable metadata manifest with configuration, model versions, software version, random seed and an output summary. Hash checks and SQLite no-update/no-delete triggers protect normal application writes.
- The append-only audit chain can be verified. Whole-workspace SQLite backup/restore exists.
- `site_workspace.py` adds versioned site profiles, optional original source-file retention after explicit consent, and portable project package export/import.
- `islandos_service_api.py` persists tenant-scoped normalized telemetry and account/workspace metadata in a separate database.

### Missing integration

- `canonical_run.create_run_manifest` and `workspace_store.create_run_manifest` are different manifest models with different purposes. The former returns a deterministic domain manifest; the latter creates a new UUID and persists a workspace metadata snapshot.
- The workspace manifest table is not currently the persistent backing store for `replay_run_request`.
- There is no first-class persisted record that stores and retrieves the exact application request together with its full result, result schema, execution status and links to the canonical manifest.
- The planning transport explicitly has no persistence. Restarting it does not provide a history of prior runs.
- Session-shared CSV bytes are not persisted by `session_dataset.py`. Optional local source retention exists separately and must remain opt-in.

**Implication:** B2 should add a deliberate run-record layer or a carefully designed extension to the workspace store. It must preserve the canonical run identity and must not silently replace it with a new workspace UUID.

### Additional persistence constraints discovered during the schema review

- The current workspace schema is `1.0`. `initialize_workspace` creates missing tables, records the schema version once, and fails closed when an existing database has a different version. There is no general migration runner in this module. A new run-record table must therefore be accompanied by an explicit, tested migration path; simply changing `SCHEMA_VERSION` would make existing workspaces fail to open.
- The existing `run_manifests.run_id` is a global primary key and `create_run_manifest` always generates a random UUID. A canonical page run ID is deterministic from run inputs and does not include a workspace/project ID. Persistent execution records should be scoped by `(project_id, run_id)` (or an equivalent composite identity), not assume a deterministic run ID is globally unique across customer projects.
- `create_run_manifest` requires an existing project. Local workspace creation and metadata retention require explicit consent and are enabled through local-workspace configuration. The public hosted Streamlit demo must not be pointed at a customer's workspace database or source-file directory.
- The portable project package in `site_workspace.py` currently exports/imports `run_manifests`, not full execution request/result records. If B2 adds persistent execution records, project export/import must either carry them with integrity hashes and source-run provenance or explicitly disclose that they are excluded; otherwise a user can back up a project and silently lose the new run history.

**B2 design consequence:** persist full request/result evidence only inside an explicitly enabled local workspace after project/actor context and consent are present. Keep the hosted public demo stateless. Treat a missing project, actor or consent as “not persisted”, not as permission to create a hidden project or retain customer data.


## 5. Replay and annual evidence

`replay_run_request` currently returns an `annual` field of `None` for 05, 06 and 09. This is an explicit transport boundary, not evidence that annual calculation is missing.

Page 06 already calls `annualise_run_summary` and `verify_annual_operating_basis`. The caller supplies `days_equivalent_per_year`, and the resulting projection records the equal-day assumption, the run and manifest digests, source provenance, and the fact that it is not a bill, measured annual consumption or site validation.

The v3 request contract does not carry that annualisation assumption. Therefore replay cannot honestly reproduce the page's annual projection yet. B4 should add an explicit optional, versioned request field and replay the existing annualisation functions only when the caller supplied it. It must never default to 365 or infer an annual basis.

Page 05's investment screen is a different economic object: it uses customer-entered annual bills/CAPEX/O&M and a service-equivalence gate. Some replacement/residual inputs remain outside the current v3 request contract. These values must not be merged with Page 06's equal-day operating projection.

## 6. Data and module hand-off

- `session_dataset.py` shares the same uploaded file between 05 and 06 only within one Streamlit session.
- `forecast_contract.py` validates aligned forecast timestamps, units, model IDs and the input-history digest.
- `prediction_dispatch_adapter.py` already converts generic prediction results into the dispatch forecast contract. This should be reused rather than introducing a parallel adapter.
- Forecasting is not one implementation path: 05 uses `forecast_engine`; 06 uses the forecast-signal/planning workflow; other workspaces have their own forecast surfaces.
- The physical dispatch engine is reused, but 05/06 embed simulation within optimisation and 09 uses its own schedule/replay chain. `simulation_adapter.py` maps simulation rows to screening signals; it is not a shared simulation-result contract.
- Source classification is not fully aligned: `data_quality.py` accepts `public`, `dataset_provenance.py` accepts `public_reanalysis` and `modeled`, and `workspace_store.py` has its own allowed source-type set. Before broadening imports, define a canonical taxonomy and explicit mappings; do not silently rename provenance.

## 7. API and frontend boundary

There are two separate local services and they should remain separate until a deliberate architecture decision says otherwise:

1. `islandos_core.transport` exposes `GET /contracts`, `POST /run`, health and the local application-viewer assets. It binds to loopback by default, has no authentication, has no persistent run store, and is not deployed as part of the public Streamlit app.
2. `islandos_service_api.py` exposes `/api/v1` account, session, site, telemetry, invitation, member and notification routes. Its store is tenant-scoped and independent of `workspace_store`. The React console consumes this service. It is a local reference service, not production SaaS.

The next backend step is not to merge these servers. First define which service owns planning-run persistence and how a local user/project/site maps to a planning request. No public endpoint, production authentication or device-control capability should be claimed.

## 8. Tests and current repository state

Relevant test coverage already exists:

- `tests/test_app_view_models.py`
- `tests/test_run_orchestration.py`
- `tests/test_application_transport.py`
- `tests/test_workspace_store.py`
- `tests/test_workspace_backup_restore.py`
- `tests/test_islandos_service_api.py`
- `tests/test_dataset_provenance.py`
- `tests/test_forecast_contract.py`

The important missing test is an end-to-end persistence test: execute a validated run, persist its request/result and provenance, close/reopen the store, retrieve and verify the record, and prove that the record still distinguishes a canonical run from a merely matching input fingerprint.

At the audited `main` SHA `17d0ec7757600ac22250bcdc6146a48793d0c0b8`, the latest visible Actions runs for Python unit tests, dependency audit, hosted-app health, container smoke, RO tests, Windows gateway build and Nan'ao scenario validation all report success. This is CI evidence for that SHA, not a local test execution by this audit.

Open frontend PRs were checked for overlap: #350 (page 05), #349 (workspace microgrid), #347 (page 06), #346 (React console) and #345 (page 09). Their changed-file lists do not overlap the backend core files proposed for the first persistence implementation. They currently target the previous `7fb7ff7` base, so their merge/rebase state must be checked again before any integration.

## 9. Prioritised backend work

| Priority | Work | First concrete deliverable | Depends on |
|---|---|---|---|
| B1 | Run identity and envelope | Define a versioned envelope that links request hash, canonical run ID where available, manifest/evidence hashes, page/run type, result schema and explicit parent input fingerprint. Preserve page-specific run boundaries. | Contract audit; no model calculation change |
| B2 | Persistent run records | Persist request, result, run metadata and verification hashes; list/get by project and run; reopen-store verification; append-only audit event. | B1 envelope and workspace schema/migration decision |
| B3 | Data hand-off | Reuse existing forecast adapters; expose forecast points and a simulation payload only where the underlying run actually produces them. | Forecast/simulation owner contracts |
| B4 | Annual replay | Carry an explicit optional annualisation assumption in a versioned request; return the existing verified projection when supplied. | B1 contract; preserve Liyue's economic boundaries |
| B5 | Dataset identity and provenance | Canonical source taxonomy, mapping rules, dataset ID/history digest and quality report references. | Data-import path audit |
| B6 | React/service integration | Document and test local API ownership, user/project/site mapping and error/session contracts without merging the two services prematurely. | B1/B2 and deployment boundary |

## 10. Recommended first implementation

Start with **B1 + the minimum B2 storage design**, not a new API server:

1. Resolve the page-06-versus-replay identity mismatch, then define the run envelope without forcing 05, 06 and 09 to share one run ID.
2. Decide how the canonical `run_id` and `manifest_sha256` are preserved when a record is written to the local workspace.
3. Add an immutable run-record persistence operation for the exact validated request and result, with schema version and integrity hashes.
4. Add list/get/reopen tests before wiring the UI.
5. Keep the existing transport stateless until its caller explicitly opts into a configured local workspace store.

No model output, annual basis, economic boundary, site validation or hardware-control capability is inferred by this audit.

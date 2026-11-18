# P0 Architecture Audit: End-to-End Product Path

**Audit date:** 2026-11-18  
**Audited revision:** `1bf8526eb95e9e415ac26405ba0eb8e6cf0195f3`  
**Scope:** Streamlit entry points, customer-facing pages, data/forecast/dispatch boundaries, local workspace boundary, and existing integration tests.

This is a static repository audit, not a claim that the hosted app or a physical site was runtime-tested.

## Executive finding

IslandOS has substantial working components, but the public product journey is still fragmented. The repository contains at least three distinct application paths:

1. The root `app.py` decision-lab path, with legacy energy-water screening, scenario forecasting, and experimental strategy modules.
2. The customer decision path in `pages/05_Customer_Decision_Dashboard.py`, using `forecast_engine`, `forecast_optimizer_adapter`, the energy-system optimizer, economics/impact assessment, and operator decision records.
3. The canonical-catalog joint-resource path in `pages/06_Forecast_Led_Joint_Resource_Optimizer.py`, using `forecast_signal_catalog` and `prediction_dispatch_adapter` to feed battery/diesel dispatch.

The code and README are appropriately candid that the five-step workflow is not yet one fully integrated customer journey. The P0 objective is therefore **one discoverable, reproducible, evidence-carrying path**, not another algorithm or dashboard.

## Evidence from the current code

| Area | Current implementation | P0 implication |
|---|---|---|
| Public app shell | `app.py` is a 97 KB Streamlit entry point. Its module docstring says the complete five-step workflow is not integrated. It directly imports experimental strategy code, `scenario_forecasting`, `app_workflow`, and legacy RO modules. | Keep this as a compatibility/demo surface during integration; do not silently treat it as the canonical runtime. |
| Customer decision page | `pages/05_Customer_Decision_Dashboard.py` parses customer history, calls `forecast_engine.forecast_signals`, then `forecast_optimizer_adapter`, the energy-system optimizer, economics, impact assessment and operator-decision recording. | This is a coherent existing decision path, but it uses a different forecast interface from page 06. |
| Joint resource page | `pages/06_Forecast_Led_Joint_Resource_Optimizer.py` calls `forecast_site_signals` from the canonical signal catalog and `optimize_prediction_resource_schedule`. | This is the strongest current candidate for the canonical forecast-to-dispatch path. Preserve its typed signal and unit contract. |
| Forecast service | `forecast_service.py` explicitly forecasts each signal independently, aligns the bundle and records limitations; it does not learn cross-signal causal or multivariate effects. | Product language must say coordinated/aligned multi-signal forecasting, not validated multivariate learning. |
| Canonical runtime | `canonical_runtime.py` exposes validated planning arrays from `ForecastService`. | Confirm whether it is used by the actual customer path or only as a library boundary; do not infer integration from its existence. |
| Data ingestion | `customer_dashboard.py` accepts a narrow hourly CSV contract: UTC timestamp, PV, wind, essential load and tariff. `onboarding.py` separately provides a broader canonical mapping/quality/provenance contract. | Avoid parallel upload semantics. Define one normalized site-history contract and explicit adapters from existing formats. |
| Persistent site workspace | `pages/08_Site_Workspace.py` is gated by `ISLANDOS_ENABLE_LOCAL_WORKSPACE=1`; it persists project/site/asset records locally. `pages/07_Local_Customer_Workspace.py` requires a configured loopback API. | These are local reference capabilities, not part of the public hosted demo's normal customer journey. |
| Device flexibility | `pages/09_Device_Flexibility_Planner.py` demonstrates device-task scheduling with its own synthetic scenario and energy accounting. | Treat as a separate bounded capability until it is deliberately connected to the shared project/run and comparison contract. |
| Integration tests | `tests/test_stage_f_canonical_workflow.py` proves a catalog forecast can feed the joint optimizer; `tests/test_canonical_runtime.py` tests the runtime facade. | Strong component-level handoff tests exist, but they do not prove a user can move from project setup and upload through economics and a final decision record in one workflow. |

## Confirmed architectural risks

### 1. Multiple forecast entry points

- `forecast_engine.forecast_signals` is used by the customer decision dashboard.
- `forecast_signal_catalog.forecast_site_signals` routes through the newer `PredictionEngine` / `ForecastService` path and is used by the joint resource optimizer.
- `scenario_forecasting` is still imported by the root app.

These are not interchangeable APIs. A migration must preserve each path's input validation, model provenance, backtest semantics, uncertainty representation and downstream schedule assumptions. The target should be one canonical forecasting service with explicit compatibility adapters, not a blind rename or wholesale replacement.

### 2. Multiple ingestion contracts

The narrow customer CSV adapter and the broader onboarding service solve overlapping but different problems. A customer can encounter different required columns depending on which page they open. The product needs one canonical normalized dataset object containing:
- UTC timestamps and cadence;
- canonical signal IDs and units;
- source type, source name and source hash;
- row-level and column-level quality findings;
- explicit missingness and rejected-field information.

Existing CSV formats should be adapted into this object; ambiguous units or missing measurements must remain unresolved rather than guessed.

### 3. No shared project-to-run spine across the visible pages

The local workspace stores project, profile, asset and audit information. The forecast/dispatch pages primarily operate on uploaded or session-shared data and page-local assumptions. The audit found no demonstrated end-to-end binding that guarantees a run is tied to a selected persistent project, immutable asset/configuration version, input digest, model version, optimizer configuration and final operator decision record.

The target run identity should carry at least:
`project_id`, `run_id`, input dataset SHA-256, normalized schema version, site/asset configuration version, forecast model IDs/versions, forecast horizon, optimizer/version/settings, scenario assumptions, result digest and decision-record reference.

### 4. The final decision evidence is not yet one shared output contract

The decision dashboard creates economics, impact assessment and operator records. The joint optimizer exposes a schedule handoff and its own output. The device planner produces a schedule table and charts. These outputs need a common, versioned run-result envelope before they can be compared or exported consistently.

### 5. Public and local deployment boundaries must remain explicit

The public demo is an offline planning/simulation surface. The local workspace and loopback API are intentionally gated. P0 must not weaken these boundaries or imply that public Streamlit is a secure customer data room, live telemetry gateway, or production controller.

## Recommended target architecture

Keep the existing domain modules. Add/strengthen a thin application orchestration boundary:

```text
Project + Site Profile + Versioned Assets
                 |
                 v
      Import / Normalize / Validate
                 |
                 v
       Immutable Dataset Manifest
                 |
                 v
      Canonical Forecast Service
                 |
                 v
       Forecast Evidence Bundle
                 |
                 v
      Resource Dispatch Adapter(s)
                 |
                 v
       Constraint / Service Checks
                 |
                 v
     Baseline vs Candidate Comparison
                 |
                 v
       Economics + Sensitivity
                 |
                 v
     Human Review + Decision Record
                 |
                 v
       Reproducible Export Package
```

The orchestration boundary should call existing tested modules; it should not duplicate forecasting, optimization or economics algorithms. It must fail closed when required signals, units, asset limits, service-equivalence evidence or provenance are missing.

## P0 implementation sequence and acceptance criteria

### P0.1 — Define canonical run contract

Create typed request/result structures for a single planning run. The request references a project/site version, normalized dataset manifest, selected asset configuration and explicit scenario settings. The result records all input and model digests plus structured outputs and limitations.

**Acceptance:** deterministic serialization and digest tests; missing provenance or mismatched units are rejected; no synthetic fallback occurs after an uploaded dataset fails validation.

### P0.2 — Build one orchestration service

Compose the existing onboarding/normalization, canonical forecast, supported dispatch adapter, service checks, paired comparison, economics and operator decision record. Keep page code limited to collecting inputs, calling the service and rendering the returned result.

**Acceptance:** one integration test executes the complete service path from a fixture dataset to a decision record and verifies that every stage shares the same `project_id` / `run_id` and input digest.

### P0.3 — Connect one user-facing golden path

Use the local site workspace as the project/configuration source where enabled; provide a clearly labelled demo project for public synthetic exploration. Connect a single upload flow to the canonical normalized dataset and run service. Do not make the public app depend on a local-only API.

**Acceptance:** a new user can follow one documented route without switching between pages to re-upload or re-enter the same assumptions; the interface clearly distinguishes synthetic demo, customer-provided, public and measured data.

### P0.4 — Standardize decision export

Export a machine-readable run package and a concise human-readable report from the same result object. Include assumptions, rejected/flagged data, forecast backtest evidence, constraints, baseline/candidate service equivalence, economics inputs, sensitivity, limitations and human approval status.

**Acceptance:** exported package verifies its hashes and can be replayed or inspected without relying on Streamlit session state.

### P0.5 — Deprecate only after parity

Once the canonical path passes parity tests, mark overlapping legacy routes as compatibility/demo paths and remove them only in a separate reviewed change.

**Acceptance:** no supported customer-facing workflow is lost; tests prove parity for the scenarios retained.

## Explicit non-goals

- Do not merge forecasting implementations before mapping their contracts and demonstrating parity.
- Do not add another forecasting model or optimizer as part of P0.
- Do not refactor the 97 KB root app wholesale.
- Do not claim site-specific accuracy, real customer savings, field validation, production security or device actuation.
- Do not move confidential site data into the public hosted demo.

## Audit conclusion

The immediate bottleneck is application integration and evidence continuity, not a lack of algorithms. The next engineering change should implement the canonical run contract and orchestration boundary, then connect one golden path. All other pages should be treated as bounded capabilities until they consume and emit that shared contract.

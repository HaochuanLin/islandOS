# IslandOS Product Architecture and Desktop Strategy

**Status:** Product architecture decision (initial)
**Applies to:** Generic IslandOS product; competition and pilot scenarios are examples only.
**Primary principle:** One Core Engine, Multiple Interfaces.

## 1. Product direction

IslandOS is an energy-intelligence and decision-support application for energy-constrained sites and distributed infrastructure. Its workflow is:

1. Acquire data with minimal operator effort.
2. Validate provenance, units, time alignment, freshness, and physical plausibility.
3. Build a versioned asset and operating-constraint model.
4. Forecast relevant signals where data and validation support it.
5. Simulate candidate operating policies using explicit physical balances.
6. Optimize only within approved constraints.
7. Explain trade-offs and preserve a reproducible audit record.

The product is decision support. The current prototype must not be represented as a certified controller, a validated digital twin, or a guarantee of savings.

## 2. Streamlit is the product laboratory, not the product boundary

The existing Streamlit application remains valuable. It is the fastest place to test workflows with users, compare interface ideas, inspect model outputs, and expose regressions.

However, Streamlit must not own domain logic. It is an experimental presentation adapter.

**Allowed in Streamlit layer**
- Page layout, navigation, forms, charts, tables, and downloads.
- Session state and temporary UI selections.
- Calling application services and rendering their results.
- Clear disclosure of synthetic, measured, public, and forecast data.

**Not allowed as the long-term architecture**
- Physics, optimization, data validation, or business rules implemented only inside `app.py`.
- Hidden assumptions that exist only in widget defaults.
- Device-specific protocol parsing embedded in page code.
- Treating browser session state as the authoritative customer database.

A Streamlit experiment is promoted into the shared product only after its behavior is moved behind a tested core/service boundary.

## 3. Target architecture

```text
                 +-----------------------------+
                 |       User Interfaces       |
                 | Streamlit Lab | Windows App |
                 +---------------+-------------+
                                 |
                 +---------------v-------------+
                 |       Application Services  |
                 | onboarding / import / runs  |
                 | reports / asset management |
                 +---------------+-------------+
                                 |
        +------------------------v-------------------------+
        |                 IslandOS Core                     |
        | canonical models | validation | physics | forecast|
        | constraints | optimization | decisions | audit    |
        +------------------------+-------------------------+
                                 |
                 +---------------v-------------+
                 |       Adapter Interfaces    |
                 | CSV/XLSX | API | protocols  |
                 | weather/tariff | databases  |
                 +---------------+-------------+
                                 |
                 +---------------v-------------+
                 |       Storage & Security     |
                 | local files | SQLite | logs  |
                 +-----------------------------+
```

### Architectural rules

- Core modules must be importable without importing Streamlit or desktop UI libraries.
- UI layers call application services; they do not implement domain rules.
- Adapters translate external formats into canonical IslandOS models.
- Every imported or inferred value carries provenance and a quality state.
- Safety-critical constraints are represented explicitly and enforced before optimization.
- Every analysis run can be reconstructed from an immutable input/configuration snapshot plus software/model version identifiers.
- Optional integrations must fail closed: an unavailable connector cannot silently substitute fabricated live data.
- The same core service call should produce the same domain result regardless of whether it is invoked from Streamlit, a desktop UI, or a CLI (subject to explicitly recorded stochastic seeds).

## 4. Streamlit laboratory acceptance loop

Every new user-facing capability follows this loop:

1. **Hypothesis:** state which user burden or decision problem is being addressed.
2. **Core contract:** define input schema, output schema, error states, provenance, and safety constraints.
3. **Tests first:** cover valid, invalid, incomplete, stale, ambiguous, and boundary inputs.
4. **Streamlit experiment:** expose the capability with a small, understandable workflow.
5. **Evaluation:** test with synthetic fixtures and, when authorized, representative customer data.
6. **Promotion:** keep the tested service/core implementation; Streamlit remains one consumer.
7. **Desktop parity:** verify that the desktop interface can call the same service without duplicating logic.

A feature is not complete merely because its Streamlit page renders.

## 5. Data onboarding and trust

IslandOS should minimize manual entry without silently guessing.

Preferred acquisition order:
1. Read-only connection to a supported and explicitly tested source.
2. Import existing CSV/XLSX and parse PDF documents where extraction is reliable.
3. Match device model/specification metadata, while distinguishing vendor ratings from installed site configuration.
4. Infer candidate values only when the inference method and uncertainty are visible.
5. Ask the operator to confirm only the missing or decision-critical information.
6. Provide an expert override with reason, source, author, and timestamp.

Every field should carry, where applicable:
- value and canonical unit;
- source type (measured, customer-provided, vendor specification, public, inferred, synthetic, forecast);
- source reference and source timestamp;
- ingestion timestamp;
- validation state and quality flags;
- confidence/uncertainty where meaningful;
- confirmation state and change history.

Completeness is not accuracy. Model readiness must be task-specific and based on required inputs, not a single average data-quality percentage.

## 6. Asset and constraint model

Each asset should have a versioned record separating:

- **Nameplate/vendor specification:** published equipment ratings.
- **Installed configuration:** what is actually installed at this site.
- **Observed operating envelope:** behavior supported by measurements.
- **Hard constraints:** limits that must never be violated by a recommendation.
- **Operational constraints:** site rules that apply by default.
- **Soft preferences:** objectives that may be traded off and explained.
- **Maintenance/availability state:** whether the asset can participate in a scenario.

Unknown safety-critical constraints must not be silently filled with optimistic defaults. If required constraints are missing, the relevant optimization must be blocked or restricted to an explicitly conservative, non-operational screening mode.

## 7. Desktop application strategy

The intended customer deliverable includes a Windows desktop application. The desktop interface is a separate shell over the shared core, not a second implementation of IslandOS.

Initial desktop direction:
- Keep the core as a normal Python package with no UI dependency.
- Evaluate a native desktop UI (for example, PySide6) after core/service contracts stabilize.
- Use a dedicated application entry point; do not package `streamlit run app.py` as the customer desktop architecture.
- Use a local SQLite database for local projects, metadata, and run indexes where appropriate.
- Store customer files and configuration in OS-approved user-data directories, not beside the executable.
- Keep secrets out of source code, logs, and exported reports.
- Package a Windows build in CI (initially evaluate PyInstaller) and test it on a clean Windows environment.
- Provide signed installers and a controlled update process before commercial distribution.

A first EXE is a packaging milestone, not proof of device compatibility, safety certification, or production readiness.

## 8. Security, privacy, and operational boundaries

- Default device integration to read-only.
- Never enable control writes through a data-import connector.
- Separate user authentication, authorization, and device credentials.
- Encrypt network transport; document local data protection and backup limitations.
- Provide export and deletion workflows and define retention behavior.
- Keep tenant/site data isolated if multi-customer cloud hosting is introduced.
- Record who changed critical asset parameters and who approved a recommendation.
- Recommendations must show assumptions, constraints, data freshness, and unresolved issues.
- Any future control capability requires a separate safety case, site engineering approval, independent interlocks, operator authorization, manual override, and emergency stop. It is out of scope for the current decision-support prototype.

## 9. Definition of done for a promoted feature

A feature can move from Streamlit experiment to shared product only when:
- domain logic lives outside UI code;
- canonical input/output contracts are documented;
- validation and failure states are explicit;
- automated tests cover normal and adversarial cases;
- data provenance and assumptions are visible;
- the Streamlit workflow is usable;
- a non-Streamlit caller can invoke the same service;
- no claim exceeds the evidence produced by the tests.

## 10. Non-goals for the current phase

- Universal plug-and-play support for all vendors.
- Autonomous write control of industrial equipment.
- Guaranteed cost savings or bankable financial projections.
- Treating synthetic demonstrations as measured site performance.
- Adding complex AI models before transparent baselines and evaluation exist.

## 11. Immediate implementation sequence

1. Audit existing core modules and identify duplicate/overlapping contracts before creating new abstractions.
2. Define canonical provenance-aware data and asset/constraint schemas.
3. Build a deterministic import-and-validation service for CSV/XLSX.
4. Add task-specific model-readiness gates.
5. Add immutable run manifests and audit records.
6. Refactor Streamlit incrementally to call those services.
7. Add a headless CLI smoke path to prove the core runs without Streamlit.
8. Prototype the Windows shell only after service boundaries are stable.

This document is an architecture baseline. Implementation status must be tracked separately; describing a planned component here does not mean it already exists.

## 12. Headless core smoke path

The shared onboarding and local workspace services can be exercised without
starting Streamlit:

```bash
python tools/islandos_core_smoke.py
```

This uses only synthetic in-memory CSV data and a temporary SQLite workspace.
It verifies import readiness, project creation with explicit metadata consent,
metadata-only artifact registration, run-manifest creation, and audit-chain
verification. It also fails if Streamlit has been imported. The smoke path is
an architecture check, not a customer deployment or desktop packaging test.


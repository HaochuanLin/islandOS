# Stage E preparation — service, identity, persistence and device boundary

Stage E is the productization and integration layer after Stage D has a repeatable offline coordination workflow. It must not be used to imply that IslandOS is already a production cloud service or a live controller.

## Stage E target architecture

### 1. Service boundary
- Extract stable application services from Streamlit page code: onboarding, forecast execution, coordination, comparison, audit export.
- Define versioned request/response schemas for each service.
- Keep domain logic in `islandos_core`; web/API layers should call it rather than reimplement it.
- Add idempotency keys and explicit job states for long-running forecast/optimization work.

### 2. Identity and customer isolation
- Introduce authenticated users, organizations/tenants, sites and role-based access.
- Enforce tenant scoping in every database query and every file/object access path.
- Separate viewer, analyst, site-admin and platform-admin permissions.
- Add audit records for login, upload, configuration changes, exports and approvals.
- Do not expose customer uploads through the public demo.

### 3. Persistence and data lifecycle
- Replace local demo SQLite metadata with a managed relational store only after a deployment threat model and migration plan exist.
- Store raw customer data in private object storage with encryption, retention controls and deletion workflows.
- Keep immutable provenance metadata: source, owner/tenant, units, timezone, cadence, schema version, content hash and import report.
- Define backup, restore, disaster recovery and tenant export/delete procedures before customer onboarding.

### 4. Device integration boundary
- Begin with read-only telemetry ingestion through a connector/gateway interface.
- Authenticate devices, rotate credentials, validate signed/authorized source identity, timestamps, units, replay and freshness.
- Normalize telemetry to the existing signal/asset contracts; stale or contradictory states must fail closed.
- Keep device write/control disabled by default. A later write path requires a separate threat model, command allow-list, human approval, interlocks, acknowledgement, rollback and independent safety review.

### 5. Operations and security
- Add secrets management, TLS, least-privilege service identities, dependency/SBOM monitoring and security event logs.
- Add health/readiness endpoints, structured logs, metrics, tracing, rate limits and abuse protection.
- Add CI deployment gates, environment separation, migrations, backup verification and incident response procedures.

## Suggested Stage E acceptance gates

1. API schemas and service tests are stable and versioned.
2. Tenant-isolation tests prove cross-tenant reads/writes are denied.
3. Upload storage is private, encrypted, retention-bounded and deletable.
4. Authentication, authorization, audit and secrets handling pass security review.
5. Read-only telemetry connector passes contract, replay, stale-data and disconnect tests.
6. Deployment, backup/restore and incident runbooks are exercised.
7. Device writes remain unavailable until a separate safety and authorization programme is approved.

## Explicit exclusions

No public production SaaS claim, customer-data security guarantee, multi-tenant isolation claim, verified savings claim, equipment command, remote actuation, safety certification or autonomous operation is made by this preparation document.

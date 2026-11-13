# Stage E — local service, identity and read-only telemetry reference

## Delivered in this repository

Stage E now has a runnable, versioned reference API in `islandos_service_api.py`.

### API v1

- `GET /api/v1/health` — API version, service mode and explicit disabled device-write status.
- `POST /api/v1/auth/register` — controlled first-tenant bootstrap; disabled unless `--allow-registration` is supplied.
- `POST /api/v1/auth/login` — PBKDF2-HMAC-SHA256 password verification and opaque expiring bearer session.
- `GET /api/v1/sites` / `POST /api/v1/sites` — tenant-scoped site metadata.
- `POST /api/v1/sites/{site_id}/telemetry` — authenticated, read-only, normalized telemetry ingestion.
- `GET /api/v1/sites/{site_id}/telemetry/latest` — tenant-scoped latest telemetry.
- `DELETE /api/v1/sites/{site_id}` — owner-only site deletion, cascading telemetry deletion.
- `GET /api/v1/members` — tenant-scoped member listing.
- `POST /api/v1/members/invitations` — owner-only invitation creation for analyst/viewer roles; returns a one-time token to the caller and does not send email.
- `POST /api/v1/members/invitations/accept` — single-use, expiring invitation acceptance and account creation.
- `POST /api/v1/members/{user_id}/role` / `DELETE /api/v1/members/{user_id}` — owner-only role changes and member removal.
- `GET /api/v1/notifications` — tenant/user-scoped inbox with unread filtering and bounded page size.
- `POST /api/v1/notifications` — analyst/owner event creation with category, severity, optional site/user target and JSON payload.
- `POST /api/v1/notifications/{notification_id}/read` — mark an accessible inbox item as read.

### Identity, authorization and audit

- Each initial registration creates an isolated tenant and owner account.
- Passwords are salted and hashed with PBKDF2-HMAC-SHA256; plaintext passwords are never stored.
- Bearer tokens are random, only token hashes are persisted, and sessions expire after 12 hours.
- Site and telemetry queries always include the authenticated tenant ID.
- Viewer cannot create or delete sites; analyst/owner can create; only owner can delete.
- Login, tenant creation, site creation/deletion, telemetry ingestion, invitations, member changes, notification creation and read acknowledgements produce audit events.
- Unknown or cross-tenant site IDs return the same not-found response.

### Persistence and lifecycle

- SQLite stores account/session records, site metadata, normalized telemetry and audit events.
- The database file is created with owner-only permissions where the host OS supports them.
- Foreign-key cascade removes site telemetry when a site is deleted.
- Raw CSV uploads and original customer files are not stored by this service.
- Invitation tokens are stored only as SHA-256 hashes and are single-use/expiring. Invitation delivery is not implemented; an authorized caller must deliver the one-time token through a separately approved channel.
- Notifications are persisted inbox records; there is no email/SMS/push delivery scheduler.
- The reference implementation is single-host and uses local disk; it is not a managed database or encrypted object-storage deployment.

### Read-only telemetry

- Reuses the canonical `validate_telemetry` contract for timestamps, freshness, units/fields and finite numeric values.
- Duplicate site/timestamp observations are rejected.
- API responses explicitly state `physical_write_performed: false`.
- Existing loopback-only telemetry gateway remains separate and unchanged; this API does not discover devices or establish vendor connectivity.

## Run locally

Python 3.11 environment with the project runtime dependencies installed:

```bash
python islandos_service_api.py --host 127.0.0.1 --port 8766 --database build/islandos-service.sqlite3 --allow-registration
```

Enable registration only for controlled bootstrap. After creating the initial tenant, stop the process and restart without `--allow-registration`. Do not expose this reference service to a LAN or public internet. It binds to loopback only; there is no built-in TLS termination, production secret manager, rate limiter, MFA, email verification or password reset flow.

Example bootstrap and login:

```bash
curl -X POST http://127.0.0.1:8766/api/v1/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"operator@example.test","password":"use-a-long-unique-password","tenant_name":"Demo utility"}'

curl -X POST http://127.0.0.1:8766/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"operator@example.test","password":"use-a-long-unique-password"}'
```

Use the returned access token as `Authorization: Bearer <token>` for protected endpoints.

## Validation

`tests/test_islandos_service_api.py` covers independent tenants, cross-tenant denial, login/session validation, telemetry validation and duplicate rejection, and cascading site deletion. `tests/test_stage_e_members_notifications.py` covers single-use/expiry invitation lifecycle, owner-only role management, member removal, tenant/user-scoped notifications, read state, and payload validation. Existing gateway integration tests continue to cover the local read-only HTTP telemetry ingress. CI remains the final merge gate.

## Production gaps — do not claim these are complete

- Replace local SQLite with a managed relational database and reviewed migration/backup/restore procedures.
- Add TLS termination, managed secrets, rate limiting, MFA, email verification, password reset, session revocation and security monitoring.
- Add explicit per-role site membership and finer-grained authorization if tenant-wide roles are insufficient.
- Add encrypted private object storage, retention schedules and verified export/deletion workflows for uploaded source files.
- Add authenticated device identity, key rotation, signed messages and device-specific protocol adapters before connecting field equipment.
- Run threat modelling, penetration testing, privacy review and deployment/incident exercises.

## Hard safety boundary

No device command endpoint exists. No PLC setpoint or actuator write is implemented. The optimizer remains offline decision support; telemetry ingestion is read-only. Any future actuation requires a separate hazard analysis, command allow-list, independent interlocks, human authorization, acknowledgement/rollback and controls-engineering sign-off.

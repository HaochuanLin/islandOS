# Shared deployment assessment — Customer Console

Status: assessment only. Nothing in this document has been implemented, and the
service still refuses every non-loopback bind. Read it as "what would have to
change before a shared deployment is even safe to evaluate", not as a plan of
record.

Evidence base: `islandos_service_api.py` (`main` at `9615d82`), `frontend/vite.config.ts`,
`docs/STAGE_6_CUSTOMER_FRONTEND.md`, and the acceptance records under
`docs/evidence/`.

## 1. What is enforced today

| Control | Implemented | Evidence |
|---|---|---|
| Loopback-only listener | Yes, hard refusal | `main()` errors unless `--host` is `127.0.0.1`, `::1` or `localhost` |
| Console dev server binding | Yes | `vite.config.ts` sets `host: "127.0.0.1"` and `strictPort` 5173 |
| Password storage | PBKDF2-SHA256, 240,000 iterations, per-user salt | `PASSWORD_ITERATIONS`, `_password` |
| Session tokens | Random bearer token, stored as SHA-256 hash, 12-hour TTL, per-session revoke | `TOKEN_TTL_SECONDS`, `authenticate`, `logout` |
| Role checks | `owner` / `analyst` / `viewer` enforced server-side | `create_site`, `create_invitation`, `update_member_role` |
| Tenant scoping | Every customer query filtered by `tenant_id` | store methods; `test_service_api_site_creation_roles.py` |
| Audit trail | `audit_events` rows for register, login, logout, site, telemetry, member, notification actions | `_audit` call sites |
| Physical device writes | Absent; health advertises `device_write_enabled: false` | `health` route; no command endpoints |

## 2. What is missing for a shared deployment

### 2.1 TLS termination and authentication gateway

- Current: plain HTTP on loopback; no certificate, no reverse proxy, no gateway, no CORS policy beyond same-origin.
- Risk if exposed: bearer tokens and passwords travel in clear text; any proxy misconfiguration becomes credential exposure. The code's own error message says a reviewed TLS/auth gateway is required.
- Prerequisites: a gateway that terminates TLS, forwards only to loopback, sets a strict host allow-list, and passes through `Authorization` without rewriting it. Session handling must stay unchanged, because the service reads the header directly.

### 2.2 Multi-user remote access

- Current: `ThreadingHTTPServer` with SQLite and no connection pooling; `IslandOSStore` serialises writes with an `RLock` per process. One process, one machine, no horizontal scale.
- Not tested: concurrent users from different machines, load behaviour, latency, or SQLite write contention under realistic traffic.
- Risk: SQLite locking under concurrent writes (`database is locked`), and the single process becoming the bottleneck. Streaming and timeouts are untuned.
- Prerequisites: a load test with several tenants, a decision on whether SQLite remains acceptable, and a process model (single writer vs. managed database) before any shared claim.

### 2.3 Database migration and backup

- Current: `_initialize` runs `CREATE TABLE IF NOT EXISTS` for eight tables at every start. There is no schema-version table, no `ALTER TABLE`, no migration runner. The only backup path is `scripts/backup_service_db.py` (proposed in a separate PR): manual, same disk, online backup API plus `PRAGMA integrity_check`, no schedule and no retention.
- Not verified: restore on a different machine, backup under sustained write load, corrupted-page recovery, or point-in-time restore.
- Risk: a schema change applied by hand can leave rows that no code path can read; a disk failure loses the database and its backups together.
- Prerequisites: a migration mechanism with a recorded schema version, an off-machine backup target, a scheduled job, and a restore drill whose result is recorded. Until a restore has actually been performed, no data-safety claim is justified.

### 2.4 Session access control

- Current: bearer token in browser memory, 12-hour TTL, per-session revoke, no refresh token, no device list, no concurrent-session limit, no lockout after failed logins, no rate limiting.
- Risk: stolen or leaked tokens stay valid up to 12 hours; there is no way to enumerate or revoke all sessions for a user; brute-force attempts are unlimited.
- Prerequisites: login throttling with a documented lockout policy, a "revoke all sessions" operation, shorter TTLs with explicit re-authentication, and transport security from 2.1.

### 2.5 Logging, audit and monitoring

- Current: `audit_events` inside the same database records business actions; `log_message` writes method, path and status to stderr, with no bodies or tokens. There is no metrics endpoint, no alerting, no log rotation, and audit rows share the database they describe.
- Risk: an incident investigation depends on files the attacker may have deleted; there is no signal for failed-login spikes or 5xx rates.
- Prerequisites: append-only log shipping off the host, metric export for request rate/latency/errors, alert thresholds, and a retention policy. Audit rows should be exported before they are relied on.

## 3. Exit criteria before calling anything "shared"

1. A named gateway terminates TLS, binds only loopback upstream, and has a tested configuration.
2. A restore from backup has been performed and recorded, including row counts and sign-in.
3. A migration has been applied to a copy of real data and verified with tests.
4. Login throttling and session revocation cover the documented scenarios.
5. Audit records leave the host and survive its loss.
6. A load test with several concurrent tenants has results that are published, not assumed.

Until all six hold, the honest description remains: single-host reference service, local only, no production security claims.

## 4. Non-claims

This document does not assert site validation, customer usage, remote access, production readiness, MFA/SSO, or any availability target. The public Streamlit demo is a different surface and does not share this database.

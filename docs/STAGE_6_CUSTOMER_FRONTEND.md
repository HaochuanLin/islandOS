# Stage 6 — React customer console

## Delivered increment

This branch adds a React + TypeScript customer-facing console under `frontend/`. It is intentionally separate from the Streamlit engineering/simulation workspace.

The console currently supports:
- Authenticated sign-in and sign-out against the existing local reference API.
- Tenant-scoped site listing and site creation with an explicit timezone.
- Latest validated telemetry display for a selected site.
- Recent notifications and mark-as-read workflow.
- API connectivity state, empty states, refresh, and readable error feedback.
- Responsive desktop and mobile layouts.

## Run locally

One command starts both loopback services, waits for the API health check, and records the PIDs:

```powershell
.\scripts\start_console.ps1        # API 127.0.0.1:8766, console 127.0.0.1:5173
.\scripts\start_console.ps1 -Stop  # stop both
```

Registration stays closed by default. A new environment needs one bootstrap window; stop and restart without the flag afterwards:

```powershell
.\scripts\start_console.ps1 -BootstrapRegistration
```

The console's `/api` proxy follows `-ApiPort` through the `ISLANDOS_API_TARGET` environment variable read by `vite.config.ts`; without it the default stays `http://127.0.0.1:8766`.

The manual equivalent remains:

1. Start the local reference API: `python islandos_service_api.py --host 127.0.0.1 --port 8766`.
2. Create the initial owner through the controlled bootstrap procedure described by the API operator; registration is disabled by default.
3. In `frontend/`, run `npm install`, then `npm run dev`.
4. Open `http://127.0.0.1:5173`. Vite proxies `/api` to the loopback API at port 8766.

Build with `npm run build`; the static output is written to `frontend/dist`.

## Database lifecycle and backup

Everything the console stores lives in one SQLite file selected by `--database` (default `build/islandos-service.sqlite3`). The behaviour below is asserted by `tests/test_service_db_lifecycle.py` and `tests/test_service_db_backup.py`.

| Situation | Actual behaviour |
|---|---|
| Normal start on an existing file | `IslandOSStore._initialize` runs `CREATE TABLE IF NOT EXISTS` for the eight tables on every start. Reopening a file keeps users and sessions; there is no schema-version table, no `ALTER TABLE`, and no migration step. A schema change needs a deliberate migration or a new database file. |
| Restart or clean shutdown | Rows survive because they are on disk. Sessions survive too, but each token expires after 12 hours and the browser keeps it in memory only, so a reload requires a fresh sign-in. |
| Database file missing | The service creates a new empty database and starts; it does not restore or warn. Every tenant, user, site, telemetry row and audit event is gone. |
| Database file corrupt | Startup fails closed with `sqlite3.DatabaseError` before serving requests. The file is left untouched; there is no automatic repair. |
| Backup while running | `python scripts/backup_service_db.py` uses SQLite's online backup API and runs `PRAGMA integrity_check` on the copy, then reports the path, byte size and per-table row counts as JSON. |
| Restore | Manual: stop both services, replace the database file with the backup, start again. The test suite copies a backup into a new path, opens it through `IslandOSStore`, and signs in with the account it contained. |

```powershell
python scripts/backup_service_db.py
# -> {"backup_path": "build\\backups\\islandos-service-20261125T130000Z.sqlite3", "integrity_check": "ok", ...}
```

Limits that remain: backups sit on the same disk as the database, so they cover a bad migration or a mistaken delete, not disk loss; there is no schedule, no retention policy, and no off-machine copy. The API exposes no export route for tenants, sites, telemetry or audit events — the CSV downloads in the repository belong to the Streamlit workspace, not to the console. That is a gap, not a feature.

## Tenant export and audit retention

`GET /api/v1/export` returns one tenant's rows as a single JSON object: tenant, members (id, email, role, created_at), sites, telemetry (parsed values), invitations and audit events, plus `schema_version`, `exported_at` and `physical_write_performed: false`. Only an `owner` may call it; `analyst` and `viewer` receive 403, and a caller without a bearer token receives 401. The payload is built from `WHERE tenant_id = ?` queries only, so one tenant's export never contains another tenant's rows. Password hashes, salts, session token hashes and invitation token hashes are never included. The call records a `tenant.export` audit event with the exported site and telemetry counts, so an export leaves a trail.

```powershell
curl.exe -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8766/api/v1/export
```

Audit retention decision: audit events are kept indefinitely inside the same database as tenant data; there is no purge job, no rotation, no retention window and no export-to-append-only sink. An owner can copy them out through `/api/v1/export`, but nothing ships them off the machine, so a deleted or corrupted file loses the trail with the data. Retention, offsite shipping and an independent audit store stay open items rather than claimed behaviour.

The route is asserted by `tests/test_service_api_export.py`: owner 200 with the tenant's rows, analyst and viewer 403, no token 401, and two tenants whose exports never contain each other's sites.

## Security and deployment boundary

- The browser keeps the bearer token in component memory only; a page reload requires a new sign-in.
- The API remains a single-host loopback reference service with SQLite persistence.
- The Vite proxy is for local development only. A deployment must serve the built assets and proxy `/api` through a same-origin, TLS-terminated, reviewed gateway.
- Do not expose the current Python reference API directly to the public internet.
- The console does not claim production multi-tenant SaaS readiness, SSO, MFA, external email delivery, or equipment write access.
- The current API does not yet expose optimization-run, dispatch-plan approval, historical analytics, or full asset-management endpoints. Those must be added and tested before corresponding UI claims are made.

## Verification

The frontend CI workflow runs dependency installation and a production TypeScript/Vite build. This validates compilation and bundling, not browser usability, security penetration testing, or production deployment.

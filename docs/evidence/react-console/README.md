# React console acceptance — 2026-11-24

Local reference console, not the judged public demo. Run against an empty disposable SQLite
database, a temporary owner tenant, one site and one unread notification. The API was bound to
`127.0.0.1:8766`; Vite served the console at `127.0.0.1:5173`. The database and services were
removed after the run.

Result: **4/4 passed**, no blocking defect, no page-level exception.

| Check | Result |
|---|---|
| Invitation and pending row | Viewer invitation created; the stored row was `viewer`, expired in 7 days, and its token SHA-256 matched the token shown once. A duplicate invite to the same email was rejected with `an invitation for this email already exists`. Acceptance removed the pending row and added the member as `viewer`. |
| Role and invalid input | A Viewer invitation stored `viewer`; changing the accepted member to Analyst persisted. `not-an-email` was blocked by the browser (`typeMismatch=true`, zero requests); the API also returned 400. The API rejected role `admin` with 400 for both invitation and member update. |
| Telemetry | The panel first showed `NO DATA` / `No telemetry received` and `—` in the metric card. A current timestamp −8 s POST returned 202 with `physical_write_performed=false`; after Refresh the panel showed `VALIDATED RECORD`, `12.5 / 3.2 / 18`, and `Source: acceptance-harness`. |
| Error banner | `.error-banner` was false at all seven steps; `pageerror` count was 0. Empty-site `telemetry/latest` 404s are the documented “no data yet” path, mapped to `null` in `frontend/src/api.ts`. |

Known UI gap at acceptance time: the console had no pending-invitation list, so the pending row was
verified through the database and the duplicate-invite rejection. The result panel also did not
echo the invitee email and role. These are product gaps, not test failures. A separate follow-up
change is tracked outside this evidence set.

## Files

| File | Shows |
|---|---|
| `01-signed-in.png` | Owner signed in, site overview. |
| `02-site-no-telemetry.png` | Empty telemetry state (`NO DATA`). |
| `03-invitation-created.png` | One-time invitation token; **the token itself is redacted**. |
| `04-invalid-email.png` | Browser-side invalid-email block. |
| `05-duplicate-invitation.png` | Duplicate invitation rejected inline. |
| `06-role-changed.png` | Member role changed to Analyst. |
| `07-telemetry-record.png` | Validated telemetry record after Refresh. |
| `summary.json` | Machine-readable result summary without IDs, emails or tokens. |

Screenshots in this folder were copied from the acceptance run. The invitation token was painted
out before committing; no password, full tenant/user ID or one-time token is stored here.

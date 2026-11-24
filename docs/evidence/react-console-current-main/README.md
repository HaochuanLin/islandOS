# Current-main React console addendum — 2026-11-24

Current `main` at `f45308a`, after PR #341 added the pending-invitation list and the
single-probe site refresh. Local empty SQLite database, API on `127.0.0.1:8766`, Vite on
`127.0.0.1:5173`, Playwright from login through invitation creation.

Result: **pass**, no error banner and no page-level exception.

- The owner created a Viewer invitation for `colleague@example.com`. The console then showed a
  `PENDING INVITATIONS` row with the email, `Invited as viewer`, the expiry and `PENDING`.
- The invitation result echoed `Invited colleague@example.com as viewer.`; the one-time token is
  present in the UI but replaced with `[one-time token redacted]` for this screenshot.
- Creating the empty site produced **one** `GET /api/v1/sites/<site>/telemetry/latest` request,
  returning 404 and mapping to the documented “no data yet” state. It did not produce the former
  duplicate probe.
- The token-free `/api/v1/members/invitations` response had one pending row with keys
  `created_at, email, expires_at, invitation_id, role`; no `invitation_token` field.

## File

| File | Shows |
|---|---|
| `01-pending-invitation-and-echo.png` | Pending Viewer invitation, result echo, and redacted token. |
| `summary.json` | Counts and assertions without tenant/site IDs or tokens. |

Test email only; no full tenant ID, site ID, bearer token or invitation token is stored.

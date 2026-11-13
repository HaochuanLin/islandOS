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

1. Start the local reference API: `python islandos_service_api.py --host 127.0.0.1 --port 8766`.
2. Create the initial owner through the controlled bootstrap procedure described by the API operator; registration is disabled by default.
3. In `frontend/`, run `npm install`, then `npm run dev`.
4. Open `http://127.0.0.1:5173`. Vite proxies `/api` to the loopback API at port 8766.

Build with `npm run build`; the static output is written to `frontend/dist`.

## Security and deployment boundary

- The browser keeps the bearer token in component memory only; a page reload requires a new sign-in.
- The API remains a single-host loopback reference service with SQLite persistence.
- The Vite proxy is for local development only. A deployment must serve the built assets and proxy `/api` through a same-origin, TLS-terminated, reviewed gateway.
- Do not expose the current Python reference API directly to the public internet.
- The console does not claim production multi-tenant SaaS readiness, SSO, MFA, external email delivery, or equipment write access.
- The current API does not yet expose optimization-run, dispatch-plan approval, historical analytics, or full asset-management endpoints. Those must be added and tested before corresponding UI claims are made.

## Verification

The frontend CI workflow runs dependency installation and a production TypeScript/Vite build. This validates compilation and bundling, not browser usability, security penetration testing, or production deployment.

# Stage E — local customer workspace UI

## Delivered slice

`pages/07_Local_Customer_Workspace.py` provides a Streamlit interface for the existing local reference API:
- owner sign-in and optional local tenant bootstrap;
- tenant-scoped member listing;
- owner invitation creation with the one-time invitation token displayed for manual delivery;
- member role updates and removal;
- notification inbox, unread filtering, and mark-as-read actions.

The bearer token is kept in Streamlit session state and is not written to a local file by this page. The page uses the API's existing authorization and tenant-scoping checks rather than duplicating them in the UI.

## Deliberate deployment boundary

The page requires `ISLANDOS_API_BASE_URL` and accepts only an explicit loopback HTTP URL. The local API is a single-host, loopback-only SQLite reference service. The public Streamlit demo does not host or expose that API, so this page does not turn the public demo into a working multi-user SaaS application. Do not expose the local API externally or configure a remote URL.

Registration remains controlled by the API's existing `allow_registration` bootstrap flag. Invitation tokens must be delivered manually through an approved channel; no email/SMS provider is connected.

## Still open for production

MFA/SSO, TLS termination, managed database, secret management, credential rotation, server-side session revocation UX, external invitation delivery, production audit retention, and security review remain unimplemented. This page is a local integration UI, not production identity infrastructure.

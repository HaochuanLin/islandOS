# Stage 7 — customer and workspace workflows

## Delivered slice

The React customer console now includes workspace membership operations backed by the existing tenant-scoped reference API:
- View members in the current tenant.
- Owner-only invitation creation for analyst/viewer roles.
- Owner-only role changes and member removal.
- Explicit one-time invitation token display and expiry.
- Role-aware read-only behavior for non-owner users.

## Important service boundary

The reference API does not send email. The owner must deliver the invitation token through an approved private channel. Invitation acceptance is available through the API endpoint; a complete managed identity lifecycle, external email delivery, MFA/SSO, and production tenant operations are not claimed. The API remains a loopback-only single-host reference service.

## Verification

The React production build checks TypeScript and bundling. The Python service tests cover tenant isolation, role restrictions, invitation lifecycle, and session behavior. A browser end-to-end test and production identity review remain outstanding.

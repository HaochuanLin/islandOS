# Stage 9 — persistent shadow evidence

## Delivered software slice

`islandos_core.shadow_evidence.ShadowEvidenceStore` persists validated read-only shadow comparison reports in a local SQLite ledger. It:
- Requires the existing shadow report mode and valid report digest.
- Rejects any report that does not explicitly set `device_write_authorized=false` and `command_generated=false`.
- Prevents duplicate (site, recommendation, observation) identities.
- Appends records with a SHA-256 hash chain.
- Provides per-site recent evidence queries and full-chain verification.
- Detects accidental or direct database tampering when the chain is verified.

## Security and field boundary

This is a local evidence ledger, not WORM storage or protection against a privileged host administrator. It is not a live sensor connector, scheduler, alert router, or site trial. Evidence should be exported and independently retained under a site-approved retention policy before it is relied on. No physical device writes or automatic corrections exist.

## Verification

Tests cover append order, duplicate rejection, report digest validation, no-write invariants, tamper detection, and query bounds. Passing tests do not establish live data quality or field acceptance.

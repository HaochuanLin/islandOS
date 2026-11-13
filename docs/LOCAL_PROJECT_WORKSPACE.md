# Local Project Workspace and Run Records

## Purpose

The workspace store is the first local persistence service intended for the
future Windows desktop shell. It is UI-independent and uses Python's standard
SQLite library. Streamlit session state is not treated as a customer database.

## What is stored

- Project identifiers and display names.
- Import metadata: source filename (basename only), media type, original
  SHA-256, source classification, worksheet, row/signal counts, quality status,
  and ingestion time.
- Immutable run manifests: input artifact hashes, configuration snapshot,
  model/software version identifiers, random seed, output summary, and the
  human-review/read-only execution boundary.
- Append-only audit events with actor, timestamp, event type, payload, previous
  event hash, and current event hash.
- Reasoned operator-override proposals and independent review events linked by
  a proposal ID, including prior/proposed values, reason, source reference,
  proposer, reviewer, and pending/approved/rejected state.

## What is not stored

Uploaded CSV/XLSX bytes are **not** stored by this service. Import retention is
fixed to metadata_only; the customer retains control of the original file.
This avoids silently copying potentially sensitive operational data into the
project database.

## Consent and traceability

Creating a project or storing import metadata requires explicit consent.
Absolute source paths are reduced to the filename only. A run can reference
only source hashes registered to the same project. Run manifests and audit
events have SQLite triggers that reject normal update/delete operations.
The audit chain also hashes each event together with the preceding event hash,
and verify_audit_chain detects edits or reordering. A reasoned override review
record is not proof that the reviewer has the legal or engineering authority
to approve the change, and it does not mutate the equipment model or authorize
operation. The hash chain cannot independently detect deletion of its final
events without an external trusted checkpoint.

These controls improve traceability; they are not cryptographic protection
against an administrator who can replace or modify the SQLite database file.
The store is a local single-user prototype, not a multi-tenant database,
encrypted vault, access-control system, or regulatory records system.

## Example

~~~python
from datetime import datetime, timezone
from islandos_core.workspace_store import (
    initialize_workspace, create_project, record_import_artifact,
    create_run_manifest, verify_audit_chain,
)

db = "islandos_workspace.sqlite3"
now = datetime.now(timezone.utc)
initialize_workspace(db, workspace_id="local-workspace", actor_id="operator", created_at=now)
create_project(
    db, project_id="site-001", display_name="Site 001",
    actor_id="operator", consent_to_store_metadata=True, created_at=now,
)
record_import_artifact(
    db, project_id="site-001", file_name="telemetry.csv", media_type="text/csv",
    sha256="<64-character-original-file-sha256>", source_type="customer_provided",
    row_count=168, signal_count=3, quality_status="needs_review",
    actor_id="operator", consent_to_store_metadata=True, imported_at=now,
)
manifest = create_run_manifest(
    db, project_id="site-001", input_artifact_hashes=["<same-file-sha256>"],
    configuration={"grid_import_limit_kw": 100},
    model_versions={"dispatch": "screening-v1"},
    software_version="0.1.0", output_summary={"unmet_load_kwh": 0},
    actor_id="operator", created_at=now,
)
assert verify_audit_chain(db)["valid"]
~~~

## Important limitations and next steps

- No raw customer data is retained by the store.
- Atomic whole-workspace SQLite backup and restore are implemented with
  SQLite integrity checks, audit-chain verification, SHA-256 output, and
  explicit overwrite opt-in. These functions back up workspace metadata,
  asset versions, run manifests, and audit history; they do not include the
  original uploaded CSV/XLSX bytes.
- The SQLite file must be placed in an OS-approved user-data directory by the
  desktop shell, not beside the executable.
- Project-level portable export/import, raw source-file retention, retention
  controls, deletion/purge policy, multi-user approvals, cloud synchronization,
  encryption-at-rest, and a security review remain unimplemented. Override
  proposals are recorded as history only; a separate authorization model and
  signed approval workflow are required before a reviewed value can be treated
  as an approved site constraint.
- A manifest records what the application says it used; it does not prove
  sensor calibration, source authenticity, or physical correctness.

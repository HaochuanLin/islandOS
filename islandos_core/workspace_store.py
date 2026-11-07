"""Local-first project metadata, reproducible run manifests, and tamper-evident audit events.

The store intentionally keeps import metadata and hashes, not uploaded raw files.
It is a single-user/local prototype; SQLite triggers and hash chaining improve
traceability but are not a security boundary against an administrator who can
edit the database file.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from contextlib import contextmanager
import re
import sqlite3
import uuid
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "1.0"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_SOURCE_TYPES = {
    "measured", "customer_provided", "public_reanalysis",
    "synthetic", "forecast", "vendor_specification", "inferred",
}
_ALLOWED_QUALITY = {"valid", "needs_review", "invalid", "unassessed"}


class WorkspaceStoreError(ValueError):
    """Raised when a workspace write would violate its data contract."""


class AuditIntegrityError(RuntimeError):
    """Raised when the append-only audit chain fails verification."""


def _timestamp(value: datetime | None = None) -> str:
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise WorkspaceStoreError("timestamps must include a timezone")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _json(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise WorkspaceStoreError(f"value is not finite JSON data: {exc}") from exc


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@contextmanager
def _connect(db_path: str | Path):
    path = Path(db_path)
    if str(db_path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(db_path), timeout=5.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _append_event(
    connection: sqlite3.Connection,
    *,
    actor_id: str,
    event_type: str,
    project_id: str | None,
    payload: Mapping[str, Any],
    created_at: str,
) -> str:
    if not actor_id.strip() or not event_type.strip():
        raise WorkspaceStoreError("actor_id and event_type are required")
    previous = connection.execute(
        "SELECT event_hash FROM audit_events ORDER BY sequence DESC LIMIT 1"
    ).fetchone()
    previous_hash = previous["event_hash"] if previous else "0" * 64
    event_id = str(uuid.uuid4())
    body = {
        "event_id": event_id,
        "created_at": created_at,
        "actor_id": actor_id.strip(),
        "event_type": event_type.strip(),
        "project_id": project_id,
        "payload": dict(payload),
        "previous_hash": previous_hash,
    }
    event_hash = _hash(_json(body))
    connection.execute(
        """INSERT INTO audit_events
        (event_id, created_at, actor_id, event_type, project_id, payload_json, previous_hash, event_hash)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            event_id, created_at, actor_id.strip(), event_type.strip(), project_id,
            _json(dict(payload)), previous_hash, event_hash,
        ),
    )
    return event_id


def initialize_workspace(
    db_path: str | Path,
    *,
    workspace_id: str,
    actor_id: str,
    created_at: datetime | None = None,
) -> None:
    """Create the local SQLite workspace schema and record its initialization."""
    if not isinstance(workspace_id, str) or not workspace_id.strip():
        raise WorkspaceStoreError("workspace_id is required")
    if not isinstance(actor_id, str) or not actor_id.strip():
        raise WorkspaceStoreError("actor_id is required")
    timestamp = _timestamp(created_at)
    with _connect(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS workspace_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS projects (
                project_id TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS import_artifacts (
                artifact_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(project_id),
                file_name TEXT NOT NULL,
                media_type TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                source_type TEXT NOT NULL,
                imported_at TEXT NOT NULL,
                row_count INTEGER NOT NULL,
                signal_count INTEGER NOT NULL,
                quality_status TEXT NOT NULL,
                worksheet TEXT,
                retention_mode TEXT NOT NULL CHECK (retention_mode = 'metadata_only')
            );
            CREATE TABLE IF NOT EXISTS run_manifests (
                run_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(project_id),
                created_at TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                manifest_json TEXT NOT NULL,
                manifest_sha256 TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audit_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                project_id TEXT,
                payload_json TEXT NOT NULL,
                previous_hash TEXT NOT NULL,
                event_hash TEXT NOT NULL
            );
            CREATE TRIGGER IF NOT EXISTS audit_events_no_update
            BEFORE UPDATE ON audit_events BEGIN
                SELECT RAISE(ABORT, 'audit events are append-only');
            END;
            CREATE TRIGGER IF NOT EXISTS audit_events_no_delete
            BEFORE DELETE ON audit_events BEGIN
                SELECT RAISE(ABORT, 'audit events are append-only');
            END;
            CREATE TRIGGER IF NOT EXISTS run_manifests_no_update
            BEFORE UPDATE ON run_manifests BEGIN
                SELECT RAISE(ABORT, 'run manifests are immutable');
            END;
            CREATE TRIGGER IF NOT EXISTS run_manifests_no_delete
            BEFORE DELETE ON run_manifests BEGIN
                SELECT RAISE(ABORT, 'run manifests are immutable');
            END;
            """
        )
        existing = connection.execute(
            "SELECT value FROM workspace_meta WHERE key='workspace_id'"
        ).fetchone()
        if existing and existing["value"] != workspace_id:
            raise WorkspaceStoreError("database already belongs to a different workspace_id")
        connection.execute(
            "INSERT OR IGNORE INTO workspace_meta(key, value) VALUES('workspace_id', ?)",
            (workspace_id,),
        )
        connection.execute(
            "INSERT OR IGNORE INTO workspace_meta(key, value) VALUES('schema_version', ?)",
            (SCHEMA_VERSION,),
        )
        schema_row = connection.execute(
            "SELECT value FROM workspace_meta WHERE key='schema_version'"
        ).fetchone()
        if schema_row and schema_row["value"] != SCHEMA_VERSION:
            raise WorkspaceStoreError("unsupported workspace schema version")
        if not connection.execute("SELECT 1 FROM audit_events LIMIT 1").fetchone():
            _append_event(
                connection, actor_id=actor_id, event_type="workspace_initialized",
                project_id=None, payload={"workspace_id": workspace_id, "schema_version": SCHEMA_VERSION},
                created_at=timestamp,
            )


def create_project(
    db_path: str | Path,
    *,
    project_id: str,
    display_name: str,
    actor_id: str,
    consent_to_store_metadata: bool,
    created_at: datetime | None = None,
) -> None:
    """Create a project only after the user explicitly consents to local metadata storage."""
    if consent_to_store_metadata is not True:
        raise WorkspaceStoreError("explicit consent is required before saving project metadata")
    if not project_id.strip() or not display_name.strip() or not actor_id.strip():
        raise WorkspaceStoreError("project_id, display_name, and actor_id are required")
    timestamp = _timestamp(created_at)
    with _connect(db_path) as connection:
        connection.execute(
            "INSERT INTO projects(project_id, display_name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (project_id.strip(), display_name.strip(), timestamp, timestamp),
        )
        _append_event(
            connection, actor_id=actor_id, event_type="project_created",
            project_id=project_id.strip(),
            payload={"display_name": display_name.strip(), "metadata_consent": True},
            created_at=timestamp,
        )


def record_import_artifact(
    db_path: str | Path,
    *,
    project_id: str,
    file_name: str,
    media_type: str,
    sha256: str,
    source_type: str,
    row_count: int,
    signal_count: int,
    quality_status: str,
    actor_id: str,
    consent_to_store_metadata: bool,
    worksheet: str | None = None,
    imported_at: datetime | None = None,
) -> str:
    """Store import metadata and a content hash; never store the uploaded file bytes."""
    if consent_to_store_metadata is not True:
        raise WorkspaceStoreError("explicit consent is required before saving import metadata")
    if not isinstance(sha256, str) or not _SHA256_RE.fullmatch(sha256):
        raise WorkspaceStoreError("sha256 must be a lowercase 64-character digest")
    if source_type not in _ALLOWED_SOURCE_TYPES:
        raise WorkspaceStoreError("unsupported source_type")
    if quality_status not in _ALLOWED_QUALITY:
        raise WorkspaceStoreError("unsupported quality_status")
    if isinstance(row_count, bool) or not isinstance(row_count, int) or row_count < 0:
        raise WorkspaceStoreError("row_count must be a non-negative integer")
    if isinstance(signal_count, bool) or not isinstance(signal_count, int) or signal_count < 0:
        raise WorkspaceStoreError("signal_count must be a non-negative integer")
    if not file_name.strip() or not media_type.strip() or not actor_id.strip():
        raise WorkspaceStoreError("file_name, media_type, and actor_id are required")
    # Store only the basename, never an absolute customer path.
    safe_name = Path(file_name.replace("\\", "/")).name
    if safe_name in {"", ".", ".."}:
        raise WorkspaceStoreError("file_name must contain a valid basename")
    timestamp = _timestamp(imported_at)
    artifact_id = str(uuid.uuid4())
    with _connect(db_path) as connection:
        if not connection.execute("SELECT 1 FROM projects WHERE project_id=?", (project_id,)).fetchone():
            raise WorkspaceStoreError("project_id does not exist")
        connection.execute(
            """INSERT INTO import_artifacts
            (artifact_id, project_id, file_name, media_type, sha256, source_type,
             imported_at, row_count, signal_count, quality_status, worksheet, retention_mode)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'metadata_only')""",
            (
                artifact_id, project_id, safe_name, media_type, sha256, source_type,
                timestamp, row_count, signal_count, quality_status, worksheet,
            ),
        )
        _append_event(
            connection, actor_id=actor_id, event_type="import_metadata_recorded",
            project_id=project_id,
            payload={
                "artifact_id": artifact_id, "file_name": safe_name, "sha256": sha256,
                "source_type": source_type, "quality_status": quality_status,
                "retention_mode": "metadata_only",
            },
            created_at=timestamp,
        )
    return artifact_id


def create_run_manifest(
    db_path: str | Path,
    *,
    project_id: str,
    input_artifact_hashes: Sequence[str],
    configuration: Mapping[str, Any],
    model_versions: Mapping[str, str],
    software_version: str,
    output_summary: Mapping[str, Any],
    actor_id: str,
    random_seed: int | None = None,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    """Persist an immutable, replay-oriented snapshot of a decision-support run."""
    if not project_id.strip() or not actor_id.strip() or not software_version.strip():
        raise WorkspaceStoreError("project_id, actor_id, and software_version are required")
    if not isinstance(configuration, Mapping) or not isinstance(model_versions, Mapping) or not isinstance(output_summary, Mapping):
        raise WorkspaceStoreError("configuration, model_versions, and output_summary must be mappings")
    hashes = list(input_artifact_hashes)
    if any(not isinstance(item, str) or not _SHA256_RE.fullmatch(item) for item in hashes):
        raise WorkspaceStoreError("input_artifact_hashes must contain SHA-256 digests")
    if len(hashes) != len(set(hashes)):
        raise WorkspaceStoreError("input_artifact_hashes must be unique")
    if random_seed is not None and (isinstance(random_seed, bool) or not isinstance(random_seed, int)):
        raise WorkspaceStoreError("random_seed must be an integer or None")
    timestamp = _timestamp(created_at)
    run_id = str(uuid.uuid4())
    manifest = {
        "manifest_schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "project_id": project_id,
        "created_at": timestamp,
        "actor_id": actor_id,
        "input_artifact_hashes": hashes,
        "configuration": dict(configuration),
        "model_versions": dict(model_versions),
        "software_version": software_version,
        "random_seed": random_seed,
        "output_summary": dict(output_summary),
        "execution_boundary": {
            "mode": "offline_decision_support",
            "control_command": None,
            "requires_human_review": True,
        },
    }
    manifest_json = _json(manifest)
    manifest_hash = _hash(manifest_json)
    with _connect(db_path) as connection:
        if not connection.execute("SELECT 1 FROM projects WHERE project_id=?", (project_id,)).fetchone():
            raise WorkspaceStoreError("project_id does not exist")
        known_hashes = {
            row["sha256"] for row in connection.execute(
                "SELECT sha256 FROM import_artifacts WHERE project_id=?", (project_id,)
            )
        }
        missing = sorted(set(hashes) - known_hashes)
        if missing:
            raise WorkspaceStoreError("run references artifacts not registered to this project")
        connection.execute(
            "INSERT INTO run_manifests(run_id, project_id, created_at, actor_id, manifest_json, manifest_sha256) VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, project_id, timestamp, actor_id, manifest_json, manifest_hash),
        )
        _append_event(
            connection, actor_id=actor_id, event_type="run_manifest_created",
            project_id=project_id,
            payload={"run_id": run_id, "manifest_sha256": manifest_hash, "input_count": len(hashes)},
            created_at=timestamp,
        )
    return {**manifest, "manifest_sha256": manifest_hash}


def verify_audit_chain(db_path: str | Path) -> dict[str, Any]:
    """Verify event ordering, previous hashes, and each canonical event digest."""
    previous_hash = "0" * 64
    count = 0
    with _connect(db_path) as connection:
        rows = connection.execute("SELECT * FROM audit_events ORDER BY sequence").fetchall()
        for row in rows:
            try:
                body = {
                    "event_id": row["event_id"],
                    "created_at": row["created_at"],
                    "actor_id": row["actor_id"],
                    "event_type": row["event_type"],
                    "project_id": row["project_id"],
                    "payload": json.loads(row["payload_json"]),
                    "previous_hash": row["previous_hash"],
                }
                expected_hash = _hash(_json(body))
            except (json.JSONDecodeError, WorkspaceStoreError, TypeError, ValueError):
                return {"valid": False, "event_count": count, "failed_sequence": row["sequence"]}
            if row["previous_hash"] != previous_hash or expected_hash != row["event_hash"]:
                return {"valid": False, "event_count": count, "failed_sequence": row["sequence"]}
            previous_hash = row["event_hash"]
            count += 1
    return {"valid": True, "event_count": count, "latest_hash": previous_hash}


def list_import_artifacts(db_path: str | Path, *, project_id: str) -> list[dict[str, Any]]:
    with _connect(db_path) as connection:
        rows = connection.execute(
            """SELECT artifact_id, project_id, file_name, media_type, sha256, source_type,
                      imported_at, row_count, signal_count, quality_status, worksheet, retention_mode
               FROM import_artifacts WHERE project_id=? ORDER BY imported_at, artifact_id""",
            (project_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_run_manifest(db_path: str | Path, *, run_id: str) -> dict[str, Any]:
    with _connect(db_path) as connection:
        row = connection.execute(
            "SELECT manifest_json, manifest_sha256 FROM run_manifests WHERE run_id=?",
            (run_id,),
        ).fetchone()
    if row is None:
        raise WorkspaceStoreError("run_id does not exist")
    try:
        manifest = json.loads(row["manifest_json"])
    except json.JSONDecodeError as exc:
        raise AuditIntegrityError("stored run manifest is not valid JSON") from exc
    if _hash(row["manifest_json"]) != row["manifest_sha256"]:
        raise AuditIntegrityError("stored run manifest hash does not match its contents")
    return {**manifest, "manifest_sha256": row["manifest_sha256"]}


def record_operator_override(
    db_path: str | Path,
    *,
    project_id: str,
    actor_id: str,
    field_path: str,
    previous_value: Any,
    proposed_value: Any,
    reason: str,
    source_reference: str,
    approval_status: str = "pending_review",
    reviewer_id: str | None = None,
    proposal_id: str | None = None,
    created_at: datetime | None = None,
) -> str:
    """Append a reasoned operator override proposal/review to the audit trail.

    This records an assertion and review trail only. It does not grant a role,
    validate reviewer authority, mutate the underlying asset configuration, or
    authorize an operational action.
    """
    if not all(isinstance(value, str) and value.strip() for value in (project_id, actor_id, field_path, reason, source_reference)):
        raise WorkspaceStoreError("project_id, actor_id, field_path, reason, and source_reference are required")
    if approval_status not in {"pending_review", "approved", "rejected"}:
        raise WorkspaceStoreError("approval_status must be pending_review, approved, or rejected")
    if approval_status == "pending_review":
        if reviewer_id is not None or proposal_id is not None:
            raise WorkspaceStoreError("reviewer_id and proposal_id must be omitted for a new pending proposal")
        proposal_id = str(uuid.uuid4())
    else:
        if not isinstance(reviewer_id, str) or not reviewer_id.strip():
            raise WorkspaceStoreError("reviewer_id is required for an approval decision")
        if reviewer_id.strip() == actor_id.strip():
            raise WorkspaceStoreError("the proposing actor cannot review their own override")
        if not isinstance(proposal_id, str) or not proposal_id.strip():
            raise WorkspaceStoreError("proposal_id is required to review an existing proposal")
    # Validate all values before appending so the audit event is always exportable JSON.
    _json({"previous_value": previous_value, "proposed_value": proposed_value})
    timestamp = _timestamp(created_at)
    with _connect(db_path) as connection:
        if not connection.execute("SELECT 1 FROM projects WHERE project_id=?", (project_id,)).fetchone():
            raise WorkspaceStoreError("project_id does not exist")
        if approval_status in {"approved", "rejected"}:
            proposals = connection.execute(
                "SELECT payload_json FROM audit_events WHERE project_id=? AND event_type='operator_override_pending_review'",
                (project_id,),
            ).fetchall()
            matching = []
            for row in proposals:
                payload = json.loads(row["payload_json"])
                if payload.get("proposal_id") == proposal_id:
                    matching.append(payload)
            if len(matching) != 1:
                raise WorkspaceStoreError("proposal_id does not identify one pending override in this project")
            reviewed_events = connection.execute(
                "SELECT payload_json FROM audit_events WHERE project_id=? AND event_type IN ('operator_override_approved', 'operator_override_rejected')",
                (project_id,),
            ).fetchall()
            if any(json.loads(row["payload_json"]).get("proposal_id") == proposal_id for row in reviewed_events):
                raise WorkspaceStoreError("override proposal has already been reviewed")
            original = matching[0]
            if original.get("proposing_actor_id") != actor_id.strip():
                raise WorkspaceStoreError("actor_id must match the original proposing actor")
            if (
                original.get("field_path") != field_path.strip()
                or original.get("previous_value") != previous_value
                or original.get("proposed_value") != proposed_value
                or original.get("reason") != reason.strip()
                or original.get("source_reference") != source_reference.strip()
            ):
                raise WorkspaceStoreError("review details must match the original override proposal")
        _append_event(
            connection,
            actor_id=reviewer_id.strip() if reviewer_id else actor_id,
            event_type="operator_override_" + approval_status,
            project_id=project_id,
            payload={
                "proposal_id": proposal_id,
                "proposing_actor_id": actor_id,
                "field_path": field_path.strip(),
                "previous_value": previous_value,
                "proposed_value": proposed_value,
                "reason": reason.strip(),
                "source_reference": source_reference.strip(),
                "approval_status": approval_status,
                "reviewer_id": reviewer_id.strip() if reviewer_id else None,
                "operational_authorization": False,
            },
            created_at=timestamp,
        )
        return proposal_id


def list_audit_events(db_path: str | Path, *, project_id: str | None = None) -> list[dict[str, Any]]:
    """Return audit events in append order for inspection or export."""
    with _connect(db_path) as connection:
        if project_id is None:
            rows = connection.execute("SELECT * FROM audit_events ORDER BY sequence").fetchall()
        else:
            rows = connection.execute(
                "SELECT * FROM audit_events WHERE project_id=? ORDER BY sequence",
                (project_id,),
            ).fetchall()
    return [
        {
            "sequence": row["sequence"],
            "event_id": row["event_id"],
            "created_at": row["created_at"],
            "actor_id": row["actor_id"],
            "event_type": row["event_type"],
            "project_id": row["project_id"],
            "payload": json.loads(row["payload_json"]),
            "previous_hash": row["previous_hash"],
            "event_hash": row["event_hash"],
        }
        for row in rows
    ]

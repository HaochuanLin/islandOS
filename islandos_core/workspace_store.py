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
import os
from pathlib import Path
from contextlib import contextmanager, closing
import shutil
import tempfile
import re
import sqlite3
import uuid
from typing import Any, Mapping, Sequence

from islandos_core.assets import AssetRecord, evaluate_asset_readiness


SCHEMA_VERSION = "1.1"
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
        existing_schema = connection.execute(
            "SELECT value FROM workspace_meta WHERE key='schema_version'"
        ).fetchone() if connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='workspace_meta'"
        ).fetchone() else None
        if existing_schema and existing_schema["value"] not in {"1.0", SCHEMA_VERSION}:
            raise WorkspaceStoreError("unsupported workspace schema version")
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
            CREATE TABLE IF NOT EXISTS asset_record_versions (
                record_version_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(project_id),
                asset_id TEXT NOT NULL,
                site_id TEXT NOT NULL,
                asset_type TEXT NOT NULL,
                version INTEGER NOT NULL CHECK (version > 0),
                created_at TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                record_json TEXT NOT NULL,
                record_sha256 TEXT NOT NULL,
                readiness_json TEXT NOT NULL,
                UNIQUE(project_id, asset_id, version)
            );
            CREATE TRIGGER IF NOT EXISTS asset_record_versions_no_update
            BEFORE UPDATE ON asset_record_versions BEGIN
                SELECT RAISE(ABORT, 'asset record versions are immutable');
            END;
            CREATE TRIGGER IF NOT EXISTS asset_record_versions_no_delete
            BEFORE DELETE ON asset_record_versions BEGIN
                SELECT RAISE(ABORT, 'asset record versions are immutable');
            END;
            CREATE TABLE IF NOT EXISTS run_manifests (
                run_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(project_id),
                created_at TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                manifest_json TEXT NOT NULL,
                manifest_sha256 TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS run_records (
                project_id TEXT NOT NULL REFERENCES projects(project_id),
                run_id TEXT NOT NULL,
                page TEXT NOT NULL,
                record_schema_version TEXT NOT NULL,
                created_at TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                request_sha256 TEXT NOT NULL,
                request_metadata_json TEXT NOT NULL,
                request_metadata_sha256 TEXT NOT NULL,
                request_payload_json TEXT,
                request_payload_sha256 TEXT,
                result_json TEXT NOT NULL,
                result_sha256 TEXT NOT NULL,
                canonical_manifest_json TEXT,
                canonical_manifest_sha256 TEXT,
                history_sha256 TEXT,
                input_fingerprint_sha256 TEXT,
                retention_mode TEXT NOT NULL CHECK(retention_mode IN ('metadata_only', 'retained_full_request')),
                PRIMARY KEY(project_id, run_id),
                CHECK((request_payload_json IS NULL AND request_payload_sha256 IS NULL AND retention_mode='metadata_only')
                   OR (request_payload_json IS NOT NULL AND request_payload_sha256 IS NOT NULL AND retention_mode='retained_full_request')),
                CHECK((canonical_manifest_json IS NULL AND canonical_manifest_sha256 IS NULL)
                   OR (canonical_manifest_json IS NOT NULL AND canonical_manifest_sha256 IS NOT NULL))
            );
            CREATE TRIGGER IF NOT EXISTS run_records_no_update
            BEFORE UPDATE ON run_records BEGIN
                SELECT RAISE(ABORT, 'run records are immutable');
            END;
            CREATE TRIGGER IF NOT EXISTS run_records_no_delete
            BEFORE DELETE ON run_records BEGIN
                SELECT RAISE(ABORT, 'run records are immutable');
            END;
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
        if schema_row and schema_row["value"] == "1.0":
            connection.execute(
                "UPDATE workspace_meta SET value=? WHERE key='schema_version'",
                (SCHEMA_VERSION,),
            )
            _append_event(
                connection, actor_id=actor_id, event_type="workspace_schema_migrated",
                project_id=None,
                payload={"from_schema_version": "1.0", "to_schema_version": SCHEMA_VERSION},
                created_at=timestamp,
            )
        elif schema_row and schema_row["value"] != SCHEMA_VERSION:
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


def list_projects(db_path: str | Path) -> list[dict[str, Any]]:
    """Return project metadata in a local workspace, ordered by creation time."""
    with _connect(db_path) as connection:
        rows = connection.execute(
            "SELECT project_id, display_name, created_at, updated_at FROM projects ORDER BY created_at, project_id"
        ).fetchall()
        return [dict(row) for row in rows]


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



def record_run_record(
    db_path: str | Path,
    *,
    project_id: str,
    run_id: str,
    page: str,
    request_sha256: str,
    request_metadata: Mapping[str, Any],
    result: Mapping[str, Any],
    actor_id: str,
    consent_to_store_result: bool,
    request_payload: Mapping[str, Any] | None = None,
    consent_to_retain_request: bool = False,
    canonical_manifest: Mapping[str, Any] | None = None,
    history_sha256: str | None = None,
    input_fingerprint_sha256: str | None = None,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    """Persist an immutable result record; retain full request data only after separate opt-in."""
    if consent_to_store_result is not True:
        raise WorkspaceStoreError("explicit consent is required before saving a run result")
    if not all(isinstance(value, str) and value.strip() for value in (project_id, run_id, page, actor_id)):
        raise WorkspaceStoreError("project_id, run_id, page, and actor_id are required")
    for name, digest in (
        ("request_sha256", request_sha256),
        ("history_sha256", history_sha256),
        ("input_fingerprint_sha256", input_fingerprint_sha256),
    ):
        if digest is not None and (not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest)):
            raise WorkspaceStoreError(f"{name} must be a lowercase SHA-256 digest")
    if not isinstance(request_sha256, str) or not _SHA256_RE.fullmatch(request_sha256):
        raise WorkspaceStoreError("request_sha256 must be a lowercase SHA-256 digest")
    if not isinstance(request_metadata, Mapping) or not isinstance(result, Mapping):
        raise WorkspaceStoreError("request_metadata and result must be mappings")
    if request_payload is not None and not isinstance(request_payload, Mapping):
        raise WorkspaceStoreError("request_payload must be a mapping or None")
    if consent_to_retain_request is not True and request_payload is not None:
        raise WorkspaceStoreError("separate explicit consent is required before retaining the full request")
    if consent_to_retain_request is True and request_payload is None:
        raise WorkspaceStoreError("request_payload is required when full-request retention is enabled")
    if canonical_manifest is not None and not isinstance(canonical_manifest, Mapping):
        raise WorkspaceStoreError("canonical_manifest must be a mapping or None")
    timestamp = _timestamp(created_at)
    metadata_json = _json(dict(request_metadata))
    result_json = _json(dict(result))
    payload_json = _json(dict(request_payload)) if request_payload is not None else None
    manifest_json = _json(dict(canonical_manifest)) if canonical_manifest is not None else None
    payload_hash = _hash(payload_json) if payload_json is not None else None
    result_hash = _hash(result_json)
    manifest_hash = _hash(manifest_json) if manifest_json is not None else None
    retention_mode = "retained_full_request" if payload_json is not None else "metadata_only"
    with _connect(db_path) as connection:
        if not connection.execute("SELECT 1 FROM projects WHERE project_id=?", (project_id,)).fetchone():
            raise WorkspaceStoreError("project_id does not exist")
        connection.execute(
            """INSERT INTO run_records
            (project_id, run_id, page, record_schema_version, created_at, actor_id,
             request_sha256, request_metadata_json, request_metadata_sha256, request_payload_json, request_payload_sha256,
             result_json, result_sha256, canonical_manifest_json, canonical_manifest_sha256,
             history_sha256, input_fingerprint_sha256, retention_mode)
            VALUES (?, ?, ?, '1.0', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                project_id, run_id, page, timestamp, actor_id.strip(), request_sha256,
                metadata_json, _hash(metadata_json), payload_json, payload_hash, result_json, result_hash,
                manifest_json, manifest_hash, history_sha256, input_fingerprint_sha256,
                retention_mode,
            ),
        )
        _append_event(
            connection, actor_id=actor_id, event_type="run_record_created",
            project_id=project_id,
            payload={
                "run_id": run_id, "page": page, "request_sha256": request_sha256,
                "result_sha256": result_hash, "retention_mode": retention_mode,
                "canonical_manifest_sha256": manifest_hash,
            },
            created_at=timestamp,
        )
    return {
        "project_id": project_id, "run_id": run_id, "page": page,
        "record_schema_version": "1.0", "created_at": timestamp,
        "actor_id": actor_id.strip(), "request_sha256": request_sha256,
        "request_metadata_sha256": _hash(metadata_json),
        "request_metadata": json.loads(metadata_json),
        "request_payload": json.loads(payload_json) if payload_json is not None else None,
        "request_payload_sha256": payload_hash,
        "result": json.loads(result_json), "result_sha256": result_hash,
        "canonical_manifest": json.loads(manifest_json) if manifest_json is not None else None,
        "canonical_manifest_sha256": manifest_hash,
        "history_sha256": history_sha256,
        "input_fingerprint_sha256": input_fingerprint_sha256,
        "retention_mode": retention_mode,
        "replayable": payload_json is not None,
    }


def get_run_record(db_path: str | Path, *, project_id: str, run_id: str) -> dict[str, Any]:
    """Read one run record and verify every stored content digest."""
    with _connect(db_path) as connection:
        row = connection.execute(
            "SELECT * FROM run_records WHERE project_id=? AND run_id=?",
            (project_id, run_id),
        ).fetchone()
    if row is None:
        raise WorkspaceStoreError("run record does not exist")
    for json_field, hash_field, label in (
        ("request_metadata_json", "request_metadata_sha256", "request metadata"),
        ("result_json", "result_sha256", "run result"),
        ("request_payload_json", "request_payload_sha256", "retained request"),
        ("canonical_manifest_json", "canonical_manifest_sha256", "canonical manifest"),
    ):
        raw = row[json_field]
        if raw is None:
            if hash_field and row[hash_field] is not None:
                raise AuditIntegrityError(f"{label} hash exists without stored content")
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AuditIntegrityError(f"stored {label} is not valid JSON") from exc
        if hash_field and _hash(raw) != row[hash_field]:
            raise AuditIntegrityError(f"stored {label} hash does not match its contents")
        if not isinstance(parsed, dict):
            raise AuditIntegrityError(f"stored {label} must be a JSON object")
    metadata = json.loads(row["request_metadata_json"])
    result = json.loads(row["result_json"])
    request_payload = json.loads(row["request_payload_json"]) if row["request_payload_json"] is not None else None
    manifest = json.loads(row["canonical_manifest_json"]) if row["canonical_manifest_json"] is not None else None
    return {
        "project_id": row["project_id"], "run_id": row["run_id"], "page": row["page"],
        "record_schema_version": row["record_schema_version"], "created_at": row["created_at"],
        "actor_id": row["actor_id"], "request_sha256": row["request_sha256"],
        "request_metadata_sha256": row["request_metadata_sha256"],
        "request_metadata": metadata, "request_payload": request_payload,
        "request_payload_sha256": row["request_payload_sha256"],
        "result": result, "result_sha256": row["result_sha256"],
        "canonical_manifest": manifest, "canonical_manifest_sha256": row["canonical_manifest_sha256"],
        "history_sha256": row["history_sha256"],
        "input_fingerprint_sha256": row["input_fingerprint_sha256"],
        "retention_mode": row["retention_mode"],
        "replayable": request_payload is not None,
    }


def list_run_records(db_path: str | Path, *, project_id: str) -> list[dict[str, Any]]:
    """List run history without returning retained full request payloads."""
    if not isinstance(project_id, str) or not project_id.strip():
        raise WorkspaceStoreError("project_id is required")
    with _connect(db_path) as connection:
        rows = connection.execute(
            """SELECT project_id, run_id, page, record_schema_version, created_at, actor_id,
                      request_sha256, request_metadata_json, request_metadata_sha256, result_sha256,
                      canonical_manifest_sha256, history_sha256, input_fingerprint_sha256,
                      retention_mode
               FROM run_records WHERE project_id=? ORDER BY created_at DESC, run_id""",
            (project_id,),
        ).fetchall()
    results = []
    for row in rows:
        try:
            metadata = json.loads(row["request_metadata_json"])
        except json.JSONDecodeError as exc:
            raise AuditIntegrityError("stored request metadata is not valid JSON") from exc
        if _hash(row["request_metadata_json"]) != row["request_metadata_sha256"]:
            raise AuditIntegrityError("stored request metadata hash does not match its contents")
        if not isinstance(metadata, dict):
            raise AuditIntegrityError("stored request metadata must be a JSON object")
        results.append({
            "project_id": row["project_id"], "run_id": row["run_id"], "page": row["page"],
            "record_schema_version": row["record_schema_version"], "created_at": row["created_at"],
            "actor_id": row["actor_id"], "request_sha256": row["request_sha256"],
            "request_metadata": metadata, "request_metadata_sha256": row["request_metadata_sha256"], "result_sha256": row["result_sha256"],
            "canonical_manifest_sha256": row["canonical_manifest_sha256"],
            "history_sha256": row["history_sha256"],
            "input_fingerprint_sha256": row["input_fingerprint_sha256"],
            "retention_mode": row["retention_mode"],
            "replayable": row["retention_mode"] == "retained_full_request",
        })
    return results

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


def save_asset_record(
    db_path: str | Path, *, project_id: str, asset: AssetRecord, actor_id: str,
    saved_at: datetime | None = None,
) -> dict[str, Any]:
    """Append an immutable, provenance-bearing asset configuration version."""
    if not isinstance(asset, AssetRecord):
        raise WorkspaceStoreError("asset must be an AssetRecord")
    if not all(isinstance(value, str) and value.strip() for value in (project_id, actor_id)):
        raise WorkspaceStoreError("project_id and actor_id are required")
    timestamp = _timestamp(saved_at)
    record_json = _json(asset.to_mapping())
    record_hash = _hash(record_json)
    readiness = evaluate_asset_readiness(asset)
    version_id = str(uuid.uuid4())
    with _connect(db_path) as connection:
        if not connection.execute("SELECT 1 FROM projects WHERE project_id=?", (project_id,)).fetchone():
            raise WorkspaceStoreError("project_id does not exist")
        row = connection.execute(
            "SELECT COALESCE(MAX(version), 0) AS current_version FROM asset_record_versions WHERE project_id=? AND asset_id=?",
            (project_id, asset.asset_id),
        ).fetchone()
        version = int(row["current_version"]) + 1
        connection.execute(
            """INSERT INTO asset_record_versions
            (record_version_id, project_id, asset_id, site_id, asset_type, version,
             created_at, actor_id, record_json, record_sha256, readiness_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (version_id, project_id, asset.asset_id, asset.site_id, asset.asset_type,
             version, timestamp, actor_id.strip(), record_json, record_hash, _json(readiness)),
        )
        _append_event(
            connection, actor_id=actor_id, event_type="asset_record_version_saved",
            project_id=project_id,
            payload={"record_version_id": version_id, "asset_id": asset.asset_id,
                     "site_id": asset.site_id, "asset_type": asset.asset_type,
                     "version": version, "record_sha256": record_hash,
                     "can_screen": readiness["can_screen"]},
            created_at=timestamp,
        )
    return {"record_version_id": version_id, "project_id": project_id,
            "asset_id": asset.asset_id, "site_id": asset.site_id,
            "asset_type": asset.asset_type, "version": version,
            "created_at": timestamp, "actor_id": actor_id.strip(),
            "record_sha256": record_hash, "readiness": readiness}


def list_asset_records(
    db_path: str | Path, *, project_id: str, include_history: bool = False,
) -> list[dict[str, Any]]:
    """List latest asset records, or all immutable versions, with hash verification."""
    if not isinstance(project_id, str) or not project_id.strip():
        raise WorkspaceStoreError("project_id is required")
    with _connect(db_path) as connection:
        if include_history:
            rows = connection.execute(
                "SELECT * FROM asset_record_versions WHERE project_id=? ORDER BY asset_id, version",
                (project_id,),
            ).fetchall()
        else:
            rows = connection.execute(
                """SELECT v.* FROM asset_record_versions v
                   JOIN (SELECT asset_id, MAX(version) AS version
                         FROM asset_record_versions WHERE project_id=? GROUP BY asset_id) latest
                   ON latest.asset_id=v.asset_id AND latest.version=v.version
                   WHERE v.project_id=? ORDER BY v.asset_id""",
                (project_id, project_id),
            ).fetchall()
    results = []
    for row in rows:
        if _hash(row["record_json"]) != row["record_sha256"]:
            raise AuditIntegrityError(f"asset record hash does not match: {row['asset_id']} v{row['version']}")
        try:
            record = AssetRecord.from_mapping(json.loads(row["record_json"]))
            readiness = json.loads(row["readiness_json"])
            computed_readiness = evaluate_asset_readiness(record)
            if _json(readiness) != _json(computed_readiness):
                raise AuditIntegrityError("asset readiness snapshot mismatch: " + row["asset_id"] + " v" + str(row["version"]))
            if (record.asset_id, record.site_id, record.asset_type) != (row["asset_id"], row["site_id"], row["asset_type"]):
                raise AuditIntegrityError("asset registry metadata mismatch: " + row["asset_id"] + " v" + str(row["version"]))
            readiness = computed_readiness
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise AuditIntegrityError(f"stored asset record is invalid: {row['asset_id']} v{row['version']}") from exc
        results.append({"record_version_id": row["record_version_id"],
                        "project_id": row["project_id"], "asset_id": row["asset_id"],
                        "site_id": row["site_id"], "asset_type": row["asset_type"],
                        "version": row["version"], "created_at": row["created_at"],
                        "actor_id": row["actor_id"], "record_sha256": row["record_sha256"],
                        "asset": record, "readiness": readiness})
    return results


def _file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_workspace_file(path: str | Path) -> dict[str, Any]:
    """Validate SQLite integrity, stored run hashes, and the append-only audit chain."""
    source = Path(path)
    if not source.is_file():
        raise WorkspaceStoreError("workspace database file does not exist")
    try:
        with closing(sqlite3.connect(str(source))) as connection:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            tables = {
                row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if not {"workspace_meta", "projects", "audit_events"}.issubset(tables):
                raise WorkspaceStoreError("file is not a supported IslandOS workspace database")
            schema_row = connection.execute(
                "SELECT value FROM workspace_meta WHERE key='schema_version'"
            ).fetchone()
            if schema_row is None or schema_row[0] not in {"1.0", SCHEMA_VERSION}:
                raise WorkspaceStoreError("workspace database has an unsupported schema version")
            has_run_records = "run_records" in tables
            run_keys = connection.execute(
                "SELECT project_id, run_id FROM run_records ORDER BY project_id, run_id"
            ).fetchall() if has_run_records else []
        if integrity != "ok":
            raise AuditIntegrityError("workspace SQLite integrity check failed")
        for project_id, run_id in run_keys:
            get_run_record(source, project_id=project_id, run_id=run_id)
        audit = verify_audit_chain(source)
    except sqlite3.Error as exc:
        raise WorkspaceStoreError(f"workspace database cannot be opened: {exc}") from exc
    if not audit["valid"]:
        raise AuditIntegrityError(
            f"workspace audit chain is invalid at sequence {audit['failed_sequence']}"
        )
    return audit


def backup_workspace(
    db_path: str | Path,
    destination_path: str | Path,
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Create an atomic, integrity-checked SQLite backup of the complete local workspace.

    Uploaded source-file bytes are not part of the workspace schema; this backs
    up project metadata, assets, run manifests, execution records, and audit history.
    """
    source = Path(db_path).expanduser().resolve()
    destination = Path(destination_path).expanduser().resolve()
    if source == destination:
        raise WorkspaceStoreError("backup destination must differ from the source database")
    if not isinstance(overwrite, bool):
        raise WorkspaceStoreError("overwrite must be a boolean")
    if destination.exists() and not overwrite:
        raise WorkspaceStoreError("backup destination already exists; pass overwrite=True to replace it")
    audit = _validate_workspace_file(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=str(destination.parent)
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with closing(sqlite3.connect(str(source))) as source_connection:
            with closing(sqlite3.connect(str(temporary))) as target_connection:
                source_connection.backup(target_connection)
                integrity = target_connection.execute("PRAGMA integrity_check").fetchone()[0]
                if integrity != "ok":
                    raise AuditIntegrityError("backup SQLite integrity check failed")
        backup_audit = _validate_workspace_file(temporary)
        if backup_audit["latest_hash"] != audit["latest_hash"]:
            raise AuditIntegrityError("backup audit checkpoint differs from source workspace")
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    digest = _file_sha256(destination)
    return {
        "backup_path": str(destination),
        "sha256": digest,
        "audit_event_count": audit["event_count"],
        "audit_latest_hash": audit["latest_hash"],
        "integrity": "ok",
    }


def restore_workspace(
    backup_path: str | Path,
    destination_path: str | Path,
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Restore a workspace from a validated backup using an atomic file replacement."""
    source = Path(backup_path).expanduser().resolve()
    destination = Path(destination_path).expanduser().resolve()
    if source == destination:
        raise WorkspaceStoreError("restore source and destination must differ")
    if not isinstance(overwrite, bool):
        raise WorkspaceStoreError("overwrite must be a boolean")
    if destination.exists() and not overwrite:
        raise WorkspaceStoreError("restore destination already exists; pass overwrite=True to replace it")
    audit = _validate_workspace_file(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".restore", dir=str(destination.parent)
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        shutil.copyfile(source, temporary)
        restored_audit = _validate_workspace_file(temporary)
        if restored_audit["latest_hash"] != audit["latest_hash"]:
            raise AuditIntegrityError("restored workspace audit checkpoint differs from backup")
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    return {
        "restored_path": str(destination),
        "sha256": _file_sha256(destination),
        "audit_event_count": audit["event_count"],
        "audit_latest_hash": audit["latest_hash"],
        "integrity": "ok",
    }

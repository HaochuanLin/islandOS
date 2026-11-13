"""Versioned site profiles, optional local source retention, and portable project export.

The module extends the local-first SQLite workspace without changing the existing
schema version. Raw customer files are retained only after explicit opt-in and
only in a caller-selected local directory. No cloud upload or device control is
performed here.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import hashlib
import json
import os
import re
import sqlite3
import tempfile
import uuid
import zipfile
from typing import Any, Mapping

from islandos_core.workspace_store import (
    AuditIntegrityError,
    WorkspaceStoreError,
    _append_event,
    _connect,
    _hash,
    _json,
    _timestamp,
)

SITE_TYPES = {"microgrid", "island", "industrial", "commercial", "community", "other"}
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_SOURCE_BYTES = 20 * 1024 * 1024


def _ensure_tables(db_path: str | Path) -> None:
    with _connect(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS site_profile_versions (
                profile_version_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(project_id),
                version INTEGER NOT NULL CHECK(version > 0),
                created_at TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                profile_json TEXT NOT NULL,
                profile_sha256 TEXT NOT NULL,
                UNIQUE(project_id, version)
            );
            CREATE TRIGGER IF NOT EXISTS site_profile_versions_no_update
            BEFORE UPDATE ON site_profile_versions BEGIN
                SELECT RAISE(ABORT, 'site profile versions are immutable');
            END;
            CREATE TRIGGER IF NOT EXISTS site_profile_versions_no_delete
            BEFORE DELETE ON site_profile_versions BEGIN
                SELECT RAISE(ABORT, 'site profile versions are immutable');
            END;
            CREATE TABLE IF NOT EXISTS retained_source_files (
                artifact_id TEXT PRIMARY KEY REFERENCES import_artifacts(artifact_id),
                project_id TEXT NOT NULL REFERENCES projects(project_id),
                relative_path TEXT NOT NULL,
                byte_count INTEGER NOT NULL CHECK(byte_count >= 0),
                sha256 TEXT NOT NULL,
                retained_at TEXT NOT NULL,
                actor_id TEXT NOT NULL
            );
            CREATE TRIGGER IF NOT EXISTS retained_source_files_no_update
            BEFORE UPDATE ON retained_source_files BEGIN
                SELECT RAISE(ABORT, 'retained source metadata is immutable');
            END;
            """
        )


def save_site_profile(
    db_path: str | Path,
    *,
    project_id: str,
    profile: Mapping[str, Any],
    actor_id: str,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    """Append a validated immutable site profile version to an existing project."""
    if not isinstance(profile, Mapping):
        raise WorkspaceStoreError("site profile must be an object")
    allowed = {"site_name", "site_type", "country", "timezone", "currency", "description"}
    unknown = sorted(set(profile) - allowed)
    if unknown:
        raise WorkspaceStoreError("unknown site profile fields: " + ", ".join(unknown))
    site_name = profile.get("site_name")
    site_type = profile.get("site_type", "other")
    timezone_name = profile.get("timezone", "UTC")
    currency = profile.get("currency", "USD")
    country = profile.get("country", "")
    description = profile.get("description", "")
    if not isinstance(site_name, str) or not site_name.strip():
        raise WorkspaceStoreError("site_name is required")
    if site_type not in SITE_TYPES:
        raise WorkspaceStoreError("unsupported site_type")
    if not isinstance(timezone_name, str) or not timezone_name.strip():
        raise WorkspaceStoreError("timezone is required")
    try:
        ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise WorkspaceStoreError("timezone must be a valid IANA timezone") from exc
    if not isinstance(currency, str) or not _CURRENCY.fullmatch(currency):
        raise WorkspaceStoreError("currency must be a three-letter uppercase code")
    if not isinstance(country, str) or len(country) > 100:
        raise WorkspaceStoreError("country must be text no longer than 100 characters")
    if not isinstance(description, str) or len(description) > 2000:
        raise WorkspaceStoreError("description must be text no longer than 2000 characters")
    if not isinstance(actor_id, str) or not actor_id.strip():
        raise WorkspaceStoreError("actor_id is required")
    normalized = {
        "schema_version": "1.0",
        "site_name": site_name.strip(),
        "site_type": site_type,
        "country": country.strip(),
        "timezone": timezone_name.strip(),
        "currency": currency,
        "description": description.strip(),
    }
    profile_json = _json(normalized)
    digest = _hash(profile_json)
    timestamp = _timestamp(created_at)
    _ensure_tables(db_path)
    profile_version_id = str(uuid.uuid4())
    with _connect(db_path) as connection:
        if not connection.execute("SELECT 1 FROM projects WHERE project_id=?", (project_id,)).fetchone():
            raise WorkspaceStoreError("project_id does not exist")
        row = connection.execute(
            "SELECT COALESCE(MAX(version), 0) AS current_version FROM site_profile_versions WHERE project_id=?",
            (project_id,),
        ).fetchone()
        version = int(row["current_version"]) + 1
        connection.execute(
            """INSERT INTO site_profile_versions
            (profile_version_id, project_id, version, created_at, actor_id, profile_json, profile_sha256)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (profile_version_id, project_id, version, timestamp, actor_id.strip(), profile_json, digest),
        )
        _append_event(
            connection, actor_id=actor_id, event_type="site_profile_version_saved",
            project_id=project_id,
            payload={"profile_version_id": profile_version_id, "version": version, "profile_sha256": digest},
            created_at=timestamp,
        )
    return {
        "profile_version_id": profile_version_id, "project_id": project_id,
        "version": version, "created_at": timestamp, "profile": normalized,
        "profile_sha256": digest,
    }


def list_site_profiles(db_path: str | Path, *, project_id: str) -> list[dict[str, Any]]:
    _ensure_tables(db_path)
    with _connect(db_path) as connection:
        rows = connection.execute(
            """SELECT profile_version_id, project_id, version, created_at, actor_id,
                      profile_json, profile_sha256
               FROM site_profile_versions WHERE project_id=? ORDER BY version""",
            (project_id,),
        ).fetchall()
    results = []
    for row in rows:
        if _hash(row["profile_json"]) != row["profile_sha256"]:
            raise AuditIntegrityError("site profile hash does not match stored contents")
        results.append({
            "profile_version_id": row["profile_version_id"],
            "project_id": row["project_id"], "version": row["version"],
            "created_at": row["created_at"], "actor_id": row["actor_id"],
            "profile": json.loads(row["profile_json"]),
            "profile_sha256": row["profile_sha256"],
        })
    return results


def retain_source_file(
    db_path: str | Path,
    storage_dir: str | Path,
    *,
    project_id: str,
    artifact_id: str,
    file_name: str,
    content: bytes,
    actor_id: str,
    explicit_consent: bool,
    retained_at: datetime | None = None,
) -> dict[str, Any]:
    """Retain an original import only after opt-in, verifying it matches registered provenance."""
    if explicit_consent is not True:
        raise WorkspaceStoreError("explicit consent is required before retaining original source files")
    if not isinstance(content, bytes) or not content:
        raise WorkspaceStoreError("source file content must be non-empty bytes")
    if len(content) > _MAX_SOURCE_BYTES:
        raise WorkspaceStoreError("source file exceeds the 20 MiB retention limit")
    if not isinstance(actor_id, str) or not actor_id.strip():
        raise WorkspaceStoreError("actor_id is required")
    safe_name = Path(str(file_name).replace("\\", "/")).name
    suffix = Path(safe_name).suffix.lower()
    if suffix not in {".csv", ".xlsx"}:
        raise WorkspaceStoreError("only CSV and XLSX source files can be retained")
    digest = hashlib.sha256(content).hexdigest()
    timestamp = _timestamp(retained_at)
    _ensure_tables(db_path)
    with _connect(db_path) as connection:
        artifact = connection.execute(
            """SELECT project_id, sha256 FROM import_artifacts WHERE artifact_id=?""",
            (artifact_id,),
        ).fetchone()
        if artifact is None or artifact["project_id"] != project_id:
            raise WorkspaceStoreError("artifact_id is not registered to this project")
        if artifact["sha256"] != digest:
            raise WorkspaceStoreError("source bytes do not match the registered import SHA-256")
        if connection.execute(
            "SELECT 1 FROM retained_source_files WHERE artifact_id=?", (artifact_id,)
        ).fetchone():
            raise WorkspaceStoreError("source file is already retained for this artifact")
    root = Path(storage_dir).expanduser().resolve()
    target_dir = root / "sources" / artifact_id
    target = target_dir / ("original" + suffix)
    target_dir.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".source-", suffix=".tmp", dir=str(target_dir))
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, target)
        relative = target.relative_to(root).as_posix()
        with _connect(db_path) as connection:
            connection.execute(
                """INSERT INTO retained_source_files
                (artifact_id, project_id, relative_path, byte_count, sha256, retained_at, actor_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (artifact_id, project_id, relative, len(content), digest, timestamp, actor_id.strip()),
            )
            _append_event(
                connection, actor_id=actor_id, event_type="source_file_retained",
                project_id=project_id,
                payload={"artifact_id": artifact_id, "sha256": digest, "byte_count": len(content)},
                created_at=timestamp,
            )
    except Exception:
        Path(temporary_name).unlink(missing_ok=True)
        target.unlink(missing_ok=True)
        raise
    return {"artifact_id": artifact_id, "relative_path": relative, "byte_count": len(content), "sha256": digest}


def read_retained_source_file(
    db_path: str | Path, storage_dir: str | Path, *, artifact_id: str
) -> tuple[dict[str, Any], bytes]:
    _ensure_tables(db_path)
    with _connect(db_path) as connection:
        row = connection.execute(
            """SELECT artifact_id, project_id, relative_path, byte_count, sha256, retained_at, actor_id
               FROM retained_source_files WHERE artifact_id=?""",
            (artifact_id,),
        ).fetchone()
    if row is None:
        raise WorkspaceStoreError("no retained source file exists for this artifact")
    root = Path(storage_dir).expanduser().resolve()
    path = (root / row["relative_path"]).resolve()
    if root not in path.parents:
        raise WorkspaceStoreError("retained source path escapes the configured storage directory")
    content = path.read_bytes()
    if len(content) != row["byte_count"] or hashlib.sha256(content).hexdigest() != row["sha256"]:
        raise AuditIntegrityError("retained source file failed size or SHA-256 verification")
    return dict(row), content


def export_project_package(
    db_path: str | Path,
    destination_path: str | Path,
    *,
    project_id: str,
    storage_dir: str | Path | None = None,
    include_retained_sources: bool = True,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Export one project and its provenance into a verifiable ZIP package."""
    from islandos_core.workspace_store import list_asset_records, list_audit_events, list_import_artifacts, list_projects

    if not isinstance(include_retained_sources, bool) or not isinstance(overwrite, bool):
        raise WorkspaceStoreError("include_retained_sources and overwrite must be booleans")
    projects = [item for item in list_projects(db_path) if item["project_id"] == project_id]
    if len(projects) != 1:
        raise WorkspaceStoreError("project_id does not exist")
    imports = list_import_artifacts(db_path, project_id=project_id)
    assets = list_asset_records(db_path, project_id=project_id, include_history=True)
    profiles = list_site_profiles(db_path, project_id=project_id)
    with _connect(db_path) as connection:
        manifests = connection.execute(
            "SELECT manifest_json, manifest_sha256 FROM run_manifests WHERE project_id=? ORDER BY created_at, run_id",
            (project_id,),
        ).fetchall()
        retained = connection.execute(
            """SELECT artifact_id, relative_path, byte_count, sha256, retained_at
               FROM retained_source_files WHERE project_id=? ORDER BY artifact_id""",
            (project_id,),
        ).fetchall() if include_retained_sources else []
    manifest_records = []
    for row in manifests:
        if _hash(row["manifest_json"]) != row["manifest_sha256"]:
            raise AuditIntegrityError("run manifest failed hash verification during export")
        manifest_records.append({"manifest": json.loads(row["manifest_json"]), "sha256": row["manifest_sha256"]})
    audit = list_audit_events(db_path, project_id=project_id)
    payload = {
        "package_schema_version": "1.0",
        "exported_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "project": projects[0], "site_profiles": profiles,
        "assets": assets, "imports": imports, "run_manifests": manifest_records,
        "audit_events": audit,
        "limitations": [
            "This package is a project evidence export, not a complete workspace database backup.",
            "Audit events retain their source workspace hash-chain references; importing them into another workspace must create new local audit events.",
            "Original source files are included only when they were separately retained with explicit consent.",
        ],
    }
    payload_bytes = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    files: dict[str, bytes] = {"project.json": payload_bytes}
    if include_retained_sources and retained:
        if storage_dir is None:
            raise WorkspaceStoreError("storage_dir is required to export retained source files")
        for item in retained:
            metadata, content = read_retained_source_file(db_path, storage_dir, artifact_id=item["artifact_id"])
            files[f"source_files/{item['artifact_id']}{Path(item['relative_path']).suffix}"] = content
    file_manifest = {
        name: {"sha256": hashlib.sha256(data).hexdigest(), "byte_count": len(data)}
        for name, data in sorted(files.items())
    }
    manifest_bytes = json.dumps(file_manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    files["manifest.json"] = manifest_bytes
    destination = Path(destination_path).expanduser().resolve()
    if destination.exists() and not overwrite:
        raise WorkspaceStoreError("package destination exists; pass overwrite=True to replace it")
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=str(destination.parent))
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data in files.items():
                archive.writestr(name, data)
        with zipfile.ZipFile(temporary, "r") as archive:
            bad = archive.testzip()
            if bad is not None:
                raise AuditIntegrityError(f"project package failed ZIP integrity check: {bad}")
            for name, expected in file_manifest.items():
                actual = archive.read(name)
                if len(actual) != expected["byte_count"] or hashlib.sha256(actual).hexdigest() != expected["sha256"]:
                    raise AuditIntegrityError("project package content hash mismatch")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    return {
        "package_path": str(destination), "sha256": digest,
        "project_id": project_id, "included_source_files": len(retained),
        "included_imports": len(imports), "included_assets": len(assets),
        "integrity": "verified",
    }


def inspect_project_package(content: bytes, *, max_package_bytes: int = 100 * 1024 * 1024) -> dict[str, Any]:
    """Validate package paths, sizes, manifest hashes, and project JSON without extracting files."""
    if not isinstance(content, bytes) or not content:
        raise WorkspaceStoreError("project package must be non-empty bytes")
    if len(content) > max_package_bytes:
        raise WorkspaceStoreError("project package exceeds the 100 MiB inspection limit")
    try:
        with zipfile.ZipFile(__import__("io").BytesIO(content)) as archive:
            members = archive.infolist()
            if len(members) > 1000:
                raise WorkspaceStoreError("project package contains too many files")
            if sum(item.file_size for item in members) > max_package_bytes:
                raise WorkspaceStoreError("project package expands beyond the 100 MiB limit")
            names = [item.filename for item in members]
            if len(names) != len(set(names)):
                raise WorkspaceStoreError("project package contains duplicate paths")
            if any(name.startswith("/") or ".." in Path(name).parts or "\\" in name for name in names):
                raise WorkspaceStoreError("project package contains an unsafe path")
            if "manifest.json" not in names or "project.json" not in names:
                raise WorkspaceStoreError("project package is missing required manifests")
            manifest = json.loads(archive.read("manifest.json"))
            if not isinstance(manifest, dict):
                raise WorkspaceStoreError("package manifest must be an object")
            expected_names = set(manifest) | {"manifest.json"}
            if set(names) != expected_names:
                raise WorkspaceStoreError("package contents do not match the file manifest")
            for name, expected in manifest.items():
                data = archive.read(name)
                if (
                    not isinstance(expected, dict)
                    or len(data) != expected.get("byte_count")
                    or hashlib.sha256(data).hexdigest() != expected.get("sha256")
                ):
                    raise AuditIntegrityError(f"project package file failed verification: {name}")
            project = json.loads(archive.read("project.json"))
            if project.get("package_schema_version") != "1.0" or not isinstance(project.get("project"), dict):
                raise WorkspaceStoreError("unsupported or malformed project package")
            return {
                "valid": True,
                "project_id": project["project"].get("project_id"),
                "project_name": project["project"].get("display_name"),
                "asset_count": len(project.get("assets", [])),
                "import_count": len(project.get("imports", [])),
                "retained_source_count": sum(name.startswith("source_files/") for name in names),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
    except (zipfile.BadZipFile, json.JSONDecodeError, KeyError) as exc:
        raise WorkspaceStoreError("project package is not a valid IslandOS export") from exc

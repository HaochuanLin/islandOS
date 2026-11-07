"""UI-independent application services shared by Streamlit and future desktop clients.

This module coordinates existing domain services; it deliberately contains no
Streamlit imports, UI state, or device-control code. Uploaded bytes are inspected
in memory and are never persisted by these functions.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from islandos_core.onboarding import (
    evaluate_task_readiness,
    inspect_csv_bytes,
    inspect_excel_bytes,
    inspect_excel_sheets,
)
from islandos_core.workspace_store import (
    create_project as _create_project,
    create_run_manifest,
    initialize_workspace,
    list_projects,
    record_import_artifact,
    verify_audit_chain,
)


SUPPORTED_UPLOAD_SUFFIXES = {".csv", ".xlsx"}


def inspect_upload(
    content: bytes,
    *,
    file_name: str,
    source_type: str,
    task: str = "exploration",
    options: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Inspect one CSV/XLSX upload and return import plus task-readiness reports.

    The filename suffix selects the parser; unsupported formats fail closed.
    Options are explicit parser options (for example timezone_name for XLSX).
    """
    if not isinstance(content, bytes):
        raise TypeError("content must be bytes")
    if not isinstance(file_name, str) or not file_name.strip():
        raise ValueError("file_name is required")
    suffix = Path(file_name).suffix.lower()
    if suffix not in SUPPORTED_UPLOAD_SUFFIXES:
        raise ValueError("unsupported upload format; supported formats are .csv and .xlsx")
    parser_options = dict(options or {})
    common = {
        "source_type": source_type,
        "source_name": Path(file_name).name,
        "now": now,
    }
    if suffix == ".csv":
        report = inspect_csv_bytes(content, **common, **parser_options)
        media_type = "text/csv"
    else:
        report = inspect_excel_bytes(content, **common, **parser_options)
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    readiness = evaluate_task_readiness(report, task)
    return {
        "format": suffix[1:],
        "media_type": media_type,
        "inspection": report,
        "readiness": readiness,
        "raw_file_retained": False,
    }


def list_excel_sheets(content: bytes) -> list[dict[str, Any]]:
    """List workbook worksheets without importing their data rows."""
    return inspect_excel_sheets(content)


def evaluate_readiness(
    inspection_report: Mapping[str, Any],
    task: str,
    *,
    confirmed_constraints: Mapping[str, bool] | None = None,
) -> dict[str, Any]:
    """Expose the canonical task gate through the shared application boundary."""
    return evaluate_task_readiness(
        inspection_report, task, confirmed_constraints=confirmed_constraints,
    )


def create_local_project(
    db_path: str | Path,
    *,
    workspace_id: str,
    project_id: str,
    display_name: str,
    actor_id: str,
    consent_to_store_metadata: bool,
    created_at: datetime | None = None,
) -> None:
    """Initialize a local workspace and create its first project after consent."""
    if consent_to_store_metadata is not True:
        raise ValueError("explicit consent is required before creating a local project")
    initialize_workspace(
        db_path, workspace_id=workspace_id, actor_id=actor_id, created_at=created_at,
    )
    _create_project(
        db_path, project_id=project_id, display_name=display_name,
        actor_id=actor_id, consent_to_store_metadata=True, created_at=created_at,
    )


def open_local_project(db_path: str | Path, *, project_id: str) -> dict[str, Any]:
    """Open an existing project only after verifying its audit chain."""
    database = Path(db_path)
    if not database.is_file():
        raise ValueError("workspace database does not exist")
    projects = list_projects(database)
    project = next((item for item in projects if item["project_id"] == project_id), None)
    if project is None:
        raise ValueError("project_id does not exist in this workspace")
    audit = verify_audit_chain(database)
    if audit.get("valid") is not True:
        raise ValueError("workspace audit chain verification failed")
    return {"project": project, "audit": audit, "database_path": str(database)}


def register_inspected_import(
    db_path: str | Path,
    *,
    project_id: str,
    file_name: str,
    inspection_result: Mapping[str, Any],
    actor_id: str,
    consent_to_store_metadata: bool,
    imported_at: datetime | None = None,
) -> str:
    """Persist metadata for an inspected file; uploaded bytes are not accepted."""
    if consent_to_store_metadata is not True:
        raise ValueError("explicit consent is required before saving import metadata")
    report = inspection_result.get("inspection")
    if not isinstance(report, Mapping):
        raise ValueError("inspection_result must contain an inspection report")
    artifact = report.get("artifact")
    if not isinstance(artifact, Mapping) or not artifact.get("sha256"):
        raise ValueError("inspection report does not contain a source SHA-256 digest")
    media_type = inspection_result.get("media_type")
    if not isinstance(media_type, str) or not media_type:
        raise ValueError("inspection_result does not contain a media type")
    worksheet = report.get("worksheet")
    return record_import_artifact(
        db_path, project_id=project_id, file_name=file_name,
        media_type=media_type, sha256=artifact["sha256"],
        source_type=report["source_type"], row_count=report["row_count"],
        signal_count=report["recognized_signal_count"],
        quality_status=report["status"], actor_id=actor_id,
        consent_to_store_metadata=True, worksheet=worksheet, imported_at=imported_at,
    )


def create_analysis_record(
    db_path: str | Path,
    *,
    project_id: str,
    inspection_result: Mapping[str, Any],
    configuration: Mapping[str, Any],
    model_versions: Mapping[str, str],
    software_version: str,
    actor_id: str,
    random_seed: int | None = None,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    """Create a reproducibility manifest only when this task passes its data gate.

    This records an analysis configuration; it does not execute a forecast,
    simulation, optimizer, or operational command.
    """
    readiness = inspection_result.get("readiness")
    report = inspection_result.get("inspection")
    if not isinstance(readiness, Mapping) or not isinstance(report, Mapping):
        raise ValueError("inspection_result must contain inspection and readiness reports")
    if readiness.get("can_run") is not True:
        raise ValueError("analysis record blocked by task readiness: " + ", ".join(readiness.get("blockers", [])))
    digest = report.get("artifact", {}).get("sha256")
    if not isinstance(digest, str):
        raise ValueError("inspection report does not contain a source SHA-256 digest")
    return create_run_manifest(
        db_path, project_id=project_id, input_artifact_hashes=[digest],
        configuration=dict(configuration),
        model_versions=dict(model_versions), software_version=software_version,
        output_summary={
            "task": readiness.get("task"),
            "readiness_status": readiness.get("status"),
            "warnings": list(readiness.get("warnings", [])),
            "record_type": "analysis_configuration_snapshot",
            "execution_performed": False,
        },
        actor_id=actor_id, random_seed=random_seed, created_at=created_at,
    )

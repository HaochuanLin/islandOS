"""Headless smoke path for the UI-independent IslandOS core services.

Run from the repository root:
    python tools/islandos_core_smoke.py

This is a local synthetic-data smoke test. It does not access customer files,
devices, networks, or the hosted Streamlit application.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from islandos_core.onboarding import evaluate_task_readiness, inspect_csv_bytes
from islandos_core.workspace_store import (
    create_project,
    create_run_manifest,
    initialize_workspace,
    record_import_artifact,
    verify_audit_chain,
)


def run_smoke() -> dict:
    if "streamlit" in sys.modules:
        raise RuntimeError("headless core smoke path unexpectedly imported Streamlit")
    now = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)
    csv_bytes = (
        b"timestamp,load_kw\n"
        b"2026-11-07T10:00:00Z,100\n"
        b"2026-11-07T11:00:00Z,110\n"
    )
    report = inspect_csv_bytes(
        csv_bytes, source_type="synthetic", source_name="synthetic-smoke.csv", now=now,
    )
    readiness = evaluate_task_readiness(report, "exploration")
    if report["status"] != "valid" or not readiness["can_run"]:
        raise RuntimeError("synthetic onboarding smoke test did not pass")

    with TemporaryDirectory(prefix="islandos-headless-") as folder:
        db_path = Path(folder) / "workspace.sqlite3"
        initialize_workspace(
            db_path, workspace_id="smoke-workspace", actor_id="smoke-test", created_at=now,
        )
        create_project(
            db_path, project_id="smoke-site", display_name="Synthetic smoke site",
            actor_id="smoke-test", consent_to_store_metadata=True, created_at=now,
        )
        digest = report["artifact"]["sha256"]
        record_import_artifact(
            db_path, project_id="smoke-site", file_name="synthetic-smoke.csv",
            media_type="text/csv", sha256=digest, source_type="synthetic",
            row_count=report["row_count"],
            signal_count=report["recognized_signal_count"],
            quality_status=report["status"], actor_id="smoke-test",
            consent_to_store_metadata=True, imported_at=now,
        )
        manifest = create_run_manifest(
            db_path, project_id="smoke-site", input_artifact_hashes=[digest],
            configuration={"mode": "headless_smoke"},
            model_versions={"onboarding": "1.0"},
            software_version="headless-smoke",
            output_summary={
                "import_status": report["status"],
                "readiness_status": readiness["status"],
            },
            actor_id="smoke-test", created_at=now,
        )
        chain = verify_audit_chain(db_path)
        if not chain["valid"]:
            raise RuntimeError("workspace audit chain did not verify")
        return {
            "status": "passed",
            "streamlit_imported": "streamlit" in sys.modules,
            "import_status": report["status"],
            "task_readiness": readiness["status"],
            "run_manifest_sha256": manifest["manifest_sha256"],
            "audit_event_count": chain["event_count"],
        }


if __name__ == "__main__":
    print(json.dumps(run_smoke(), indent=2, sort_keys=True))

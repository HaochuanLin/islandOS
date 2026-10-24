#!/usr/bin/env python3
"""Audit a site configuration's validity, provenance labels, and cost completeness.

A successful audit is a structural preflight only. It does not certify that
configuration values are measured, correct, safe, or suitable for operation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

# Direct execution sets sys.path[0] to tools/, so expose the repository root
# before importing the shared top-level configuration module.
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from islandos_config import economics_completeness, load_config


def audit_config(path: Path) -> dict[str, Any]:
    """Build a deterministic, machine-readable audit record for a config file."""
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    # Audit declarations from the exact user-supplied document, not the
    # effective configuration after the loader fills in default values.
    declared = json.loads(raw.decode("utf-8"))
    config = load_config(path)
    metadata = config.get("metadata", {})
    declared_metadata = declared.get("metadata", {}) if isinstance(declared, dict) else {}
    if not isinstance(declared_metadata, dict):
        declared_metadata = {}
    declared_status = declared_metadata.get("status")
    declared_notes = declared_metadata.get("notes", "")
    status = declared_status if declared_status is not None else "unspecified"
    notes = declared_notes
    is_illustrative = "illustrative" in str(declared_status or "").lower() or "assum" in str(declared_notes).lower()
    return {
        "audit_version": 1,
        "configuration_file": path.name,
        "configuration_sha256": digest,
        "config_version": config.get("config_version"),
        "metadata": {
            "name": declared_metadata.get("name"),
            "status": status,
            "notes": notes,
        },
        "configuration_resolution": {
            "defaults_merged": True,
            "note": (
                "Equipment and economics values below are effective values after the shared loader "
                "merges defaults; they are not necessarily all explicitly declared in the hashed file."
            ),
        },
        "provenance_review": {
            "status_label_present": bool(str(declared_status or "").strip()),
            "appears_illustrative_or_assumed": is_illustrative,
            "warning": (
                "Configuration labels and notes are self-reported; they do not prove data provenance."
            ),
        },
        "equipment": {
            "ro_specific_energy_kwh_m3": config["equipment"]["ro"]["specific_energy_kwh_m3"],
            "reservoir_capacity_m3": config["equipment"]["ro"]["reservoir_capacity_m3"],
            "initial_water_m3": config["equipment"]["ro"]["initial_water_m3"],
            "ice_storage_capacity_kwh_th": config["equipment"]["ice"]["storage_capacity_kwh_th"],
        },
        "economics_completeness": economics_completeness(config),
        "limitations": [
            "Successful validation checks structure and declared bounds only.",
            "The configuration SHA-256 identifies exact file bytes; it does not prove values are true.",
            "Do not use this report as a safety certification or operational authorization.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path, help="site-parameter JSON to audit")
    parser.add_argument("--output", type=Path, help="optional JSON report output path")
    args = parser.parse_args(argv)
    try:
        report = audit_config(args.config)
    except (OSError, ValueError) as exc:
        print(f"CONFIG AUDIT FAILED: {exc}", file=sys.stderr)
        return 2

    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
        print(f"Configuration audit written to {args.output}")
        print(f"Configuration SHA-256: {report['configuration_sha256']}")
    else:
        print(rendered, end="")
    print("Scope: structural validity and declared metadata only; values are not independently verified.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

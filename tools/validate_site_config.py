#!/usr/bin/env python3
"""Validate an IslandOS parameter JSON file before running an experiment.

This checks schema and numeric consistency only. It cannot verify that supplied
values are measured, correctly sourced, or suitable for operating real equipment.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from islandos_config import economics_completeness, load_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "config",
        nargs="?",
        default="config/site_parameters.example.json",
        help="parameter JSON to validate (default: %(default)s)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="emit a machine-readable JSON report",
    )
    args = parser.parse_args(argv)
    path = Path(args.config)
    try:
        config = load_config(path)
    except (OSError, ValueError) as exc:
        if args.json_output:
            print(json.dumps({"valid": False, "path": str(path), "error": str(exc)}))
        else:
            print(f"INVALID: {path}: {exc}", file=sys.stderr)
        return 2

    economics = economics_completeness(config)
    report = {
        "valid": True,
        "path": str(path),
        "config_version": config["config_version"],
        "name": config["metadata"]["name"],
        "status": config["metadata"]["status"],
        "economics_complete": economics["complete_for_current_declared_fields"],
        "economics_missing_fields": economics["missing_fields"],
        "limitations": [
            "Schema validation does not authenticate parameter provenance.",
            "Illustrative defaults are not measured site data.",
            "A valid configuration is not an operational safety approval.",
        ],
    }
    if args.json_output:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"VALID: {path}")
        print(f"Configuration: {report['name']} (version {report['config_version']})")
        print(f"Status: {report['status']}")
        if economics["missing_fields"]:
            print("Lifecycle-cost objective remains disabled; missing: "
                  + ", ".join(economics["missing_fields"]))
        print("Note: validity confirms schema/numeric consistency, not data provenance or safety.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

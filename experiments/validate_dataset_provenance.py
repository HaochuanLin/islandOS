"""Validate dataset provenance JSON and optionally bind it to exact artifact bytes.

Example:
    python experiments/validate_dataset_provenance.py provenance.json --artifact data.csv
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

from islandos_core.dataset_provenance import (
    DatasetProvenanceError,
    sha256_file_bytes,
    validate_dataset_provenance,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("metadata_json", type=Path, help="JSON file containing provenance metadata")
    parser.add_argument(
        "--artifact",
        type=Path,
        help="optional local dataset file whose exact bytes should be SHA-256 checked",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="write normalized provenance JSON to this path (default: stdout)",
    )
    args = parser.parse_args(argv)

    try:
        metadata = json.loads(args.metadata_json.read_text(encoding="utf-8"))
        if not isinstance(metadata, dict):
            raise DatasetProvenanceError("metadata JSON root must be an object")

        if args.artifact is not None:
            digest = sha256_file_bytes(args.artifact.read_bytes())
            declared_digest = metadata.get("sha256")
            if declared_digest is not None and declared_digest != digest:
                raise DatasetProvenanceError(
                    "sha256 does not match the exact bytes of the supplied artifact"
                )
            metadata["sha256"] = digest

        normalized = validate_dataset_provenance(metadata)
        rendered = json.dumps(normalized, indent=2, ensure_ascii=False) + "\n"
        if args.output is None:
            sys.stdout.write(rendered)
        else:
            protected_paths = {args.metadata_json.resolve()}
            if args.artifact is not None:
                protected_paths.add(args.artifact.resolve())
            if args.output.resolve() in protected_paths:
                raise DatasetProvenanceError(
                    "--output must not overwrite the metadata JSON or supplied artifact"
                )
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
    except (OSError, json.JSONDecodeError, DatasetProvenanceError, ValueError) as exc:
        print(f"provenance validation failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

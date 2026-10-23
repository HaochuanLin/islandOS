"""Provenance contract for datasets used in experiments and evaluations.

This records where data came from and whether it is measured, public, modeled,
or synthetic. Metadata validation does not establish data accuracy or fitness
for operational control.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import re
from typing import Any, Mapping
from urllib.parse import urlparse


_ALLOWED_STATUSES = {"measured", "public_reanalysis", "modeled", "synthetic"}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class DatasetProvenanceError(ValueError):
    """Raised when dataset provenance metadata is incomplete or inconsistent."""


def validate_dataset_provenance(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and return a JSON-compatible copy of dataset provenance.

    Required fields: dataset_id, source_name, source_url, retrieved_at,
    time_start, time_end, timezone, frequency, variables, license, data_status,
    source_version. Optional sha256 is a lowercase SHA-256 digest of the exact
    local artifact. Timestamps must be ISO-8601 and timezone-aware.

    Invalid input is reported consistently as ``DatasetProvenanceError`` rather
    than leaking implementation exceptions such as ``TypeError`` from set
    membership or URL parsing.
    """
    if not isinstance(metadata, Mapping):
        raise DatasetProvenanceError("metadata must be a mapping")

    required = {
        "dataset_id", "source_name", "source_url", "retrieved_at",
        "time_start", "time_end", "timezone", "frequency", "variables",
        "license", "data_status", "source_version",
    }
    missing = sorted(required - set(metadata))
    if missing:
        raise DatasetProvenanceError("missing required fields: " + ", ".join(missing))

    for key in ("dataset_id", "source_name", "timezone", "frequency", "license", "source_version"):
        value = metadata[key]
        if not isinstance(value, str) or not value.strip():
            raise DatasetProvenanceError(f"{key} must be a non-empty string")

    url = metadata["source_url"]
    if not isinstance(url, str) or not url.strip():
        raise DatasetProvenanceError("source_url must be an absolute HTTPS URL")
    try:
        parsed = urlparse(url)
        valid_https_url = parsed.scheme == "https" and bool(parsed.netloc) and bool(parsed.hostname)
    except ValueError:
        valid_https_url = False
    if not valid_https_url:
        raise DatasetProvenanceError("source_url must be an absolute HTTPS URL")

    status = metadata["data_status"]
    if not isinstance(status, str) or status not in _ALLOWED_STATUSES:
        raise DatasetProvenanceError(
            "data_status must be one of: " + ", ".join(sorted(_ALLOWED_STATUSES))
        )

    timestamps: dict[str, datetime] = {}
    for key in ("retrieved_at", "time_start", "time_end"):
        raw = metadata[key]
        if not isinstance(raw, str) or not raw.strip():
            raise DatasetProvenanceError(f"{key} must be a non-empty ISO-8601 string")
        try:
            parsed_time = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise DatasetProvenanceError(f"{key} must be valid ISO-8601") from exc
        if parsed_time.tzinfo is None or parsed_time.utcoffset() is None:
            raise DatasetProvenanceError(f"{key} must include a timezone")
        timestamps[key] = parsed_time

    if timestamps["time_start"] >= timestamps["time_end"]:
        raise DatasetProvenanceError("time_start must be earlier than time_end")

    variables = metadata["variables"]
    if not isinstance(variables, list) or not variables:
        raise DatasetProvenanceError("variables must be a non-empty list")
    seen: set[str] = set()
    normalized_variables = []
    for index, variable in enumerate(variables):
        if not isinstance(variable, Mapping):
            raise DatasetProvenanceError(f"variables[{index}] must be an object")
        for key in ("name", "unit", "meaning"):
            value = variable.get(key)
            if not isinstance(value, str) or not value.strip():
                raise DatasetProvenanceError(f"variables[{index}].{key} must be a non-empty string")
        name = variable["name"].strip()
        if name in seen:
            raise DatasetProvenanceError(f"duplicate variable name: {name}")
        seen.add(name)
        normalized_variables.append({
            "name": name,
            "unit": variable["unit"].strip(),
            "meaning": variable["meaning"].strip(),
        })

    result = {
        "provenance_schema_version": "1.0",
        "dataset_id": metadata["dataset_id"].strip(),
        "source_name": metadata["source_name"].strip(),
        "source_url": url,
        "retrieved_at": timestamps["retrieved_at"].isoformat(),
        "time_start": timestamps["time_start"].isoformat(),
        "time_end": timestamps["time_end"].isoformat(),
        "timezone": metadata["timezone"].strip(),
        "frequency": metadata["frequency"].strip(),
        "variables": normalized_variables,
        "license": metadata["license"].strip(),
        "data_status": status,
        "source_version": metadata["source_version"].strip(),
    }
    digest = metadata.get("sha256")
    if digest is not None:
        if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
            raise DatasetProvenanceError("sha256 must be a lowercase 64-character SHA-256 hex digest")
        result["sha256"] = digest
    return result


def sha256_file_bytes(content: bytes) -> str:
    """Return the SHA-256 digest for exact artifact bytes, without file I/O."""
    if not isinstance(content, bytes):
        raise TypeError("content must be bytes")
    return hashlib.sha256(content).hexdigest()

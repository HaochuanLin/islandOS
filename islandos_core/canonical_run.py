"""Versioned, hash-addressed manifest for reproducible IslandOS planning runs.

The manifest binds a run to its project, source dataset, site configuration,
forecast contract and optimizer settings. It is metadata only: it does not run
models, infer missing inputs, or authorize equipment commands.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from typing import Any


MANIFEST_SCHEMA_VERSION = 1
_ALLOWED_SOURCE_TYPES = {
    "measured", "customer_provided", "public_reanalysis",
    "synthetic", "forecast", "vendor_specification", "inferred",
}


def _utc_timestamp(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("created_at_utc must be a non-empty ISO-8601 timestamp")
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError("created_at_utc must be a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("created_at_utc must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _json_value(value: Any, path: str = "value") -> Any:
    """Return a detached JSON-safe value and reject NaN, infinity and opaque objects."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} must contain only finite numbers")
        return value
    if isinstance(value, Mapping):
        normalized = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key.strip():
                raise ValueError(f"{path} mapping keys must be non-empty strings")
            normalized[key] = _json_value(item, f"{path}.{key}")
        return {key: normalized[key] for key in sorted(normalized)}
    if isinstance(value, (list, tuple)):
        return [_json_value(item, f"{path}[{index}]") for index, item in enumerate(value)]
    raise ValueError(f"{path} contains a non-JSON value: {type(value).__name__}")


def _sha256(value: str, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError(f"{field} must be a 64-character lowercase SHA-256 digest")
    if any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field} must be a 64-character lowercase SHA-256 digest")
    return value


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    )


@dataclass(frozen=True)
class CanonicalRunManifest:
    """Immutable serialized manifest; callers receive detached dictionaries."""

    canonical_payload: str
    manifest_sha256: str

    def to_dict(self) -> dict[str, Any]:
        payload = json.loads(self.canonical_payload)
        payload["manifest_sha256"] = self.manifest_sha256
        return payload


def create_run_manifest(
    *,
    project_id: str,
    run_id: str,
    site_ref: str,
    created_at_utc: str,
    dataset_sha256: str,
    dataset_schema_version: str,
    source_type: str,
    site_configuration_version: str,
    site_configuration_sha256: str,
    required_signals: Mapping[str, str],
    forecast_horizon_hours: int,
    optimizer_id: str,
    optimizer_version: str,
    optimizer_settings: Mapping[str, Any],
    scenario_assumptions: Mapping[str, Any],
    forecast_model_ids: Mapping[str, str] | None = None,
) -> CanonicalRunManifest:
    """Create a deterministic manifest or fail closed on incomplete provenance."""
    identifiers = {
        "project_id": project_id,
        "run_id": run_id,
        "site_ref": site_ref,
        "dataset_schema_version": dataset_schema_version,
        "site_configuration_version": site_configuration_version,
        "optimizer_id": optimizer_id,
        "optimizer_version": optimizer_version,
    }
    for name, value in identifiers.items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string")
    if source_type not in _ALLOWED_SOURCE_TYPES:
        raise ValueError("source_type is not a supported provenance category")
    if isinstance(forecast_horizon_hours, bool) or not isinstance(forecast_horizon_hours, int) or forecast_horizon_hours < 1:
        raise ValueError("forecast_horizon_hours must be a positive integer")
    if not isinstance(required_signals, Mapping) or not required_signals:
        raise ValueError("required_signals must be a non-empty signal-to-unit mapping")
    signals: dict[str, str] = {}
    for signal_id, unit in required_signals.items():
        if not isinstance(signal_id, str) or not signal_id.strip():
            raise ValueError("required signal IDs must be non-empty strings")
        if not isinstance(unit, str) or not unit.strip():
            raise ValueError(f"required signal {signal_id!r} must have an explicit unit")
        signals[signal_id] = unit
    models = dict(forecast_model_ids or {})
    if any(key not in signals for key in models):
        raise ValueError("forecast_model_ids may only reference required signals")
    if any(not isinstance(value, str) or not value.strip() for value in models.values()):
        raise ValueError("forecast model IDs must be non-empty strings")

    payload = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "record_type": "islandos_canonical_run_manifest",
        "project_id": project_id.strip(),
        "run_id": run_id.strip(),
        "site_ref": site_ref.strip(),
        "created_at_utc": _utc_timestamp(created_at_utc),
        "dataset": {
            "sha256": _sha256(dataset_sha256, "dataset_sha256"),
            "schema_version": dataset_schema_version.strip(),
            "source_type": source_type,
        },
        "site_configuration": {
            "version": site_configuration_version.strip(),
            "sha256": _sha256(site_configuration_sha256, "site_configuration_sha256"),
        },
        "forecast": {
            "horizon_hours": forecast_horizon_hours,
            "required_signals": {key: signals[key] for key in sorted(signals)},
            "model_ids": {key: models[key] for key in sorted(models)},
        },
        "optimizer": {
            "id": optimizer_id.strip(),
            "version": optimizer_version.strip(),
            "settings": _json_value(optimizer_settings, "optimizer_settings"),
        },
        "scenario_assumptions": _json_value(scenario_assumptions, "scenario_assumptions"),
        "safety": {
            "human_review_required": True,
            "device_write_authorized": False,
            "command_generated": False,
        },
    }
    if not isinstance(optimizer_settings, Mapping):
        raise ValueError("optimizer_settings must be a mapping")
    if not isinstance(scenario_assumptions, Mapping):
        raise ValueError("scenario_assumptions must be a mapping")
    canonical = _canonical_json(payload)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return CanonicalRunManifest(canonical_payload=canonical, manifest_sha256=digest)


def verify_run_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Verify manifest integrity and mandatory advisory-only safety flags."""
    if not isinstance(manifest, Mapping):
        raise TypeError("manifest must be a mapping")
    value = dict(manifest)
    digest = value.pop("manifest_sha256", None)
    errors: list[str] = []
    if not isinstance(digest, str) or len(digest) != 64:
        return {"valid": False, "errors": ["manifest_sha256 is missing or malformed"]}
    try:
        rendered = _canonical_json(value)
    except (TypeError, ValueError) as exc:
        return {"valid": False, "errors": [f"manifest is not canonical JSON: {exc}"]}
    actual = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
    if actual != digest:
        errors.append("manifest digest mismatch")
    if value.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        errors.append("unsupported manifest schema_version")
    if value.get("record_type") != "islandos_canonical_run_manifest":
        errors.append("unexpected record_type")
    safety = value.get("safety")
    if not isinstance(safety, Mapping):
        errors.append("safety boundary is missing")
    else:
        if safety.get("human_review_required") is not True:
            errors.append("human review must remain required")
        if safety.get("device_write_authorized") is not False:
            errors.append("device writes must remain unauthorized")
        if safety.get("command_generated") is not False:
            errors.append("commands must not be generated")
    return {"valid": not errors, "errors": errors, "manifest_sha256": actual}

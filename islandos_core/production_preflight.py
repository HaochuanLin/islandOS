"""Fail-closed production configuration preflight (no deployment or device access).

This validates an operator-supplied configuration manifest. It does not verify
that referenced infrastructure exists, is reachable, or has been independently
approved. It never prints secret values.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlparse


_REQUIRED_TEXT = {
    "secret_manager_ref": "managed secret-manager reference",
    "network_policy_reference": "approved network-policy reference",
    "backup_encryption_key_ref": "off-host backup encryption-key reference",
    "metrics_auth_secret_ref": "metrics authentication secret reference",
    "identity_provider_issuer": "identity-provider issuer URL",
    "public_base_url": "public application base URL",
    "backup_target_uri": "off-host backup target URI",
    "database_url": "managed database connection URL",
}


def _nonempty_text(value):
    return isinstance(value, str) and bool(value.strip())


def _valid_exact_https_origin(value):
    """Accept only exact HTTPS origins, never wildcard or URL-like targets."""
    if not isinstance(value, str) or not value or value != value.strip() or "*" in value:
        return False
    parsed = urlparse(value)
    try:
        hostname = parsed.hostname
        parsed.port  # Force validation of a malformed port, if present.
    except ValueError:
        return False
    return bool(
        parsed.scheme == "https"
        and parsed.netloc
        and hostname
        and parsed.username is None
        and parsed.password is None
        and parsed.path in {"", "/"}
        and not parsed.query
        and not parsed.fragment
        and not any(character.isspace() for character in value)
    )


def evaluate_production_preflight(config):
    """Return blockers/warnings without echoing credentials or connection strings."""
    if not isinstance(config, dict):
        config = {}
    blockers, warnings = [], []

    if config.get("environment") != "production":
        blockers.append({"code": "environment_not_production", "field": "environment",
                         "message": "environment must be explicitly set to production."})

    for field, label in _REQUIRED_TEXT.items():
        if not _nonempty_text(config.get(field)):
            blockers.append({"code": "missing_reference", "field": field,
                             "message": f"Missing {label}."})

    database_url = config.get("database_url")
    if _nonempty_text(database_url):
        parsed_database = urlparse(database_url)
        if parsed_database.scheme.lower() not in {"postgres", "postgresql"} or not parsed_database.netloc:
            blockers.append({"code": "database_not_managed_postgres", "field": "database_url",
                             "message": "Production database must use a valid PostgreSQL connection URL; local SQLite is not accepted."})

    for field in ("identity_provider_issuer", "public_base_url"):
        value = config.get(field)
        if _nonempty_text(value):
            parsed = urlparse(value)
            if parsed.scheme != "https" or not parsed.netloc:
                blockers.append({"code": "https_required", "field": field,
                                 "message": f"{field} must be an absolute HTTPS URL."})

    backup_target = config.get("backup_target_uri")
    if _nonempty_text(backup_target):
        parsed_backup = urlparse(backup_target)
        if parsed_backup.scheme.lower() not in {"s3", "gs", "az", "azure"} or not parsed_backup.netloc:
            blockers.append({"code": "backup_not_offhost", "field": "backup_target_uri",
                             "message": "Backup target must use a valid approved off-host object-storage URI."})

    boolean_requirements = {
        "database_tls_required": "database TLS must be required",
        "mfa_required": "MFA must be required",
        "trusted_proxy_headers": "trusted proxy headers must be explicitly configured",
        "metrics_exporter_enabled": "authenticated metrics export must be enabled",
        "backup_encryption_enabled": "off-host backup encryption must be enabled",
    }
    for field, message in boolean_requirements.items():
        if config.get(field) is not True:
            blockers.append({"code": "security_control_missing", "field": field, "message": message + "."})

    if config.get("device_write_enabled") is not False:
        blockers.append({"code": "device_write_must_remain_disabled", "field": "device_write_enabled",
                         "message": "device_write_enabled must be explicitly false."})

    origins = config.get("allowed_origins")
    if not isinstance(origins, list) or not origins:
        blockers.append({"code": "allowed_origins_missing", "field": "allowed_origins",
                         "message": "At least one explicit HTTPS origin is required; wildcard origins are not accepted."})
    elif any(not _valid_exact_https_origin(origin) for origin in origins):
        blockers.append({"code": "allowed_origins_invalid", "field": "allowed_origins",
                         "message": "Every allowed origin must be an exact HTTPS origin without wildcard, path, query, or fragment."})

    retention = config.get("audit_log_retention_days")
    if isinstance(retention, bool) or not isinstance(retention, int) or retention < 365:
        blockers.append({"code": "audit_retention_too_short", "field": "audit_log_retention_days",
                         "message": "Audit log retention must be an explicit integer of at least 365 days."})

    if not blockers:
        warnings.append({
            "code": "configuration_only_not_operational_approval",
            "message": "All declared configuration checks passed. This does not prove infrastructure reachability, control effectiveness, site approval, or production readiness.",
        })

    return {
        "schema_version": 1,
        "mode": "production_configuration_preflight",
        "status": "blocked" if blockers else "configuration_checks_passed",
        "blockers": blockers,
        "warnings": warnings,
        "secrets_echoed": False,
        "device_write_enabled": False,
        "operational_approval": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="JSON configuration manifest")
    parser.add_argument("--output", help="Optional JSON report output path")
    args = parser.parse_args(argv)
    try:
        config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        parser.error(f"cannot read configuration JSON: {exc}")
    report = evaluate_production_preflight(config)
    rendered = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["status"] == "configuration_checks_passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())

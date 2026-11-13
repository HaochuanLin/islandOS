from islandos_core.production_preflight import evaluate_production_preflight


def _valid_config():
    return {
        "environment": "production",
        "database_url": "postgresql://user:secret@example.invalid/islandos",
        "database_tls_required": True,
        "secret_manager_ref": "vault://prod/islandos",
        "network_policy_reference": "change-1234",
        "backup_encryption_key_ref": "kms://backup-key",
        "metrics_auth_secret_ref": "vault://prod/metrics",
        "identity_provider_issuer": "https://identity.example.invalid/",
        "public_base_url": "https://app.example.invalid",
        "backup_target_uri": "s3://approved-bucket/islandos",
        "database_tls_required": True,
        "mfa_required": True,
        "trusted_proxy_headers": True,
        "metrics_exporter_enabled": True,
        "backup_encryption_enabled": True,
        "device_write_enabled": False,
        "allowed_origins": ["https://app.example.invalid"],
        "audit_log_retention_days": 400,
    }


def test_production_preflight_accepts_complete_declared_configuration():
    report = evaluate_production_preflight(_valid_config())
    assert report["status"] == "configuration_checks_passed"
    assert report["operational_approval"] is False
    assert report["device_write_enabled"] is False
    assert report["secrets_echoed"] is False


def test_production_preflight_fails_closed_on_sqlite_and_missing_controls():
    config = _valid_config()
    config["database_url"] = "sqlite:///local.db"
    config["mfa_required"] = False
    config["device_write_enabled"] = True
    config["allowed_origins"] = ["*"]
    report = evaluate_production_preflight(config)
    assert report["status"] == "blocked"
    codes = {item["code"] for item in report["blockers"]}
    assert "database_not_managed_postgres" in codes
    assert "security_control_missing" in codes
    assert "device_write_must_remain_disabled" in codes
    assert "allowed_origins_invalid" in codes


def test_production_preflight_does_not_echo_secret_values():
    config = _valid_config()
    config["database_url"] = "postgresql://user:super-secret@example.invalid/db"
    rendered = str(evaluate_production_preflight(config))
    assert "super-secret" not in rendered
    assert "vault://prod/islandos" not in rendered


def test_production_preflight_rejects_non_https_identity_and_short_retention():
    config = _valid_config()
    config["identity_provider_issuer"] = "http://identity.example.invalid"
    config["audit_log_retention_days"] = 30
    report = evaluate_production_preflight(config)
    codes = {item["code"] for item in report["blockers"]}
    assert "https_required" in codes
    assert "audit_retention_too_short" in codes



def test_production_preflight_rejects_non_exact_https_origins():
    invalid_origins = [
        "*",
        "https://*.example.invalid",
        "https://app.example.invalid/path",
        "https://app.example.invalid?tenant=other",
        "https://app.example.invalid?",
        "https://app.example.invalid#",
        "https://app.example.invalid#section",
        "https://user@app.example.invalid",
        "https://app.example.invalid:not-a-port",
        " https://app.example.invalid",
    ]
    for origin in invalid_origins:
        config = _valid_config()
        config["allowed_origins"] = [origin]
        report = evaluate_production_preflight(config)
        assert report["status"] == "blocked", origin
        assert any(
            item["code"] == "allowed_origins_invalid"
            for item in report["blockers"]
        ), origin

from datetime import datetime, timezone

import pytest

from islandos_core.onboarding import evaluate_task_readiness, inspect_csv_bytes


NOW = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)


def csv_bytes(body: str) -> bytes:
    return body.encode("utf-8")


def test_recognizes_common_headers_and_preserves_provenance():
    raw = csv_bytes(
        "timestamp_utc,Load (kW),PV Power (W),Battery SOC (%)\n"
        "2026-11-07T10:00:00Z,100,25000,50\n"
        "2026-11-07T11:00:00Z,110,30000,51\n"
    )
    report = inspect_csv_bytes(
        raw, source_type="measured", source_name="site-telemetry.csv",
        now=NOW, expected_interval_minutes=60,
    )
    assert report["status"] == "valid"
    assert report["artifact"]["source_name"] == "site-telemetry.csv"
    assert report["ingested_at"] == "2026-11-07T12:00:00Z"
    assert report["artifact"]["sha256"]
    mappings = {item["canonical_field"]: item for item in report["column_mappings"]}
    assert mappings["load_kw"]["canonical_unit"] == "kW"
    assert mappings["pv_power_kw"]["conversion_to_canonical"] == 0.001
    assert report["preview"][0]["values"]["pv_power_kw"] == 25.0
    assert report["data_was_modified"] is False


def test_unknown_columns_are_not_guessed_and_can_be_confirmed_by_override():
    raw = csv_bytes(
        "timestamp,site_consumption,solar_output\n"
        "2026-11-07T10:00:00Z,10,5\n"
    )
    report = inspect_csv_bytes(raw, source_type="customer_provided", now=NOW)
    assert report["status"] == "invalid"
    confirmed = inspect_csv_bytes(
        raw, source_type="customer_provided",
        column_overrides={"site_consumption": "load_kw", "solar_output": "pv_power_kw"},
        now=NOW,
    )
    assert confirmed["status"] == "needs_review"
    assert {x["mapping_method"] for x in confirmed["column_mappings"]} == {"user_confirmed"}
    assert confirmed["warning_count"] == 2
    unit_confirmed = inspect_csv_bytes(
        raw, source_type="customer_provided",
        column_overrides={"site_consumption": "load_kw", "solar_output": "pv_power_kw"},
        source_unit_overrides={"site_consumption": "kW", "solar_output": "kW"},
        now=NOW,
    )
    assert unit_confirmed["status"] == "valid"


def test_missing_values_are_warnings_and_never_imputed():
    raw = csv_bytes(
        "timestamp,load_kw,pv_kw\n"
        "2026-11-07T10:00:00Z,10,\n"
    )
    report = inspect_csv_bytes(raw, source_type="measured", now=NOW)
    assert report["status"] == "needs_review"
    assert report["preview"][0]["values"]["pv_power_kw"] is None
    assert report["warning_count"] == 1


def test_rejects_naive_timestamps_negative_power_and_invalid_soc():
    raw = csv_bytes(
        "timestamp,load_kw,battery_soc_pct\n"
        "2026-11-07T10:00:00,10,50\n"
        "2026-11-07T11:00:00Z,-1,120\n"
    )
    report = inspect_csv_bytes(raw, source_type="measured", now=NOW)
    codes = {item["code"] for item in report["issues"]}
    assert "invalid_timestamp" in codes
    assert "negative_value" in codes
    assert "soc_out_of_range" in codes
    assert report["status"] == "invalid"


def test_rejects_duplicate_headers_and_duplicate_canonical_mapping():
    raw = csv_bytes(
        "timestamp,load_kw,Load (kW)\n"
        "2026-11-07T10:00:00Z,10,11\n"
    )
    report = inspect_csv_bytes(raw, source_type="measured", now=NOW)
    assert "ambiguous_mapping" in {item["code"] for item in report["issues"]}


def test_unknown_unit_does_not_get_silently_converted():
    raw = csv_bytes(
        "timestamp,load (kWh),pv_kw\n"
        "2026-11-07T10:00:00Z,10,5\n"
    )
    report = inspect_csv_bytes(raw, source_type="measured", now=NOW)
    assert "unit_or_mapping_error" in {item["code"] for item in report["issues"]}
    assert report["status"] == "invalid"


def test_forecasting_readiness_is_task_specific():
    raw = csv_bytes(
        "timestamp,load_kw\n" + "".join(
            f"2026-11-{day:02d}T{hour:02d}:00:00Z,100\n"
            for day in range(1, 2) for hour in range(24)
        )
    )
    report = inspect_csv_bytes(raw, source_type="measured", now=NOW)
    readiness = evaluate_task_readiness(report, "forecasting")
    assert readiness["can_run"] is True
    assert "less_than_one_week_of_history" in readiness["warnings"]


def test_forecasting_is_blocked_until_target_unit_is_confirmed():
    raw = csv_bytes(
        "timestamp,load\n" + "".join(
            f"2026-11-{day:02d}T{hour:02d}:00:00Z,100\n"
            for day in range(1, 2) for hour in range(24)
        )
    )
    report = inspect_csv_bytes(raw, source_type="measured", now=NOW)
    readiness = evaluate_task_readiness(report, "forecasting")
    assert readiness["can_run"] is False
    assert "source_unit_confirmation_required:load_kw" in readiness["blockers"]


def test_forecasting_is_blocked_when_target_values_are_missing():
    raw = csv_bytes(
        "timestamp,load_kw\n"
        "2026-11-07T10:00:00Z,\n"
        "2026-11-07T11:00:00Z,100\n"
    )
    report = inspect_csv_bytes(raw, source_type="measured", now=NOW)
    readiness = evaluate_task_readiness(report, "forecasting")
    assert "missing_target_values:load_kw" in readiness["blockers"]


def test_dispatch_optimization_requires_confirmed_operating_constraints():
    raw = csv_bytes(
        "timestamp,load_kw,pv_kw\n"
        "2026-11-07T10:00:00Z,10,5\n"
    )
    report = inspect_csv_bytes(raw, source_type="measured", now=NOW)
    blocked = evaluate_task_readiness(report, "dispatch_optimization")
    assert blocked["can_run"] is False
    allowed = evaluate_task_readiness(
        report, "dispatch_optimization",
        confirmed_constraints={
            "asset_limits": True,
            "critical_load_policy": True,
            "grid_import_limit": True,
        },
    )
    assert allowed["can_run"] is True


def test_invalid_arguments_fail_explicitly():
    with pytest.raises(ValueError):
        inspect_csv_bytes(b"timestamp,load_kw\n", source_type="invented", now=NOW)
    with pytest.raises(ValueError):
        inspect_csv_bytes(b"x", source_type="measured", expected_interval_minutes=0, now=NOW)
    with pytest.raises(TypeError):
        inspect_csv_bytes("not bytes", source_type="measured", now=NOW)
    with pytest.raises(ValueError):
        inspect_csv_bytes(b"x", source_type="measured", source_unit_overrides={"x": "kWh"}, now=NOW)

"""Low-friction, provenance-aware CSV onboarding for the IslandOS core.

This module is UI-independent and deliberately conservative: it recognizes
known aliases and explicit units, but never guesses ambiguous units or fills
missing measurements. It is an import/triage service, not a site-accuracy
certification.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import csv
import hashlib
import io
import math
import re
from typing import Any, Mapping


SCHEMA_VERSION = "1.0"
ALLOWED_SOURCE_TYPES = {
    "measured", "customer_provided", "public_reanalysis",
    "synthetic", "forecast", "vendor_specification", "inferred",
}

# Canonical signals and units used by the generic energy-site onboarding path.
CANONICAL_UNITS = {
    "load_kw": "kW",
    "pv_power_kw": "kW",
    "wind_power_kw": "kW",
    "grid_import_kw": "kW",
    "grid_export_kw": "kW",
    "battery_charge_kw": "kW",
    "battery_discharge_kw": "kW",
    "battery_soc_pct": "%",
    "tariff_per_kwh": "currency/kWh",
    "diesel_power_kw": "kW",
    "diesel_fuel_lph": "L/h",
    "temperature_c": "degC",
}

_HEADER_ALIASES = {
    "load_kw": {"load", "load_kw", "demand", "demand_kw", "site_load", "site_load_kw", "critical_load_kw", "critical_load", "active_load_kw"},
    "pv_power_kw": {"pv", "pv_kw", "pv_power", "pv_power_kw", "solar", "solar_kw", "solar_power_kw"},
    "wind_power_kw": {"wind", "wind_kw", "wind_power", "wind_power_kw"},
    "grid_import_kw": {"grid_import", "grid_import_kw", "import_kw", "utility_import_kw"},
    "grid_export_kw": {"grid_export", "grid_export_kw", "export_kw", "utility_export_kw"},
    "battery_charge_kw": {"battery_charge", "battery_charge_kw", "charge_kw", "storage_charge_kw"},
    "battery_discharge_kw": {"battery_discharge", "battery_discharge_kw", "discharge_kw", "storage_discharge_kw"},
    "battery_soc_pct": {"soc", "soc_pct", "battery_soc", "battery_soc_pct", "state_of_charge_pct"},
    "tariff_per_kwh": {"tariff", "tariff_per_kwh", "electricity_price", "electricity_price_per_kwh", "price_per_kwh"},
    "diesel_power_kw": {"diesel_power", "diesel_power_kw", "generator_power_kw", "genset_kw"},
    "diesel_fuel_lph": {"diesel_fuel_lph", "fuel_consumption_lph", "generator_fuel_lph"},
    "temperature_c": {"temperature", "temperature_c", "ambient_temperature_c"},
}
_TIMESTAMP_ALIASES = {"timestamp", "timestamp_utc", "datetime", "date_time", "time", "observed_at", "date"}
_UNIT_SUFFIXES = {
    "kw": "kW", "w": "W", "mw": "MW",
    "%": "%", "pct": "%", "l/h": "L/h", "lph": "L/h",
    "c": "degC", "°c": "degC",
}


@dataclass(frozen=True)
class ColumnMapping:
    source_column: str
    canonical_field: str
    canonical_unit: str
    detected_source_unit: str | None
    conversion_to_canonical: float
    mapping_method: str


@dataclass(frozen=True)
class ImportIssue:
    code: str
    severity: str
    message: str
    row: int | None = None
    column: str | None = None


def _normalise_header(value: str) -> str:
    text = value.strip().lower().replace("（", "(").replace("）", ")")
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"[^a-z0-9%°/()._-]", "", text)
    return text.strip("_")


def _split_header_unit(header: str) -> tuple[str, str | None]:
    raw = header.strip()
    match = re.match(r"^(.*?)\s*\(([^()]*)\)\s*$", raw)
    if match:
        unit_raw = match.group(2).strip().lower().replace(" ", "")
        return _normalise_header(match.group(1)), _UNIT_SUFFIXES.get(unit_raw, unit_raw)
    normalized = _normalise_header(raw)
    match = re.match(r"^(.*?)[_-](kw|mw|w|kwh|pct|lph)$", normalized)
    if match:
        return match.group(1), _UNIT_SUFFIXES[match.group(2)]
    return normalized, None


def _timestamp(value: str) -> datetime:
    raw = value.strip()
    if not raw:
        raise ValueError("timestamp is empty")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("timestamp is not valid ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include a timezone offset")
    return parsed.astimezone(timezone.utc)


def _resolve_column(header: str, overrides: Mapping[str, str], unit_overrides: Mapping[str, str]) -> ColumnMapping | None:
    if header in overrides:
        canonical = overrides[header]
        if canonical not in CANONICAL_UNITS:
            raise ValueError(f"unsupported canonical field override: {canonical}")
        base, unit = _split_header_unit(header)
        return _make_mapping(header, canonical, unit_overrides.get(header, unit), "user_confirmed")
    normalized = _normalise_header(header)
    base, unit = _split_header_unit(header)
    if normalized in _TIMESTAMP_ALIASES or base in _TIMESTAMP_ALIASES:
        return None
    for canonical, aliases in _HEADER_ALIASES.items():
        if normalized in aliases:
            candidate_unit = unit_overrides.get(header, unit)
            if candidate_unit and candidate_unit not in {CANONICAL_UNITS[canonical], "W", "MW"}:
                candidate_unit = None if header not in unit_overrides else candidate_unit
            return _make_mapping(header, canonical, candidate_unit, "alias_match")
        if base in aliases:
            return _make_mapping(header, canonical, unit_overrides.get(header, unit), "alias_match")
    return None


def _make_mapping(header: str, canonical: str, source_unit: str | None, method: str) -> ColumnMapping:
    target = CANONICAL_UNITS[canonical]
    factors = {
        ("W", "kW"): 0.001, ("MW", "kW"): 1000.0,
        ("kW", "kW"): 1.0, ("%", "%"): 1.0,
        ("L/h", "L/h"): 1.0, ("degC", "degC"): 1.0,
        ("currency/kWh", "currency/kWh"): 1.0,
    }
    # Units must be explicit when the header supplies one. Energy and power
    # are never silently interchanged.
    if source_unit is None:
        factor = 1.0
    elif source_unit == target:
        factor = 1.0
    elif (source_unit, target) in factors:
        factor = factors[(source_unit, target)]
    else:
        raise ValueError(f"unit mismatch for {header}: {source_unit} cannot be converted to {target}")
    return ColumnMapping(header, canonical, target, source_unit, factor, method)


def inspect_csv_bytes(
    content: bytes,
    *,
    source_type: str,
    column_overrides: Mapping[str, str] | None = None,
    source_unit_overrides: Mapping[str, str] | None = None,
    expected_interval_minutes: int | None = None,
    now: datetime | None = None,
    future_tolerance_minutes: int = 5,
) -> dict[str, Any]:
    """Inspect a CSV without modifying values; return mappings, issues and preview.

    Ambiguous columns are left unmapped. Unrecognized columns are reported but
    do not invalidate otherwise usable data. No missing values are imputed.
    """
    if not isinstance(content, bytes):
        raise TypeError("content must be bytes")
    if source_type not in ALLOWED_SOURCE_TYPES:
        raise ValueError("unsupported source_type: " + str(source_type))
    if expected_interval_minutes is not None and (
        isinstance(expected_interval_minutes, bool)
        or not isinstance(expected_interval_minutes, int)
        or expected_interval_minutes <= 0
    ):
        raise ValueError("expected_interval_minutes must be a positive integer or None")
    if isinstance(future_tolerance_minutes, bool) or not isinstance(future_tolerance_minutes, int) or future_tolerance_minutes < 0:
        raise ValueError("future_tolerance_minutes must be a non-negative integer")
    reference_now = now or datetime.now(timezone.utc)
    if reference_now.tzinfo is None or reference_now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    overrides = dict(column_overrides or {})
    unit_overrides = dict(source_unit_overrides or {})
    allowed_units = {"kW", "W", "MW", "%", "L/h", "degC", "currency/kWh"}
    invalid_units = {key: value for key, value in unit_overrides.items() if value not in allowed_units}
    if invalid_units:
        raise ValueError("unsupported source unit override: " + ", ".join(sorted(invalid_units)))
    digest = hashlib.sha256(content).hexdigest()
    issues: list[ImportIssue] = []
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return _invalid_report(digest, source_type, [ImportIssue("encoding_error", "error", "CSV must be UTF-8 or UTF-8 with BOM")])
    if not text.strip():
        return _invalid_report(digest, source_type, [ImportIssue("empty_file", "error", "CSV file is empty")])
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text, newline=""), dialect=dialect)
    headers = reader.fieldnames or []
    if not headers:
        return _invalid_report(digest, source_type, [ImportIssue("missing_header", "error", "CSV header row is missing")])
    if any(not h or not h.strip() for h in headers):
        issues.append(ImportIssue("empty_header", "error", "One or more column names are empty"))
    normalized_headers = [_normalise_header(h) for h in headers]
    if len(set(normalized_headers)) != len(normalized_headers):
        issues.append(ImportIssue("duplicate_header", "error", "Duplicate column names after normalization"))
    timestamp_columns = [h for h in headers if _normalise_header(h) in _TIMESTAMP_ALIASES]
    if len(timestamp_columns) != 1:
        issues.append(ImportIssue("timestamp_column", "error", "Exactly one recognized timestamp column is required"))
    mappings: list[ColumnMapping] = []
    recognized_source_headers = set(timestamp_columns)
    for header in headers:
        try:
            mapping = _resolve_column(header, overrides, unit_overrides)
        except ValueError as exc:
            issues.append(ImportIssue("unit_or_mapping_error", "error", str(exc), column=header))
            continue
        if mapping:
            mappings.append(mapping)
            recognized_source_headers.add(header)
    for header in headers:
        if header not in recognized_source_headers:
            issues.append(ImportIssue("unrecognized_column", "warning", "Column was not mapped automatically; review or map it manually", column=header))
    for mapping in mappings:
        if mapping.detected_source_unit is None:
            issues.append(ImportIssue("unit_not_explicit", "warning", "Unit was not explicit in the header; confirm the source unit", column=mapping.source_column))
    canonical_names = [m.canonical_field for m in mappings]
    if len(set(canonical_names)) != len(canonical_names):
        issues.append(ImportIssue("ambiguous_mapping", "error", "Multiple source columns map to the same canonical field"))
    if not mappings:
        issues.append(ImportIssue("no_recognized_signals", "error", "No supported energy signals were recognized"))
    rows_out: list[dict[str, Any]] = []
    timestamps: list[datetime] = []
    seen: set[datetime] = set()
    for row_number, row in enumerate(reader, start=2):
        if None in row:
            issues.append(ImportIssue("extra_fields", "error", "Row contains more values than the header", row=row_number))
        raw_ts = row.get(timestamp_columns[0]) if len(timestamp_columns) == 1 else None
        try:
            ts = _timestamp(raw_ts or "")
        except ValueError as exc:
            issues.append(ImportIssue("invalid_timestamp", "error", str(exc), row=row_number, column=timestamp_columns[0] if len(timestamp_columns) == 1 else None))
            continue
        if ts in seen:
            issues.append(ImportIssue("duplicate_timestamp", "error", "Duplicate timestamp", row=row_number))
        seen.add(ts)
        if timestamps and ts <= timestamps[-1]:
            issues.append(ImportIssue("non_monotonic_timestamp", "error", "Timestamps must be strictly increasing", row=row_number))
        timestamps.append(ts)
        values: dict[str, float | None] = {}
        for mapping in mappings:
            raw = row.get(mapping.source_column)
            if raw is None or not raw.strip():
                values[mapping.canonical_field] = None
                issues.append(ImportIssue("missing_value", "warning", "Missing value; it was not imputed", row=row_number, column=mapping.source_column))
                continue
            try:
                number = float(raw)
            except (TypeError, ValueError):
                values[mapping.canonical_field] = None
                issues.append(ImportIssue("non_numeric", "error", "Value is not numeric", row=row_number, column=mapping.source_column))
                continue
            if not math.isfinite(number):
                values[mapping.canonical_field] = None
                issues.append(ImportIssue("non_finite", "error", "Value must be finite", row=row_number, column=mapping.source_column))
                continue
            value = number * mapping.conversion_to_canonical
            if mapping.canonical_field != "temperature_c" and value < 0:
                issues.append(ImportIssue("negative_value", "error", "Negative value is not accepted for this signal", row=row_number, column=mapping.source_column))
            if mapping.canonical_field == "battery_soc_pct" and not 0 <= value <= 100:
                issues.append(ImportIssue("soc_out_of_range", "error", "Battery SOC must be between 0 and 100 percent", row=row_number, column=mapping.source_column))
            values[mapping.canonical_field] = value
        rows_out.append({"timestamp_utc": ts.isoformat().replace("+00:00", "Z"), "values": values})
    if not rows_out:
        issues.append(ImportIssue("empty_dataset", "error", "No usable data rows were found"))
    if timestamps and future_tolerance_minutes >= 0:
        latest = max(timestamps)
        if (latest - reference_now.astimezone(timezone.utc)).total_seconds() > future_tolerance_minutes * 60:
            issues.append(ImportIssue("future_timestamp", "error", "Latest data timestamp is unexpectedly in the future"))
    if expected_interval_minutes and len(timestamps) > 1:
        for index, (left, right) in enumerate(zip(timestamps, timestamps[1:]), start=3):
            delta = (right - left).total_seconds() / 60
            if delta != expected_interval_minutes:
                issues.append(ImportIssue("interval_mismatch", "warning", f"Expected {expected_interval_minutes} minute interval; found {delta:g}", row=index))
    error_count = sum(issue.severity == "error" for issue in issues)
    warning_count = sum(issue.severity == "warning" for issue in issues)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "invalid" if error_count else ("needs_review" if warning_count else "valid"),
        "source_type": source_type,
        "artifact": {"sha256": digest, "byte_count": len(content)},
        "timestamp_column": timestamp_columns[0] if len(timestamp_columns) == 1 else None,
        "column_mappings": [asdict(item) for item in mappings],
        "row_count": len(rows_out),
        "recognized_signal_count": len(mappings),
        "error_count": error_count,
        "warning_count": warning_count,
        "issues": [asdict(issue) for issue in issues],
        "preview": rows_out[:10],
        "data_was_modified": False,
        "limitations": [
            "Header recognition is a suggestion, not proof of sensor accuracy.",
            "Unspecified units are preserved as an assumption and require operator review.",
            "Missing values are not imputed and no outlier is silently removed.",
            "A valid import does not establish that the dataset is suitable for every analysis task.",
        ],
    }


def _invalid_report(digest: str, source_type: str, issues: list[ImportIssue]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION, "status": "invalid", "source_type": source_type,
        "artifact": {"sha256": digest, "byte_count": None}, "timestamp_column": None,
        "column_mappings": [], "row_count": 0, "recognized_signal_count": 0,
        "error_count": len(issues), "warning_count": 0,
        "issues": [asdict(issue) for issue in issues], "preview": [],
        "data_was_modified": False, "limitations": ["No data was repaired or inferred."],
    }


def evaluate_task_readiness(
    report: Mapping[str, Any],
    task: str,
    *,
    confirmed_constraints: Mapping[str, bool] | None = None,
) -> dict[str, Any]:
    """Apply task-specific minimum gates; a global completeness score is avoided."""
    if task not in {"exploration", "forecasting", "dispatch_optimization"}:
        raise ValueError("task must be exploration, forecasting, or dispatch_optimization")
    if report.get("status") == "invalid":
        return {"task": task, "status": "blocked", "can_run": False, "blockers": ["import_invalid"]}
    fields = {item["canonical_field"] for item in report.get("column_mappings", [])}
    rows = int(report.get("row_count", 0))
    blockers: list[str] = []
    warnings: list[str] = []
    if task == "exploration":
        if not fields:
            blockers.append("no_recognized_signals")
    elif task == "forecasting":
        if "load_kw" not in fields and not ({"pv_power_kw", "wind_power_kw"} & fields):
            blockers.append("no_forecast_target_signal")
        if rows < 24:
            blockers.append("insufficient_history_for_baseline_screening")
        if rows < 168:
            warnings.append("less_than_one_week_of_history")
    elif task == "dispatch_optimization":
        if "load_kw" not in fields:
            blockers.append("load_signal_required")
        if not ({"pv_power_kw", "wind_power_kw", "grid_import_kw", "diesel_power_kw"} & fields):
            blockers.append("no_supply_or_dispatchable_resource_signal")
        constraints = dict(confirmed_constraints or {})
        required_constraints = {"asset_limits", "critical_load_policy", "grid_import_limit"}
        missing = sorted(key for key in required_constraints if constraints.get(key) is not True)
        if missing:
            blockers.extend("constraint_confirmation_required:" + key for key in missing)
    can_run = not blockers
    return {
        "task": task,
        "status": "ready_for_screening" if can_run else "blocked",
        "can_run": can_run,
        "blockers": blockers,
        "warnings": warnings,
        "note": "Readiness permits the named analysis workflow only; it is not a safety approval or operational-control authorization.",
    }

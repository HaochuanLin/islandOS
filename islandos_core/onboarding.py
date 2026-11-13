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
import zipfile
from typing import Any, Mapping

from .forecast_signal_catalog import FORECAST_SIGNAL_SPECS


SCHEMA_VERSION = "1.0"
ALLOWED_SOURCE_TYPES = {
    "measured", "customer_provided", "public_reanalysis",
    "synthetic", "forecast", "vendor_specification", "inferred",
}

# Canonical signals and units used by the generic energy-site onboarding path.
CANONICAL_UNITS = {
    signal_id: spec.canonical_unit
    for signal_id, spec in FORECAST_SIGNAL_SPECS.items()
}

_HEADER_ALIASES = {
    "load_kw": {"load", "load_kw", "demand", "demand_kw", "site_load", "site_load_kw", "critical_load_kw", "critical_load", "active_load_kw"},
    "flexible_load_kw": {"flexible_load", "flexible_load_kw", "shiftable_load_kw", "controllable_load_kw"},
    "water_demand_m3_per_hour": {"water_demand", "water_demand_m3_per_hour", "water_demand_m3h", "water_use_m3_per_hour"},
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
    "c": "degC", "°c": "degC", "currency/kwh": "currency/kWh", "m3/h": "m3/h",
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
    source_name: str | None = None,
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
    if source_name is not None and (not isinstance(source_name, str) or not source_name.strip()):
        raise ValueError("source_name must be a non-empty string when provided")
    if source_name is not None and (not isinstance(source_name, str) or not source_name.strip()):
        raise ValueError("source_name must be a non-empty string when provided")
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
            if mapping.canonical_field not in {"temperature_c", "tariff_per_kwh"} and value < 0:
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
        "ingested_at": reference_now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "artifact": {"source_name": source_name, "sha256": digest, "byte_count": len(content)},
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
        "artifact": {"source_name": None, "sha256": digest, "byte_count": None}, "timestamp_column": None,
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
    """Apply task-specific gates for required signals, units, history and constraints."""
    if task not in {"exploration", "forecasting", "dispatch_optimization"}:
        raise ValueError("task must be exploration, forecasting, or dispatch_optimization")
    if report.get("status") == "invalid":
        return {"task": task, "status": "blocked", "can_run": False, "blockers": ["import_invalid"]}
    mappings = list(report.get("column_mappings", []))
    fields = {item["canonical_field"] for item in mappings}
    rows = int(report.get("row_count", 0))
    unit_missing = {
        item["canonical_field"] for item in mappings
        if item.get("detected_source_unit") is None
    }
    source_to_field = {item["source_column"]: item["canonical_field"] for item in mappings}
    missing_value_fields = {
        source_to_field[issue["column"]]
        for issue in report.get("issues", [])
        if issue.get("code") == "missing_value" and issue.get("column") in source_to_field
    }
    issue_codes = {issue.get("code") for issue in report.get("issues", [])}
    blockers: list[str] = []
    warnings: list[str] = []

    if task == "exploration":
        if not fields:
            blockers.append("no_recognized_signals")
        if unit_missing:
            warnings.extend("unit_confirmation_recommended:" + field for field in sorted(unit_missing))
    elif task == "forecasting":
        targets = ["load_kw"] if "load_kw" in fields else [
            field for field in ("pv_power_kw", "wind_power_kw") if field in fields
        ]
        if not targets:
            blockers.append("no_forecast_target_signal")
        for field in targets:
            if field in unit_missing:
                blockers.append("source_unit_confirmation_required:" + field)
            if field in missing_value_fields:
                blockers.append("missing_target_values:" + field)
        if rows < 24:
            blockers.append("insufficient_history_for_baseline_screening")
        if rows < 168:
            warnings.append("less_than_one_week_of_history")
        if "interval_mismatch" in issue_codes:
            blockers.append("irregular_sampling_interval")
    elif task == "dispatch_optimization":
        if "load_kw" not in fields:
            blockers.append("load_signal_required")
        supply_fields = {"pv_power_kw", "wind_power_kw", "grid_import_kw", "diesel_power_kw"} & fields
        if not supply_fields:
            blockers.append("no_supply_or_dispatchable_resource_signal")
        used_fields = ({"load_kw"} & fields) | supply_fields
        for field in sorted(used_fields & unit_missing):
            blockers.append("source_unit_confirmation_required:" + field)
        for field in sorted(used_fields & missing_value_fields):
            blockers.append("missing_operating_values:" + field)
        if "interval_mismatch" in issue_codes:
            blockers.append("irregular_sampling_interval")
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


def inspect_excel_bytes(
    content: bytes,
    *,
    source_type: str,
    source_name: str | None = None,
    sheet_name: str | None = None,
    header_row: int | None = None,
    timezone_name: str | None = None,
    column_overrides: Mapping[str, str] | None = None,
    source_unit_overrides: Mapping[str, str] | None = None,
    expected_interval_minutes: int | None = None,
    now: datetime | None = None,
    max_file_bytes: int = 20 * 1024 * 1024,
    max_rows: int = 200_000,
    max_columns: int = 256,
) -> dict[str, Any]:
    """Extract one worksheet and pass it through the same conservative CSV validator.

    The original workbook hash is retained as the source artifact. Formula cells
    are read only from cached workbook values; formulas are never evaluated.
    Naive Excel timestamps require an explicit IANA timezone. Ambiguous or
    nonexistent daylight-saving timestamps are rejected rather than guessed.
    """
    from datetime import date
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    from openpyxl import load_workbook

    if not isinstance(content, bytes):
        raise TypeError("content must be bytes")
    if not content:
        raise ValueError("workbook is empty")
    if len(content) > max_file_bytes:
        raise ValueError(f"workbook exceeds the {max_file_bytes // (1024 * 1024)} MB import limit")
    if max_rows < 1 or max_columns < 1:
        raise ValueError("row and column limits must be positive")
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            members = archive.infolist()
            uncompressed_total = sum(item.file_size for item in members)
            if uncompressed_total > 200 * 1024 * 1024:
                raise ValueError("workbook expands beyond the 200 MB safety limit")
            if any(item.file_size > 1024 * 1024 and item.compress_size > 0 and item.file_size / item.compress_size > 200 for item in members):
                raise ValueError("workbook contains an unusually highly compressed member")
            if "[Content_Types].xml" not in archive.namelist() or "xl/workbook.xml" not in archive.namelist():
                raise ValueError("file is not a valid .xlsx package")
    except zipfile.BadZipFile as exc:
        raise ValueError("file is not a valid .xlsx package") from exc

    try:
        value_book = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        formula_book = load_workbook(io.BytesIO(content), read_only=True, data_only=False)
    except Exception as exc:
        raise ValueError("file is not a readable .xlsx workbook") from exc

    try:
        sheet_names = value_book.sheetnames
        if not sheet_names:
            raise ValueError("workbook contains no worksheets")
        selected_name = sheet_name or sheet_names[0]
        if selected_name not in sheet_names:
            raise ValueError(f"worksheet not found: {selected_name}")
        ws = value_book[selected_name]
        formula_ws = formula_book[selected_name]

        def cell_text(value: Any) -> str:
            if value is None:
                return ""
            if isinstance(value, datetime):
                return value.isoformat()
            if isinstance(value, date):
                return datetime(value.year, value.month, value.day).isoformat()
            return str(value)

        def localize_naive(value: Any) -> str:
            if isinstance(value, str):
                raw = value.strip()
                try:
                    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                except ValueError:
                    return raw
            elif isinstance(value, datetime):
                parsed = value
            elif isinstance(value, date):
                parsed = datetime(value.year, value.month, value.day)
            else:
                return cell_text(value)
            if parsed.tzinfo is not None and parsed.utcoffset() is not None:
                return parsed.isoformat()
            if not timezone_name:
                return parsed.isoformat()
            try:
                zone = ZoneInfo(timezone_name)
            except ZoneInfoNotFoundError as exc:
                raise ValueError(f"unknown IANA timezone: {timezone_name}") from exc
            first = parsed.replace(tzinfo=zone, fold=0)
            second = parsed.replace(tzinfo=zone, fold=1)
            roundtrip_first = first.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None)
            roundtrip_second = second.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None)
            valid_first = roundtrip_first == parsed
            valid_second = roundtrip_second == parsed
            if not valid_first and not valid_second:
                raise ValueError(f"nonexistent local timestamp during daylight-saving transition: {parsed.isoformat()}")
            if valid_first and valid_second and first.utcoffset() != second.utcoffset():
                raise ValueError(f"ambiguous local timestamp during daylight-saving transition: {parsed.isoformat()}")
            selected = first if valid_first else second
            return selected.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

        # Scan a bounded prefix and select the row with the strongest recognizable header.
        if header_row is None:
            best_row = None
            best_score = -1
            for row_index, row in enumerate(ws.iter_rows(min_row=1, max_row=min(ws.max_row or 1, 20), values_only=True), start=1):
                values = list(row[:max_columns])
                score = 0
                has_timestamp = False
                for value in values:
                    if value is None:
                        continue
                    header = str(value).strip()
                    normalized = _normalise_header(header)
                    base, _ = _split_header_unit(header)
                    if normalized in _TIMESTAMP_ALIASES or base in _TIMESTAMP_ALIASES:
                        has_timestamp = True
                    if _resolve_column(header, {}, {}) is not None:
                        score += 1
                if has_timestamp and score > best_score:
                    best_score, best_row = score, row_index
            if best_row is None or best_score < 1:
                raise ValueError("could not identify a timestamp and supported signal header in the first 20 rows")
            header_row = best_row
        if header_row < 1 or header_row > 20:
            raise ValueError("header_row must be between 1 and 20")

        headers = [cell_text(value).strip() for value in next(
            ws.iter_rows(min_row=header_row, max_row=header_row, values_only=True)
        )[:max_columns]]
        while headers and not headers[-1]:
            headers.pop()
        if not headers:
            raise ValueError("selected header row is empty")
        timestamp_columns = []
        for index, header in enumerate(headers):
            normalized = _normalise_header(header)
            base, _ = _split_header_unit(header)
            if normalized in _TIMESTAMP_ALIASES or base in _TIMESTAMP_ALIASES:
                timestamp_columns.append(index)
        if len(timestamp_columns) != 1:
            raise ValueError("worksheet must contain exactly one recognizable timestamp column")
        timestamp_index = timestamp_columns[0]

        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(headers)
        extracted_rows = 0
        scanned_rows = 0
        formula_count = 0
        for row_number, row in enumerate(
            ws.iter_rows(min_row=header_row + 1, max_col=min(ws.max_column or 1, max_columns), values_only=True),
            start=header_row + 1,
        ):
            scanned_rows += 1
            if scanned_rows > max_rows:
                raise ValueError(f"worksheet scan exceeds the {max_rows:,}-row safety limit")
            values = list(row[:len(headers)])
            if not any(value is not None for value in values):
                continue
            if extracted_rows >= max_rows:
                raise ValueError(f"worksheet exceeds the {max_rows:,}-row import limit")
            # Count formulas separately; only cached values are imported.
            formula_row = next(
                formula_ws.iter_rows(min_row=row_number, max_row=row_number, max_col=len(headers), values_only=True)
            )
            formula_count += sum(
                1 for value in formula_row
                if isinstance(value, str) and value.startswith("=")
            )
            if timestamp_index < len(values):
                values[timestamp_index] = localize_naive(values[timestamp_index])
            writer.writerow([cell_text(value) for value in values])
            extracted_rows += 1

        report = inspect_csv_bytes(
            output.getvalue().encode("utf-8"),
            source_type=source_type,
            source_name=source_name,
            column_overrides=column_overrides,
            source_unit_overrides=source_unit_overrides,
            expected_interval_minutes=expected_interval_minutes,
            now=now,
        )
        report["artifact"] = {
            **report["artifact"],
            "source_name": source_name,
            "source_type": source_type,
            "sha256": hashlib.sha256(content).hexdigest(),
            "media_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "worksheet": selected_name,
            "header_row": header_row,
            "extracted_row_count": extracted_rows,
            "formula_cell_count": formula_count,
        }
        report["source_adapter"] = "xlsx_cached_values_only"
        if formula_count:
            report["issues"].append({
                "code": "formula_cells_present",
                "severity": "warning",
                "message": f"{formula_count} formula cells were detected; IslandOS imported cached values only and did not calculate formulas.",
            })
            report["warning_count"] += 1
        report["source_timezone"] = timezone_name
        report["source_workbook_sha256"] = hashlib.sha256(content).hexdigest()
        return report
    finally:
        value_book.close()
        formula_book.close()


def inspect_excel_sheets(content: bytes, *, max_file_bytes: int = 20 * 1024 * 1024) -> list[dict[str, Any]]:
    """Return worksheet names and visibility without extracting customer data."""
    from openpyxl import load_workbook

    if not isinstance(content, bytes):
        raise TypeError("content must be bytes")
    if not content:
        raise ValueError("workbook is empty")
    if len(content) > max_file_bytes:
        raise ValueError(f"workbook exceeds the {max_file_bytes // (1024 * 1024)} MB import limit")
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            members = archive.infolist()
            if sum(item.file_size for item in members) > 200 * 1024 * 1024:
                raise ValueError("workbook expands beyond the 200 MB safety limit")
            if any(item.file_size > 1024 * 1024 and item.compress_size > 0 and item.file_size / item.compress_size > 200 for item in members):
                raise ValueError("workbook contains an unusually highly compressed member")
            if "[Content_Types].xml" not in archive.namelist() or "xl/workbook.xml" not in archive.namelist():
                raise ValueError("file is not a valid .xlsx package")
    except zipfile.BadZipFile as exc:
        raise ValueError("file is not a valid .xlsx package") from exc
    try:
        workbook = load_workbook(io.BytesIO(content), read_only=False, data_only=True)
    except Exception as exc:
        raise ValueError("file is not a readable .xlsx workbook") from exc
    try:
        return [
            {"name": sheet.title, "state": sheet.sheet_state, "visible": sheet.sheet_state == "visible"}
            for sheet in workbook.worksheets
        ]
    finally:
        workbook.close()

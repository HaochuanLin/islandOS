"""Join out-of-sample water-demand forecasts to paired power/dispatch data.

The model report must come from one of IslandOS's chronological forecast
experiments. The adapter only joins predictions by UTC timestamp; it does not
train a model, create forecasts, impute missing values, or alter actual demand.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

POWER_COLUMNS = (
    "timestamp_utc",
    "actual_surplus_kw",
    "forecast_surplus_kw",
    "water_demand_m3",
    "cooling_demand_kw_th",
)
SUPPORTED_REPORT_STATUSES = {
    "baseline_evaluated",
    "models_compared",
    "rolling_backtest_completed",
}
FORECAST_COLUMN_CANDIDATES = (
    "plugin_forecast_m3",
    "hist_gradient_boosting",
    "lstm_deep_learning",
    "rolling_origin_bias_corrected_forecast_m3",
    "seasonal_bias_corrected_forecast_m3",
    "seasonal_naive_24h_forecast_m3",
    "seasonal_naive_previous_day",
    "seasonal_naive_previous_week",
    "persistence_forecast_m3",
    "persistence_previous_hour",
)


def _parse_timestamp(raw: str, label: str) -> datetime:
    try:
        stamp = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Invalid timezone-aware timestamp for {label}: {raw!r}") from exc
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError(f"Timestamp must include a timezone for {label}: {raw!r}")
    return stamp.astimezone(timezone.utc)


def _parse_nonnegative(raw: Any, label: str) -> float:
    try:
        value = float(raw)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Invalid numeric value for {label}: {raw!r}") from exc
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"Value must be finite and non-negative for {label}: {raw!r}")
    return value


def _load_power_rows(input_csv: str | Path) -> dict[datetime, dict[str, str]]:
    input_path = Path(input_csv)
    with input_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = reader.fieldnames or []
        duplicates = sorted({header for header in headers if headers.count(header) > 1})
        if duplicates:
            raise ValueError("Power CSV has duplicate columns: " + ", ".join(duplicates))
        missing = set(POWER_COLUMNS) - set(headers)
        if missing:
            raise ValueError("Power CSV missing columns: " + ", ".join(sorted(missing)))
        rows = list(reader)

    for line, row in enumerate(rows, start=2):
        if None in row:
            raise ValueError(f"Power CSV has extra fields at CSV line {line}")

    if not rows:
        raise ValueError("Power CSV must contain at least one hourly row")

    indexed: dict[datetime, dict[str, str]] = {}
    previous: datetime | None = None
    for line, row in enumerate(rows, start=2):
        stamp = _parse_timestamp(row.get("timestamp_utc") or "", f"power CSV line {line}")
        if stamp in indexed:
            raise ValueError(f"Duplicate power timestamp at CSV line {line}")
        if previous is not None and (stamp - previous).total_seconds() != 3600:
            raise ValueError(
                f"Power CSV must contain strictly ordered, continuous hourly records at line {line}"
            )
        for column in POWER_COLUMNS[1:]:
            _parse_nonnegative(row.get(column), f"{column} at power CSV line {line}")
        indexed[stamp] = row
        previous = stamp
    return indexed


def _load_forecast_rows(
    report_json: str | Path,
    forecast_column: str | None,
    fold: int | None,
) -> tuple[str, list[dict[str, Any]], str]:
    report_path = Path(report_json)
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid forecast report JSON: {report_path}") from exc

    status = report.get("status")
    if status not in SUPPORTED_REPORT_STATUSES:
        raise ValueError(
            "Forecast report status must be one of: "
            + ", ".join(sorted(SUPPORTED_REPORT_STATUSES))
        )

    rows = report.get("forecast_rows")
    if rows is None:
        rows = report.get("test_predictions")
    if not isinstance(rows, list) or not rows:
        raise ValueError("Forecast report must contain non-empty forecast_rows or test_predictions")
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError("Every forecast report row must be an object")
    if fold is not None:
        if not any("fold" in row for row in rows):
            raise ValueError("--fold can only be used with a report that contains fold identifiers")
        rows = [row for row in rows if row.get("fold") == fold]
        if not rows:
            raise ValueError(f"Forecast report does not contain fold {fold}")

    available_columns = set(rows[0]) - {"timestamp", "actual_water_demand_m3", "fold"}
    selected_column = forecast_column
    if selected_column is None:
        selected_column = next(
            (candidate for candidate in FORECAST_COLUMN_CANDIDATES if candidate in available_columns),
            None,
        )
    if not selected_column:
        raise ValueError(
            "Cannot select a forecast column automatically; pass --forecast-column. "
            "Available columns: " + ", ".join(sorted(available_columns))
        )

    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"Forecast report row {index + 1} is not an object")
        if "timestamp" not in row or "actual_water_demand_m3" not in row:
            raise ValueError(
                f"Forecast report row {index + 1} must include timestamp and actual_water_demand_m3"
            )
        if selected_column not in row:
            raise ValueError(
                f"Forecast column {selected_column!r} is missing at forecast report row {index + 1}"
            )
    return selected_column, rows, status


def build_forecast_dispatch_input(
    power_csv: str | Path,
    forecast_report_json: str | Path,
    output_csv: str | Path,
    forecast_column: str | None = None,
    report_json: str | Path | None = None,
    fold: int | None = None,
) -> dict[str, Any]:
    """Join a chronological forecast report to paired dispatch inputs by timestamp."""
    power_rows = _load_power_rows(power_csv)
    selected_column, forecast_rows, source_status = _load_forecast_rows(
        forecast_report_json, forecast_column, fold
    )

    joined: list[tuple[datetime, dict[str, str], float]] = []
    seen_forecast_timestamps: set[datetime] = set()
    previous: datetime | None = None
    for index, forecast_row in enumerate(forecast_rows, start=1):
        stamp = _parse_timestamp(str(forecast_row["timestamp"]), f"forecast report row {index}")
        if stamp in seen_forecast_timestamps:
            raise ValueError(f"Duplicate forecast timestamp at report row {index}")
        if previous is not None and (stamp - previous).total_seconds() != 3600:
            raise ValueError(
                f"Forecast report must contain continuous hourly records at row {index}"
            )
        seen_forecast_timestamps.add(stamp)
        previous = stamp

        if stamp not in power_rows:
            raise ValueError(
                "No matching power/dispatch row for forecast timestamp "
                + stamp.isoformat().replace("+00:00", "Z")
            )
        power_row = power_rows[stamp]
        reported_actual = _parse_nonnegative(
            forecast_row["actual_water_demand_m3"],
            f"actual_water_demand_m3 at forecast report row {index}",
        )
        paired_actual = _parse_nonnegative(
            power_row["water_demand_m3"],
            f"water_demand_m3 at matching power row {index}",
        )
        if not math.isclose(reported_actual, paired_actual, rel_tol=1e-9, abs_tol=1e-6):
            raise ValueError(
                "Actual water demand differs between forecast report and power CSV at "
                + stamp.isoformat().replace("+00:00", "Z")
                + "; refusing to join mismatched series"
            )
        predicted = _parse_nonnegative(
            forecast_row[selected_column],
            f"{selected_column} at forecast report row {index}",
        )
        joined.append((stamp, power_row, predicted))

    output_path = Path(output_csv)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [*POWER_COLUMNS, "forecast_water_demand_m3"]
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for stamp, power_row, predicted in joined:
            writer.writerow({
                "timestamp_utc": stamp.isoformat().replace("+00:00", "Z"),
                "actual_surplus_kw": power_row["actual_surplus_kw"],
                "forecast_surplus_kw": power_row["forecast_surplus_kw"],
                "water_demand_m3": power_row["water_demand_m3"],
                "cooling_demand_kw_th": power_row["cooling_demand_kw_th"],
                "forecast_water_demand_m3": predicted,
            })

    result: dict[str, Any] = {
        "status": "forecast_dispatch_input_built",
        "power_input_csv": str(power_csv),
        "forecast_report_json": str(forecast_report_json),
        "forecast_report_status": source_status,
        "forecast_column_used": selected_column,
        "fold_selected": fold,
        "output_csv": str(output_path),
        "matched_rows": len(joined),
        "first_timestamp_utc": joined[0][0].isoformat().replace("+00:00", "Z"),
        "last_timestamp_utc": joined[-1][0].isoformat().replace("+00:00", "Z"),
        "join_key": "timezone-normalized UTC timestamp",
        "actual_water_demand_preserved_for_execution": True,
        "forecast_water_demand_added_for_planning": True,
        "limitations": [
            "This adapter joins existing out-of-sample predictions; it does not train or update a model.",
            "Power forecast quality and data provenance are not independently verified.",
            "The selected water-demand forecast report must correspond to the same site and actual demand series as the paired power CSV.",
            "Successful joining verifies data alignment, not forecast skill or operational readiness.",
        ],
    }
    report_path = Path(report_json) if report_json else output_path.with_name(
        output_path.stem + ".report.json"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    result["report_json"] = str(report_path)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("power_csv", help="Hourly paired power/dispatch CSV")
    parser.add_argument("forecast_report_json", help="JSON from an IslandOS chronological water-demand forecast experiment")
    parser.add_argument("--forecast-column", help="Prediction field in forecast_rows/test_predictions; auto-selects a known model field if omitted")
    parser.add_argument("--fold", type=int, help="Optional fold number when joining one window from a repeated backtest report")
    parser.add_argument("--output", default="build/forecast-dispatch/paired_with_water_forecast.csv")
    parser.add_argument("--report", help="Optional JSON sidecar report path")
    args = parser.parse_args()
    try:
        report = build_forecast_dispatch_input(
            args.power_csv,
            args.forecast_report_json,
            args.output,
            forecast_column=args.forecast_column,
            report_json=args.report,
            fold=args.fold,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

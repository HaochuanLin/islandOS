"""Build auditable model features from the raw NASA POWER hourly CSV.

This produces environmental/time covariates only. It does not create dispatch
inputs, infer actual renewable generation, or train a model.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import datetime
from pathlib import Path

PARAMETERS = ("ALLSKY_SFC_SW_DWN", "T2M", "WS10M")
RAW_COLUMNS = ("timestamp_utc", *PARAMETERS)
LAG_HOURS = (1, 3, 24)


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Invalid timestamp_utc: {value!r}") from exc
    if parsed.tzinfo is None:
        raise ValueError("timestamp_utc must include a timezone")
    return parsed


def prepare_features(input_csv: str | Path, output_csv: str | Path) -> dict:
    input_path = Path(input_csv)
    metadata_path = input_path.with_suffix(input_path.suffix + ".metadata.json")
    if not metadata_path.exists():
        raise ValueError(f"Missing provenance sidecar: {metadata_path}")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    source_parameters = metadata.get("response_metadata", {}).get("parameters", {})
    missing_units = [
        name for name in PARAMETERS
        if not isinstance(source_parameters.get(name), dict)
        or not source_parameters[name].get("units")
    ]
    if missing_units:
        raise ValueError(
            "Missing source units in metadata for: " + ", ".join(missing_units)
        )

    with input_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = reader.fieldnames or []
        duplicates = sorted({name for name in headers if headers.count(name) > 1})
        if duplicates:
            raise ValueError("Input CSV has duplicate columns: " + ", ".join(duplicates))
        missing = [name for name in RAW_COLUMNS if name not in headers]
        if missing:
            raise ValueError("Input CSV missing columns: " + ", ".join(missing))
        raw = list(reader)

    for line, row in enumerate(raw, start=2):
        if None in row:
            raise ValueError(f"Input CSV has extra fields at CSV line {line}")

    if not raw:
        raise ValueError("Input CSV contains no records")
    parsed = []
    previous = None
    for line, row in enumerate(raw, start=2):
        stamp = _parse_timestamp(row["timestamp_utc"])
        if previous is not None:
            delta = (stamp - previous).total_seconds()
            if delta != 3600:
                raise ValueError(
                    f"Expected ordered hourly records; line {line} is {delta / 60:g} minutes after previous row"
                )
        values = {}
        for name in PARAMETERS:
            text_value = (row.get(name) or "").strip()
            if not text_value:
                raise ValueError(f"Missing {name} at {row['timestamp_utc']}; no imputation performed")
            try:
                value = float(text_value)
            except ValueError as exc:
                raise ValueError(f"Non-numeric {name} at {row['timestamp_utc']}") from exc
            if not math.isfinite(value):
                raise ValueError(f"Non-finite {name} at {row['timestamp_utc']}")
            values[name] = value
        parsed.append((stamp, values))
        previous = stamp

    feature_names = [
        "hour_sin", "hour_cos", "day_of_year_sin", "day_of_year_cos",
        *[f"{name.lower()}_lag_{lag}h" for name in PARAMETERS for lag in LAG_HOURS],
        *[f"{name.lower()}_current" for name in PARAMETERS],
    ]
    output_rows = []
    for i, (stamp, values) in enumerate(parsed):
        # Lags only refer to earlier observations. The first 24 hours are
        # omitted rather than filled with fabricated values.
        if i < max(LAG_HOURS):
            continue
        hour = stamp.hour + stamp.minute / 60
        day_fraction = (stamp.timetuple().tm_yday - 1) / 366.0
        features = {
            "timestamp_utc": stamp.isoformat().replace("+00:00", "Z"),
            "hour_sin": math.sin(2 * math.pi * hour / 24),
            "hour_cos": math.cos(2 * math.pi * hour / 24),
            "day_of_year_sin": math.sin(2 * math.pi * day_fraction),
            "day_of_year_cos": math.cos(2 * math.pi * day_fraction),
        }
        for name in PARAMETERS:
            for lag in LAG_HOURS:
                features[f"{name.lower()}_lag_{lag}h"] = parsed[i - lag][1][name]
        for name in PARAMETERS:
            features[f"{name.lower()}_current"] = values[name]
        output_rows.append(features)

    if not output_rows:
        raise ValueError(
            f"Need at least {max(LAG_HOURS) + 1} continuous hourly rows to build lag features"
        )

    output_path = Path(output_csv)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["timestamp_utc", *feature_names])
        writer.writeheader()
        writer.writerows(output_rows)

    result = {
        "source": "NASA POWER raw hourly CSV",
        "input_csv": str(input_path),
        "output_csv": str(output_path),
        "source_metadata": str(metadata_path),
        "output_metadata": str(output_path) + ".metadata.json",
        "input_rows": len(raw),
        "output_rows": len(output_rows),
        "warmup_rows_omitted": len(raw) - len(output_rows),
        "lag_hours": list(LAG_HOURS),
        "units": {name: source_parameters[name]["units"] for name in PARAMETERS},
        "feature_columns": feature_names,
        "limitations": [
            "Features are environmental covariates, not actual wind/PV generation or operational demand.",
            "No target labels are generated and no forecasting model is trained.",
            "First 24 rows are omitted because 24-hour lag features are unavailable.",
            "No missing-value imputation, clipping, or unit conversion is performed.",
            "Current-hour weather covariates are included; for prospective forecasting, supply weather forecasts available at the decision time to avoid look-ahead leakage.",
        ],
    }
    Path(str(output_path) + ".metadata.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_csv")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(json.dumps(prepare_features(args.input_csv, args.output), indent=2))


if __name__ == "__main__":
    main()

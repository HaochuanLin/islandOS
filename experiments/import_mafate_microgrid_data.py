"""Normalize open Mafate island microgrid measurements to hourly CSVs.

Raw CSV files must be downloaded from the cited Zenodo record and extracted
locally. This script averages measurements within each hour, never interpolates
missing readings, and keeps the original timezone status explicit.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

DATASET_FILES = {
    "meteo": ("Meteo_dataset.csv", "Meteo_dataset_.csv"),
    "solar": ("Solar_plant_dataset.csv",),
    "house_1": ("Demand_house_1_dataset.csv",),
    "house_2": ("Demand_house_2_dataset.csv",),
    "house_3": ("Demand_house_3_dataset.csv",),
}
METEO_FIELDS = {
    "Gincl": "ghi_inclined_kw_m2",
    "Ghi": "ghi_horizontal_kw_m2",
    "Tpv": "pv_surface_temperature_c",
    "Ta": "air_temperature_c",
    "Rh": "relative_humidity_pct",
    "Wd": "wind_direction_deg",
    "Ws": "wind_speed_m_s",
    "Press": "pressure_mbar",
}
SOLAR_FIELDS = {
    "Pout": "inverter_output_power_kw",
    "Ppv1": "pv1_power_kw",
    "Ppv2": "pv2_power_kw",
    "Upv1": "pv1_voltage_v",
    "Upv2": "pv2_voltage_v",
    "Ubat": "battery_voltage_v",
    "Ibat": "battery_current_a",
    "Tbat": "battery_temperature_c",
}
HOUSE_CHANNELS = {
    "house_1": (4, "Input4"),
    "house_2": (5, "Input5"),
    "house_3": (4, "Input1"),
}


def _parse_timestamp(raw: Any, path: Path, line: int) -> datetime:
    value = str(raw or "").strip()
    if not value:
        raise ValueError(f"Missing Date at {path.name}:{line}")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        return datetime.fromisoformat(candidate)
    except ValueError:
        pass
    # The source documents its first record as 1 May 2020; day-first parsing
    # avoids interpreting 01/05/2020 as January 5 in a US locale.
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M",
                "%d-%m-%Y %H:%M:%S", "%Y/%m/%d %H:%M:%S",
                "%Y-%m-%d %H:%M", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise ValueError(f"Unsupported Date value {value!r} at {path.name}:{line}")


def _number(raw: Any, path: Path, line: int, column: str) -> float | None:
    value = str(raw or "").strip()
    if not value:
        return None
    try:
        number = float(value)
    except ValueError as exc:
        raise ValueError(f"Non-numeric {column}={value!r} at {path.name}:{line}") from exc
    if not math.isfinite(number):
        raise ValueError(f"Non-finite {column} at {path.name}:{line}")
    return number


def _resolve_file(root: Path, key: str) -> Path:
    candidates = DATASET_FILES[key]
    matches = []
    for candidate in candidates:
        direct = root / candidate
        if direct.is_file():
            matches.append(direct)
        else:
            matches.extend(path for path in root.rglob(candidate) if path.is_file())
    unique = sorted(set(path.resolve() for path in matches))
    if not unique:
        raise FileNotFoundError(
            f"Could not find {', '.join(candidates)} under {root}. "
            "Download and extract the Zenodo dataset files first."
        )
    if len(unique) > 1:
        raise ValueError(f"Multiple candidate files found for {key}: {unique}")
    return unique[0]


def _read_hourly(path: Path, fields: dict[str, str], scale: float = 1.0) -> dict[str, Any]:
    """Read one raw series and calculate within-hour means without filling gaps."""
    bins: dict[datetime, dict[str, Any]] = {}
    first_stamp = last_stamp = None
    timezone_modes: set[bool] = set()
    raw_count = 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        sample = handle.read(8192)
        handle.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(handle, dialect=dialect)
        if not reader.fieldnames:
            raise ValueError(f"No CSV header in {path.name}")
        reader.fieldnames = [name.strip() for name in reader.fieldnames]
        duplicates = sorted({name for name in reader.fieldnames if reader.fieldnames.count(name) > 1})
        if duplicates:
            raise ValueError(f"{path.name} has duplicate columns after whitespace normalization: {', '.join(duplicates)}")
        required = {"Date", *fields.keys()}
        missing = required - set(reader.fieldnames)
        if missing:
            raise ValueError(f"{path.name} missing columns: {', '.join(sorted(missing))}")
        for line, row in enumerate(reader, start=2):
            if None in row:
                raise ValueError(f"{path.name} has extra fields at CSV line {line}")
            row = {(key or "").strip(): value for key, value in row.items()}
            stamp = _parse_timestamp(row.get("Date"), path, line)
            timezone_modes.add(stamp.tzinfo is not None and stamp.utcoffset() is not None)
            if len(timezone_modes) > 1:
                raise ValueError(f"Mixed timezone-aware and timezone-naive timestamps in {path.name}")
            hour = stamp.replace(minute=0, second=0, microsecond=0)
            first_stamp = stamp if first_stamp is None or stamp < first_stamp else first_stamp
            last_stamp = stamp if last_stamp is None or stamp > last_stamp else last_stamp
            entry = bins.setdefault(hour, {
                "samples_in_hour": 0,
                "sums": {name: 0.0 for name in fields.values()},
                "counts": {name: 0 for name in fields.values()},
            })
            entry["samples_in_hour"] += 1
            raw_count += 1
            for source_name, output_name in fields.items():
                number = _number(row.get(source_name), path, line, source_name)
                if number is not None:
                    entry["sums"][output_name] += number * scale
                    entry["counts"][output_name] += 1

    if not bins:
        raise ValueError(f"No data rows found in {path.name}")
    output_fields = list(fields.values())
    hourly = {}
    for hour, entry in bins.items():
        record = {"samples_in_hour": entry["samples_in_hour"]}
        for name in output_fields:
            count = entry["counts"][name]
            record[name] = entry["sums"][name] / count if count else None
        hourly[hour] = record
    return {
        "path": path,
        "bins": hourly,
        "raw_row_count": raw_count,
        "first_timestamp": first_stamp,
        "last_timestamp": last_stamp,
        "timezone_aware": next(iter(timezone_modes)),
        "fields": output_fields,
    }


def _write_csv(path: Path, columns: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)



def _sha256_file(path: Path) -> str:
    """Hash a source file incrementally so large raw datasets need not fit in memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def _hour_range(start: datetime, end: datetime):
    current = start.replace(minute=0, second=0, microsecond=0)
    final = end.replace(minute=0, second=0, microsecond=0)
    while current <= final:
        yield current
        current += timedelta(hours=1)


def import_dataset(data_dir: str | Path, output_dir: str | Path) -> dict[str, Any]:
    """Normalize five extracted Mafate CSV files and create an hourly merged table."""
    root, output = Path(data_dir), Path(output_dir)
    if not root.is_dir():
        raise NotADirectoryError(f"Data directory not found: {root}")
    output.mkdir(parents=True, exist_ok=True)
    paths = {key: _resolve_file(root, key) for key in DATASET_FILES}

    meteo = _read_hourly(paths["meteo"], METEO_FIELDS)
    solar = _read_hourly(paths["solar"], SOLAR_FIELDS)
    houses = {}
    for key, (last_channel, _) in HOUSE_CHANNELS.items():
        fields = {f"Input{i}": f"input_{i}_kw" for i in range(1, last_channel + 1)}
        houses[key] = _read_hourly(paths[key], fields, scale=0.001)

    timezone_modes = {series["timezone_aware"] for series in [meteo, solar, *houses.values()]}
    if len(timezone_modes) > 1:
        raise ValueError("Source files mix timezone-aware and timezone-naive timestamps")

    all_stamps = [
        stamp for series in [meteo, solar, *houses.values()]
        for stamp in (series["first_timestamp"], series["last_timestamp"])
    ]
    start, end = min(all_stamps), max(all_stamps)
    hours = list(_hour_range(start, end))

    def series_rows(series: dict[str, Any]) -> list[dict[str, Any]]:
        rows = []
        for hour in hours:
            values = series["bins"].get(hour, {})
            row = {"timestamp_local": hour.isoformat(), "samples_in_hour": values.get("samples_in_hour", 0)}
            row.update({field: values.get(field) for field in series["fields"]})
            rows.append(row)
        return rows

    _write_csv(output / "meteo_hourly.csv",
               ["timestamp_local", "samples_in_hour", *meteo["fields"]], series_rows(meteo))
    _write_csv(output / "solar_plant_hourly.csv",
               ["timestamp_local", "samples_in_hour", *solar["fields"]], series_rows(solar))

    house_fields = ["timestamp_local", "house_id", "total_load_kw",
                    "aggregate_source_column", "samples_in_hour",
                    "input_1_kw", "input_2_kw", "input_3_kw", "input_4_kw", "input_5_kw"]
    house_rows = []
    aggregate_columns = {}
    for key, (last_channel, aggregate_source) in HOUSE_CHANNELS.items():
        house_id = int(key.split("_")[1])
        aggregate_columns[key] = aggregate_source
        series = houses[key]
        for hour in hours:
            values = series["bins"].get(hour, {})
            channel_values = {f"input_{i}_kw": None for i in range(1, 6)}
            channel_values.update({name: values.get(name) for name in series["fields"]})
            house_rows.append({
                "timestamp_local": hour.isoformat(), "house_id": house_id,
                "total_load_kw": values.get(f"input_{int(aggregate_source[5:])}_kw"),
                "aggregate_source_column": aggregate_source,
                "samples_in_hour": values.get("samples_in_hour", 0),
                **channel_values,
            })
    _write_csv(output / "house_loads_hourly.csv", house_fields, house_rows)

    combined_rows = []
    combined_fields = [
        "timestamp_local", "ghi_horizontal_kw_m2", "ghi_inclined_kw_m2",
        "air_temperature_c", "pv_surface_temperature_c", "relative_humidity_pct",
        "wind_speed_m_s", "wind_direction_deg", "pressure_mbar", "meteo_samples",
        "inverter_output_power_kw", "pv1_power_kw", "pv2_power_kw",
        "pv1_voltage_v", "pv2_voltage_v", "battery_voltage_v",
        "battery_current_a", "battery_temperature_c", "plant_samples",
        "house_1_load_kw", "house_1_samples", "house_2_load_kw",
        "house_2_samples", "house_3_load_kw", "house_3_samples",
    ]
    for hour in hours:
        m, p = meteo["bins"].get(hour, {}), solar["bins"].get(hour, {})
        row = {
            "timestamp_local": hour.isoformat(),
            "meteo_samples": m.get("samples_in_hour", 0),
            "plant_samples": p.get("samples_in_hour", 0),
        }
        for field in METEO_FIELDS.values():
            row[field] = m.get(field)
        for field in SOLAR_FIELDS.values():
            row[field] = p.get(field)
        for key, (_, aggregate_source) in HOUSE_CHANNELS.items():
            values = houses[key]["bins"].get(hour, {})
            channel = int(aggregate_source[5:])
            row[f"{key}_load_kw"] = values.get(f"input_{channel}_kw")
            row[f"{key}_samples"] = values.get("samples_in_hour", 0)
        combined_rows.append(row)
    _write_csv(output / "microgrid_hourly.csv", combined_fields, combined_rows)

    manifest = {
        "status": "imported",
        "dataset": "Mafate Roche Plate experimental stand-alone microgrid",
        "source_url": "https://zenodo.org/records/8186303",
        "doi": "10.5281/zenodo.8186303",
        "citation": "Calogine, D., Francou, J., Abbezzot, C., & Tovondahiniriko, F. (2023). Data in experimental stand-alone microgrid: solar production, domestic loads, battery storage and meteorological series. Data in Brief, 51, 109643. https://doi.org/10.1016/j.dib.2023.109643",
        "license": "Creative Commons Attribution 4.0 International (CC BY 4.0); attribute the authors and dataset.",
        "site": "Roche Plate, Mafate, Reunion Island",
        "measurement_period_as_published": "2020-05-01 through 2021-05-01",
        "raw_sampling_as_published": {
            "meteorology": "20 seconds",
            "solar_plant_and_house_loads": "1 minute",
        },
        "timezone_status": "preserved as provided; original timezone metadata should be confirmed before operational use",
        "hourly_aggregation": "arithmetic mean of available readings within each hour; no interpolation or gap filling",
        "source_row_counts": {key: series["raw_row_count"] for key, series in {
            "meteo": meteo, "solar": solar, **houses
        }.items()},
        "source_file_sha256": {
            key: _sha256_file(paths[key]) for key in DATASET_FILES
        },
        "hourly_bin_counts": {
            "meteo_hours_with_samples": len(meteo["bins"]),
            "solar_plant_hours_with_samples": len(solar["bins"]),
            **{f"{key}_hours_with_samples": len(series["bins"]) for key, series in houses.items()},
            "continuous_hourly_rows_in_output": len(hours),
        },
        "row_counts": {
            "meteo_hourly.csv": len(hours),
            "solar_plant_hourly.csv": len(hours),
            "house_loads_hourly.csv": len(house_rows),
            "microgrid_hourly.csv": len(combined_rows),
        },
        "data_limitations": [
            "This is a real field dataset from three homes and one experimental microgrid, not a representative sample of all islands.",
            "No freshwater demand, desalination output, or reservoir-level measurements are included.",
            "Household channel meanings differ by house; aggregate total load is selected from Input4, Input5, and Input1 for houses 1, 2, and 3 respectively, per the dataset README.",
            "Hourly values are means of high-frequency readings, not reconstructed hourly energy totals.",
            "Missing readings remain blank; sample counts indicate the number of source rows per hour, not completeness guarantees.",
            "Timezone metadata is not stated in the dataset README and must be checked before operational scheduling.",
        ],
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True, help="Directory containing extracted Zenodo CSV files")
    parser.add_argument("--output-dir", required=True, help="Directory for normalized hourly outputs")
    args = parser.parse_args()
    print(json.dumps(import_dataset(args.data_dir, args.output_dir), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

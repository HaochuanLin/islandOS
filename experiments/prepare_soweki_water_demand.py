"""Convert the public SOWEKI 15-minute water-demand series to hourly CSV.

The source values are flow rates in m³/h. For each complete UTC hour, the
arithmetic mean of its four 15-minute samples is numerically the hourly volume
in m³ over a one-hour interval. Missing quarter-hours are never interpolated.
Only the longest continuous run of complete hours is exported, because the
forecast baseline intentionally rejects time gaps.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen

QUARTER_HOUR_SECONDS = 15 * 60
HOUR_SECONDS = 60 * 60


def _parse_timestamp(raw: str, line_number: int) -> datetime:
    try:
        stamp = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Invalid timestamp at CSV line {line_number}: {raw!r}") from exc
    if stamp.tzinfo is None:
        raise ValueError(f"Timestamp must include a timezone at CSV line {line_number}")
    return stamp.astimezone(timezone.utc)


def _longest_contiguous_run(hours: list[tuple[datetime, float]]) -> list[tuple[datetime, float]]:
    if not hours:
        return []
    best_start = current_start = 0
    best_length = current_length = 1
    for index in range(1, len(hours)):
        if (hours[index][0] - hours[index - 1][0]).total_seconds() == HOUR_SECONDS:
            current_length += 1
        else:
            current_start = index
            current_length = 1
        if current_length > best_length:
            best_start = current_start
            best_length = current_length
    return hours[best_start : best_start + best_length]


def prepare_soweki_water_demand(
    input_csv: str | Path,
    output_csv: str | Path,
    report_json: str | Path | None = None,
    min_hours: int = 48,
) -> dict:
    """Prepare a contiguous hourly demand series without inventing missing values."""
    if min_hours < 43:
        raise ValueError("min_hours must be at least 43 for the forecast baseline's default chronological split")

    input_path = Path(input_csv)
    with input_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"timestamp", "value"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError("Input CSV missing columns: " + ", ".join(sorted(missing)))
        rows = list(reader)

    if not rows:
        raise ValueError("Input CSV contains no data rows")

    samples: list[tuple[datetime, float]] = []
    source_rows = len(rows)
    source_hour_bins_seen: set[datetime] = set()
    source_non_increasing_adjacent_pairs = 0
    invalid_value_rows_excluded = 0
    invalid_value_examples: list[dict] = []
    previous_source_timestamp: datetime | None = None
    for line_number, row in enumerate(rows, start=2):
        stamp = _parse_timestamp(row.get("timestamp") or "", line_number)
        if stamp.second or stamp.microsecond or stamp.minute not in (0, 15, 30, 45):
            raise ValueError(
                f"Expected a 15-minute-aligned timestamp at CSV line {line_number}"
            )
        source_hour_bins_seen.add(stamp.replace(minute=0, second=0, microsecond=0))
        if previous_source_timestamp is not None and stamp <= previous_source_timestamp:
            source_non_increasing_adjacent_pairs += 1
        previous_source_timestamp = stamp

        raw_value = (row.get("value") or "").strip()
        try:
            value = float(raw_value)
            invalid_reason = (
                "non_finite" if not math.isfinite(value)
                else "negative" if value < 0
                else None
            )
        except ValueError:
            value = math.nan
            invalid_reason = "not_numeric"
        if invalid_reason is not None:
            invalid_value_rows_excluded += 1
            if len(invalid_value_examples) < 10:
                invalid_value_examples.append({
                    "line": line_number,
                    "timestamp": stamp.isoformat(),
                    "raw_value": raw_value,
                    "reason": invalid_reason,
                })
            continue
        samples.append((stamp, value))

    # The public export contains exact duplicate rows. Sort by the explicit
    # timestamp, drop only duplicates with the same numeric value, and reject
    # conflicting values for one timestamp rather than silently averaging them.
    valid_value_rows = len(samples)
    samples.sort(key=lambda item: item[0])
    unique_samples: list[tuple[datetime, float]] = []
    exact_duplicate_rows_deduplicated = 0
    for stamp, value in samples:
        if unique_samples and stamp == unique_samples[-1][0]:
            if value != unique_samples[-1][1]:
                raise ValueError(
                    f"Conflicting values for duplicate timestamp {stamp.isoformat()}; "
                    "review the source instead of choosing or averaging values"
                )
            exact_duplicate_rows_deduplicated += 1
            continue
        unique_samples.append((stamp, value))
    samples = unique_samples

    grouped: dict[datetime, list[tuple[datetime, float]]] = defaultdict(list)
    for stamp, value in samples:
        hour = stamp.replace(minute=0, second=0, microsecond=0)
        grouped[hour].append((stamp, value))

    complete_hours: list[tuple[datetime, float]] = []
    for hour in sorted(grouped):
        bucket = grouped[hour]
        expected = [hour + timedelta(minutes=15 * part) for part in range(4)]
        observed = [stamp for stamp, _ in bucket]
        if observed == expected:
            # Source is m³/h; average flow rate over one hour gives m³ per hour.
            hourly_volume_m3 = sum(value for _, value in bucket) / 4.0
            complete_hours.append((hour, hourly_volume_m3))

    selected = _longest_contiguous_run(complete_hours)
    if len(selected) < min_hours:
        raise ValueError(
            f"Only {len(selected)} consecutive complete hours are available; "
            f"at least {min_hours} are required. Check source gaps or lower --min-hours "
            "(minimum allowed: 43)."
        )

    output_path = Path(output_csv)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["timestamp", "water_demand_m3"])
        writer.writeheader()
        for stamp, value in selected:
            writer.writerow({
                "timestamp": stamp.isoformat().replace("+00:00", "Z"),
                "water_demand_m3": f"{value:.9f}",
            })

    source_span_hour_bins = int((max(source_hour_bins_seen) - min(source_hour_bins_seen)).total_seconds() // HOUR_SECONDS) + 1
    report = {
        "status": "prepared",
        "source_dataset": "SOWEKI Water Demand Dataset, soweki_wdd_*.csv",
        "source_url": "https://zenodo.org/records/19627517",
        "license": "CC BY 4.0",
        "source_rows": source_rows,
        "valid_value_rows_before_deduplication": valid_value_rows,
        "unique_timestamp_samples": len(samples),
        "exact_duplicate_rows_deduplicated": exact_duplicate_rows_deduplicated,
        "invalid_value_rows_excluded": invalid_value_rows_excluded,
        "invalid_value_examples": invalid_value_examples,
        "source_non_increasing_adjacent_pairs": source_non_increasing_adjacent_pairs,
        "complete_hour_bins_found": len(complete_hours),
        "partially_observed_hour_bins_excluded": len(source_hour_bins_seen) - len(complete_hours),
        "missing_hour_bins_inside_source_span": source_span_hour_bins - len(source_hour_bins_seen),
        "incomplete_hour_bins_excluded": source_span_hour_bins - len(complete_hours),
        "selected_contiguous_hours": len(selected),
        "minimum_hours_required": min_hours,
        "first_timestamp_utc": selected[0][0].isoformat().replace("+00:00", "Z"),
        "last_timestamp_utc": selected[-1][0].isoformat().replace("+00:00", "Z"),
        "source_value_unit": "m³/h sampled every 15 minutes",
        "output_value_unit": "m³ per hourly interval; mean of four quarter-hour flow-rate samples",
        "missing_data_policy": (
            "No interpolation. Exact duplicate timestamp/value rows are deduplicated; "
            "conflicting duplicate values are rejected. Invalid numeric rows are excluded, "
            "which makes their hour incomplete. Incomplete hours are excluded; only the "
            "longest continuous run of complete hours is exported."
        ),
        "output_csv": str(output_path),
        "limitations": [
            "This is measured demand from rural German water-reservoir outflows, not island or Nan'ao data.",
            "The chosen continuous segment may not cover the full source period.",
            "The source contains known quality issues; inspect the dataset record before interpreting results.",
            "Performance on this dataset does not establish accuracy for another location.",
        ],
    }
    report_path = Path(report_json) if report_json else output_path.with_suffix(".report.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def _download_source(dataset_id: int, destination: str | Path) -> Path:
    """Download one openly licensed SOWEKI CSV from its canonical Zenodo record."""
    if not 1 <= dataset_id <= 11:
        raise ValueError("dataset_id must be between 1 and 11")
    url = (
        "https://zenodo.org/records/19627517/files/"
        f"soweki_wdd_{dataset_id}.csv?download=1"
    )
    destination_path = Path(destination)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    request = Request(url, headers={"User-Agent": "islandOS-public-data-adapter/1.0"})
    with urlopen(request, timeout=60) as response:
        if response.status != 200:
            raise RuntimeError(f"Dataset download failed with HTTP status {response.status}")
        with destination_path.open("wb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
    return destination_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_csv", nargs="?", help="Local SOWEKI CSV; omit when using --download")
    parser.add_argument("--download", action="store_true", help="Download the selected public SOWEKI dataset automatically")
    parser.add_argument("--dataset-id", type=int, choices=range(1, 12), default=1, help="SOWEKI series number (1–11) when using --download")
    parser.add_argument("--output", default="build/water-demand-forecast/soweki_hourly.csv")
    parser.add_argument("--report", default=None, help="Optional report JSON path")
    parser.add_argument("--min-hours", type=int, default=48)
    args = parser.parse_args()
    if args.download:
        if args.input_csv:
            parser.error("Do not pass input_csv together with --download")
        raw_path = Path("build/water-demand-forecast/raw") / f"soweki_wdd_{args.dataset_id}.csv"
        input_csv = _download_source(args.dataset_id, raw_path)
    else:
        if not args.input_csv:
            parser.error("Provide input_csv or use --download")
        input_csv = args.input_csv
    report = prepare_soweki_water_demand(
        input_csv, args.output, report_json=args.report, min_hours=args.min_hours
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

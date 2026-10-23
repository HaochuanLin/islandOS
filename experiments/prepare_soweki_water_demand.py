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
    previous: datetime | None = None
    for line_number, row in enumerate(rows, start=2):
        stamp = _parse_timestamp(row.get("timestamp") or "", line_number)
        if stamp.second or stamp.microsecond or stamp.minute not in (0, 15, 30, 45):
            raise ValueError(
                f"Expected a 15-minute-aligned timestamp at CSV line {line_number}"
            )
        if previous is not None:
            delta = (stamp - previous).total_seconds()
            if delta <= 0:
                raise ValueError(
                    f"Timestamps must be strictly increasing; check CSV line {line_number}"
                )
            if delta % QUARTER_HOUR_SECONDS != 0:
                raise ValueError(
                    f"Timestamp spacing is not a multiple of 15 minutes at CSV line {line_number}"
                )
        raw_value = (row.get("value") or "").strip()
        try:
            value = float(raw_value)
        except ValueError as exc:
            raise ValueError(f"Invalid value at CSV line {line_number}") from exc
        if not math.isfinite(value) or value < 0:
            raise ValueError(
                f"Demand rate must be finite and non-negative at CSV line {line_number}"
            )
        samples.append((stamp, value))
        previous = stamp

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

    source_span_hour_bins = int((max(grouped) - min(grouped)).total_seconds() // HOUR_SECONDS) + 1
    report = {
        "status": "prepared",
        "source_dataset": "SOWEKI Water Demand Dataset, soweki_wdd_*.csv",
        "source_url": "https://zenodo.org/records/19627517",
        "license": "CC BY 4.0",
        "source_rows": len(samples),
        "complete_hour_bins_found": len(complete_hours),
        "partially_observed_hour_bins_excluded": len(grouped) - len(complete_hours),
        "missing_hour_bins_inside_source_span": source_span_hour_bins - len(grouped),
        "incomplete_hour_bins_excluded": source_span_hour_bins - len(complete_hours),
        "selected_contiguous_hours": len(selected),
        "minimum_hours_required": min_hours,
        "first_timestamp_utc": selected[0][0].isoformat().replace("+00:00", "Z"),
        "last_timestamp_utc": selected[-1][0].isoformat().replace("+00:00", "Z"),
        "source_value_unit": "m³/h sampled every 15 minutes",
        "output_value_unit": "m³ per hourly interval; mean of four quarter-hour flow-rate samples",
        "missing_data_policy": (
            "No interpolation. Incomplete hours are excluded; only the longest "
            "continuous run of complete hours is exported."
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_csv", help="Downloaded SOWEKI source CSV, e.g. soweki_wdd_1.csv")
    parser.add_argument("--output", default="build/water-demand-forecast/soweki_hourly.csv")
    parser.add_argument("--report", default=None, help="Optional report JSON path")
    parser.add_argument("--min-hours", type=int, default=48)
    args = parser.parse_args()
    report = prepare_soweki_water_demand(
        args.input_csv, args.output, report_json=args.report, min_hours=args.min_hours
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

"""Command-line replay gateway for canonical telemetry messages.

Reads JSON Lines or CSV, validates every row, and emits auditable JSON Lines.
It is a read-only ingest/replay tool; it does not connect to or command hardware.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from islandos_io import validate_telemetry


def _read_rows(path: str, input_format: str):
    if path == "-":
        text = sys.stdin.read()
    else:
        text = Path(path).read_text(encoding="utf-8")
    chosen = input_format
    if chosen == "auto":
        chosen = "csv" if path.lower().endswith(".csv") else "jsonl"
    if chosen == "csv":
        yield from csv.DictReader(text.splitlines())
        return
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            yield {"__parse_error__": "line %d: %s" % (line_number, exc)}
            continue
        if not isinstance(row, dict):
            yield {"__parse_error__": "line %d: each JSONL row must be an object" % line_number}
            continue
        yield row


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="CSV/JSONL file path, or - for stdin")
    parser.add_argument("--format", choices=("auto", "csv", "jsonl"), default="auto")
    parser.add_argument("--source", default="file-replay")
    parser.add_argument("--max-age-seconds", type=float, default=300.0)
    parser.add_argument(
        "--received-at",
        help="Override receive time (ISO-8601 with timezone) for deterministic replay",
    )
    parser.add_argument("--output", default="-", help="Output JSONL path, or - for stdout")
    args = parser.parse_args(argv)

    try:
        received_at = None
        if args.received_at:
            value = args.received_at[:-1] + "+00:00" if args.received_at.endswith("Z") else args.received_at
            received_at = datetime.fromisoformat(value)
            if received_at.tzinfo is None or received_at.utcoffset() is None:
                raise ValueError("--received-at must include a timezone")
            received_at = received_at.astimezone(timezone.utc)
        if args.max_age_seconds < 0:
            raise ValueError("--max-age-seconds must be non-negative")
        records = []
        invalid_count = 0
        for index, row in enumerate(_read_rows(args.input, args.format), start=1):
            if "__parse_error__" in row:
                record = {
                    "source": args.source,
                    "row": index,
                    "valid": False,
                    "errors": [row["__parse_error__"]],
                    "values": {},
                }
            else:
                frame = validate_telemetry(
                    row, source=args.source, received_at=received_at,
                    max_age_seconds=args.max_age_seconds,
                )
                record = frame.as_dict()
                record["row"] = index
            if not record["valid"]:
                invalid_count += 1
            records.append(record)

        output_text = "".join(json.dumps(item, sort_keys=True, allow_nan=False) + "\n" for item in records)
        if args.output == "-":
            sys.stdout.write(output_text)
        else:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(output_text, encoding="utf-8")
        return 2 if invalid_count else 0
    except (OSError, ValueError, TypeError, csv.Error) as exc:
        print("islandOS gateway error: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

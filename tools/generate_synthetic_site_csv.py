#!/usr/bin/env python3
"""Generate a reproducible synthetic hourly input file for the IslandOS app.

This is a software onboarding fixture, not a forecast or substitute for site data.
Every output is explicitly synthetic and must not be presented as measured data.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
from datetime import datetime, timedelta
from pathlib import Path

FIELDS = [
    "timestamp",
    "renewable_surplus_kw",
    "diesel_displacement_potential_kw",
    "grid_price_per_kwh",
    "off_peak",
    "grid_available",
    "water_demand_m3",
    "backup_available_kw",
]


def generate_rows(hours: int, seed: int, start: datetime) -> list[dict[str, str | int | float]]:
    """Return deterministic hourly rows under clearly synthetic assumptions."""
    if isinstance(hours, bool) or hours < 1 or hours > 24 * 366:
        raise ValueError("hours must be between 1 and 8784")
    if start.tzinfo is not None:
        raise ValueError("start must be a naive local timestamp; document the intended site timezone separately")
    rng = random.Random(seed)
    rows = []
    for index in range(hours):
        timestamp = start + timedelta(hours=index)
        hour = timestamp.hour
        day = timestamp.timetuple().tm_yday
        seasonal_factor = 0.75 + 0.25 * math.sin(2 * math.pi * (day - 80) / 365)
        solar = max(0.0, 42.0 * seasonal_factor * math.sin(math.pi * (hour - 6) / 12))
        wind = max(0.0, 7.0 + rng.gauss(0.0, 3.0))
        critical_load = 18.0 + (5.0 if 18 <= hour < 23 else 2.0 if 7 <= hour < 10 else 0.0)
        surplus = max(0.0, solar + wind - critical_load)
        off_peak = hour < 7 or hour >= 23
        price = 0.12 if off_peak else (0.28 if 17 <= hour < 22 else 0.20)
        demand = max(0.2, 1.1 + (0.4 if hour in (6, 7, 8, 18, 19, 20) else 0.0) + rng.gauss(0, 0.08))
        rows.append({
            "timestamp": timestamp.isoformat(timespec="minutes"),
            "renewable_surplus_kw": round(surplus, 3),
            "diesel_displacement_potential_kw": round(max(0.0, min(10.0, solar + wind - 12.0)), 3),
            "grid_price_per_kwh": price,
            "off_peak": str(off_peak).lower(),
            "grid_available": "true",
            "water_demand_m3": round(demand, 3),
            "backup_available_kw": 8.0 if day % 5 else 0.0,
        })
    return rows


def write_csv(path: Path, rows: list[dict[str, str | int | float]]) -> str:
    """Write CSV deterministically and return the SHA-256 of its exact bytes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_manifest(
    output: Path, rows: list[dict[str, str | int | float]], *,
    seed: int, start: datetime, sha256: str,
) -> dict:
    """Describe provenance and reproducibility without implying field validity."""
    return {
        "manifest_version": 1,
        "dataset_type": "synthetic",
        "is_measured_site_data": False,
        "intended_use": "software onboarding, examples, and tests only",
        "prohibited_use": "operational decisions or claims of real-site performance",
        "file": output.name,
        "sha256": sha256,
        "row_count": len(rows),
        "columns": FIELDS,
        "generation": {
            "generator": "tools/generate_synthetic_site_csv.py",
            "seed": seed,
            "start_local_naive": start.isoformat(timespec="seconds"),
            "hours": len(rows),
            "time_step": "1 hour",
        },
        "time_range": {
            "first_timestamp": rows[0]["timestamp"],
            "last_timestamp": rows[-1]["timestamp"],
            "timezone": "not encoded; timestamps are naive local time",
        },
        "limitations": [
            "Synthetic values follow illustrative rules and random noise, not a calibrated site model.",
            "A matching SHA-256 proves file identity, not measurement authenticity or physical accuracy.",
            "Document the intended site timezone before aligning with external data.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("build/synthetic_site_hourly.csv"))
    parser.add_argument(
        "--manifest", type=Path,
        help="provenance JSON path (default: <output>.manifest.json)",
    )
    parser.add_argument("--hours", type=int, default=168, help="number of hourly rows (1–8784; default: 168)")
    parser.add_argument("--seed", type=int, default=20261023, help="deterministic synthetic-data seed")
    parser.add_argument("--start", default="2026-01-01T00:00:00", help="naive local start timestamp, ISO-8601")
    args = parser.parse_args(argv)
    try:
        start = datetime.fromisoformat(args.start)
        rows = generate_rows(args.hours, args.seed, start)
    except ValueError as exc:
        parser.error(str(exc))

    digest = write_csv(args.output, rows)
    manifest_path = args.manifest or args.output.with_suffix(".manifest.json")
    manifest = build_manifest(args.output, rows, seed=args.seed, start=start, sha256=digest)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(rows)} SYNTHETIC hourly rows to {args.output}")
    print(f"SHA-256: {digest}")
    print(f"Provenance manifest: {manifest_path}")
    print("Do not use this fixture as measured site data or for operational decisions.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

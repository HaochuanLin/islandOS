"""Generate/check the deterministic synthetic forecast-dispatch benchmark fixture.

The fixture is software-test data only. It is not measured island data.
"""
from __future__ import annotations

import argparse
import csv
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data" / "examples" / "synthetic_dispatch_benchmark.csv"
FIELDS = (
    "timestamp_utc",
    "actual_surplus_kw",
    "forecast_surplus_kw",
    "water_demand_m3",
    "cooling_demand_kw_th",
)


def generate_rows() -> list[dict[str, str]]:
    rows = []
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(168):
        hour = i % 24
        day = i // 24
        solar = max(0.0, 650.0 * math.sin(math.pi * (hour - 6) / 12.0))
        wind = 75.0 + 35.0 * math.sin(i * 0.31) + 18.0 * math.cos(day * 0.9 + hour * 0.17)
        critical = 185.0 + 15.0 * math.sin(i * 0.13)
        actual = max(0.0, solar + wind - critical)
        forecast = max(0.0, actual * (1.0 + 0.18 * math.sin(i * 0.43)) + 28.0 * math.cos(i * 0.21))
        water = 1.35 + 0.22 * (1.0 + math.sin((hour - 5) * math.pi / 12.0)) + 0.08 * math.cos(day * 0.7)
        cooling = 78.0 + 24.0 * max(0.0, math.sin((hour - 8) * math.pi / 12.0)) + 12.0 * math.sin(i * 0.19)
        rows.append({
            "timestamp_utc": (start + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "actual_surplus_kw": f"{actual:.3f}",
            "forecast_surplus_kw": f"{forecast:.3f}",
            "water_demand_m3": f"{water:.3f}",
            "cooling_demand_kw_th": f"{cooling:.3f}",
        })
    return rows


def render_csv() -> str:
    import io

    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(generate_rows())
    return buffer.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--check", action="store_true", help="fail if the committed fixture differs from generated data")
    args = parser.parse_args()
    path = Path(args.output)
    expected = render_csv()
    if args.check:
        actual = path.read_text(encoding="utf-8")
        if actual != expected:
            raise SystemExit(f"{path} differs from the deterministic generated fixture")
        print(f"OK: {path} matches the deterministic 168-hour synthetic fixture")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(expected, encoding="utf-8", newline="")
    print(f"Wrote {len(generate_rows())} synthetic hourly rows to {path}")


if __name__ == "__main__":
    main()

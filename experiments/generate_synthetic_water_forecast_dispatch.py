"""Generate/check a synthetic paired power-and-water forecast dispatch fixture.

The first water forecast is a shared warm-up value; subsequent hours use
one-step persistence (the previous hour's measured water demand). All data are
synthetic software-test data, not measured island demand or forecast evidence.
"""
from __future__ import annotations

import argparse
import csv
import io
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "examples" / "synthetic_dispatch_benchmark.csv"
DEFAULT_OUTPUT = ROOT / "data" / "examples" / "synthetic_water_forecast_dispatch.csv"


def render_csv() -> str:
    with SOURCE.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError("Synthetic dispatch source fixture is empty")
    fieldnames = list(rows[0]) + ["forecast_water_demand_m3"]
    previous_demand = None
    for row in rows:
        actual = row["water_demand_m3"]
        # Shared warm-up at t=0; after that, a transparent persistence forecast.
        row["forecast_water_demand_m3"] = actual if previous_demand is None else previous_demand
        previous_demand = actual
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--check", action="store_true", help="fail if the committed fixture differs from generated data")
    args = parser.parse_args()
    output = Path(args.output)
    expected = render_csv()
    if args.check:
        if not output.exists() or output.read_text(encoding="utf-8") != expected:
            raise SystemExit(f"{output} differs from the deterministic generated fixture")
        print(f"OK: {output} matches the deterministic synthetic water-forecast fixture")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(expected, encoding="utf-8", newline="")
    print(f"Wrote synthetic paired dispatch data to {output}")


if __name__ == "__main__":
    main()

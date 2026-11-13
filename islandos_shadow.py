"""Offline JSON replay CLI for read-only shadow comparisons."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from islandos_core.shadow_mode import compare_shadow_run


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recommendation", required=True, help="JSON recommendation record")
    parser.add_argument("--observation", required=True, help="JSON observed telemetry record")
    parser.add_argument("--evaluated-at-utc", required=True, help="ISO-8601 timestamp with timezone")
    parser.add_argument("--max-age-seconds", type=float, default=300.0)
    parser.add_argument("--output", default="-", help="JSON report path or - for stdout")
    args = parser.parse_args(argv)

    try:
        recommendation = json.loads(Path(args.recommendation).read_text(encoding="utf-8"))
        observation = json.loads(Path(args.observation).read_text(encoding="utf-8"))
        report = compare_shadow_run(
            recommendation,
            observation,
            evaluated_at_utc=args.evaluated_at_utc,
            max_observation_age_seconds=args.max_age_seconds,
        )
        output = json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n"
        if args.output == "-":
            sys.stdout.write(output)
        else:
            destination = Path(args.output)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(output, encoding="utf-8")
        return 0 if report["status"] == "within_tolerance" else 1 if report["status"] == "deviation" else 2
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"islandOS shadow replay error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

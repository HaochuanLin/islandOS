"""Send an explicitly synthetic 24-hour telemetry window to a local islandOS gateway.

Demo only. The gateway must be started with --max-age-seconds 90000 because
older synthetic samples intentionally represent the preceding hourly window.
Never use this permissive freshness window for real sensor feeds.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import math
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def generate_demo_samples(hours=24, now=None):
    if isinstance(hours, bool) or not isinstance(hours, int) or not 2 <= hours <= 168:
        raise ValueError("hours must be an integer between 2 and 168")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    end = now.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    rows = []
    for index in range(hours):
        timestamp = end - timedelta(hours=hours - index - 1)
        hour = timestamp.hour
        daylight = max(0.0, math.sin(math.pi * (hour - 6) / 12))
        surplus = max(0.0, 7.0 + 38.0 * daylight + 5.0 * math.sin(index * 0.71))
        water = 3.5 + 0.9 * (hour in range(6, 10) or hour in range(17, 21)) + 0.4 * math.sin(index * 0.43)
        cooling = 5.5 + 3.0 * daylight + 0.6 * math.sin(index * 0.37)
        rows.append({
            "timestamp_utc": timestamp.isoformat().replace("+00:00", "Z"),
            "device_id": "synthetic-demo-generator",
            "quality_flag": "good",
            "renewable_surplus_kw": round(surplus, 3),
            "water_demand_m3": round(max(0.1, water), 3),
            "cooling_demand_kw_th": round(max(0.1, cooling), 3),
        })
    return rows


def send_samples(url, samples, timeout=3.0):
    accepted = 0
    for sample in samples:
        request = Request(
            url.rstrip("/") + "/telemetry",
            data=json.dumps(sample, allow_nan=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
                if response.status != 202 or result.get("status") != "accepted":
                    raise RuntimeError("gateway did not accept a demo sample")
                accepted += 1
        except (HTTPError, URLError, TimeoutError) as exc:
            raise RuntimeError(
                "could not post synthetic sample %d/%d: %s; confirm the local gateway is running "
                "with --max-age-seconds 90000" % (accepted + 1, len(samples), exc)
            ) from exc
    return accepted


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--timeout", type=float, default=3.0)
    args = parser.parse_args(argv)
    if not args.url.startswith("http://127.0.0.1:") and not args.url.startswith("http://localhost:"):
        parser.error("demo sender only permits a loopback HTTP URL")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    try:
        samples = generate_demo_samples(args.hours)
        accepted = send_samples(args.url, samples, timeout=args.timeout)
    except (ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    print("SYNTHETIC DEMO ONLY: accepted %d hourly samples; these are not site data." % accepted)
    print("Open %s/dashboard to review the model advice." % args.url.rstrip("/"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

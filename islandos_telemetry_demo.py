"""Send an explicitly synthetic 24-hour telemetry window to a local islandOS gateway.

Demo only. The gateway must be started with --max-age-seconds 90000 because
older synthetic samples intentionally represent the preceding hourly window.
Never use this permissive freshness window for real sensor feeds.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
import math
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlsplit


def validate_loopback_url(url):
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except (TypeError, ValueError):
        raise ValueError("demo sender requires a valid loopback HTTP URL")
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise ValueError("demo sender only permits a loopback HTTP URL")
    return url.rstrip("/")


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


def wait_for_gateway(url, timeout=20.0, request_timeout=1.0):
    """Wait for the local gateway to become ready after a packaged EXE starts."""
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            with urlopen(url.rstrip("/") + "/health", timeout=request_timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
                if response.status == 200 and payload.get("status") == "ok":
                    return True
                last_error = "gateway health endpoint did not report status=ok"
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = str(exc)
        time.sleep(0.25)
    raise RuntimeError("local gateway did not become ready within %.1f seconds: %s" % (timeout, last_error))


def send_samples(url, samples, timeout=3.0):
    accepted = 0
    for sample in samples:
        headers = {"Content-Type": "application/json"}
        token = os.environ.get("ISLANDOS_GATEWAY_TOKEN", "")
        if token:
            headers["Authorization"] = "Bearer " + token
        request = Request(
            url.rstrip("/") + "/telemetry",
            data=json.dumps(sample, allow_nan=False).encode("utf-8"),
            headers=headers,
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
    try:
        args.url = validate_loopback_url(args.url)
    except ValueError as exc:
        parser.error(str(exc))
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    try:
        wait_for_gateway(args.url, timeout=20.0, request_timeout=args.timeout)
        samples = generate_demo_samples(args.hours)
        accepted = send_samples(args.url, samples, timeout=args.timeout)
    except (ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    print("SYNTHETIC DEMO ONLY: accepted %d hourly samples; these are not site data." % accepted)
    print("Open %s/dashboard to review the model advice." % args.url.rstrip("/"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

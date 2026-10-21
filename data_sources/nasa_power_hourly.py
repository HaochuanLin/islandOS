"""Download hourly solar/weather data from NASA POWER and preserve provenance.

This module imports environmental covariates only. It deliberately does not
invent wind/PV generation, critical load, water demand, or cooling demand.
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API_URL = "https://power.larc.nasa.gov/api/temporal/hourly/point"
PARAMETERS = ("ALLSKY_SFC_SW_DWN", "T2M", "WS10M")


def build_request_url(latitude: float, longitude: float, start: str, end: str) -> str:
    if not -90 <= latitude <= 90:
        raise ValueError("latitude must be between -90 and 90")
    if not -180 <= longitude <= 180:
        raise ValueError("longitude must be between -180 and 180")
    for label, value in (("start", start), ("end", end)):
        if len(value) != 8 or not value.isdigit():
            raise ValueError(f"{label} must use YYYYMMDD")
        datetime.strptime(value, "%Y%m%d")
    if start > end:
        raise ValueError("start must be on or before end")
    query = urlencode({
        "parameters": ",".join(PARAMETERS),
        "community": "RE",
        "longitude": longitude,
        "latitude": latitude,
        "start": start,
        "end": end,
        "format": "JSON",
        "time-standard": "UTC",
    })
    return f"{API_URL}?{query}"


def parse_response(payload: dict) -> tuple[list[dict], dict]:
    try:
        params = payload["properties"]["parameter"]
        metadata = {
            "header": payload.get("header", {}),
            "parameters": payload.get("parameters", {}),
            "geometry": payload.get("geometry", {}),
            "messages": payload.get("messages", []),
        }
    except (KeyError, TypeError) as exc:
        raise ValueError("NASA POWER response is missing properties.parameter") from exc
    missing = [name for name in PARAMETERS if name not in params]
    if missing:
        raise ValueError(f"NASA POWER response missing parameters: {', '.join(missing)}")
    time_keys = set(params[PARAMETERS[0]])
    if not time_keys:
        raise ValueError("NASA POWER response contains no hourly records")
    if any(set(params[name]) != time_keys for name in PARAMETERS):
        raise ValueError("NASA POWER parameter time keys do not align")

    rows = []
    for key in sorted(time_keys):
        try:
            stamp = datetime.strptime(key, "%Y%m%d%H").replace(tzinfo=timezone.utc)
        except ValueError as exc:
            raise ValueError(f"Unexpected NASA POWER timestamp: {key}") from exc
        row = {"timestamp_utc": stamp.isoformat().replace("+00:00", "Z")}
        for name in PARAMETERS:
            value = params[name][key]
            if value is None:
                row[name] = ""
            elif isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"Non-numeric value for {name} at {key}")
            else:
                row[name] = value
        rows.append(row)
    return rows, metadata


def download_hourly(latitude: float, longitude: float, start: str, end: str,
                    output_csv: str | Path, timeout: int = 30) -> dict:
    url = build_request_url(latitude, longitude, start, end)
    request = Request(url, headers={"User-Agent": "IslandOS-data-import/0.1"})
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    rows, response_metadata = parse_response(payload)

    csv_path = Path(output_csv)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["timestamp_utc", *PARAMETERS])
        writer.writeheader()
        writer.writerows(rows)

    sidecar = {
        "source": "NASA POWER Hourly Point API",
        "source_url": url,
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
        "requested_location": {"latitude": latitude, "longitude": longitude},
        "requested_dates": {"start": start, "end": end},
        "time_standard": "UTC",
        "parameters": list(PARAMETERS),
        "response_metadata": response_metadata,
        "record_count": len(rows),
        "data_class": "public gridded solar/meteorological data; not site-metered generation or demand",
        "limitations": [
            "Solar irradiance and weather are environmental covariates, not actual wind/PV output.",
            "No critical load, freshwater demand, or cooling demand is provided by this importer.",
            "Confirm parameter units from NASA POWER response metadata before any conversion.",
            "Gridded/reanalysis data are not equivalent to on-site sensor measurements.",
        ],
    }
    metadata_path = csv_path.with_suffix(csv_path.suffix + ".metadata.json")
    metadata_path.write_text(json.dumps(sidecar, indent=2), encoding="utf-8")
    return {"csv_path": str(csv_path), "metadata_path": str(metadata_path),
            "record_count": len(rows), "source_url": url}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latitude", type=float, required=True)
    parser.add_argument("--longitude", type=float, required=True)
    parser.add_argument("--start", required=True, help="YYYYMMDD")
    parser.add_argument("--end", required=True, help="YYYYMMDD")
    parser.add_argument("--output", required=True, help="Destination CSV path")
    args = parser.parse_args()
    result = download_hourly(args.latitude, args.longitude, args.start, args.end, args.output)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

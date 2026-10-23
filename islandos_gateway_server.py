"""Read-only HTTP telemetry ingress for islandOS.

The server validates sensor/gateway JSON messages and appends an audit trail.
It never writes PLC setpoints or actuator commands. It binds to loopback by
default; non-loopback binding requires explicit opt-in and a bearer token.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
from urllib.parse import urlparse

from islandos_io import validate_telemetry


_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


def _json_bytes(payload):
    return (json.dumps(payload, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def make_handler(audit_path, source, max_age_seconds, token):
    audit_path = Path(audit_path)
    lock = threading.Lock()
    latest = {"record": None}

    class Handler(BaseHTTPRequestHandler):
        server_version = "IslandOSReadOnlyGateway/1.0"

        def _send(self, status, payload):
            body = _json_bytes(payload)
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _authorized(self):
            if token is None:
                return True
            header = self.headers.get("Authorization", "")
            prefix = "Bearer "
            if not header.startswith(prefix):
                return False
            return hmac.compare_digest(header[len(prefix):], token)

        def do_GET(self):
            path = urlparse(self.path).path
            if path not in ("/health", "/latest"):
                self._send(404, {"error": "not found"})
                return
            if not self._authorized():
                self._send(401, {"error": "unauthorized"})
                return
            if path == "/health":
                self._send(200, {
                    "status": "ok",
                    "mode": "read_only_telemetry_ingest",
                    "physical_write_performed": False,
                })
                return
            with lock:
                record = latest["record"]
            if record is None:
                self._send(404, {"error": "no valid telemetry received yet"})
            else:
                self._send(200, record)

        def do_POST(self):
            if urlparse(self.path).path != "/telemetry":
                self._send(404, {"error": "not found"})
                return
            if not self._authorized():
                self._send(401, {"error": "unauthorized"})
                return
            content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type != "application/json":
                self._send(415, {"error": "Content-Type must be application/json"})
                return
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._send(400, {"error": "invalid Content-Length"})
                return
            if content_length <= 0 or content_length > 65536:
                self._send(413, {"error": "request body must be between 1 and 65536 bytes"})
                return
            try:
                payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._send(400, {"error": "body must be valid UTF-8 JSON"})
                return
            if not isinstance(payload, dict):
                self._send(400, {"error": "body must be a JSON object"})
                return
            try:
                frame = validate_telemetry(
                    payload,
                    source=source,
                    received_at=datetime.now(timezone.utc),
                    max_age_seconds=max_age_seconds,
                )
            except (TypeError, ValueError) as exc:
                self._send(400, {"error": str(exc)})
                return
            record = frame.as_dict()
            record["received_at_utc"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            record["physical_write_performed"] = False
            if not frame.valid:
                self._send(422, {
                    "status": "rejected",
                    "valid": False,
                    "errors": list(frame.errors),
                    "warnings": list(frame.warnings),
                    "physical_write_performed": False,
                })
                return
            try:
                with lock:
                    audit_path.parent.mkdir(parents=True, exist_ok=True)
                    with audit_path.open("a", encoding="utf-8") as stream:
                        stream.write(_json_bytes(record).decode("utf-8"))
                    latest["record"] = record
            except OSError as exc:
                self._send(500, {"error": "could not persist telemetry audit: " + str(exc)})
                return
            self._send(202, {
                "status": "accepted",
                "valid": True,
                "timestamp_utc": record["timestamp_utc"],
                "audit_file": str(audit_path),
                "physical_write_performed": False,
            })

        def log_message(self, format_string, *args):
            # Keep the console useful but avoid dumping raw telemetry payloads.
            super().log_message(format_string, *args)

    return Handler


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--source", default="http-gateway")
    parser.add_argument("--audit-file", default="build/telemetry/http-ingest-audit.jsonl")
    parser.add_argument("--max-age-seconds", type=float, default=300.0)
    parser.add_argument("--allow-remote", action="store_true",
                        help="Allow a non-loopback bind only with ISLANDOS_GATEWAY_TOKEN set")
    args = parser.parse_args(argv)

    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    if args.max_age_seconds < 0:
        parser.error("--max-age-seconds must be non-negative")
    token = os.environ.get("ISLANDOS_GATEWAY_TOKEN") or None
    if args.host not in _LOOPBACK_HOSTS:
        if not args.allow_remote:
            parser.error("non-loopback binding requires --allow-remote")
        if token is None:
            parser.error("non-loopback binding requires ISLANDOS_GATEWAY_TOKEN")
        parser.error("remote HTTP is not TLS-protected; use a trusted TLS reverse proxy and network controls")
    if args.allow_remote and args.host in _LOOPBACK_HOSTS:
        parser.error("--allow-remote is only meaningful for non-loopback hosts")

    handler = make_handler(args.audit_file, args.source, args.max_age_seconds, token)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print("IslandOS read-only telemetry gateway listening on http://%s:%d" % (args.host, args.port), flush=True)
    print("No PLC commands or actuator writes are supported.", flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""A read-only, stateless HTTP surface over the application contracts.

Two endpoints, no authentication, no persistence, no writes:

``GET /contracts``   the machine-readable schema (`contract_schemas.contract_schema()`)
``POST /run``        replay one `run_request` and return its summary (+ annual)

The server binds to 127.0.0.1 by default and is not part of the Streamlit deployment. It
exists so a non-Streamlit client can obtain the same validated shapes the pages render
without re-implementing the call sequence or the field rules.
"""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from typing import Any

from .contract_schemas import contract_schema
from .run_orchestration import replay_run_request


class ApplicationHandler(BaseHTTPRequestHandler):
    server_version = "IslandOSApplicationViews/1"

    def _send(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        if self.path == "/contracts":
            self._send(200, contract_schema())
        elif self.path == "/health":
            self._send(200, {"status": "ok"})
        else:
            self._send(404, {"error": "unknown path", "paths": ["/contracts", "/run", "/health"]})

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        if self.path != "/run":
            self._send(404, {"error": "unknown path", "paths": ["/contracts", "/run", "/health"]})
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            self._send(400, {"error": "empty body"})
            return
        try:
            request = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._send(400, {"error": f"body is not JSON: {exc}"})
            return
        if not isinstance(request, dict):
            self._send(400, {"error": "body must be a JSON object"})
            return
        try:
            result = replay_run_request(request)
        except (ValueError, KeyError, TypeError) as exc:
            # A malformed or unsupported request is the caller's problem, not a server bug.
            self._send(400, {"error": str(exc)})
            return
        self._send(200, result)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        # Keep the demo quiet; a real deployment would log here.
        return


def create_server(host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), ApplicationHandler)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="IslandOS application-views transport (read-only)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    server = create_server(args.host, args.port)
    print(f"serving on http://{args.host}:{server.server_port} (GET /contracts, POST /run)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""A read-only, stateless HTTP surface over the application contracts.

Three surfaces, no authentication, no persistence, no writes:

``GET /contracts``   the machine-readable schema (`contract_schemas.contract_schema()`)
``POST /run``        replay one `run_request` and return its summary (+ annual)
``GET /``            the built contract viewer (`frontend/application-views.html`)

The server binds to 127.0.0.1 by default and is not part of the Streamlit deployment. It
exists so a non-Streamlit client can obtain the same validated shapes the pages render
without re-implementing the call sequence or the field rules, and so a locally built
viewer can be opened without a second web server: serving the HTML from the same origin
means its `/contracts` fetch is same-origin and needs no allowance.
"""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from typing import Any

from .contract_schemas import contract_schema
from .run_orchestration import replay_run_request

MAX_BODY_BYTES = 1_000_000
PATHS = ["/", "/contracts", "/run", "/health"]

#: Where `npm run build` leaves the viewer. Read at request time so a test can point it at
#: a temporary directory instead of requiring a built `dist/` in CI.
VIEWER_DIR = Path(__file__).resolve().parents[1] / "frontend" / "dist"
_VIEWER_HINT = "run `npm run build` in frontend/ first"
_CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                  ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png",
                  ".woff2": "font/woff2"}


class ApplicationHandler(BaseHTTPRequestHandler):
    server_version = "IslandOSApplicationViews/1"

    def _send(
        self, status: int, payload: dict[str, Any], *, cors: bool = False,
        allow: str | None = None,
    ) -> None:
        body = json.dumps(payload, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if allow:
            self.send_header("Allow", allow)
        if cors:
            # Only the schema is cross-origin readable: it is a committed public file and a
            # static viewer served from another port has to be able to fetch it. `/run`
            # stays same-origin so no opened page can drive a replay on the user's machine.
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Accept")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path) -> None:
        body = path.read_bytes()
        content_type = _CONTENT_TYPES.get(path.suffix, "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_viewer(self) -> None:
        index = VIEWER_DIR / "application-views.html"
        if not index.is_file():
            self._send(404, {"error": "the viewer is not built", "hint": _VIEWER_HINT})
        else:
            self._send_file(index)

    def _send_asset(self, relative: str) -> None:
        root = (VIEWER_DIR / "assets").resolve()
        candidate = (root / relative).resolve()
        # A path cannot leave the build output, and the file is served as bytes only.
        if root not in candidate.parents or not candidate.is_file():
            self._send(404, {"error": "unknown asset", "hint": _VIEWER_HINT})
            return
        self._send_file(candidate)

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        if self.path in ("/", "/application-views.html"):
            self._send_viewer()
        elif self.path.startswith("/assets/"):
            self._send_asset(self.path[len("/assets/"):])
        elif self.path == "/contracts":
            self._send(200, contract_schema(), cors=True)
        elif self.path == "/health":
            self._send(200, {"status": "ok"})
        else:
            self._send(404, {"error": "unknown path", "paths": PATHS})

    def do_OPTIONS(self) -> None:  # noqa: N802 - http.server API
        # Preflight for the one cross-origin read. `/run` deliberately has no preflight:
        # it is not a cross-origin surface.
        if self.path == "/contracts":
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Accept")
            self.send_header("Allow", "GET, OPTIONS")
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif self.path == "/run":
            self._send(405, {"error": "method not allowed; POST /run only", "paths": PATHS},
                       allow="POST")
        else:
            self._send(404, {"error": "unknown path", "paths": PATHS})

    def _method_not_allowed(self) -> None:
        self._send(405, {"error": f"{self.command} is not supported", "paths": PATHS},
                   allow="GET, POST, OPTIONS")

    do_PUT = _method_not_allowed  # noqa: N815 - http.server API
    do_DELETE = _method_not_allowed  # noqa: N815 - http.server API
    do_PATCH = _method_not_allowed  # noqa: N815 - http.server API

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        if self.path != "/run":
            self._send(404, {"error": "unknown path", "paths": PATHS})
            return
        content_type = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if content_type != "application/json":
            self._send(415, {"error": "body must declare Content-Type: application/json"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            self._send(400, {"error": "empty body"})
            return
        if length > MAX_BODY_BYTES:
            # Refuse before reading: a caller cannot make this process buffer an arbitrary body.
            self.close_connection = True
            self._send(413, {"error": f"body exceeds {MAX_BODY_BYTES} bytes"})
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
    print(
        f"serving on http://{args.host}:{server.server_port} "
        "(GET / for the built viewer, /contracts, POST /run)"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

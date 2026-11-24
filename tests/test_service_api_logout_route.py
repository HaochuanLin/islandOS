"""HTTP-level checks for the loopback service logout route.

The Streamlit page and the React console both sign out with
``POST /api/v1/auth/logout``. The route used to live on ``do_GET`` only, so the
browser click returned ``404 not found`` and the page fell back to
"server-side revocation could not be confirmed" while the token stayed valid.
These tests pin the verb to the store-level revocation behaviour.
"""

from __future__ import annotations

import json
import threading
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from islandos_service_api import IslandOSStore, make_handler


EMAIL = "logout-route@example.test"
PASSWORD = "a-correct-long-password"


def _call(url: str, method: str, token: str | None = None, payload: dict | None = None):
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


@pytest.fixture()
def service(tmp_path):
    store = IslandOSStore(str(tmp_path / "logout-route.sqlite3"))
    store.register(EMAIL, PASSWORD, "Logout route tenant")
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(store))
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _login(base: str) -> str:
    status, body = _call(f"{base}/api/v1/auth/login", "POST", payload={"email": EMAIL, "password": PASSWORD})
    assert status == 200
    return body["access_token"]


def test_post_logout_revokes_the_current_session(service):
    token = _login(service)
    assert _call(f"{service}/api/v1/members", "GET", token=token)[0] == 200

    status, body = _call(f"{service}/api/v1/auth/logout", "POST", token=token, payload={})
    assert status == 200
    assert body == {"revoked": True}

    status, body = _call(f"{service}/api/v1/members", "GET", token=token)
    assert status == 401
    assert "invalid or expired" in body["error"]


def test_get_logout_is_not_a_state_change(service):
    token = _login(service)

    status, _ = _call(f"{service}/api/v1/auth/logout", "GET", token=token)
    assert status == 404

    assert _call(f"{service}/api/v1/members", "GET", token=token)[0] == 200

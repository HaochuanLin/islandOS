"""HTTP checks for the pending-invitation read used by the React console.

The console could create an invitation but never look at it again: there was no
read route, so the UI had no way to show who was still pending. These tests pin
``GET /api/v1/members/invitations`` to the store behaviour: owner-only, tenant
scoped, and token-free.
"""

from __future__ import annotations

import json
import threading
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from islandos_service_api import IslandOSStore, make_handler


OWNER = "invitation-route@example.test"
PASSWORD = "a-correct-long-password"
INVITED = "pending-route@example.test"
INVITED_PASSWORD = "another-correct-long-password"


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
    store = IslandOSStore(str(tmp_path / "invitation-route.sqlite3"))
    store.register(OWNER, PASSWORD, "Invitation route tenant")
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(store))
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _login(base: str, email: str, password: str) -> str:
    status, body = _call(f"{base}/api/v1/auth/login", "POST", payload={"email": email, "password": password})
    assert status == 200
    return body["access_token"]


def test_owner_sees_the_pending_invitation_without_the_token(service):
    owner = _login(service, OWNER, PASSWORD)
    status, created = _call(
        f"{service}/api/v1/members/invitations", "POST", token=owner,
        payload={"email": INVITED, "role": "viewer", "expires_in_seconds": 3600},
    )
    assert status == 201
    assert created["role"] == "viewer"

    status, body = _call(f"{service}/api/v1/members/invitations", "GET", token=owner)
    assert status == 200
    assert len(body["invitations"]) == 1
    entry = body["invitations"][0]
    assert entry["email"] == INVITED
    assert entry["role"] == "viewer"
    assert entry["invitation_id"] == created["invitation_id"]
    assert entry["expires_at"] == created["expires_at"]
    assert "invitation_token" not in entry
    assert "token_hash" not in entry

    status, accepted = _call(
        f"{service}/api/v1/members/invitations/accept", "POST", token=None,
        payload={"invitation_token": created["invitation_token"], "password": INVITED_PASSWORD},
    )
    assert status == 201
    assert _call(f"{service}/api/v1/members/invitations", "GET", token=owner)[1]["invitations"] == []

    member = _login(service, INVITED, INVITED_PASSWORD)
    status, body = _call(f"{service}/api/v1/members/invitations", "GET", token=member)
    assert status == 403
    assert "owner role required" in body["error"]

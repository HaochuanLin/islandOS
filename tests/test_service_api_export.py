"""HTTP checks for the tenant export route.

The export is the only way to take rows out of the reference database; the
backup script only copies the file. These tests pin three things: only an
owner may call it, the payload never carries credential material, and one
tenant's export never contains another tenant's rows.
"""

from __future__ import annotations

import json
import threading
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from islandos_service_api import IslandOSStore, make_handler

OWNER = "export-owner@example.test"
ANALYST = "export-analyst@example.test"
VIEWER = "export-viewer@example.test"
OTHER_OWNER = "export-other@example.test"
PASSWORD = "a-correct-long-password"


def _call(url: str, method: str = "GET", token: str | None = None, payload: dict | None = None):
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


def _login(base: str, email: str) -> str:
    status, body = _call(f"{base}/api/v1/auth/login", "POST", payload={"email": email, "password": PASSWORD})
    assert status == 200
    return body["access_token"]


def _invite_and_accept(base: str, owner_token: str, email: str, role: str) -> None:
    status, created = _call(
        f"{base}/api/v1/members/invitations", "POST", token=owner_token,
        payload={"email": email, "role": role, "expires_in_seconds": 3600},
    )
    assert status == 201
    status, _ = _call(
        f"{base}/api/v1/members/invitations/accept", "POST", token=None,
        payload={"invitation_token": created["invitation_token"], "password": PASSWORD},
    )
    assert status == 201


@pytest.fixture()
def service(tmp_path):
    store = IslandOSStore(str(tmp_path / "export.sqlite3"))
    store.register(OWNER, PASSWORD, "Export tenant")
    store.register(OTHER_OWNER, PASSWORD, "Other export tenant")
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(store))
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_owner_export_returns_rows_and_no_credentials(service):
    owner_token = _login(service, OWNER)
    status, _ = _call(
        f"{service}/api/v1/sites", "POST", token=owner_token,
        payload={"name": "Export site", "timezone": "UTC"},
    )
    assert status == 201

    status, exported = _call(f"{service}/api/v1/export", token=owner_token)

    assert status == 200
    assert isinstance(exported["schema_version"], int)
    assert exported["tenant"]["name"] == "Export tenant"
    assert [site["name"] for site in exported["sites"]] == ["Export site"]
    assert [member["email"] for member in exported["members"]] == [OWNER]
    assert exported["audit_events"], "the export must carry the tenant audit trail"
    assert exported["physical_write_performed"] is False

    raw = json.dumps(exported)
    for forbidden in ("password_hash", "password_salt", "access_token", "token_hash"):
        assert forbidden not in raw


def test_only_the_owner_may_export(service):
    owner_token = _login(service, OWNER)
    _invite_and_accept(service, owner_token, ANALYST, "analyst")
    _invite_and_accept(service, owner_token, VIEWER, "viewer")
    analyst_token = _login(service, ANALYST)
    viewer_token = _login(service, VIEWER)

    status, body = _call(f"{service}/api/v1/export", token=analyst_token)
    assert status == 403
    assert "owner role required" in body["error"]

    status, body = _call(f"{service}/api/v1/export", token=viewer_token)
    assert status == 403
    assert "owner role required" in body["error"]

    status, body = _call(f"{service}/api/v1/export")
    assert status == 401


def test_export_stays_inside_its_tenant(service):
    owner_token = _login(service, OWNER)
    other_token = _login(service, OTHER_OWNER)
    _call(f"{service}/api/v1/sites", "POST", token=owner_token,
          payload={"name": "Tenant one site", "timezone": "UTC"})
    _call(f"{service}/api/v1/sites", "POST", token=other_token,
          payload={"name": "Tenant two site", "timezone": "UTC"})

    status, owner_export = _call(f"{service}/api/v1/export", token=owner_token)
    assert status == 200
    status, other_export = _call(f"{service}/api/v1/export", token=other_token)
    assert status == 200

    assert [site["name"] for site in owner_export["sites"]] == ["Tenant one site"]
    assert [site["name"] for site in other_export["sites"]] == ["Tenant two site"]
    assert owner_export["tenant"]["id"] != other_export["tenant"]["id"]
    assert "Tenant two site" not in json.dumps(owner_export)
    assert "Tenant one site" not in json.dumps(other_export)

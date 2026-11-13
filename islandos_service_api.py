"""Versioned local IslandOS service API with tenant-scoped SQLite persistence.

This is a single-host reference service, not a production SaaS deployment. It
stores normalized telemetry and metadata only; raw uploaded files are not stored.
The listener is loopback-only and physical device writes do not exist.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3
import threading
from urllib.parse import urlparse

from islandos_io import validate_telemetry

MAX_BODY = 65536
TOKEN_TTL_SECONDS = 12 * 60 * 60
PASSWORD_ITERATIONS = 240000
ROLES = {"owner", "analyst", "viewer"}
LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def _utcnow():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json(payload):
    return (json.dumps(payload, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


class IslandOSStore:
    """SQLite repository; every customer-owned query is scoped by tenant_id."""

    def __init__(self, path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    @contextmanager
    def session(self):
        db = self.connect()
        try:
            with db:
                yield db
        finally:
            db.close()

    def _initialize(self):
        with self._lock, self.session() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS tenants (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                    email TEXT NOT NULL, password_salt TEXT NOT NULL, password_hash TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('owner','analyst','viewer')),
                    created_at TEXT NOT NULL, UNIQUE(tenant_id,email)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS users_email_unique ON users(email);
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    expires_at TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sites (
                    id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                    name TEXT NOT NULL, timezone TEXT NOT NULL, created_at TEXT NOT NULL,
                    UNIQUE(tenant_id,name)
                );
                CREATE TABLE IF NOT EXISTS telemetry (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                    site_id TEXT NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
                    timestamp_utc TEXT NOT NULL, received_at_utc TEXT NOT NULL,
                    values_json TEXT NOT NULL, source TEXT NOT NULL,
                    UNIQUE(site_id,timestamp_utc)
                );
                CREATE INDEX IF NOT EXISTS telemetry_tenant_site_time
                    ON telemetry(tenant_id,site_id,timestamp_utc);
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                    user_id TEXT, action TEXT NOT NULL, resource_type TEXT NOT NULL,
                    resource_id TEXT, created_at TEXT NOT NULL, details_json TEXT NOT NULL
                );
            """)

    @staticmethod
    def _password(password, salt):
        return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS).hex()

    def register(self, email, password, tenant_name):
        email = email.strip().lower()
        if len(email) > 254 or "@" not in email or len(password) < 12 or len(password) > 256:
            raise ValueError("valid email and password of 12–256 characters are required")
        if not tenant_name.strip() or len(tenant_name) > 120:
            raise ValueError("tenant_name must contain 1–120 characters")
        tenant_id, user_id = secrets.token_hex(16), secrets.token_hex(16)
        salt = secrets.token_bytes(16)
        with self._lock, self.session() as db:
            db.execute("INSERT INTO tenants VALUES (?,?,?)", (tenant_id, tenant_name.strip(), _utcnow()))
            try:
                db.execute(
                    "INSERT INTO users VALUES (?,?,?,?,?,?,?)",
                    (user_id, tenant_id, email, salt.hex(), self._password(password, salt), "owner", _utcnow()),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("email is already registered") from exc
            self._audit(db, tenant_id, user_id, "tenant.register", "tenant", tenant_id, {})
        return {"tenant_id": tenant_id, "user_id": user_id, "role": "owner"}

    def login(self, email, password):
        with self.session() as db:
            row = db.execute("SELECT * FROM users WHERE email=?", (email.strip().lower(),)).fetchone()
            if row is None:
                raise PermissionError("invalid credentials")
            expected = self._password(password, bytes.fromhex(row["password_salt"]))
            if not hmac.compare_digest(expected, row["password_hash"]):
                raise PermissionError("invalid credentials")
            token = secrets.token_urlsafe(32)
            token_hash = hashlib.sha256(token.encode()).hexdigest()
            expires = datetime.fromtimestamp(
                datetime.now(timezone.utc).timestamp() + TOKEN_TTL_SECONDS, timezone.utc
            ).isoformat().replace("+00:00", "Z")
            db.execute("INSERT INTO sessions VALUES (?,?,?,?)", (token_hash, row["id"], expires, _utcnow()))
            self._audit(db, row["tenant_id"], row["id"], "auth.login", "user", row["id"], {})
            return {"access_token": token, "token_type": "Bearer", "expires_at": expires,
                    "tenant_id": row["tenant_id"], "role": row["role"]}

    def authenticate(self, token):
        if not token:
            raise PermissionError("bearer token required")
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self.connect() as db:
            row = db.execute("""
                SELECT u.id AS user_id,u.tenant_id,u.role,u.email,s.expires_at
                FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=?
            """, (digest,)).fetchone()
            if row is None or row["expires_at"] <= _utcnow():
                raise PermissionError("session is invalid or expired")
            return dict(row)

    @staticmethod
    def _audit(db, tenant_id, user_id, action, resource_type, resource_id, details):
        db.execute(
            "INSERT INTO audit_events(tenant_id,user_id,action,resource_type,resource_id,created_at,details_json) VALUES (?,?,?,?,?,?,?)",
            (tenant_id, user_id, action, resource_type, resource_id, _utcnow(),
             json.dumps(details, sort_keys=True, allow_nan=False)),
        )

    def list_sites(self, principal):
        with self.connect() as db:
            rows = db.execute(
                "SELECT id,name,timezone,created_at FROM sites WHERE tenant_id=? ORDER BY name",
                (principal["tenant_id"],),
            ).fetchall()
            return [dict(row) for row in rows]

    def create_site(self, principal, name, timezone_name):
        if principal["role"] not in {"owner", "analyst"}:
            raise PermissionError("analyst or owner role required")
        if not isinstance(name, str) or not name.strip() or len(name) > 120:
            raise ValueError("site name must contain 1–120 characters")
        if not isinstance(timezone_name, str) or not timezone_name.strip() or len(timezone_name) > 80:
            raise ValueError("timezone must be explicit")
        site_id = secrets.token_hex(16)
        with self._lock, self.connect() as db:
            db.execute("INSERT INTO sites VALUES (?,?,?,?,?)",
                       (site_id, principal["tenant_id"], name.strip(), timezone_name.strip(), _utcnow()))
            self._audit(db, principal["tenant_id"], principal["user_id"], "site.create", "site", site_id, {})
        return {"id": site_id, "name": name.strip(), "timezone": timezone_name.strip()}

    def ingest_telemetry(self, principal, site_id, payload, source):
        with self._lock, self.connect() as db:
            site = db.execute("SELECT id FROM sites WHERE id=? AND tenant_id=?",
                              (site_id, principal["tenant_id"])).fetchone()
            if site is None:
                raise LookupError("site not found")
            frame = validate_telemetry(
                payload, source=source, received_at=datetime.now(timezone.utc), max_age_seconds=300.0
            )
            if not frame.valid:
                raise ValueError("; ".join(frame.errors))
            values_json = json.dumps(frame.values, sort_keys=True, allow_nan=False)
            try:
                db.execute(
                    "INSERT INTO telemetry(tenant_id,site_id,timestamp_utc,received_at_utc,values_json,source) VALUES (?,?,?,?,?,?)",
                    (principal["tenant_id"], site_id, frame.timestamp_utc.isoformat().replace("+00:00", "Z"),
                     _utcnow(), values_json, source),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("duplicate telemetry timestamp for this site") from exc
            self._audit(db, principal["tenant_id"], principal["user_id"], "telemetry.ingest",
                        "site", site_id, {"source": source, "timestamp_utc": frame.timestamp_utc.isoformat()})
        return {"accepted": True, "site_id": site_id, "timestamp_utc": frame.timestamp_utc.isoformat(),
                "physical_write_performed": False}

    def latest_telemetry(self, principal, site_id):
        with self.connect() as db:
            row = db.execute(
                "SELECT timestamp_utc,received_at_utc,values_json,source FROM telemetry WHERE tenant_id=? AND site_id=? ORDER BY timestamp_utc DESC LIMIT 1",
                (principal["tenant_id"], site_id),
            ).fetchone()
            if row is None:
                # Avoid revealing whether a foreign tenant owns this site.
                exists = db.execute("SELECT 1 FROM sites WHERE id=? AND tenant_id=?",
                                    (site_id, principal["tenant_id"])).fetchone()
                if exists is None:
                    raise LookupError("site not found")
                return None
            return {"timestamp_utc": row["timestamp_utc"], "received_at_utc": row["received_at_utc"],
                    "values": json.loads(row["values_json"]), "source": row["source"],
                    "physical_write_performed": False}

    def delete_site(self, principal, site_id):
        if principal["role"] != "owner":
            raise PermissionError("owner role required")
        with self._lock, self.connect() as db:
            cursor = db.execute("DELETE FROM sites WHERE id=? AND tenant_id=?",
                                (site_id, principal["tenant_id"]))
            if cursor.rowcount != 1:
                raise LookupError("site not found")
            self._audit(db, principal["tenant_id"], principal["user_id"], "site.delete",
                        "site", site_id, {"cascade_deleted_telemetry": True})
        return {"deleted": True, "site_id": site_id}


def make_handler(store, allow_registration=False):
    class Handler(BaseHTTPRequestHandler):
        server_version = "IslandOSServiceAPI/1.0"

        def send_json(self, status, payload):
            body = _json(payload)
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.end_headers()
            self.wfile.write(body)

        def read_body(self):
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                raise ValueError("invalid Content-Length")
            if length <= 0 or length > MAX_BODY:
                raise ValueError("request body must be 1–65536 bytes")
            if self.headers.get("Content-Type", "").split(";", 1)[0].lower() != "application/json":
                raise ValueError("Content-Type must be application/json")
            value = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError("JSON body must be an object")
            return value

        def principal(self):
            header = self.headers.get("Authorization", "")
            if not header.startswith("Bearer "):
                raise PermissionError("bearer token required")
            return store.authenticate(header[7:])

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/api/v1/health":
                return self.send_json(200, {"status": "ok", "api_version": "v1",
                                            "mode": "single_host_reference", "device_write_enabled": False})
            try:
                who = self.principal()
                if path == "/api/v1/sites":
                    return self.send_json(200, {"sites": store.list_sites(who)})
                prefix, suffix = "/api/v1/sites/", "/telemetry/latest"
                if path.startswith(prefix) and path.endswith(suffix):
                    site_id = path[len(prefix):-len(suffix)].strip("/")
                    result = store.latest_telemetry(who, site_id)
                    return self.send_json(200 if result else 404, result or {"error": "no telemetry"})
                return self.send_json(404, {"error": "not found"})
            except PermissionError as exc:
                return self.send_json(401, {"error": str(exc)})
            except LookupError as exc:
                return self.send_json(404, {"error": str(exc)})

        def do_POST(self):
            path = urlparse(self.path).path
            try:
                body = self.read_body()
                if path == "/api/v1/auth/register":
                    if not allow_registration:
                        return self.send_json(403, {"error": "registration disabled; enable only for controlled local bootstrap"})
                    result = store.register(body.get("email", ""), body.get("password", ""),
                                            body.get("tenant_name", ""))
                    return self.send_json(201, result)
                if path == "/api/v1/auth/login":
                    return self.send_json(200, store.login(body.get("email", ""), body.get("password", "")))
                who = self.principal()
                if path == "/api/v1/sites":
                    result = store.create_site(who, body.get("name"), body.get("timezone"))
                    return self.send_json(201, result)
                prefix = "/api/v1/sites/"
                suffix = "/telemetry"
                if path.startswith(prefix) and path.endswith(suffix):
                    site_id = path[len(prefix):-len(suffix)].strip("/")
                    source = body.pop("source", "authenticated-api")
                    return self.send_json(202, store.ingest_telemetry(who, site_id, body, source))
                return self.send_json(404, {"error": "not found"})
            except PermissionError as exc:
                return self.send_json(403 if "role required" in str(exc) else 401, {"error": str(exc)})
            except LookupError as exc:
                return self.send_json(404, {"error": str(exc)})
            except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                return self.send_json(400, {"error": str(exc)})

        def do_DELETE(self):
            path = urlparse(self.path).path
            prefix = "/api/v1/sites/"
            if not path.startswith(prefix):
                return self.send_json(404, {"error": "not found"})
            try:
                who = self.principal()
                site_id = path[len(prefix):].strip("/")
                return self.send_json(200, store.delete_site(who, site_id))
            except PermissionError as exc:
                return self.send_json(403 if "role required" in str(exc) else 401, {"error": str(exc)})
            except LookupError as exc:
                return self.send_json(404, {"error": str(exc)})

        def log_message(self, fmt, *args):
            # Never log request bodies or bearer tokens.
            super().log_message(fmt, *args)

    return Handler


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--database", default="build/islandos-service.sqlite3")
    parser.add_argument("--allow-registration", action="store_true",
                        help="enable controlled bootstrap registration; disable after first tenant")
    args = parser.parse_args(argv)
    if args.host not in LOOPBACK:
        parser.error("reference service binds to loopback only; deploy behind a reviewed TLS/auth gateway")
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    store = IslandOSStore(args.database)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(store, args.allow_registration))
    print("IslandOS API v1 listening on http://%s:%d" % (args.host, args.port), flush=True)
    print("Single-host reference only; raw files are not stored; device writes disabled.", flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

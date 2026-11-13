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
from urllib.parse import parse_qs, urlparse

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
                CREATE TABLE IF NOT EXISTS invitations (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                    email TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('analyst','viewer')),
                    token_hash TEXT NOT NULL UNIQUE,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    created_by TEXT NOT NULL REFERENCES users(id),
                    UNIQUE(tenant_id,email)
                );
                CREATE TABLE IF NOT EXISTS notifications (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                    site_id TEXT REFERENCES sites(id) ON DELETE CASCADE,
                    user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
                    category TEXT NOT NULL,
                    severity TEXT NOT NULL CHECK(severity IN ('info','warning','critical')),
                    title TEXT NOT NULL,
                    message TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    read_at TEXT
                );
                CREATE INDEX IF NOT EXISTS notifications_inbox
                    ON notifications(tenant_id,user_id,created_at DESC);
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

    def revoke_session(self, token, principal):
        """Revoke only the authenticated caller's current bearer session."""
        if not isinstance(token, str) or not token:
            raise PermissionError("bearer token required")
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self._lock, self.session() as db:
            cursor = db.execute(
                "DELETE FROM sessions WHERE token_hash=? AND user_id=?",
                (digest, principal["user_id"]),
            )
            if cursor.rowcount != 1:
                raise PermissionError("session is invalid or already revoked")
            self._audit(db, principal["tenant_id"], principal["user_id"],
                        "auth.logout", "session", digest[:16], {})
        return {"revoked": True}

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


    def create_invitation(self, principal, email, role="analyst", expires_in_seconds=604800):
        if principal["role"] != "owner":
            raise PermissionError("owner role required")
        email = email.strip().lower() if isinstance(email, str) else ""
        if len(email) > 254 or "@" not in email:
            raise ValueError("a valid email address is required")
        if role not in {"analyst", "viewer"}:
            raise ValueError("invited role must be analyst or viewer")
        if isinstance(expires_in_seconds, bool) or not isinstance(expires_in_seconds, int) or not 3600 <= expires_in_seconds <= 2592000:
            raise ValueError("invitation expiry must be between one hour and 30 days")
        invitation_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(invitation_token.encode("utf-8")).hexdigest()
        invitation_id = secrets.token_hex(16)
        created = datetime.now(timezone.utc)
        expires = datetime.fromtimestamp(
            created.timestamp() + expires_in_seconds, timezone.utc
        ).isoformat().replace("+00:00", "Z")
        with self._lock, self.session() as db:
            db.execute("DELETE FROM invitations WHERE expires_at<=?", (_utcnow(),))
            if db.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
                raise ValueError("email is already registered")
            existing = db.execute(
                "SELECT id FROM invitations WHERE tenant_id=? AND email=?",
                (principal["tenant_id"], email),
            ).fetchone()
            if existing:
                raise ValueError("an invitation for this email already exists")
            db.execute(
                "INSERT INTO invitations VALUES (?,?,?,?,?,?,?,?)",
                (invitation_id, principal["tenant_id"], email, role, token_hash,
                 expires, _utcnow(), principal["user_id"]),
            )
            self._audit(db, principal["tenant_id"], principal["user_id"],
                        "member.invitation.create", "invitation", invitation_id,
                        {"email": email, "role": role, "expires_at": expires})
        # The caller must deliver this secret through an approved channel.
        # The reference service intentionally has no email-sending integration.
        return {
            "invitation_id": invitation_id, "email": email, "role": role,
            "expires_at": expires, "invitation_token": invitation_token,
            "email_delivery_performed": False,
        }

    def accept_invitation(self, invitation_token, password):
        if not isinstance(invitation_token, str) or not 20 <= len(invitation_token) <= 256:
            raise PermissionError("invitation is invalid or expired")
        if not isinstance(password, str) or not 12 <= len(password) <= 256:
            raise ValueError("password must contain 12–256 characters")
        token_hash = hashlib.sha256(invitation_token.encode("utf-8")).hexdigest()
        with self._lock, self.session() as db:
            row = db.execute(
                "SELECT * FROM invitations WHERE token_hash=?", (token_hash,)
            ).fetchone()
            if row is None or row["expires_at"] <= _utcnow():
                raise PermissionError("invitation is invalid or expired")
            if db.execute("SELECT 1 FROM users WHERE email=?", (row["email"],)).fetchone():
                raise ValueError("email is already registered")
            user_id = secrets.token_hex(16)
            salt = secrets.token_bytes(16)
            db.execute(
                "INSERT INTO users VALUES (?,?,?,?,?,?,?)",
                (user_id, row["tenant_id"], row["email"], salt.hex(),
                 self._password(password, salt), row["role"], _utcnow()),
            )
            invitation_id = row["id"]
            tenant_id = row["tenant_id"]
            role = row["role"]
            db.execute("DELETE FROM invitations WHERE id=?", (invitation_id,))
            self._audit(db, tenant_id, user_id, "member.invitation.accept",
                        "user", user_id, {"invitation_id": invitation_id, "role": role})
        return {"tenant_id": tenant_id, "user_id": user_id, "role": role}

    def list_members(self, principal):
        with self.connect() as db:
            rows = db.execute(
                "SELECT id,email,role,created_at FROM users WHERE tenant_id=? ORDER BY email",
                (principal["tenant_id"],),
            ).fetchall()
        return [dict(row) for row in rows]

    def update_member_role(self, principal, user_id, role):
        if principal["role"] != "owner":
            raise PermissionError("owner role required")
        if role not in {"analyst", "viewer"}:
            raise ValueError("member role must be analyst or viewer")
        with self._lock, self.session() as db:
            target = db.execute(
                "SELECT role FROM users WHERE id=? AND tenant_id=?",
                (user_id, principal["tenant_id"]),
            ).fetchone()
            if target is None:
                raise LookupError("member not found")
            if target["role"] == "owner":
                raise ValueError("owner role cannot be changed through member management")
            db.execute(
                "UPDATE users SET role=? WHERE id=? AND tenant_id=?",
                (role, user_id, principal["tenant_id"]),
            )
            self._audit(db, principal["tenant_id"], principal["user_id"],
                        "member.role.update", "user", user_id, {"role": role})
        return {"user_id": user_id, "role": role}

    def remove_member(self, principal, user_id):
        if principal["role"] != "owner":
            raise PermissionError("owner role required")
        if user_id == principal["user_id"]:
            raise ValueError("owner cannot remove their own account")
        with self._lock, self.session() as db:
            target = db.execute(
                "SELECT role FROM users WHERE id=? AND tenant_id=?",
                (user_id, principal["tenant_id"]),
            ).fetchone()
            if target is None:
                raise LookupError("member not found")
            if target["role"] == "owner":
                raise ValueError("owner account cannot be removed through member management")
            self._audit(db, principal["tenant_id"], principal["user_id"],
                        "member.remove", "user", user_id, {})
            db.execute("DELETE FROM users WHERE id=? AND tenant_id=?",
                       (user_id, principal["tenant_id"]))
        return {"removed": True, "user_id": user_id}

    def create_notification(
        self, principal, *, title, message, category="decision", severity="info",
        site_id=None, user_id=None, payload=None,
    ):
        if principal["role"] not in {"owner", "analyst"}:
            raise PermissionError("analyst or owner role required")
        if category not in {"decision", "data_quality", "asset", "system", "security"}:
            raise ValueError("unsupported notification category")
        if severity not in {"info", "warning", "critical"}:
            raise ValueError("severity must be info, warning, or critical")
        if not isinstance(title, str) or not title.strip() or len(title) > 120:
            raise ValueError("notification title must contain 1–120 characters")
        if not isinstance(message, str) or not message.strip() or len(message) > 2000:
            raise ValueError("notification message must contain 1–2000 characters")
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            raise ValueError("notification payload must be an object")
        payload_json = json.dumps(payload, sort_keys=True, allow_nan=False)
        notification_id = secrets.token_hex(16)
        with self._lock, self.session() as db:
            if site_id is not None and not db.execute(
                "SELECT 1 FROM sites WHERE id=? AND tenant_id=?",
                (site_id, principal["tenant_id"]),
            ).fetchone():
                raise LookupError("site not found")
            if user_id is not None and not db.execute(
                "SELECT 1 FROM users WHERE id=? AND tenant_id=?",
                (user_id, principal["tenant_id"]),
            ).fetchone():
                raise LookupError("member not found")
            created = _utcnow()
            db.execute(
                "INSERT INTO notifications VALUES (?,?,?,?,?,?,?,?,?,?,NULL)",
                (notification_id, principal["tenant_id"], site_id, user_id,
                 category, severity, title.strip(), message.strip(), payload_json, created),
            )
            self._audit(db, principal["tenant_id"], principal["user_id"],
                        "notification.create", "notification", notification_id,
                        {"category": category, "severity": severity, "site_id": site_id,
                         "target_user_id": user_id})
        return {
            "id": notification_id, "site_id": site_id, "user_id": user_id,
            "category": category, "severity": severity, "title": title.strip(),
            "message": message.strip(), "payload": payload, "created_at": created,
            "read_at": None,
        }

    def list_notifications(self, principal, *, unread_only=False, limit=50):
        if not isinstance(unread_only, bool):
            raise ValueError("unread_only must be a boolean")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("limit must be an integer from 1 to 100")
        query = (
            "SELECT id,site_id,user_id,category,severity,title,message,payload_json,created_at,read_at "
            "FROM notifications WHERE tenant_id=? AND (user_id IS NULL OR user_id=?)"
        )
        args = [principal["tenant_id"], principal["user_id"]]
        if unread_only:
            query += " AND read_at IS NULL"
        query += " ORDER BY created_at DESC,id DESC LIMIT ?"
        args.append(limit)
        with self.connect() as db:
            rows = db.execute(query, args).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            items.append(item)
        return items

    def mark_notification_read(self, principal, notification_id):
        with self._lock, self.session() as db:
            row = db.execute(
                "SELECT id,read_at FROM notifications WHERE id=? AND tenant_id=? "
                "AND (user_id IS NULL OR user_id=?)",
                (notification_id, principal["tenant_id"], principal["user_id"]),
            ).fetchone()
            if row is None:
                raise LookupError("notification not found")
            read_at = row["read_at"] or _utcnow()
            db.execute(
                "UPDATE notifications SET read_at=? WHERE id=? AND tenant_id=?",
                (read_at, notification_id, principal["tenant_id"]),
            )
            self._audit(db, principal["tenant_id"], principal["user_id"],
                        "notification.read", "notification", notification_id, {})
        return {"id": notification_id, "read_at": read_at}


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
            parsed = urlparse(self.path)
            path = parsed.path
            if path == "/api/v1/health":
                return self.send_json(200, {"status": "ok", "api_version": "v1",
                                            "mode": "single_host_reference", "device_write_enabled": False})
            try:
                who = self.principal()
                if path == "/api/v1/auth/logout":
                    token = self.headers.get("Authorization", "")[7:]
                    return self.send_json(200, store.revoke_session(token, who))
                if path == "/api/v1/sites":
                    return self.send_json(200, {"sites": store.list_sites(who)})
                if path == "/api/v1/members":
                    return self.send_json(200, {"members": store.list_members(who)})
                if path == "/api/v1/notifications":
                    query = parse_qs(parsed.query)
                    unread_value = query.get("unread_only", ["false"])[0].lower()
                    if unread_value not in {"true", "false", "1", "0"}:
                        raise ValueError("unread_only must be true or false")
                    limit_value = query.get("limit", ["50"])[0]
                    try:
                        limit = int(limit_value)
                    except ValueError as exc:
                        raise ValueError("limit must be an integer from 1 to 100") from exc
                    items = store.list_notifications(
                        who, unread_only=unread_value in {"true", "1"}, limit=limit
                    )
                    return self.send_json(200, {"notifications": items})
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
            except ValueError as exc:
                return self.send_json(400, {"error": str(exc)})

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
                if path == "/api/v1/members/invitations/accept":
                    result = store.accept_invitation(
                        body.get("invitation_token", ""), body.get("password", "")
                    )
                    return self.send_json(201, result)
                who = self.principal()
                if path == "/api/v1/sites":
                    result = store.create_site(who, body.get("name"), body.get("timezone"))
                    return self.send_json(201, result)
                if path == "/api/v1/members/invitations":
                    result = store.create_invitation(
                        who, body.get("email", ""), body.get("role", "analyst"),
                        body.get("expires_in_seconds", 604800),
                    )
                    return self.send_json(201, result)
                if path == "/api/v1/notifications":
                    result = store.create_notification(
                        who, title=body.get("title"), message=body.get("message"),
                        category=body.get("category", "decision"),
                        severity=body.get("severity", "info"),
                        site_id=body.get("site_id"), user_id=body.get("user_id"),
                        payload=body.get("payload"),
                    )
                    return self.send_json(201, result)
                prefix, suffix = "/api/v1/notifications/", "/read"
                if path.startswith(prefix) and path.endswith(suffix):
                    notification_id = path[len(prefix):-len(suffix)].strip("/")
                    return self.send_json(200, store.mark_notification_read(who, notification_id))
                prefix, suffix = "/api/v1/members/", "/role"
                if path.startswith(prefix) and path.endswith(suffix):
                    user_id = path[len(prefix):-len(suffix)].strip("/")
                    return self.send_json(200, store.update_member_role(who, user_id, body.get("role")))
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
            try:
                who = self.principal()
                member_prefix = "/api/v1/members/"
                if path.startswith(member_prefix):
                    user_id = path[len(member_prefix):].strip("/")
                    return self.send_json(200, store.remove_member(who, user_id))
                site_prefix = "/api/v1/sites/"
                if path.startswith(site_prefix):
                    site_id = path[len(site_prefix):].strip("/")
                    return self.send_json(200, store.delete_site(who, site_id))
                return self.send_json(404, {"error": "not found"})
            except PermissionError as exc:
                return self.send_json(403 if "role required" in str(exc) else 401, {"error": str(exc)})
            except LookupError as exc:
                return self.send_json(404, {"error": str(exc)})
            except ValueError as exc:
                return self.send_json(400, {"error": str(exc)})

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

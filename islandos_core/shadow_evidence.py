"""Append-only local evidence ledger for read-only shadow comparisons.

This is an offline/local SQLite evidence store. It does not ingest live devices,
authorize control, or provide tamper-proof storage against a privileged host.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import threading
from typing import Mapping


_ZERO_HASH = "0" * 64
_ALLOWED_STATUS = {"within_tolerance", "deviation", "blocked"}


def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _validate_report(report: Mapping) -> dict:
    if not isinstance(report, Mapping):
        raise TypeError("shadow report must be a mapping")
    value = dict(report)
    if value.get("mode") != "read_only_shadow_comparison":
        raise ValueError("report mode must be read_only_shadow_comparison")
    if value.get("status") not in _ALLOWED_STATUS:
        raise ValueError("report status is invalid")
    if value.get("device_write_authorized") is not False or value.get("command_generated") is not False:
        raise ValueError("shadow evidence must explicitly prohibit device writes and commands")
    supplied = value.get("audit_sha256")
    if not isinstance(supplied, str) or len(supplied) != 64:
        raise ValueError("report audit_sha256 is required")
    unsigned = dict(value)
    unsigned.pop("audit_sha256", None)
    if _sha256(_canonical(unsigned)) != supplied:
        raise ValueError("shadow report audit digest does not match its contents")
    for field in ("recommendation_id", "observation_id", "evaluated_at_utc"):
        if not isinstance(value.get(field), str) or not value[field].strip():
            raise ValueError(f"report {field} is required")
    return value


class ShadowEvidenceStore:
    """Append-only SQLite ledger with a verifiable SHA-256 hash chain."""

    def __init__(self, path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self._connection() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS shadow_evidence (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    site_ref TEXT NOT NULL,
                    recommendation_id TEXT NOT NULL,
                    observation_id TEXT NOT NULL,
                    evaluated_at_utc TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('within_tolerance','deviation','blocked')),
                    report_json TEXT NOT NULL,
                    report_sha256 TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    chain_hash TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL,
                    UNIQUE(site_ref,recommendation_id,observation_id)
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS shadow_evidence_site_time ON shadow_evidence(site_ref,id DESC)")

    @contextmanager
    def _connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            yield db
        finally:
            db.close()

    @staticmethod
    def _chain_hash(previous_hash: str, site_ref: str, report_sha256: str) -> str:
        return _sha256(_canonical({
            "previous_hash": previous_hash,
            "site_ref": site_ref,
            "report_sha256": report_sha256,
        }))

    def append(self, site_ref: str, report: Mapping) -> dict:
        if not isinstance(site_ref, str) or not site_ref.strip() or len(site_ref) > 256:
            raise ValueError("site_ref must contain 1–256 characters")
        value = _validate_report(report)
        rendered = _canonical(value)
        report_hash = _sha256(rendered)
        with self._lock, self._connect() as db:
            duplicate = db.execute(
                "SELECT id FROM shadow_evidence WHERE site_ref=? AND recommendation_id=? AND observation_id=?",
                (site_ref, value["recommendation_id"], value["observation_id"]),
            ).fetchone()
            if duplicate:
                raise ValueError("duplicate shadow evidence identity")
            previous = db.execute(
                "SELECT chain_hash FROM shadow_evidence ORDER BY id DESC LIMIT 1"
            ).fetchone()
            previous_hash = previous["chain_hash"] if previous else _ZERO_HASH
            chain_hash = self._chain_hash(previous_hash, site_ref, report_hash)
            created = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            cursor = db.execute(
                """INSERT INTO shadow_evidence
                (site_ref,recommendation_id,observation_id,evaluated_at_utc,status,
                 report_json,report_sha256,previous_hash,chain_hash,created_at_utc)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (site_ref, value["recommendation_id"], value["observation_id"],
                 value["evaluated_at_utc"], value["status"], rendered, report_hash,
                 previous_hash, chain_hash, created),
            )
            row_id = cursor.lastrowid
        return {
            "id": row_id, "site_ref": site_ref, "status": value["status"],
            "report_sha256": report_hash, "previous_hash": previous_hash,
            "chain_hash": chain_hash, "device_write_authorized": False,
        }

    def list_recent(self, site_ref: str, limit: int = 50) -> list[dict]:
        if not isinstance(site_ref, str) or not site_ref.strip():
            raise ValueError("site_ref is required")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError("limit must be an integer from 1 to 500")
        with self._connection() as db:
            rows = db.execute(
                """SELECT id,site_ref,recommendation_id,observation_id,evaluated_at_utc,
                   status,report_sha256,previous_hash,chain_hash,created_at_utc
                   FROM shadow_evidence WHERE site_ref=? ORDER BY id DESC LIMIT ?""",
                (site_ref, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def verify_chain(self) -> dict:
        errors = []
        expected_previous = _ZERO_HASH
        checked = 0
        with self._connection() as db:
            rows = db.execute("SELECT * FROM shadow_evidence ORDER BY id ASC").fetchall()
        for row in rows:
            checked += 1
            if row["previous_hash"] != expected_previous:
                errors.append(f"record {row['id']}: previous hash mismatch")
            if _sha256(row["report_json"]) != row["report_sha256"]:
                errors.append(f"record {row['id']}: report hash mismatch")
            expected_chain = self._chain_hash(row["previous_hash"], row["site_ref"], row["report_sha256"])
            if expected_chain != row["chain_hash"]:
                errors.append(f"record {row['id']}: chain hash mismatch")
            try:
                parsed = json.loads(row["report_json"])
                _validate_report(parsed)
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                errors.append(f"record {row['id']}: invalid report ({exc})")
            expected_previous = row["chain_hash"]
        return {
            "valid": not errors, "records_checked": checked, "errors": errors,
            "last_chain_hash": expected_previous, "device_write_authorized": False,
        }

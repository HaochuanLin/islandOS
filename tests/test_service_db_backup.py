"""Tests for scripts/backup_service_db.py.

The console keeps all customer state in one SQLite file, so a backup is a
correctness feature: the copy must be readable, complete and verifiably intact.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from backup_service_db import backup_database  # noqa: E402


def make_database(path: Path) -> Path:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            CREATE TABLE tenants (id TEXT PRIMARY KEY, name TEXT NOT NULL);
            CREATE TABLE sites (id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL);
            """
        )
        connection.execute("INSERT INTO tenants VALUES ('t1', 'Tenant one')")
        connection.execute("INSERT INTO tenants VALUES ('t2', 'Tenant two')")
        connection.execute("INSERT INTO sites VALUES ('s1', 't1')")
        connection.commit()
    finally:
        connection.close()
    return path


def test_backup_copies_rows_and_reports_integrity(tmp_path):
    source = make_database(tmp_path / "service.sqlite3")
    summary = backup_database(source, tmp_path / "backups", timestamp="20261125T120000Z")

    assert summary["integrity_check"] == "ok"
    assert summary["table_rows"] == {"sites": 1, "tenants": 2}
    backup_path = Path(summary["backup_path"])
    assert backup_path.name == "service-20261125T120000Z.sqlite3"
    assert backup_path.stat().st_size == summary["bytes"]

    copy = sqlite3.connect(backup_path)
    try:
        assert copy.execute("SELECT count(*) FROM tenants").fetchone()[0] == 2
    finally:
        copy.close()


def test_backup_never_overwrites_an_existing_file(tmp_path):
    source = make_database(tmp_path / "service.sqlite3")
    first = backup_database(source, tmp_path / "backups", timestamp="20261125T120000Z")
    second = backup_database(source, tmp_path / "backups", timestamp="20261125T120000Z")

    assert first["backup_path"] != second["backup_path"]
    assert Path(first["backup_path"]).is_file()
    assert Path(second["backup_path"]).is_file()
    assert not list((tmp_path / "backups").glob("*.partial"))


def test_missing_or_empty_database_is_refused(tmp_path):
    with pytest.raises(FileNotFoundError):
        backup_database(tmp_path / "absent.sqlite3", tmp_path / "backups")

    empty = tmp_path / "empty.sqlite3"
    empty.touch()
    with pytest.raises(ValueError):
        backup_database(empty, tmp_path / "backups")


def test_command_line_prints_json_summary(tmp_path, capsys):
    source = make_database(tmp_path / "service.sqlite3")
    from backup_service_db import main

    code = main(["--database", str(source), "--destination-dir", str(tmp_path / "backups")])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["integrity_check"] == "ok"
    assert Path(payload["backup_path"]).is_file()

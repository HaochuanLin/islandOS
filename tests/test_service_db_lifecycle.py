"""Lifecycle checks for the reference service's SQLite file.

Evidence for the documented behaviour, not a promise of data safety:

* ``IslandOSStore`` creates its schema with ``CREATE TABLE IF NOT EXISTS`` on
  every start, so reopening an existing file keeps the rows.
* Opening a corrupt file fails closed with ``sqlite3.DatabaseError``; the
  service does not start and does not rewrite the file.
* A backup taken with ``scripts/backup_service_db.py`` can be put back in place
  and still authenticates the accounts it contained.
"""
from __future__ import annotations

import shutil
import sqlite3
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from backup_service_db import backup_database  # noqa: E402
from islandos_service_api import IslandOSStore  # noqa: E402

EMAIL = "lifecycle@example.test"
PASSWORD = "a-correct-long-password"


def test_reopening_the_same_file_keeps_users(tmp_path):
    path = tmp_path / "service.sqlite3"
    first = IslandOSStore(str(path))
    first.register(EMAIL, PASSWORD, "Lifecycle tenant")

    second = IslandOSStore(str(path))
    session = second.login(EMAIL, PASSWORD)
    assert session["role"] == "owner"
    principal = second.authenticate(session["access_token"])
    assert [member["email"] for member in second.list_members(principal)] == [EMAIL]


def test_corrupt_file_fails_closed(tmp_path):
    path = tmp_path / "corrupt.sqlite3"
    path.write_bytes(b"this is not a sqlite database" * 4)
    original = path.read_bytes()

    with pytest.raises(sqlite3.DatabaseError):
        IslandOSStore(str(path))

    assert path.read_bytes() == original


def test_backup_restores_into_a_working_service_file(tmp_path):
    source = tmp_path / "service.sqlite3"
    store = IslandOSStore(str(source))
    store.register(EMAIL, PASSWORD, "Lifecycle tenant")
    summary = backup_database(source, tmp_path / "backups", timestamp="20261125T130000Z")

    restored = tmp_path / "restored.sqlite3"
    shutil.copyfile(summary["backup_path"], restored)
    restored_store = IslandOSStore(str(restored))

    session = restored_store.login(EMAIL, PASSWORD)
    assert session["role"] == "owner"
    assert summary["table_rows"]["users"] == 1


def test_missing_database_is_created_empty_not_recovered(tmp_path):
    path = tmp_path / "absent.sqlite3"
    store = IslandOSStore(str(path))
    assert path.is_file()

    with pytest.raises(PermissionError):
        store.login(EMAIL, PASSWORD)

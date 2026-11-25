"""Schema versioning checks for the local reference database.

Before versioning, ``IslandOSStore`` only ran ``CREATE TABLE IF NOT EXISTS``,
so a caller could not tell which schema a file carried and a future change had
no place to run. These tests pin the new contract: every file reports
``PRAGMA user_version``, a pre-versioning file is stamped on the next open
without losing rows, and a file written by a newer build refuses to open.
"""

from __future__ import annotations

import sqlite3

import pytest

from islandos_service_api import SCHEMA_VERSION, IslandOSStore, SchemaVersionError

OWNER = "schema-version-owner@example.test"
PASSWORD = "a-correct-long-password"


def _version(path) -> int:
    with sqlite3.connect(str(path)) as db:
        return db.execute("PRAGMA user_version").fetchone()[0]


def _set_version(path, value: int) -> None:
    with sqlite3.connect(str(path)) as db:
        db.execute(f"PRAGMA user_version={value}")


def test_a_new_database_reports_the_declared_version(tmp_path):
    path = tmp_path / "fresh.sqlite3"
    store = IslandOSStore(str(path))

    assert SCHEMA_VERSION >= 1
    assert store.schema_version() == SCHEMA_VERSION
    assert _version(path) == SCHEMA_VERSION

    created = store.register(OWNER, PASSWORD, "Fresh tenant")
    assert created["role"] == "owner"
    assert store.authenticate(store.login(OWNER, PASSWORD)["access_token"])["role"] == "owner"


def test_a_pre_versioning_file_is_stamped_without_losing_rows(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    store = IslandOSStore(str(path))
    store.register(OWNER, PASSWORD, "Legacy tenant")
    # A file written before versioning existed reports 0 and carries real rows.
    _set_version(path, 0)

    reopened = IslandOSStore(str(path))

    assert reopened.schema_version() == SCHEMA_VERSION
    assert _version(path) == SCHEMA_VERSION
    token = reopened.login(OWNER, PASSWORD)["access_token"]
    assert reopened.authenticate(token)["role"] == "owner"
    with reopened.session() as db:
        assert db.execute("SELECT count(*) FROM tenants").fetchone()[0] == 1


def test_a_newer_schema_is_refused_instead_of_guessed(tmp_path):
    path = tmp_path / "newer.sqlite3"
    IslandOSStore(str(path)).register(OWNER, PASSWORD, "Newer tenant")
    _set_version(path, SCHEMA_VERSION + 1)

    with pytest.raises(SchemaVersionError) as raised:
        IslandOSStore(str(path))

    message = str(raised.value)
    assert str(SCHEMA_VERSION + 1) in message
    assert str(SCHEMA_VERSION) in message
    # The refusal happens before any write: the file keeps its version.
    assert _version(path) == SCHEMA_VERSION + 1

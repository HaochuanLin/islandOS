"""Copy the local reference-service SQLite database to a dated backup file.

The console stores every tenant, user, site, telemetry row and audit event in
one SQLite file. This script uses SQLite's online backup API instead of a plain
file copy, so a running service still produces a consistent snapshot, and it
verifies the copy with ``PRAGMA integrity_check`` before reporting success.

It backs up only the database file; it does not export rows, archive logs, or
restore anything. Restoring is a manual act: stop both services, replace the
``--database`` file with a backup, and start again.

Usage::

    python scripts/backup_service_db.py
    python scripts/backup_service_db.py --database build/islandos-service.sqlite3 \
        --destination-dir build/backups
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


def backup_database(
    source: str | Path,
    destination_dir: str | Path,
    *,
    timestamp: str | None = None,
) -> dict[str, object]:
    """Write one verified copy of ``source`` into ``destination_dir``."""
    source_path = Path(source)
    if not source_path.is_file():
        raise FileNotFoundError(f"database file not found: {source_path}")
    if source_path.stat().st_size == 0:
        raise ValueError(f"database file is empty: {source_path}")

    stamp = timestamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination_dir = Path(destination_dir)
    destination_dir.mkdir(parents=True, exist_ok=True)

    destination = destination_dir / f"{source_path.stem}-{stamp}{source_path.suffix}"
    suffix = 1
    while destination.exists():
        destination = destination_dir / f"{source_path.stem}-{stamp}-{suffix}{source_path.suffix}"
        suffix += 1
    partial = destination.with_name(destination.name + ".partial")

    source_connection = sqlite3.connect(f"file:{source_path.as_posix()}?mode=ro", uri=True)
    destination_connection = sqlite3.connect(partial)
    try:
        source_connection.backup(destination_connection)
        integrity = destination_connection.execute("PRAGMA integrity_check").fetchone()[0]
        schema_version = destination_connection.execute("PRAGMA user_version").fetchone()[0]
        tables = {
            row[0]: destination_connection.execute(
                'SELECT count(*) FROM "%s"' % row[0].replace('"', '""')
            ).fetchone()[0]
            for row in destination_connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        }
    finally:
        destination_connection.close()
        source_connection.close()

    if integrity != "ok":
        partial.unlink(missing_ok=True)
        raise ValueError(f"backup failed integrity_check: {integrity}")

    partial.replace(destination)
    return {
        "backup_path": str(destination),
        "bytes": destination.stat().st_size,
        "integrity_check": integrity,
        "schema_version": schema_version,
        "table_rows": tables,
        "source": str(source_path),
        "created_at_utc": stamp,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default="build/islandos-service.sqlite3",
                        help="SQLite file used by the reference API")
    parser.add_argument("--destination-dir", default="build/backups",
                        help="directory that receives the dated copy")
    args = parser.parse_args(argv)

    try:
        summary = backup_database(args.database, args.destination_dir)
    except (FileNotFoundError, ValueError, sqlite3.Error) as exc:
        print(f"backup failed: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

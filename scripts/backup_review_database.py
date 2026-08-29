#!/usr/bin/env python3
"""Create and verify an atomic SQLite review-database backup."""

from __future__ import annotations

import argparse
import os
import sqlite3
import tempfile
from pathlib import Path


def integrity_check(connection: sqlite3.Connection) -> None:
    result = connection.execute("PRAGMA integrity_check").fetchone()[0]
    if result != "ok":
        raise RuntimeError("review database integrity check failed")


def backup_database(source: Path, destination: Path) -> None:
    source = source.expanduser().resolve()
    destination = destination.expanduser().resolve()
    if not source.is_file():
        raise ValueError("source review database does not exist")
    if destination.exists():
        raise ValueError("destination already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    os.chmod(temporary_path, 0o600)
    source_connection = sqlite3.connect(f"{source.as_uri()}?mode=ro", uri=True)
    destination_connection = sqlite3.connect(temporary_path)
    try:
        integrity_check(source_connection)
        source_connection.backup(destination_connection)
        integrity_check(destination_connection)
        destination_connection.close()
        source_connection.close()
        os.replace(temporary_path, destination)
        os.chmod(destination, 0o600)
    except Exception:
        destination_connection.close()
        source_connection.close()
        temporary_path.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    try:
        backup_database(args.source, args.destination)
    except (OSError, sqlite3.Error, RuntimeError, ValueError) as error:
        parser.error(str(error))
    print(f"verified_backup={args.destination.expanduser().resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

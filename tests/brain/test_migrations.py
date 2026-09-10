from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from mico.brain.migrations import MigrationError, apply_migrations, current_version

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "migrations"


@pytest.fixture
def conn() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    try:
        yield connection
    finally:
        connection.close()


def write_migration(directory: Path, name: str, sql: str) -> None:
    (directory / name).write_text(sql, encoding="utf-8")


def test_current_version_defaults_to_zero(conn: sqlite3.Connection) -> None:
    assert current_version(conn) == 0


def test_apply_migrations_from_fresh_database(conn: sqlite3.Connection) -> None:
    result = apply_migrations(conn, FIXTURES_DIR)

    assert result == 2
    assert current_version(conn) == 2
    rows = conn.execute("PRAGMA table_info(widgets)").fetchall()
    columns = {row[1] for row in rows}
    assert columns == {"id", "name", "color"}


def test_apply_migrations_only_runs_newer_ones(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA user_version = 1")
    conn.executescript(
        (FIXTURES_DIR / "0001_create_widgets.sql").read_text(encoding="utf-8")
    )

    result = apply_migrations(conn, FIXTURES_DIR)

    assert result == 2
    assert current_version(conn) == 2
    rows = conn.execute("PRAGMA table_info(widgets)").fetchall()
    columns = {row[1] for row in rows}
    assert columns == {"id", "name", "color"}


def test_apply_migrations_is_noop_when_already_current(conn: sqlite3.Connection) -> None:
    apply_migrations(conn, FIXTURES_DIR)

    result = apply_migrations(conn, FIXTURES_DIR)

    assert result == 2
    assert current_version(conn) == 2


def test_apply_migrations_empty_directory_is_noop(conn: sqlite3.Connection, tmp_path: Path) -> None:
    result = apply_migrations(conn, tmp_path)

    assert result == 0
    assert current_version(conn) == 0


def test_apply_migrations_applies_in_ascending_order(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    write_migration(tmp_path, "0002_second.sql", "CREATE TABLE second (id INTEGER);")
    write_migration(tmp_path, "0001_first.sql", "CREATE TABLE first (id INTEGER);")
    write_migration(tmp_path, "0010_tenth.sql", "CREATE TABLE tenth (id INTEGER);")

    result = apply_migrations(conn, tmp_path)

    assert result == 10
    for table in ("first", "second", "tenth"):
        conn.execute(f"SELECT * FROM {table}")  # raises if missing


def test_apply_migrations_rejects_malformed_filename(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    write_migration(tmp_path, "not_a_migration.sql", "CREATE TABLE t (id INTEGER);")

    with pytest.raises(MigrationError, match="naming convention"):
        apply_migrations(conn, tmp_path)


def test_apply_migrations_rejects_duplicate_version(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    write_migration(tmp_path, "0001_first.sql", "CREATE TABLE first (id INTEGER);")
    write_migration(tmp_path, "0001_also_first.sql", "CREATE TABLE also_first (id INTEGER);")

    with pytest.raises(MigrationError, match="duplicate migration version"):
        apply_migrations(conn, tmp_path)


def test_apply_migrations_rolls_back_failed_migration(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    write_migration(tmp_path, "0001_good.sql", "CREATE TABLE good (id INTEGER);")
    write_migration(
        tmp_path,
        "0002_bad.sql",
        "CREATE TABLE bad (id INTEGER);\nSELECT * FROM nonexistent_table;",
    )

    with pytest.raises(sqlite3.OperationalError):
        apply_migrations(conn, tmp_path)

    assert current_version(conn) == 1
    conn.execute("SELECT * FROM good")  # committed by the successful migration
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("SELECT * FROM bad")  # rolled back with the failed migration


def test_apply_migrations_stops_at_first_failure_leaving_later_ones_unapplied(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    write_migration(
        tmp_path,
        "0001_bad.sql",
        "SELECT * FROM nonexistent_table;",
    )
    write_migration(tmp_path, "0002_never_reached.sql", "CREATE TABLE never (id INTEGER);")

    with pytest.raises(sqlite3.OperationalError):
        apply_migrations(conn, tmp_path)

    assert current_version(conn) == 0
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("SELECT * FROM never")

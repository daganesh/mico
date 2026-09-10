"""SQLite migration runner (M1.7, AD-14).

Numbered `.sql` files + `PRAGMA user_version`, hand-rolled in favour of
`yoyo-migrations`/Alembic per AD-14's "Rejected in favour of stdlib" table:
the schema is small and forward-only, and Alembic assumes SQLAlchemy.

Convention: migration files live in a directory and are named
``<NNNN>_<description>.sql`` (e.g. ``0001_initial.sql``), where ``NNNN`` is
the schema version that file brings the database *to*. Numbers need not be
contiguous, but must be unique. A migration file must not issue its own
``BEGIN``/``COMMIT``/``ROLLBACK`` — the runner wraps each file in its own
transaction so partial failure within one file cannot corrupt the schema.

Failure semantics: migrations run one at a time, oldest-pending first. Each
file's SQL and the resulting ``PRAGMA user_version`` update are committed
together as a single transaction. If a file fails, that transaction is
rolled back (leaving the schema at the version applied by the previous
file) and the exception propagates immediately -- later, higher-numbered
files in the same batch are never attempted.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

_MIGRATION_FILENAME_RE = re.compile(r"^(\d+)_.+\.sql$")


class MigrationError(Exception):
    """Raised for migration-directory/convention problems, not SQL errors."""


@dataclass(frozen=True)
class _Migration:
    version: int
    path: Path


def current_version(conn: sqlite3.Connection) -> int:
    """Return the schema version last recorded via `PRAGMA user_version`."""
    (version,) = conn.execute("PRAGMA user_version").fetchone()
    return int(version)


def _discover_migrations(migrations_dir: Path) -> list[_Migration]:
    by_version: dict[int, Path] = {}
    for path in sorted(migrations_dir.glob("*.sql")):
        match = _MIGRATION_FILENAME_RE.match(path.name)
        if not match:
            raise MigrationError(
                f"migration file {path.name!r} does not match the "
                "'<NNNN>_<description>.sql' naming convention"
            )
        version = int(match.group(1))
        if version in by_version:
            raise MigrationError(
                f"duplicate migration version {version}: "
                f"{by_version[version].name!r} and {path.name!r}"
            )
        by_version[version] = path
    return [_Migration(version, by_version[version]) for version in sorted(by_version)]


def apply_migrations(conn: sqlite3.Connection, migrations_dir: Path) -> int:
    """Apply every pending migration in `migrations_dir`, in order.

    A migration is pending if its version number is greater than the
    connection's current `PRAGMA user_version`. Returns the resulting
    schema version (a no-op call returns the current version unchanged).
    """
    version = current_version(conn)
    pending = [m for m in _discover_migrations(migrations_dir) if m.version > version]

    for migration in pending:
        sql = migration.path.read_text(encoding="utf-8")
        script = f"BEGIN;\n{sql}\nPRAGMA user_version = {migration.version};\nCOMMIT;"
        try:
            conn.executescript(script)
        except sqlite3.Error:
            conn.rollback()
            raise
        version = migration.version

    return version

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Protocol


class SecondaryBackendError(RuntimeError):
    """Raised for secondary-backend connectivity/config problems. Never
    raised for "SQLite is fine, nothing configured" — that's the default,
    silent, always-working path (AGENTS.md's local-first guarantee)."""


@dataclass(frozen=True)
class SecondaryBackendCredentials:
    host: str
    port: int
    user: str
    password: str
    database: str


# Tables mirrored from the SQLite cache into an active secondary backend.
# Deliberately excludes fts_index/fts_index_search: SQLite FTS5 is a
# SQLite-specific virtual table mechanism with no direct MariaDB/PostgreSQL
# equivalent, it's a derived search index (not source data), and it's
# trivially rebuilt via `db sync` on whichever engine is primary. YAML/
# Markdown stays the one true source of truth for all of this regardless
# of backend — every mirrored table here is itself already a cache derived
# from workspace files, same as it is in SQLite.
MIRRORED_TABLES = [
    "sync_files",
    "pending_changes",
    "memory_entries",
    "search_queries",
    "validation_runs",
    "evidence_matches",
    "citation_plans",
    "guideline_registrations",
    "document_versions",
    "document_aliases",
]


class DbApiConnection(Protocol):
    """The subset of PEP 249 (DB-API 2.0) both psycopg2 and PyMySQL
    implement identically enough for the generic mirror/repopulate logic
    below to work unchanged against either driver."""

    def cursor(self) -> Any: ...
    def commit(self) -> None: ...
    def close(self) -> None: ...


def mirror_sqlite_into_secondary(
    sqlite_conn: sqlite3.Connection, secondary_conn: DbApiConnection, *, placeholder: str = "%s"
) -> dict[str, int]:
    """Copy every row of every mirrored table from the SQLite cache into an
    already-schema-initialized secondary backend connection, replacing
    whatever was there. SQLite (built from workspace YAML/Markdown) is
    always the source for this direction — the secondary backend is a
    mirror, never edited directly.
    """
    counts: dict[str, int] = {}
    cursor = secondary_conn.cursor()
    for table in MIRRORED_TABLES:
        sqlite_cursor = sqlite_conn.execute(f"select * from {table}")
        columns = [description[0] for description in sqlite_cursor.description]
        rows = sqlite_cursor.fetchall()
        cursor.execute(f"delete from {table}")
        if rows:
            column_list = ", ".join(columns)
            value_placeholders = ", ".join([placeholder] * len(columns))
            cursor.executemany(
                f"insert into {table} ({column_list}) values ({value_placeholders})",
                [tuple(row) for row in rows],
            )
        counts[table] = len(rows)
    secondary_conn.commit()
    return counts


def repopulate_sqlite_from_secondary(sqlite_conn: sqlite3.Connection, secondary_conn: DbApiConnection) -> dict[str, int]:
    """The reverse repair direction: if the local SQLite file went missing
    and was recreated empty (schema only), repopulate it from an active,
    reachable secondary backend. Used only for repair — the normal
    steady-state direction is always SQLite -> secondary.
    """
    counts: dict[str, int] = {}
    cursor = secondary_conn.cursor()
    for table in MIRRORED_TABLES:
        cursor.execute(f"select * from {table}")
        columns = [description[0] for description in cursor.description]
        rows = cursor.fetchall()
        sqlite_conn.execute(f"delete from {table}")
        if rows:
            column_list = ", ".join(columns)
            value_placeholders = ", ".join(["?"] * len(columns))
            sqlite_conn.executemany(
                f"insert into {table} ({column_list}) values ({value_placeholders})",
                [tuple(row) for row in rows],
            )
        counts[table] = len(rows)
    sqlite_conn.commit()
    return counts

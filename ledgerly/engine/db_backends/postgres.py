from __future__ import annotations

from typing import Any

from ledgerly.engine.db_backends.base import SecondaryBackendCredentials, SecondaryBackendError


_SCHEMA_STATEMENTS = [
    """
    create table if not exists sync_files (
        relative_path text primary key,
        sha256 text not null,
        size_bytes integer not null,
        mtime double precision not null,
        last_synced_at text not null,
        db_revision integer not null,
        file_revision integer not null,
        dirty_flag integer not null default 0,
        conflict_status text not null default 'clean',
        file_kind text not null
    )
    """,
    """
    create table if not exists pending_changes (
        id bigserial primary key,
        relative_path text not null,
        proposed_content text not null,
        reason text not null,
        created_at text not null,
        applied_at text,
        status text not null default 'pending'
    )
    """,
    """
    create table if not exists memory_entries (
        id bigserial primary key,
        category text not null,
        key text not null,
        value_json text not null,
        created_at text not null,
        updated_at text not null,
        unique(category, key)
    )
    """,
    """
    create table if not exists search_queries (
        id bigserial primary key,
        query text not null,
        source text not null,
        status text not null,
        result_count integer,
        created_at text not null
    )
    """,
    """
    create table if not exists validation_runs (
        report_id text primary key,
        report_path text not null,
        target text,
        source_count integer,
        unsupported_count integer,
        weak_count integer,
        created_at text not null
    )
    """,
    """
    create table if not exists evidence_matches (
        id bigserial primary key,
        report_id text not null references validation_runs(report_id) on delete cascade,
        source_id text,
        match_text text,
        confidence double precision,
        status text
    )
    """,
    """
    create table if not exists citation_plans (
        plan_id text primary key,
        plan_path text not null,
        target text,
        insertion_count integer,
        status text,
        created_at text not null
    )
    """,
    """
    create table if not exists guideline_registrations (
        guideline_id text primary key,
        title text,
        scopes_json text not null,
        snapshot_path text,
        text_path text,
        updated_at text not null
    )
    """,
    """
    create table if not exists document_versions (
        version_id text primary key,
        target_path text not null,
        parent_version_id text,
        content_hash text,
        creation_reason text,
        source_command text,
        model_metadata_json text not null default '{}',
        guideline_ids_json text not null default '[]',
        validation_report_id text,
        citation_plan_id text,
        created_at text not null
    )
    """,
    """
    create table if not exists document_aliases (
        alias text primary key,
        target_kind text not null,
        target_value text not null,
        source text not null,
        updated_at text not null
    )
    """,
]


def connect(credentials: SecondaryBackendCredentials) -> Any:
    try:
        import psycopg2
    except ImportError as exc:
        raise SecondaryBackendError(
            "PostgreSQL support requires the optional 'postgres' extra: pip install -e '.[postgres]'"
        ) from exc
    try:
        return psycopg2.connect(
            host=credentials.host,
            port=credentials.port,
            user=credentials.user,
            password=credentials.password,
            dbname=credentials.database,
            connect_timeout=5,
        )
    except psycopg2.OperationalError as exc:
        raise SecondaryBackendError(f"Could not connect to PostgreSQL: {exc}") from exc


def create_schema(connection: Any) -> None:
    cursor = connection.cursor()
    for statement in _SCHEMA_STATEMENTS:
        cursor.execute(statement)
    connection.commit()


def is_reachable(credentials: SecondaryBackendCredentials) -> bool:
    try:
        connection = connect(credentials)
    except SecondaryBackendError:
        return False
    connection.close()
    return True

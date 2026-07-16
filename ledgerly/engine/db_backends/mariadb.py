from __future__ import annotations

from typing import Any

from ledgerly.engine.db_backends.base import SecondaryBackendCredentials, SecondaryBackendError


# MariaDB/MySQL requires a bounded length for any indexed/primary-key text
# column (a bare TEXT column can't be a primary key at all) — varchar(255)
# for those, plain TEXT for large unbounded content fields. PostgreSQL and
# SQLite have no such restriction, hence the separate DDL from postgres.py
# rather than one shared string.
_SCHEMA_STATEMENTS = [
    """
    create table if not exists sync_files (
        relative_path varchar(1024) primary key,
        sha256 varchar(64) not null,
        size_bytes bigint not null,
        mtime double not null,
        last_synced_at varchar(64) not null,
        db_revision integer not null,
        file_revision integer not null,
        dirty_flag integer not null default 0,
        conflict_status varchar(32) not null default 'clean',
        file_kind varchar(64) not null
    )
    """,
    """
    create table if not exists pending_changes (
        id bigint auto_increment primary key,
        relative_path varchar(1024) not null,
        proposed_content longtext not null,
        reason text not null,
        created_at varchar(64) not null,
        applied_at varchar(64),
        status varchar(32) not null default 'pending'
    )
    """,
    """
    create table if not exists memory_entries (
        id bigint auto_increment primary key,
        category varchar(255) not null,
        `key` varchar(255) not null,
        value_json longtext not null,
        created_at varchar(64) not null,
        updated_at varchar(64) not null,
        unique(category, `key`)
    )
    """,
    """
    create table if not exists search_queries (
        id bigint auto_increment primary key,
        query text not null,
        source varchar(255) not null,
        status varchar(32) not null,
        result_count integer,
        created_at varchar(64) not null
    )
    """,
    """
    create table if not exists validation_runs (
        report_id varchar(255) primary key,
        report_path varchar(1024) not null,
        target text,
        source_count integer,
        unsupported_count integer,
        weak_count integer,
        created_at varchar(64) not null
    )
    """,
    """
    create table if not exists evidence_matches (
        id bigint auto_increment primary key,
        report_id varchar(255) not null,
        source_id varchar(255),
        match_text text,
        confidence double,
        status varchar(32),
        foreign key(report_id) references validation_runs(report_id) on delete cascade
    )
    """,
    """
    create table if not exists citation_plans (
        plan_id varchar(255) primary key,
        plan_path varchar(1024) not null,
        target text,
        insertion_count integer,
        status varchar(32),
        created_at varchar(64) not null
    )
    """,
    """
    create table if not exists guideline_registrations (
        guideline_id varchar(255) primary key,
        title text,
        scopes_json text not null,
        snapshot_path varchar(1024),
        text_path varchar(1024),
        updated_at varchar(64) not null
    )
    """,
    """
    create table if not exists document_versions (
        version_id varchar(255) primary key,
        target_path varchar(1024) not null,
        parent_version_id varchar(255),
        content_hash varchar(64),
        creation_reason text,
        source_command text,
        model_metadata_json longtext not null,
        guideline_ids_json longtext not null,
        validation_report_id varchar(255),
        citation_plan_id varchar(255),
        created_at varchar(64) not null
    )
    """,
    """
    create table if not exists document_aliases (
        alias varchar(255) primary key,
        target_kind varchar(64) not null,
        target_value text not null,
        source varchar(255) not null,
        updated_at varchar(64) not null
    )
    """,
]


def connect(credentials: SecondaryBackendCredentials) -> Any:
    try:
        import pymysql
    except ImportError as exc:
        raise SecondaryBackendError(
            "MariaDB support requires the optional 'mariadb' extra: pip install -e '.[mariadb]'"
        ) from exc
    try:
        return pymysql.connect(
            host=credentials.host,
            port=credentials.port,
            user=credentials.user,
            password=credentials.password,
            database=credentials.database,
            connect_timeout=5,
            autocommit=False,
        )
    except pymysql.err.OperationalError as exc:
        raise SecondaryBackendError(f"Could not connect to MariaDB: {exc}") from exc


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

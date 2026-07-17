"""Phase 24: optional MariaDB/PostgreSQL secondary backend, kept in sync
with the always-on SQLite cache. SQLite-only behavior (today's default)
must keep passing unmodified — that's covered by the rest of the existing
suite (tests/test_database.py) continuing to pass without any changes here,
not duplicated in this file.

Real round-trip coverage against PostgreSQL runs when a local server is
reachable (`CORROBORLY_TEST_POSTGRES_*` env vars, defaults match a local
`createdb corroborly_test` on the current user) and skips gracefully
otherwise. No MariaDB server is available in this environment — those
tests are written the same way and will run wherever one is reachable via
`CORROBORLY_TEST_MARIADB_*`, but skip here rather than being silently
omitted, so the gap is visible in test output, not hidden.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from corroborly.engine.database import (
    activate_secondary_backend,
    database_path,
    deactivate_secondary_backend,
    repair_secondary_from_sqlite,
    repair_sqlite_from_secondary,
    secondary_backend_status,
    sync_database,
)
from corroborly.engine.db_backends.base import (
    SecondaryBackendCredentials,
    SecondaryBackendError,
    mirror_sqlite_into_secondary,
    repopulate_sqlite_from_secondary,
)
from corroborly.engine.db_backends.config import (
    configured_secondary_backend,
    secondary_backend_credentials,
)
from corroborly.engine.workspace import init_workspace


# --- config parsing (no real server needed) ---


def test_configured_secondary_backend_defaults_to_none(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("CORROBORLY_DB_BACKEND", raising=False)
    monkeypatch.chdir(tmp_path)

    assert configured_secondary_backend(tmp_path) is None


def test_configured_secondary_backend_reads_env_var(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CORROBORLY_DB_BACKEND", "postgres")
    monkeypatch.chdir(tmp_path)

    assert configured_secondary_backend(tmp_path) == "postgres"


def test_configured_secondary_backend_rejects_unknown_value(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CORROBORLY_DB_BACKEND", "oracle")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SecondaryBackendError, match="Invalid CORROBORLY_DB_BACKEND"):
        configured_secondary_backend(tmp_path)


def test_secondary_backend_credentials_requires_host_user_database(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("CORROBORLY_POSTGRES_HOST", raising=False)
    monkeypatch.delenv("CORROBORLY_POSTGRES_USER", raising=False)
    monkeypatch.delenv("CORROBORLY_POSTGRES_DATABASE", raising=False)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SecondaryBackendError, match="Missing required config"):
        secondary_backend_credentials("postgres", tmp_path)


def test_secondary_backend_credentials_defaults_port(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CORROBORLY_POSTGRES_HOST", "localhost")
    monkeypatch.setenv("CORROBORLY_POSTGRES_USER", "u")
    monkeypatch.setenv("CORROBORLY_POSTGRES_DATABASE", "d")
    monkeypatch.delenv("CORROBORLY_POSTGRES_PORT", raising=False)
    monkeypatch.chdir(tmp_path)

    credentials = secondary_backend_credentials("postgres", tmp_path)

    assert credentials.port == 5432


def test_secondary_backend_status_without_configuration(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test", project_type="M.Phil", topic="Topic")
    monkeypatch.delenv("CORROBORLY_DB_BACKEND", raising=False)
    monkeypatch.chdir(tmp_path)

    result = secondary_backend_status(workspace)

    assert result.report["configured"] is None
    assert result.report["active"] is None
    assert result.report["needs_activation_prompt"] is False


def test_activate_secondary_backend_requires_configuration(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test", project_type="M.Phil", topic="Topic")
    monkeypatch.delenv("CORROBORLY_DB_BACKEND", raising=False)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SecondaryBackendError, match="No secondary backend configured"):
        activate_secondary_backend(workspace)


def test_repair_sqlite_from_secondary_requires_active_backend(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test", project_type="M.Phil", topic="Topic")

    with pytest.raises(SecondaryBackendError, match="nothing to repair from"):
        repair_sqlite_from_secondary(workspace)


# --- core mirror/repopulate row-copy logic, offline (two SQLite connections stand in for "any DB-API 2.0 driver") ---


def _make_sqlite_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        create table sync_files (
            relative_path text primary key, sha256 text, size_bytes integer,
            mtime real, last_synced_at text, db_revision integer,
            file_revision integer, dirty_flag integer, conflict_status text, file_kind text
        );
        create table pending_changes (
            id integer primary key, relative_path text, proposed_content text,
            reason text, created_at text, applied_at text, status text
        );
        create table memory_entries (id integer primary key, category text, key text, value_json text, created_at text, updated_at text);
        create table search_queries (id integer primary key, query text, source text, status text, result_count integer, created_at text);
        create table validation_runs (report_id text primary key, report_path text, target text, source_count integer, unsupported_count integer, weak_count integer, created_at text);
        create table evidence_matches (id integer primary key, report_id text, source_id text, match_text text, confidence real, status text);
        create table citation_plans (plan_id text primary key, plan_path text, target text, insertion_count integer, status text, created_at text);
        create table guideline_registrations (guideline_id text primary key, title text, scopes_json text, snapshot_path text, text_path text, updated_at text);
        create table document_versions (version_id text primary key, target_path text, parent_version_id text, content_hash text, creation_reason text, source_command text, model_metadata_json text, guideline_ids_json text, validation_report_id text, citation_plan_id text, created_at text);
        create table document_aliases (alias text primary key, target_kind text, target_value text, source text, updated_at text);
        """
    )


def test_mirror_and_repopulate_round_trip_offline() -> None:
    source = sqlite3.connect(":memory:")
    source.row_factory = sqlite3.Row
    _make_sqlite_schema(source)
    source.execute(
        "insert into sync_files values ('a.yaml', 'hash1', 10, 1.0, 't1', 1, 1, 0, 'clean', 'yaml')"
    )
    source.execute(
        "insert into document_aliases values ('thesis', 'file_path', 'artefacts/thesis/x.md', 'workspace_config', 't1')"
    )
    source.commit()

    mirror = sqlite3.connect(":memory:")
    mirror.row_factory = sqlite3.Row
    _make_sqlite_schema(mirror)

    counts = mirror_sqlite_into_secondary(source, mirror, placeholder="?")

    assert counts["sync_files"] == 1
    assert counts["document_aliases"] == 1
    mirrored_row = mirror.execute("select * from sync_files").fetchone()
    assert mirrored_row["relative_path"] == "a.yaml"
    assert mirrored_row["sha256"] == "hash1"

    # Now simulate the reverse repair: a fresh, empty SQLite repopulated from the mirror.
    fresh = sqlite3.connect(":memory:")
    fresh.row_factory = sqlite3.Row
    _make_sqlite_schema(fresh)

    repopulated_counts = repopulate_sqlite_from_secondary(fresh, mirror)

    assert repopulated_counts == counts
    row = fresh.execute("select * from document_aliases").fetchone()
    assert row["alias"] == "thesis"


def test_mirror_replaces_stale_rows_not_appends() -> None:
    source = sqlite3.connect(":memory:")
    source.row_factory = sqlite3.Row
    _make_sqlite_schema(source)
    source.execute("insert into sync_files values ('a.yaml', 'h1', 1, 1.0, 't', 1, 1, 0, 'clean', 'yaml')")
    source.commit()

    mirror = sqlite3.connect(":memory:")
    mirror.row_factory = sqlite3.Row
    _make_sqlite_schema(mirror)
    mirror.execute("insert into sync_files values ('stale.yaml', 'old', 1, 1.0, 't', 1, 1, 0, 'clean', 'yaml')")
    mirror.commit()

    mirror_sqlite_into_secondary(source, mirror, placeholder="?")

    rows = mirror.execute("select relative_path from sync_files").fetchall()
    assert [row["relative_path"] for row in rows] == ["a.yaml"]


# --- real PostgreSQL round-trip (skips if no local server reachable) ---


def _postgres_test_credentials() -> SecondaryBackendCredentials:
    return SecondaryBackendCredentials(
        host=os.environ.get("CORROBORLY_TEST_POSTGRES_HOST", "localhost"),
        port=int(os.environ.get("CORROBORLY_TEST_POSTGRES_PORT", "5432")),
        user=os.environ.get("CORROBORLY_TEST_POSTGRES_USER", os.environ.get("USER", "postgres")),
        password=os.environ.get("CORROBORLY_TEST_POSTGRES_PASSWORD", ""),
        database=os.environ.get("CORROBORLY_TEST_POSTGRES_DATABASE", "corroborly_test"),
    )


def _postgres_reachable() -> bool:
    try:
        from corroborly.engine.db_backends import postgres
    except Exception:
        return False
    try:
        return postgres.is_reachable(_postgres_test_credentials())
    except Exception:
        return False


requires_postgres = pytest.mark.skipif(not _postgres_reachable(), reason="No reachable local PostgreSQL test server")


def _set_postgres_env(monkeypatch) -> None:
    creds = _postgres_test_credentials()
    monkeypatch.setenv("CORROBORLY_DB_BACKEND", "postgres")
    monkeypatch.setenv("CORROBORLY_POSTGRES_HOST", creds.host)
    monkeypatch.setenv("CORROBORLY_POSTGRES_PORT", str(creds.port))
    monkeypatch.setenv("CORROBORLY_POSTGRES_USER", creds.user)
    monkeypatch.setenv("CORROBORLY_POSTGRES_PASSWORD", creds.password)
    monkeypatch.setenv("CORROBORLY_POSTGRES_DATABASE", creds.database)


def _clear_postgres_tables() -> None:
    from corroborly.engine.db_backends import postgres
    from corroborly.engine.db_backends.base import MIRRORED_TABLES

    conn = postgres.connect(_postgres_test_credentials())
    try:
        postgres.create_schema(conn)
        cursor = conn.cursor()
        for table in MIRRORED_TABLES:
            cursor.execute(f"delete from {table}")
        conn.commit()
    finally:
        conn.close()


@requires_postgres
def test_activate_sync_and_status_against_real_postgres(tmp_path: Path, monkeypatch) -> None:
    _clear_postgres_tables()
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="PG Test", project_type="M.Phil", topic="x")
    _set_postgres_env(monkeypatch)

    before = secondary_backend_status(workspace)
    assert before.report == {"configured": "postgres", "active": None, "reachable": True, "needs_activation_prompt": True}

    activation = activate_secondary_backend(workspace)
    assert activation.report["status"] == "activated"

    sync_result = sync_database(workspace)
    assert sync_result.report["secondary_backend"]["status"] == "mirrored"
    assert sync_result.report["secondary_backend"]["counts"]["sync_files"] > 0

    after = secondary_backend_status(workspace)
    assert after.report["active"] == "postgres"
    assert after.report["needs_activation_prompt"] is False


@requires_postgres
def test_at_most_one_secondary_backend_active_at_a_time(tmp_path: Path, monkeypatch) -> None:
    _clear_postgres_tables()
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="PG Test", project_type="M.Phil", topic="x")
    _set_postgres_env(monkeypatch)
    activate_secondary_backend(workspace)

    monkeypatch.setenv("CORROBORLY_DB_BACKEND", "mariadb")
    monkeypatch.setenv("CORROBORLY_MARIADB_HOST", "localhost")
    monkeypatch.setenv("CORROBORLY_MARIADB_USER", "x")
    monkeypatch.setenv("CORROBORLY_MARIADB_DATABASE", "x")

    with pytest.raises(SecondaryBackendError, match="already the active secondary backend"):
        activate_secondary_backend(workspace)


@requires_postgres
def test_deactivate_secondary_backend(tmp_path: Path, monkeypatch) -> None:
    _clear_postgres_tables()
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="PG Test", project_type="M.Phil", topic="x")
    _set_postgres_env(monkeypatch)
    activate_secondary_backend(workspace)

    result = deactivate_secondary_backend(workspace)

    assert result.report == {"status": "deactivated", "backend": "postgres"}
    assert secondary_backend_status(workspace).report["active"] is None


@requires_postgres
def test_repair_sqlite_from_secondary_survives_sqlite_deletion(tmp_path: Path, monkeypatch) -> None:
    """The exact bug this repair direction exists to catch: deleting the
    local SQLite file must not also lose track of which secondary backend
    to recover from — that state has to live outside the file being
    recovered."""
    _clear_postgres_tables()
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="PG Test", project_type="M.Phil", topic="x")
    _set_postgres_env(monkeypatch)
    activate_secondary_backend(workspace)
    sync_database(workspace)

    database_path(workspace).unlink()
    assert not database_path(workspace).exists()

    result = repair_sqlite_from_secondary(workspace)

    assert result.report["status"] == "repaired"
    assert result.report["direction"] == "secondary_to_sqlite"
    assert result.report["counts"]["sync_files"] > 0
    assert database_path(workspace).is_file()
    assert secondary_backend_status(workspace).report["active"] == "postgres"


@requires_postgres
def test_repair_secondary_from_sqlite_after_secondary_wiped(tmp_path: Path, monkeypatch) -> None:
    _clear_postgres_tables()
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="PG Test", project_type="M.Phil", topic="x")
    _set_postgres_env(monkeypatch)
    activate_secondary_backend(workspace)
    sync_database(workspace)

    _clear_postgres_tables()  # simulate the secondary backend having lost its data

    result = repair_secondary_from_sqlite(workspace)

    assert result.report["status"] == "repaired"
    assert result.report["direction"] == "sqlite_to_secondary"
    assert result.report["counts"]["sync_files"] > 0


# --- MariaDB round-trip: same shape as the PostgreSQL tests above, skips ---
# --- here since no MariaDB server is available in this environment.     ---


def _mariadb_test_credentials() -> SecondaryBackendCredentials:
    return SecondaryBackendCredentials(
        host=os.environ.get("CORROBORLY_TEST_MARIADB_HOST", "localhost"),
        port=int(os.environ.get("CORROBORLY_TEST_MARIADB_PORT", "3306")),
        user=os.environ.get("CORROBORLY_TEST_MARIADB_USER", "root"),
        password=os.environ.get("CORROBORLY_TEST_MARIADB_PASSWORD", ""),
        database=os.environ.get("CORROBORLY_TEST_MARIADB_DATABASE", "corroborly_test"),
    )


def _mariadb_reachable() -> bool:
    try:
        from corroborly.engine.db_backends import mariadb
    except Exception:
        return False
    try:
        return mariadb.is_reachable(_mariadb_test_credentials())
    except Exception:
        return False


requires_mariadb = pytest.mark.skipif(not _mariadb_reachable(), reason="No reachable local MariaDB test server")


@requires_mariadb
def test_activate_sync_and_status_against_real_mariadb(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="MariaDB Test", project_type="M.Phil", topic="x")
    creds = _mariadb_test_credentials()
    monkeypatch.setenv("CORROBORLY_DB_BACKEND", "mariadb")
    monkeypatch.setenv("CORROBORLY_MARIADB_HOST", creds.host)
    monkeypatch.setenv("CORROBORLY_MARIADB_PORT", str(creds.port))
    monkeypatch.setenv("CORROBORLY_MARIADB_USER", creds.user)
    monkeypatch.setenv("CORROBORLY_MARIADB_PASSWORD", creds.password)
    monkeypatch.setenv("CORROBORLY_MARIADB_DATABASE", creds.database)

    activation = activate_secondary_backend(workspace)
    assert activation.report["status"] == "activated"

    sync_result = sync_database(workspace)
    assert sync_result.report["secondary_backend"]["status"] == "mirrored"


# --- CLI commands (real PostgreSQL round trip) ---

from typer.testing import CliRunner  # noqa: E402

from corroborly.cli import app  # noqa: E402


runner = CliRunner()


@requires_postgres
def test_cli_db_activate_sync_status_deactivate_round_trip(tmp_path: Path) -> None:
    _clear_postgres_tables()
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="CLI PG Test", project_type="M.Phil", topic="x")
    creds = _postgres_test_credentials()
    env = {
        "CORROBORLY_DB_BACKEND": "postgres",
        "CORROBORLY_POSTGRES_HOST": creds.host,
        "CORROBORLY_POSTGRES_PORT": str(creds.port),
        "CORROBORLY_POSTGRES_USER": creds.user,
        "CORROBORLY_POSTGRES_PASSWORD": creds.password,
        "CORROBORLY_POSTGRES_DATABASE": creds.database,
    }
    cli_runner = CliRunner(env=env)

    activate_result = cli_runner.invoke(app, ["db", "activate-backend", "--workspace", str(workspace), "--quiet"])
    assert activate_result.exit_code == 0, activate_result.output

    sync_result = cli_runner.invoke(app, ["db", "sync", "--workspace", str(workspace), "--quiet"])
    assert sync_result.exit_code == 0, sync_result.output

    status_result = cli_runner.invoke(app, ["db", "backend-status", "--workspace", str(workspace)])
    assert status_result.exit_code == 0, status_result.output
    assert "postgres" in status_result.output

    deactivate_result = cli_runner.invoke(app, ["db", "deactivate-backend", "--workspace", str(workspace), "--quiet"])
    assert deactivate_result.exit_code == 0, deactivate_result.output


@requires_postgres
def test_cli_db_sync_prompts_for_activation_when_configured_but_inactive(tmp_path: Path) -> None:
    _clear_postgres_tables()
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="CLI PG Prompt Test", project_type="M.Phil", topic="x")
    creds = _postgres_test_credentials()
    env = {
        "CORROBORLY_DB_BACKEND": "postgres",
        "CORROBORLY_POSTGRES_HOST": creds.host,
        "CORROBORLY_POSTGRES_PORT": str(creds.port),
        "CORROBORLY_POSTGRES_USER": creds.user,
        "CORROBORLY_POSTGRES_PASSWORD": creds.password,
        "CORROBORLY_POSTGRES_DATABASE": creds.database,
    }
    cli_runner = CliRunner(env=env)

    result = cli_runner.invoke(app, ["db", "sync", "--workspace", str(workspace)], input="y\n")

    assert result.exit_code == 0, result.output
    assert "Activate it now" in result.output
    assert "Activated postgres" in result.output
    assert secondary_backend_status(workspace).report["active"] == "postgres"


@requires_postgres
def test_cli_db_sync_declining_activation_prompt_leaves_backend_inactive(tmp_path: Path) -> None:
    _clear_postgres_tables()
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="CLI PG Decline Test", project_type="M.Phil", topic="x")
    creds = _postgres_test_credentials()
    env = {
        "CORROBORLY_DB_BACKEND": "postgres",
        "CORROBORLY_POSTGRES_HOST": creds.host,
        "CORROBORLY_POSTGRES_PORT": str(creds.port),
        "CORROBORLY_POSTGRES_USER": creds.user,
        "CORROBORLY_POSTGRES_PASSWORD": creds.password,
        "CORROBORLY_POSTGRES_DATABASE": creds.database,
    }
    cli_runner = CliRunner(env=env)

    result = cli_runner.invoke(app, ["db", "sync", "--workspace", str(workspace)], input="n\n")

    assert result.exit_code == 0, result.output
    assert secondary_backend_status(workspace).report["active"] is None


def test_cli_db_commands_with_quiet_never_prompt(tmp_path: Path, monkeypatch) -> None:
    """--quiet must never block on stdin waiting for a prompt answer, even
    when a secondary backend happens to be configured (invalid or not)."""
    workspace = tmp_path / "workspace"
    init_workspace(workspace, project_name="Test", project_type="M.Phil", topic="Topic")
    monkeypatch.setenv("CORROBORLY_DB_BACKEND", "postgres")
    monkeypatch.setenv("CORROBORLY_POSTGRES_HOST", "192.0.2.1")  # TEST-NET-1, never routable
    monkeypatch.setenv("CORROBORLY_POSTGRES_USER", "u")
    monkeypatch.setenv("CORROBORLY_POSTGRES_DATABASE", "d")

    for args in [
        ["db", "init", "--workspace", str(workspace), "--quiet"],
        ["db", "sync", "--workspace", str(workspace), "--quiet"],
        ["db", "status", "--workspace", str(workspace), "--quiet"],
    ]:
        result = runner.invoke(app, args)
        assert result.exit_code == 0, result.output

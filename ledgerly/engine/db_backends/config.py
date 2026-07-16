from __future__ import annotations

import os
from pathlib import Path

from ledgerly.engine.ai import load_dotenv_values
from ledgerly.engine.db_backends.base import SecondaryBackendCredentials, SecondaryBackendError


SECONDARY_BACKENDS = {"mariadb", "postgres"}
DEFAULT_PORTS = {"mariadb": 3306, "postgres": 5432}


def _env(workspace: Path | None, key: str) -> str | None:
    if key in os.environ:
        return os.environ[key]
    values = load_dotenv_values(Path.cwd() / ".env")
    if workspace is not None:
        values = {**values, **load_dotenv_values(workspace / ".env")}
    return values.get(key)


def configured_secondary_backend(workspace: Path | None = None) -> str | None:
    """`LEDGERLY_DB_BACKEND` if set to a real secondary backend name, else
    None. SQLite stays active whenever this is unset or set to "sqlite" —
    the zero-config default never changes based on this function's result.
    """
    value = (_env(workspace, "LEDGERLY_DB_BACKEND") or "sqlite").strip().lower()
    if value == "sqlite" or not value:
        return None
    if value not in SECONDARY_BACKENDS:
        allowed = ", ".join(sorted({"sqlite", *SECONDARY_BACKENDS}))
        raise SecondaryBackendError(f"Invalid LEDGERLY_DB_BACKEND: {value!r}. Expected one of: {allowed}")
    return value


def secondary_backend_credentials(backend: str, workspace: Path | None = None) -> SecondaryBackendCredentials:
    prefix = backend.upper()
    host = _env(workspace, f"LEDGERLY_{prefix}_HOST")
    user = _env(workspace, f"LEDGERLY_{prefix}_USER")
    password = _env(workspace, f"LEDGERLY_{prefix}_PASSWORD") or ""
    database = _env(workspace, f"LEDGERLY_{prefix}_DATABASE")
    port_raw = _env(workspace, f"LEDGERLY_{prefix}_PORT")
    missing = [
        name
        for name, value in [("HOST", host), ("USER", user), ("DATABASE", database)]
        if not value
    ]
    if missing:
        raise SecondaryBackendError(
            f"Missing required config for LEDGERLY_DB_BACKEND={backend}: "
            + ", ".join(f"LEDGERLY_{prefix}_{name}" for name in missing)
        )
    try:
        port = int(port_raw) if port_raw else DEFAULT_PORTS[backend]
    except ValueError as exc:
        raise SecondaryBackendError(f"Invalid LEDGERLY_{prefix}_PORT: {port_raw!r}") from exc
    return SecondaryBackendCredentials(host=host, port=port, user=user, password=password, database=database)


def backend_module(backend: str):
    if backend == "postgres":
        from ledgerly.engine.db_backends import postgres

        return postgres
    if backend == "mariadb":
        from ledgerly.engine.db_backends import mariadb

        return mariadb
    raise SecondaryBackendError(f"Unknown secondary backend: {backend!r}")

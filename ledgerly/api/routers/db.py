from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ledgerly.api.deps import resolve_workspace
from ledgerly.api.envelope import ApiError, ok
from ledgerly.engine.database import (
    DbCommandResult,
    activate_secondary_backend,
    apply_pending_changes,
    database_privacy_report,
    database_status,
    deactivate_secondary_backend,
    init_database,
    pending_changes_report,
    rebuild_database,
    repair_secondary_from_sqlite,
    repair_sqlite_from_secondary,
    search_corpus,
    secondary_backend_status,
    sync_database,
)
from ledgerly.engine.db_backends.base import SecondaryBackendError


router = APIRouter()


def _result(result: DbCommandResult) -> dict[str, Any]:
    return {"database_path": str(result.path), "report": result.report}


@router.post("/init")
def db_init(workspace: Path = Depends(resolve_workspace)) -> dict[str, Any]:
    return ok(_result(init_database(workspace)))


@router.post("/sync")
def db_sync(workspace: Path = Depends(resolve_workspace)) -> dict[str, Any]:
    return ok(_result(sync_database(workspace)))


@router.get("/status")
def db_status(workspace: Path = Depends(resolve_workspace)) -> dict[str, Any]:
    return ok(_result(database_status(workspace)))


@router.post("/rebuild")
def db_rebuild(workspace: Path = Depends(resolve_workspace)) -> dict[str, Any]:
    return ok(_result(rebuild_database(workspace)))


@router.get("/pending")
def db_pending(workspace: Path = Depends(resolve_workspace)) -> dict[str, Any]:
    return ok(_result(pending_changes_report(workspace)))


class ApplyPendingRequest(BaseModel):
    apply: bool = False


@router.post("/apply-pending")
def db_apply_pending(payload: ApplyPendingRequest, workspace: Path = Depends(resolve_workspace)) -> dict[str, Any]:
    return ok(_result(apply_pending_changes(workspace, apply=payload.apply)))


@router.get("/privacy")
def db_privacy(workspace: Path = Depends(resolve_workspace)) -> dict[str, Any]:
    return ok(_result(database_privacy_report(workspace)))


@router.get("/search")
def db_search(query: str, limit: int = 20, workspace: Path = Depends(resolve_workspace)) -> dict[str, Any]:
    return ok(_result(search_corpus(workspace, query, limit=limit)))


@router.get("/backend-status")
def db_backend_status(workspace: Path = Depends(resolve_workspace)) -> dict[str, Any]:
    """Whether a secondary MariaDB/PostgreSQL backend is configured, active, and reachable. Read-only —
    never activates anything. The web configuration panel's opt-in prompt uses this to decide what to show."""
    return ok(_result(secondary_backend_status(workspace)))


@router.post("/activate-backend")
def db_activate_backend(workspace: Path = Depends(resolve_workspace)) -> dict[str, Any]:
    """Explicit opt-in: activate the configured secondary backend and mirror the current SQLite cache into
    it. Never called automatically — this is the web equivalent of the CLI's activation prompt."""
    try:
        return ok(_result(activate_secondary_backend(workspace)))
    except SecondaryBackendError as exc:
        raise ApiError("secondary_backend_activation_failed", str(exc), status_code=400) from exc


@router.post("/deactivate-backend")
def db_deactivate_backend(workspace: Path = Depends(resolve_workspace)) -> dict[str, Any]:
    return ok(_result(deactivate_secondary_backend(workspace)))


@router.post("/repair-sqlite")
def db_repair_sqlite(workspace: Path = Depends(resolve_workspace)) -> dict[str, Any]:
    """Repair direction 1: local SQLite file is missing. Recreate it and repopulate from the active
    secondary backend."""
    try:
        return ok(_result(repair_sqlite_from_secondary(workspace)))
    except SecondaryBackendError as exc:
        raise ApiError("sqlite_repair_failed", str(exc), status_code=400) from exc


@router.post("/repair-backend")
def db_repair_backend(workspace: Path = Depends(resolve_workspace)) -> dict[str, Any]:
    """Repair direction 2: the active secondary backend was unreachable or lost data. Re-mirror it from
    SQLite."""
    try:
        return ok(_result(repair_secondary_from_sqlite(workspace)))
    except SecondaryBackendError as exc:
        raise ApiError("secondary_backend_repair_failed", str(exc), status_code=400) from exc

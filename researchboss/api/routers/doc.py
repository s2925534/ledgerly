from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from researchboss.api.deps import resolve_workspace
from researchboss.api.envelope import ApiError, ok
from researchboss.engine.vault import (
    compare_document_versions,
    create_document_version,
    diff_document_versions,
    list_document_versions,
    restore_document_version,
)


router = APIRouter()


class DocVersionRequest(BaseModel):
    target: str
    reason: str = "manual_snapshot"


@router.post("/version")
def doc_version(payload: DocVersionRequest, workspace: Path = Depends(resolve_workspace)) -> dict[str, Any]:
    try:
        record = create_document_version(
            workspace,
            payload.target,
            creation_reason=payload.reason,
            source_command="api doc version",
        )
    except ValueError as exc:
        raise ApiError("invalid_document_target", str(exc)) from exc
    return ok(record)


@router.get("/versions")
def doc_versions(
    workspace: Path = Depends(resolve_workspace),
    target: Optional[str] = Query(None),
) -> dict[str, Any]:
    try:
        rows = list_document_versions(workspace, target)
    except ValueError as exc:
        raise ApiError("invalid_document_target", str(exc)) from exc
    return ok(rows)


@router.get("/diff")
def doc_diff(
    version_id_a: str = Query(...),
    version_id_b: str = Query(...),
    workspace: Path = Depends(resolve_workspace),
) -> dict[str, Any]:
    try:
        report = diff_document_versions(workspace, version_id_a, version_id_b)
    except ValueError as exc:
        raise ApiError("unknown_document_version", str(exc), status_code=404) from exc
    return ok(report)


@router.get("/compare")
def doc_compare(
    version_id_a: str = Query(...),
    version_id_b: str = Query(...),
    workspace: Path = Depends(resolve_workspace),
) -> dict[str, Any]:
    try:
        report = compare_document_versions(workspace, version_id_a, version_id_b)
    except ValueError as exc:
        raise ApiError("unknown_document_version", str(exc), status_code=404) from exc
    return ok(report)


class DocRestoreRequest(BaseModel):
    version_id: str
    output_path: Optional[str] = None


@router.post("/restore")
def doc_restore(payload: DocRestoreRequest, workspace: Path = Depends(resolve_workspace)) -> dict[str, Any]:
    try:
        record = restore_document_version(
            workspace,
            payload.version_id,
            output_path=Path(payload.output_path) if payload.output_path else None,
        )
    except ValueError as exc:
        raise ApiError("document_restore_failed", str(exc)) from exc
    return ok(record)

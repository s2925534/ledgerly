from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from ledgerly.api.deps import resolve_workspace
from ledgerly.api.envelope import ApiError, ok
from ledgerly.engine.ai import OpenAiError, openai_credentials
from ledgerly.engine.ai_edit_sessions import (
    apply_ai_edit_session,
    create_ai_edit_session,
    list_ai_edit_sessions,
    set_ai_edit_review_status,
)
from ledgerly.engine.vault import (
    compare_document_versions,
    create_document_version,
    diff_document_versions,
    list_document_versions,
    restore_document_version,
)


router = APIRouter()


def _require_full_target_document_ai(ai: bool, full_target_document_ai: bool, workspace: Path):
    """The web equivalent of `require_full_target_document_ai_opt_in`: needs
    both `ai: true` and `full_target_document_ai: true`, matching `cite
    ai-plan`'s CLI double opt-in -- the whole document's sentence map (not
    just excerpts) is sent, so this is a stricter boundary than a plain
    `--ai` flag.
    """
    if not ai:
        raise ApiError("ai_not_enabled", 'Set "ai": true to explicitly opt in to this AI action.', status_code=400)
    if not full_target_document_ai:
        raise ApiError(
            "full_target_document_ai_not_enabled",
            'Set "full_target_document_ai": true to explicitly allow sending the whole target document to an AI provider.',
            status_code=400,
        )
    try:
        return openai_credentials(workspace)
    except OpenAiError as exc:
        raise ApiError("openai_not_configured", str(exc), status_code=503) from exc


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


class AiEditSessionCreateRequest(BaseModel):
    target: str
    ai: bool = False
    full_target_document_ai: bool = False
    instructions: str = ""
    max_sources: int = 10
    max_excerpt_chars: int = 1200


@router.post("/ai-edit-sessions")
def doc_ai_edit_session_create(
    payload: AiEditSessionCreateRequest, workspace: Path = Depends(resolve_workspace)
) -> dict[str, Any]:
    credentials = _require_full_target_document_ai(payload.ai, payload.full_target_document_ai, workspace)
    try:
        session = create_ai_edit_session(
            workspace,
            credentials,
            payload.target,
            instructions=payload.instructions,
            full_target_document_ai=True,
            max_sources=payload.max_sources,
            max_excerpt_chars=payload.max_excerpt_chars,
        )
    except (OpenAiError, ValueError) as exc:
        raise ApiError("ai_edit_session_failed", str(exc)) from exc
    return ok(session)


@router.get("/ai-edit-sessions")
def doc_ai_edit_sessions_list(workspace: Path = Depends(resolve_workspace)) -> dict[str, Any]:
    return ok(list_ai_edit_sessions(workspace))


class AiEditSessionReviewRequest(BaseModel):
    review_status: str


@router.post("/ai-edit-sessions/{session_id}/edits/{edit_id}/review")
def doc_ai_edit_session_review(
    session_id: str,
    edit_id: str,
    payload: AiEditSessionReviewRequest,
    workspace: Path = Depends(resolve_workspace),
) -> dict[str, Any]:
    try:
        edit = set_ai_edit_review_status(workspace, session_id, edit_id, payload.review_status)
    except ValueError as exc:
        status_code = 404 if str(exc).startswith("Unknown AI edit session_id") or str(exc).startswith("No edit found") else 400
        raise ApiError("invalid_ai_edit_review_status", str(exc), status_code=status_code) from exc
    return ok(edit)


@router.post("/ai-edit-sessions/{session_id}/apply")
def doc_ai_edit_session_apply(session_id: str, workspace: Path = Depends(resolve_workspace)) -> dict[str, Any]:
    try:
        report = apply_ai_edit_session(workspace, session_id)
    except ValueError as exc:
        raise ApiError("unknown_ai_edit_session", str(exc), status_code=404) from exc
    return ok(report)

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from researchboss.api.deps import resolve_workspace
from researchboss.api.envelope import ApiError, ok
from researchboss.engine.research_questions import (
    approve_research_question,
    archive_research_question,
    check_research_question_readiness,
    list_research_questions,
    reject_research_question,
)


router = APIRouter()


@router.get("")
def rqs_list(workspace: Path = Depends(resolve_workspace)) -> dict[str, Any]:
    return ok(list_research_questions(workspace))


class RqCheckRequest(BaseModel):
    rq_id: Optional[str] = None


@router.post("/check")
def rqs_check(payload: RqCheckRequest, workspace: Path = Depends(resolve_workspace)) -> dict[str, Any]:
    try:
        report = check_research_question_readiness(workspace, rq_id=payload.rq_id)
    except ValueError as exc:
        raise ApiError("unknown_rq_id", str(exc), status_code=404) from exc
    return ok(report)


@router.post("/{rq_id}/approve")
def rqs_approve(rq_id: str, workspace: Path = Depends(resolve_workspace)) -> dict[str, Any]:
    try:
        approve_research_question(workspace, rq_id)
    except ValueError as exc:
        raise ApiError("unknown_rq_id", str(exc), status_code=404) from exc
    return ok({"rq_id": rq_id, "status": "approved"})


class RqRejectRequest(BaseModel):
    reason: str = ""


@router.post("/{rq_id}/reject")
def rqs_reject(rq_id: str, payload: RqRejectRequest, workspace: Path = Depends(resolve_workspace)) -> dict[str, Any]:
    try:
        reject_research_question(workspace, rq_id, reason=payload.reason)
    except ValueError as exc:
        raise ApiError("unknown_rq_id", str(exc), status_code=404) from exc
    return ok({"rq_id": rq_id, "status": "rejected"})


@router.post("/{rq_id}/archive")
def rqs_archive(rq_id: str, payload: RqRejectRequest, workspace: Path = Depends(resolve_workspace)) -> dict[str, Any]:
    try:
        archive_research_question(workspace, rq_id, reason=payload.reason)
    except ValueError as exc:
        raise ApiError("unknown_rq_id", str(exc), status_code=404) from exc
    return ok({"rq_id": rq_id, "status": "archived"})

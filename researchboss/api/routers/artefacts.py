from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from researchboss.api.deps import resolve_workspace
from researchboss.api.envelope import ApiError, ok
from researchboss.engine.artefact_creation import create_deterministic_artefact
from researchboss.engine.artefacts import (
    artefact_dependency_report,
    list_artefacts,
    register_artefact,
    set_artefact_review_status,
)


router = APIRouter()


@router.get("")
def artefacts_list(workspace: Path = Depends(resolve_workspace)) -> dict[str, Any]:
    return ok(list_artefacts(workspace))


class ArtefactRegisterRequest(BaseModel):
    title: str
    artefact_type: str
    path: str
    linked_sources: list[str] = []
    linked_research_questions: list[str] = []
    requires_user_review: bool = True


@router.post("")
def artefacts_register(payload: ArtefactRegisterRequest, workspace: Path = Depends(resolve_workspace)) -> dict[str, Any]:
    record = register_artefact(
        workspace,
        title=payload.title,
        artefact_type=payload.artefact_type,
        path=Path(payload.path),
        linked_sources=payload.linked_sources,
        linked_research_questions=payload.linked_research_questions,
        requires_user_review=payload.requires_user_review,
    )
    return ok(record)


class ArtefactCreateRequest(BaseModel):
    artefact_type: str
    title: Optional[str] = None
    include_maybe: bool = False
    rq_id: Optional[str] = None
    overwrite: bool = False


@router.post("/create")
def artefacts_create(payload: ArtefactCreateRequest, workspace: Path = Depends(resolve_workspace)) -> dict[str, Any]:
    try:
        result = create_deterministic_artefact(
            workspace,
            payload.artefact_type,
            title=payload.title,
            include_maybe=payload.include_maybe,
            rq_id=payload.rq_id,
            overwrite=payload.overwrite,
        )
    except ValueError as exc:
        status_code = 409 if "already exists" in str(exc) else 400
        raise ApiError("artefact_creation_failed", str(exc), status_code=status_code) from exc
    return ok({"record": result.record, "path": str(result.path)})


class ArtefactReviewRequest(BaseModel):
    status: str


@router.post("/{artefact_id}/review")
def artefacts_review(
    artefact_id: str,
    payload: ArtefactReviewRequest,
    workspace: Path = Depends(resolve_workspace),
) -> dict[str, Any]:
    try:
        set_artefact_review_status(workspace, artefact_id, payload.status)
    except ValueError as exc:
        status_code = 404 if str(exc).startswith("Unknown artefact_id") else 400
        raise ApiError("invalid_artefact_review_status", str(exc), status_code=status_code) from exc
    return ok({"artefact_id": artefact_id, "review_status": payload.status})


@router.get("/dependencies")
def artefacts_dependencies(workspace: Path = Depends(resolve_workspace)) -> dict[str, Any]:
    return ok(artefact_dependency_report(workspace))
